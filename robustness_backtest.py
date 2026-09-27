# ============================================================
#  robustness_backtest.py — Full-range intraday replay + two checks
#
#  Runs intraday_backtest.Replay (unmodified) over the whole cached range:
#    1. SURVIVORSHIP: the same replay with the symbols that were dropped
#       from the watchlist after losing in backtests (REMOVED) added back.
#       Dropping losers after seeing results inflates any backtest run on
#       the survivors; this measures by how much. The two runs can halt on
#       different dates (cumulative kill switch), so they are compared over
#       their common period only.
#    2. PER-SYMBOL COSTS: each fill charged that symbol's measured SIP
#       half-spread (data/spreads.json from quote_spreads.py, "open" bucket
#       before 10:00 ET) next to the flat 5/10/20 bps levels. The spread is
#       a FLOOR — it excludes stop slippage and the data-delay gap.
#
#  The pre-registered verdict (validation.py, 10 bps/side) is unchanged
#  and is the only PASS/FAIL that counts.
#
#    python robustness_backtest.py download          # bars for REMOVED
#    python quote_spreads.py                         # data/spreads.json
#    python robustness_backtest.py run --universe current
#    python robustness_backtest.py run --universe with_removed
#    python robustness_backtest.py report
# ============================================================

import argparse
import json
import logging
import os
from datetime import date, time

import pandas as pd

import config
import crt_strategy as crt
import intraday_backtest as ib
import intraday_data
import validation

# Dropped from WATCHLIST after losing in earlier backtests (see config.py).
REMOVED     = {"VRT": "ai_core", "MARA": "growth", "HOOD": "growth"}
OUT_DIR     = os.path.join("data", "robustness")
SPREAD_JSON = os.path.join("data", "spreads.json")
FLAT_COSTS  = (0.0005, 0.0010, 0.0020)


def trades_path(universe: str) -> str:
    return os.path.join(OUT_DIR, f"trades_{universe}.csv")


def set_universe(universe: str):
    if universe == "with_removed":
        for s, theme in REMOVED.items():
            config.WATCHLIST[s] = {"theme": theme, "avg_swing_days": 4}
        config.TICKERS = list(config.WATCHLIST)
        config.CRT_SYMBOLS = config.TICKERS


def run(universe: str, start: str, end: str):
    set_universe(universe)
    rep = ib.Replay(date.fromisoformat(start), date.fromisoformat(end))
    print(f"[{universe}] {len(rep.syms)} symbols, {len(rep.sessions)} sessions "
          f"{rep.sessions[0]} -> {rep.sessions[-1]}", flush=True)
    trades = rep.run()
    os.makedirs(OUT_DIR, exist_ok=True)
    trades.to_csv(trades_path(universe), index=False)
    print(f"[{universe}] {len(trades)} trades -> {trades_path(universe)}")


# ── costs ─────────────────────────────────────────────────────
def load_spreads() -> dict:
    with open(SPREAD_JSON) as f:
        return json.load(f)["symbols"]


def with_spread_costs(t: pd.DataFrame, spreads: dict) -> pd.DataFrame:
    def cost(sym, ts):
        return spreads[sym]["open"] if ts.time() < time(10, 0) else spreads[sym]["day"]

    t = t.copy()
    ce = pd.Series([cost(s, ts) for s, ts in zip(t.symbol, t.entry_time)], t.index)
    cx = pd.Series([cost(s, ts) for s, ts in zip(t.symbol, t.exit_time)], t.index)
    long_pct  = (t.exit_price * (1 - cx) - t.entry_price * (1 + ce)) / t.entry_price
    short_pct = (t.entry_price * (1 - ce) - t.exit_price * (1 + cx)) / t.entry_price
    t["net_pct"] = short_pct.where(t.side == crt.SHORT, long_pct)
    t["net_usd"] = t.net_pct * t.entry_price * t.qty
    t["cost_per_side"] = (ce + cx).mean() / 2
    return t


def load_trades(universe: str) -> pd.DataFrame:
    t = pd.read_csv(trades_path(universe))
    for c in ("entry_time", "exit_time"):
        t[c] = pd.to_datetime(t[c], utc=True).dt.tz_convert("America/New_York")
    t["session"] = pd.to_datetime(t["session"]).dt.date
    return t


def line(label: str, s: dict) -> str:
    if not s.get("n"):
        return f"  {label:<26} no trades"
    return (f"  {label:<26} n={s['n']:>5}  win={s['win_rate']:6.1%}  mean={s['mean_net_pct']:+.3%}  "
            f"t={s['t_stat']:+6.2f}  p={s['p_value']:.3f}  net=${s['total_net_usd']:+8.2f}  "
            f"maxDD={s['max_drawdown']:5.1%}")


def report():
    cap = config.ACCOUNT_CAPITAL
    spreads = load_spreads()
    runs = {u: load_trades(u) for u in ("current", "with_removed") if os.path.exists(trades_path(u))}
    summary = {}
    for universe, trades in runs.items():
        span = f"{trades.session.min()} -> {trades.session.max()}"
        print(f"\n=== {universe.upper()}  ({trades.symbol.nunique()} symbols traded, {span}) ===")
        print("Exit reasons:\n" + trades.groupby(["strategy", "exit_reason"]).size().to_string())
        summary[universe] = {"last_session": str(trades.session.max())}
        for strat in sorted(trades.strategy.unique()):
            ts = trades[trades.strategy == strat]
            print(f"\n[{strat}] all sessions, by cost model:")
            print(f"  gross (zero cost)          mean={ts.gross_pct.mean():+.3%}  win={(ts.gross_pct > 0).mean():.1%}")
            for c in FLAT_COSTS:
                print(line(f"flat {c * 1e4:.0f} bps/side", validation.describe(ib.with_costs(ts, c), cap)))
            print(line("measured spread (floor)", validation.describe(with_spread_costs(ts, spreads), cap)))

            pre = validation.evaluate(ib.with_costs(ts, ib.VERDICT_COST), strat)
            spr = validation.evaluate(with_spread_costs(ts, spreads), strat)
            print(f"  PRE-REGISTERED VERDICT (10 bps, OOS from {pre['oos_start']}): {pre['verdict']}")
            print("".join(f"    - {r}\n" for r in pre["reasons"]), end="")
            print(f"  same test at spread-only cost: {spr['verdict']}"
                  + "".join(f"\n    - {r}" for r in spr["reasons"]))
            summary[universe][strat] = {"gross_mean_pct": float(ts.gross_pct.mean()),
                                        "pre_registered": pre, "spread_cost": spr}

    if len(runs) == 2:
        end = min(t.session.max() for t in runs.values())
        print(f"\n=== SURVIVORSHIP: effect of having dropped {'/'.join(REMOVED)} "
              f"(10 bps, common period to {end}) ===")
        summary["survivorship"] = {"common_period_end": str(end)}
        for strat in sorted(runs["current"].strategy.unique()):
            a, b = (ib.with_costs(runs[u][(runs[u].strategy == strat) & (runs[u].session <= end)],
                                  ib.VERDICT_COST) for u in ("current", "with_removed"))
            da, db = validation.describe(a, cap), validation.describe(b, cap)
            print(line(f"{strat} survivors only", da))
            print(line(f"{strat} with removed", db))
            print(line(f"{strat} removed symbols' trades", validation.describe(b[b.symbol.isin(REMOVED)], cap)))
            inflation = da["mean_net_pct"] - db["mean_net_pct"]
            print(f"    inflation from dropping them: {inflation:+.3%}/trade")
            summary["survivorship"][strat] = {"survivors": da, "with_removed": db,
                                              "inflation_mean_pct": inflation}
    with open(os.path.join(OUT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download")
    r = sub.add_parser("run")
    r.add_argument("--universe", choices=["current", "with_removed"], required=True)
    r.add_argument("--start", default="2024-01-01")
    r.add_argument("--end", default=date.today().isoformat())
    sub.add_parser("report")
    a = ap.parse_args()
    if a.cmd == "download":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        intraday_data.download("2024-01-01", symbols=list(REMOVED))
    elif a.cmd == "run":
        run(a.universe, a.start, a.end)
    else:
        report()
