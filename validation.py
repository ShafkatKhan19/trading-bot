# ============================================================
#  validation.py — Pre-registered out-of-sample verdict
#
#  The rules below were written BEFORE any intraday backtest result was
#  seen (2026-09-27). They are the only thing that decides whether a
#  strategy has an edge. Changing them after looking at results turns
#  this back into curve-fitting — if they ever change, say so in the
#  commit message and re-run everything.
#
#  Protocol:
#    1. Sort trading sessions by date. The first (1 - OOS_FRACTION) of
#       sessions are IN-SAMPLE: anything may be fitted there (constitution,
#       thresholds). The last OOS_FRACTION are OUT-OF-SAMPLE: never used for
#       fitting, looked at once.
#    2. The verdict is computed on OOS trades only, net of costs.
#    3. PASS requires ALL of:
#         - at least MIN_OOS_TRADES trades
#         - mean net return per trade > 0
#         - t-statistic of mean net return >= MIN_T_STAT
#         - sign-flip permutation p-value <= MAX_P_VALUE (luck vs edge)
#         - max drawdown on the capital base <= MAX_DRAWDOWN_PCT
#
#    python validation.py data/intraday_trades.csv
# ============================================================

import json
import math
import os
import sys
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

import config


@dataclass(frozen=True)
class Criteria:
    oos_fraction: float     = 0.30
    min_oos_trades: int     = 100
    min_t_stat: float       = 2.0
    max_p_value: float      = 0.05
    max_drawdown_pct: float = 0.20
    permutations: int       = 20_000
    seed: int               = 20260927


CRITERIA = Criteria()


def split_sessions(trades: pd.DataFrame, oos_fraction: float = CRITERIA.oos_fraction):
    """Split trades by session date — never by trade index, which would leak
    same-day trades across the boundary. Returns (in_sample, out_of_sample, cut_date)."""
    days = sorted(trades["session"].unique())
    cut  = days[int(len(days) * (1 - oos_fraction))]
    return trades[trades["session"] < cut], trades[trades["session"] >= cut], cut


def max_drawdown(pnl_dollars: np.ndarray, capital: float) -> float:
    equity = capital + np.cumsum(pnl_dollars)
    peak   = np.maximum.accumulate(np.concatenate([[capital], equity]))[1:]
    return float(np.max((peak - equity) / peak)) if len(equity) else 0.0


def sign_flip_p_value(returns: np.ndarray, n: int, seed: int) -> float:
    """
    Luck-vs-edge test. Under "no edge" each trade's return is as likely to
    have been the same size with the opposite sign. Flip signs at random
    n times; p = share of shuffled means at least as large as the real one.
    """
    if len(returns) == 0:
        return 1.0
    rng   = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n, len(returns)))
    null  = (signs * np.abs(returns)).mean(axis=1)
    return float((np.sum(null >= returns.mean()) + 1) / (n + 1))


def describe(trades: pd.DataFrame, capital: float, criteria: Criteria = CRITERIA) -> dict:
    r = trades["net_pct"].to_numpy(dtype=float)
    n = len(r)
    if n == 0:
        return {"n": 0}
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    t  = float(r.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0
    wins, losses = r[r > 0], r[r <= 0]
    return {
        "n":               n,
        "sessions":        int(trades["session"].nunique()),
        "win_rate":        float((r > 0).mean()),
        "mean_net_pct":    float(r.mean()),
        "median_net_pct":  float(np.median(r)),
        "avg_win_pct":     float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_pct":    float(losses.mean()) if len(losses) else 0.0,
        "t_stat":          t,
        "p_value":         sign_flip_p_value(r, criteria.permutations, criteria.seed),
        "total_net_usd":   float(trades["net_usd"].sum()),
        "max_drawdown":    max_drawdown(trades["net_usd"].to_numpy(dtype=float), capital),
        "std_net_pct":     sd,
    }


def verdict(oos: dict, criteria: Criteria = CRITERIA) -> tuple[str, list]:
    fails = []
    if oos.get("n", 0) < criteria.min_oos_trades:
        fails.append(f"only {oos.get('n', 0)} OOS trades (need {criteria.min_oos_trades})")
    if oos.get("n", 0):
        if oos["mean_net_pct"] <= 0:
            fails.append(f"mean net return {oos['mean_net_pct']:+.4%} <= 0")
        if oos["t_stat"] < criteria.min_t_stat:
            fails.append(f"t-stat {oos['t_stat']:.2f} < {criteria.min_t_stat}")
        if oos["p_value"] > criteria.max_p_value:
            fails.append(f"p-value {oos['p_value']:.3f} > {criteria.max_p_value} (indistinguishable from luck)")
        if oos["max_drawdown"] > criteria.max_drawdown_pct:
            fails.append(f"max drawdown {oos['max_drawdown']:.1%} > {criteria.max_drawdown_pct:.0%}")
    return ("PASS" if not fails else "FAIL"), fails


def evaluate(trades: pd.DataFrame, strategy: str, capital: float = None,
             criteria: Criteria = CRITERIA) -> dict:
    capital = capital or config.ACCOUNT_CAPITAL
    t = trades[trades["strategy"] == strategy].sort_values("entry_time")
    if t.empty:
        return {"strategy": strategy, "verdict": "FAIL", "reasons": ["no trades"]}
    ins, oos, cut = split_sessions(t, criteria.oos_fraction)
    oos_stats = describe(oos, capital, criteria)
    v, reasons = verdict(oos_stats, criteria)
    return {
        "strategy":      strategy,
        "cost_per_side": float(t["cost_per_side"].iloc[0]),
        "oos_start":     str(cut),
        "in_sample":     describe(ins, capital, criteria),
        "out_of_sample": oos_stats,
        "verdict":       v,
        "reasons":       reasons,
        "criteria":      asdict(criteria),
    }


def report_path(strategy: str) -> str:
    return os.path.join("data", f"validation_{strategy}.json")


def save(report: dict) -> None:
    with open(report_path(report["strategy"]), "w") as f:
        json.dump(report, f, indent=2, default=str)


def load(strategy: str) -> dict | None:
    try:
        with open(report_path(strategy)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def format_report(rep: dict) -> str:
    def row(label, s):
        if not s.get("n"):
            return f"  {label:<14} no trades"
        return (f"  {label:<14} n={s['n']:>4}  win={s['win_rate']:.1%}  "
                f"mean={s['mean_net_pct']:+.3%}  t={s['t_stat']:+.2f}  p={s['p_value']:.3f}  "
                f"net=${s['total_net_usd']:+.2f}  maxDD={s['max_drawdown']:.1%}")
    lines = [f"[{rep['strategy']}] cost {rep.get('cost_per_side', 0):.2%}/side, "
             f"OOS from {rep.get('oos_start')}",
             row("in-sample", rep.get("in_sample", {})),
             row("OUT-OF-SAMPLE", rep.get("out_of_sample", {})),
             f"  VERDICT: {rep['verdict']}"]
    lines += [f"    - {r}" for r in rep.get("reasons", [])]
    return "\n".join(lines)


if __name__ == "__main__":
    df = pd.read_csv(sys.argv[1] if len(sys.argv) > 1 else "data/intraday_trades.csv",
                     parse_dates=["entry_time", "exit_time"])
    for strat in sorted(df["strategy"].unique()):
        print(format_report(evaluate(df, strat)))
