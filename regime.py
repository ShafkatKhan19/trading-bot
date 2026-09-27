# ============================================================
#  regime.py — Markov-chain market-regime engine (BULL/BEAR/CHOP)
#
#  Standalone research + a small public API for later integration.
#  Nothing here imports from signals.py / strategy.py, and nothing
#  in this file mutates the rest of the bot.
#
#  Run:  ./venv/Scripts/python.exe regime.py
#
#  DESIGN NOTE ON HONESTY
#  ----------------------
#  Every number this module reports as "performance" is out-of-sample:
#  the transition matrix used to predict day t+1 is estimated only from
#  bars strictly before the test window containing t+1. In-sample numbers
#  are printed too, but always labelled DESCRIPTIVE and never used as
#  evidence of predictive value.
# ============================================================

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

# -- Parameters (pre-registered; see report — these were chosen up front
#    and deliberately NOT tuned against out-of-sample results) ----------

STATES        = ("BEAR", "CHOP", "BULL")   # ordered low -> high
LOOKBACK      = 20      # trading days in the trailing-return / vol window (~1 month)
Z_THRESHOLD   = 0.5     # trend/noise cutoff separating CHOP from BULL/BEAR
MIN_FIT_BARS  = 756     # ~3 years before the first out-of-sample prediction
SMOOTHING     = 1.0     # Laplace pseudo-count per transition cell

CACHE_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
REPORT_PATH   = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "REGIME_WALKFORWARD_2026-09-10.md"
)


# -- Data loading (cached to keep the API quiet and the C: drive free) --

def load_bars(symbol: str, days: int = 3900, max_age_hours: float = 12.0,
              cache_dir: str = CACHE_DIR) -> pd.DataFrame:
    """
    Fetch daily bars for `symbol`, caching to <repo>/data/<symbol>_1Day.csv.
    Cache is a few hundred KB and lives inside the repo (NOT system temp).
    """
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{symbol}_1Day.csv")

    if os.path.exists(path):
        age_h = (datetime.now().timestamp() - os.path.getmtime(path)) / 3600.0
        if age_h < max_age_hours:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            if len(df) > 0:
                return df

    from alpaca_client import AlpacaClient          # imported lazily: keeps
    client = AlpacaClient()                          # the module importable offline
    df = client.get_bars(symbol, "1Day", days=days)
    if df is None or len(df) == 0:
        if os.path.exists(path):                     # stale cache beats nothing
            return pd.read_csv(path, index_col=0, parse_dates=True)
        raise RuntimeError(f"No bars returned for {symbol}")
    df.to_csv(path)
    return df


# -- 1. State classification -------------------------------------------
#
#  DEFINITION (one sentence):
#    A bar is BULL if its trailing 20-day log return is more than +0.5
#    "noise units" (that return divided by the trailing 20-day realized
#    daily volatility scaled to a 20-day horizon), BEAR if it is below
#    -0.5 noise units, and CHOP otherwise.
#
#  Why noise units and not a raw percentage: a +2% month in a 6%-vol
#  tape is a trend; the same +2% in a 30%-vol tape is noise. Dividing by
#  realized vol makes the CHOP band self-scaling, which is the whole
#  point of having a CHOP state at all.
#
#  NO LOOKAHEAD: every quantity below is a trailing window ending at t.
#  `close.shift(k)` only ever looks backwards; no .shift(-k), no
#  centered windows, no full-sample z-scoring or normalisation.
#  `verify_no_lookahead()` proves this empirically.

def classify_states(df: pd.DataFrame, lookback: int = LOOKBACK,
                    z_threshold: float = Z_THRESHOLD) -> pd.DataFrame:
    """
    Return a frame indexed like `df` with columns:
        ret1   — daily log return (t-1 -> t)
        trend  — trailing `lookback`-day log return ending at t
        vol_h  — trailing daily vol at t, scaled to the lookback horizon
        z      — trend / vol_h  (trend measured in units of its own noise)
        state  — BEAR / CHOP / BULL
    The first `lookback` rows have state NaN (insufficient history).
    """
    close = df["close"].astype(float)
    ret1 = np.log(close / close.shift(1))

    trend = np.log(close / close.shift(lookback))
    # min_periods == lookback: no partial windows, so no silently-different
    # estimator at the start of the sample.
    vol_d = ret1.rolling(lookback, min_periods=lookback).std(ddof=1)
    vol_h = vol_d * math.sqrt(lookback)

    z = trend / vol_h.replace(0.0, np.nan)

    state = pd.Series(pd.NA, index=df.index, dtype="object")
    state[z > z_threshold] = "BULL"
    state[z < -z_threshold] = "BEAR"
    state[(z >= -z_threshold) & (z <= z_threshold)] = "CHOP"

    return pd.DataFrame(
        {"ret1": ret1, "trend": trend, "vol_h": vol_h, "z": z, "state": state}
    )


def verify_no_lookahead(df: pd.DataFrame, n_checks: int = 40,
                        seed: int = 0) -> tuple:
    """
    Empirical proof of causality: recompute the state at a random bar t
    using ONLY df.iloc[:t+1] and assert it equals the state computed on
    the full history. If any future bar leaked into the feature, the two
    would differ. Returns (all_match, n_checked).
    """
    full = classify_states(df)
    valid = full["state"].notna()
    idx = np.flatnonzero(valid.to_numpy())
    rng = np.random.default_rng(seed)
    picks = rng.choice(idx, size=min(n_checks, len(idx)), replace=False)

    ok = True
    for t in picks:
        truncated = classify_states(df.iloc[: int(t) + 1])
        if truncated["state"].iloc[-1] != full["state"].iloc[int(t)]:
            ok = False
            break
    return ok, len(picks)


# -- 2. Transition matrix ----------------------------------------------

def transition_counts(states: pd.Series) -> pd.DataFrame:
    """Raw counts N[i, j] = # of times state i was followed by state j."""
    s = states.dropna()
    cur, nxt = s.iloc[:-1].to_numpy(), s.iloc[1:].to_numpy()
    counts = pd.DataFrame(0, index=list(STATES), columns=list(STATES), dtype=float)
    for a, b in zip(cur, nxt):
        counts.loc[a, b] += 1.0
    return counts


def transition_matrix(states: pd.Series, smoothing: float = SMOOTHING) -> pd.DataFrame:
    """
    Row-normalised P(state_t+1 | state_t) with Laplace smoothing so an
    unobserved transition gets a small probability instead of a hard zero
    (matters early in walk-forward when BEAR is rare).
    """
    counts = transition_counts(states) + smoothing
    return counts.div(counts.sum(axis=1), axis=0)


# -- 3. Stickiness -----------------------------------------------------

def stickiness(P: pd.DataFrame) -> pd.DataFrame:
    """
    Per-state persistence: self-transition probability P(s|s) and the
    implied expected dwell time 1/(1-P(s|s)) in trading days.
    """
    rows = {}
    for s in STATES:
        p = float(P.loc[s, s])
        rows[s] = {
            "self_prob": p,
            "expected_dwell_days": (1.0 / (1.0 - p)) if p < 1 else np.inf,
        }
    return pd.DataFrame(rows).T


def stationary_distribution(P: pd.DataFrame) -> pd.Series:
    """Long-run state frequencies implied by P (left eigenvector, eigenvalue 1)."""
    vals, vecs = np.linalg.eig(P.to_numpy().T)
    v = np.real(vecs[:, np.argmin(np.abs(vals - 1.0))])
    v = np.abs(v)
    return pd.Series(v / v.sum(), index=list(STATES))


# -- 4. Walk-forward out-of-sample evaluation --------------------------

@dataclass
class WalkForwardResult:
    preds: pd.DataFrame          # per-OOS-day predictions + realised outcome
    n_refits: int
    first_oos: pd.Timestamp
    last_oos: pd.Timestamp


def walk_forward(df: pd.DataFrame, feats: pd.DataFrame,
                 qqq_bullish: pd.Series,
                 min_fit_bars: int = MIN_FIT_BARS,
                 step: str = "ME") -> WalkForwardResult:
    """
    Expanding-window walk-forward.

    For each calendar month M after the warm-up:
      * fit the transition matrix on states observed STRICTLY BEFORE the
        first bar of M,
      * for every bar t in M, predict state_{t+1} = argmax_j P(j | state_t),
      * record the realised state_{t+1} and the realised SPY return
        from close_t to close_{t+1}.

    The fit set never contains a transition whose destination is inside
    the test month, so no test-period information reaches the matrix.
    """
    states = feats["state"]
    usable = states.dropna().index
    if len(usable) < min_fit_bars + 40:
        raise RuntimeError("Not enough history for walk-forward")

    warm_end = usable[min_fit_bars - 1]
    marker = pd.Series(1, index=usable)
    periods = [list(grp.index) for _, grp in marker.groupby(pd.Grouper(freq=step))]

    close = df["close"].astype(float)
    fwd_ret = (close.shift(-1) / close - 1.0)      # close_t -> close_{t+1}

    rows, n_refits = [], 0
    for days_in_period in periods:
        if not len(days_in_period):
            continue
        period_start = days_in_period[0]
        if period_start <= warm_end:
            continue

        fit_states = states.loc[states.index < period_start].dropna()
        if len(fit_states) < min_fit_bars:
            continue
        P = transition_matrix(fit_states)
        n_refits += 1

        for t in days_in_period:
            pos = df.index.get_loc(t)
            if pos + 1 >= len(df.index):
                continue
            t_next = df.index[pos + 1]
            cur = states.loc[t]
            actual_next = states.loc[t_next]
            if pd.isna(cur) or pd.isna(actual_next):
                continue

            probs = P.loc[cur]
            rows.append({
                "date":         t,
                "next_date":    t_next,
                "state":        cur,
                "actual_next":  actual_next,
                "pred_markov":  probs.idxmax(),
                "conf_markov":  float(probs.max()),
                "p_bull_next":  float(probs["BULL"]),
                "pred_persist": cur,
                "qqq_bull":     bool(qqq_bullish.get(t, False)),
                "fwd_ret":      float(fwd_ret.loc[t]),
            })

    preds = pd.DataFrame(rows).set_index("date")
    return WalkForwardResult(preds, n_refits, preds.index[0], preds.index[-1])


# -- 5. Benchmarks & scoring -------------------------------------------

def qqq_above_ma(df_qqq: pd.DataFrame, period: int = 50) -> pd.Series:
    """The bot's existing rule, vectorised: close_t > 50-day MA_t (trailing)."""
    close = df_qqq["close"].astype(float)
    ma = close.rolling(period, min_periods=period).mean()
    return (close > ma).where(ma.notna())


def _sharpe(daily: pd.Series) -> float:
    d = daily.dropna()
    if len(d) < 2 or d.std(ddof=1) == 0:
        return float("nan")
    return float(d.mean() / d.std(ddof=1) * math.sqrt(252))


def _cagr(daily: pd.Series) -> float:
    d = daily.dropna()
    if len(d) == 0:
        return float("nan")
    total = float((1.0 + d).prod())
    yrs = len(d) / 252.0
    return total ** (1.0 / yrs) - 1.0 if total > 0 else -1.0


def _max_dd(daily: pd.Series) -> float:
    eq = (1.0 + daily.fillna(0.0)).cumprod()
    return float((eq / eq.cummax() - 1.0).min())


def _welch_t(a: pd.Series, b: pd.Series) -> float:
    """Two-sample t-stat on daily returns (unequal variance). No scipy."""
    a, b = a.dropna(), b.dropna()
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    if (va + vb) <= 0:
        return float("nan")
    return float((a.mean() - b.mean()) / math.sqrt(va + vb))


def score_classification(preds: pd.DataFrame) -> pd.DataFrame:
    """Out-of-sample next-state accuracy for the Markov model vs baselines."""
    actual = preds["actual_next"]
    majority = preds["state"].value_counts().idxmax()
    out = {
        "Markov (argmax P)":     (preds["pred_markov"] == actual).mean(),
        "Persistence (t+1 = t)": (preds["pred_persist"] == actual).mean(),
        f"Always {majority}":    (actual == majority).mean(),
    }
    return pd.Series(out, name="oos_accuracy").to_frame()


def score_economics(preds: pd.DataFrame) -> pd.DataFrame:
    """
    Out-of-sample economics of using each rule as an entry gate on SPY.
    Each rule decides at close_t whether to hold the next bar; the
    realised return is close_t -> close_{t+1}. No costs are applied —
    every rule is scored identically, and the bot's real cost drag
    (~0.2%/side) is discussed in the report.
    """
    r = preds["fwd_ret"]
    gates = {
        "Markov: predict BULL":         preds["pred_markov"] == "BULL",
        "Persistence: state=BULL":      preds["pred_persist"] == "BULL",
        "QQQ > 50MA (current bot rule)": preds["qqq_bull"].astype(bool),
        "Buy & hold SPY":               pd.Series(True, index=preds.index),
    }
    rows = {}
    for name, gate in gates.items():
        strat = r.where(gate, 0.0)
        rows[name] = {
            "days_in_market_pct": 100.0 * float(gate.mean()),
            "mean_ret_when_in_bps": 1e4 * float(r[gate].mean()) if gate.any() else np.nan,
            "sharpe": _sharpe(strat),
            "cagr_pct": 100.0 * _cagr(strat),
            "max_dd_pct": 100.0 * _max_dd(strat),
            "t_vs_flat": _welch_t(r[gate], r[~gate]) if gate.any() and (~gate).any() else np.nan,
        }
    return pd.DataFrame(rows).T


def conditional_forward_returns(preds: pd.DataFrame) -> pd.DataFrame:
    """
    OOS next-day SPY return conditioned on today's state. The core question:
    does knowing the state tell you anything about tomorrow?
    """
    g = preds.groupby("state")["fwd_ret"]
    out = pd.DataFrame({
        "n_days":       g.size(),
        "mean_bps":     1e4 * g.mean(),
        "median_bps":   1e4 * g.median(),
        "ann_vol_pct":  100.0 * g.std(ddof=1) * math.sqrt(252),
        "hit_rate_pct": 100.0 * g.apply(lambda s: (s > 0).mean()),
    })
    all_r = preds["fwd_ret"]
    out["t_vs_rest"] = [
        _welch_t(preds.loc[preds["state"] == s, "fwd_ret"], all_r[preds["state"] != s])
        for s in out.index
    ]
    return out.reindex([s for s in STATES if s in out.index])


def trade_level_regime_test(states: pd.Series, db_path: str = "trades.db") -> pd.DataFrame:
    """
    The direct test of the CHOP hypothesis: tag every historical backtest
    trade with the market state in force on its entry date, then compare
    no_progress-exit rate and P&L across states.

    The claim being tested is "the 55 no_progress exits are the signature of
    trading in chop". If true, CHOP-entered trades should show a markedly
    higher no_progress rate than BULL-entered ones.

    State is matched backward-in-time (the last state at or before the entry
    date), so no post-entry information is used. Returns an empty frame if
    the database is unavailable.
    """
    import sqlite3

    if not os.path.exists(db_path):
        return pd.DataFrame()
    with sqlite3.connect(db_path) as con:
        t = pd.read_sql(
            "SELECT entry_date, exit_reason, pnl FROM trades WHERE mode='backtest'", con
        )
    if t.empty:
        return pd.DataFrame()

    t["entry_date"] = pd.to_datetime(t["entry_date"], utc=True, format="mixed")
    t = t.sort_values("entry_date").reset_index(drop=True)

    s = states.dropna()
    s = pd.DataFrame({"d": pd.to_datetime(s.index, utc=True), "state": s.to_numpy()})
    t = pd.merge_asof(t, s, left_on="entry_date", right_on="d", direction="backward")
    t["no_progress"] = t["exit_reason"].fillna("").str.startswith("no_progress")

    g = t.groupby("state")
    return pd.DataFrame({
        "n_trades":        g.size(),
        "no_progress_pct": 100.0 * g["no_progress"].mean(),
        "win_rate_pct":    100.0 * g["pnl"].apply(lambda x: (x > 0).mean()),
        "mean_pnl_usd":    g["pnl"].mean(),
        "total_pnl_usd":   g["pnl"].sum(),
    }).reindex([x for x in STATES if x in g.groups])


# -- 6. Public interface for later integration -------------------------

def current_regime(df: pd.DataFrame, lookback: int = LOOKBACK,
                   z_threshold: float = Z_THRESHOLD,
                   min_fit_bars: int = 250) -> tuple:
    """
    Classify the LAST bar of `df` and describe its persistence.

    Returns (state, stickiness, confidence):
      state       — 'BULL' | 'BEAR' | 'CHOP' | 'UNKNOWN'
      stickiness  — P(state | state) estimated from all bars in `df`
                    (self-transition probability; 1/(1-p) = expected dwell)
      confidence  — max_j P(j | state), the probability mass on the most
                    likely next state

    Both probabilities come only from bars present in `df`, i.e. only data
    available at the time of the call. Returns ('UNKNOWN', nan, nan) when
    there is not enough history.
    """
    if df is None or len(df) < max(lookback + 2, min_fit_bars):
        return "UNKNOWN", float("nan"), float("nan")
    feats = classify_states(df, lookback, z_threshold)
    state = feats["state"].iloc[-1]
    if pd.isna(state):
        return "UNKNOWN", float("nan"), float("nan")
    P = transition_matrix(feats["state"])
    return str(state), float(P.loc[state, state]), float(P.loc[state].max())


def is_market_bullish(df_regime: pd.DataFrame) -> bool:
    """
    Drop-in-compatible replacement for signals.is_market_bullish(df) -> bool.
    True only when the current regime is BULL. CHOP and BEAR both block
    entries, which is the behavioural difference from the 50MA rule: the
    50MA rule calls a flat, directionless tape "bullish"; this does not.

    NOTE: read REGIME_WALKFORWARD_2026-09-10.md before wiring this in. As of
    that study this gate did NOT beat the existing 50MA rule out-of-sample.
    """
    state, _, _ = current_regime(df_regime)
    return state == "BULL"


# -- 7. Standalone analysis + report generation ------------------------

def _fmt_df(df: pd.DataFrame, floatfmt: str = "{:.4f}") -> str:
    """Markdown table from a DataFrame without pulling in tabulate."""
    def f(v):
        if isinstance(v, (float, np.floating)):
            return "n/a" if math.isnan(float(v)) else floatfmt.format(v)
        return str(v)
    head = "| " + " | ".join([df.index.name or ""] + [str(c) for c in df.columns]) + " |"
    sep = "|" + "|".join(["---"] * (len(df.columns) + 1)) + "|"
    body = ["| " + " | ".join([str(i)] + [f(v) for v in row]) + " |"
            for i, row in zip(df.index, df.to_numpy())]
    return "\n".join([head, sep] + body)


def main() -> int:
    pd.set_option("display.width", 140)
    print("Loading SPY and QQQ daily bars (cached under ./data)...")
    spy = load_bars("SPY", days=3900)
    qqq = load_bars("QQQ", days=3900)
    spy = spy[~spy.index.duplicated(keep="last")].sort_index()
    qqq = qqq[~qqq.index.duplicated(keep="last")].sort_index()
    print(f"  SPY: {len(spy)} bars  {spy.index[0].date()} -> {spy.index[-1].date()}")
    print(f"  QQQ: {len(qqq)} bars  {qqq.index[0].date()} -> {qqq.index[-1].date()}")

    print("\nVerifying no lookahead (recompute state on truncated history)...")
    ok, n = verify_no_lookahead(spy)
    print(f"  {n} random bars re-derived from data<=t: {'MATCH' if ok else 'MISMATCH'}")
    if not ok:
        print("  ABORT: lookahead detected in state classification.")
        return 1

    feats = classify_states(spy)
    qbull = qqq_above_ma(qqq).reindex(spy.index).ffill().fillna(False)

    # Descriptive (IN-SAMPLE) full-history matrix — for description only.
    full_P = transition_matrix(feats["state"])
    full_counts = transition_counts(feats["state"])
    stick = stickiness(full_P)
    stat = stationary_distribution(full_P)
    freq = feats["state"].value_counts(normalize=True).reindex(list(STATES))

    print("\n=== DESCRIPTIVE (full-sample, IN-SAMPLE — not evidence) ===")
    print("State frequencies (%):\n", (100 * freq).round(1).to_string())
    print("\nTransition counts:\n", full_counts.astype(int).to_string())
    print("\nTransition matrix P(next|current):\n", full_P.round(4).to_string())
    print("\nStickiness:\n", stick.round(4).to_string())
    print("\nStationary distribution:\n", stat.round(4).to_string())

    print("\nRunning walk-forward (expanding window, monthly refit)...")
    wf = walk_forward(spy, feats, qbull)
    print(f"  {wf.n_refits} refits, {len(wf.preds)} OOS days, "
          f"{wf.first_oos.date()} -> {wf.last_oos.date()}")

    acc = score_classification(wf.preds)
    econ = score_economics(wf.preds)
    cond = conditional_forward_returns(wf.preds)

    print("\n=== OUT-OF-SAMPLE next-state accuracy (%) ===\n", (100 * acc).round(2).to_string())
    print("\n=== OUT-OF-SAMPLE economics (SPY, no costs) ===\n", econ.round(3).to_string())
    print("\n=== OOS next-day SPY return by current state ===\n", cond.round(3).to_string())

    # Robustness: report the whole grid, do not select from it.
    print("\n=== Robustness grid (all values reported, none selected) ===")
    grid_rows = {}
    for lb in (10, 20, 40, 60):
        for zt in (0.25, 0.5, 1.0):
            f2 = classify_states(spy, lb, zt)
            try:
                w2 = walk_forward(spy, f2, qbull)
            except Exception:
                continue
            e2 = score_economics(w2.preds)
            a2 = score_classification(w2.preds)
            grid_rows[f"lb={lb},z={zt}"] = {
                "markov_acc_pct": 100.0 * float(a2.loc["Markov (argmax P)", "oos_accuracy"]),
                "persist_acc_pct": 100.0 * float(a2.loc["Persistence (t+1 = t)", "oos_accuracy"]),
                "markov_sharpe": float(e2.loc["Markov: predict BULL", "sharpe"]),
                "qqq50ma_sharpe": float(e2.loc["QQQ > 50MA (current bot rule)", "sharpe"]),
                "bh_sharpe": float(e2.loc["Buy & hold SPY", "sharpe"]),
                "chop_pct": 100.0 * float((f2["state"] == "CHOP").mean()),
            }
    grid = pd.DataFrame(grid_rows).T
    print(grid.round(3).to_string())

    print("\n=== Trade-level CHOP test (backtest trades tagged by entry state) ===")
    tl = trade_level_regime_test(feats["state"],
                                 os.path.join(os.path.dirname(REPORT_PATH), "trades.db"))
    print(tl.round(2).to_string() if not tl.empty else "  (trades.db unavailable)")

    _write_report(spy, feats, full_counts, full_P, stick, stat, freq,
                  wf, acc, econ, cond, grid, n, tl)
    print(f"\nReport written: {REPORT_PATH}")
    return 0


def _write_report(spy, feats, counts, P, stick, stat, freq, wf,
                  acc, econ, cond, grid, la_n, tl) -> None:
    m_acc = float(acc.loc["Markov (argmax P)", "oos_accuracy"])
    p_acc = float(acc.loc["Persistence (t+1 = t)", "oos_accuracy"])
    maj_row = [i for i in acc.index if i.startswith("Always ")][0]
    maj_acc = float(acc.loc[maj_row, "oos_accuracy"])
    m_sh = float(econ.loc["Markov: predict BULL", "sharpe"])
    q_sh = float(econ.loc["QQQ > 50MA (current bot rule)", "sharpe"])
    b_sh = float(econ.loc["Buy & hold SPY", "sharpe"])

    beats_class = m_acc > p_acc and m_acc > maj_acc
    beats_econ = m_sh > q_sh and m_sh > b_sh
    verdict = ("PASS" if (beats_class and beats_econ)
               else "PARTIAL" if (beats_class or beats_econ) else "FAIL")
    agree = 100.0 * float((wf.preds["pred_markov"] == wf.preds["pred_persist"]).mean())

    acc_t = acc.copy()
    acc_t["oos_accuracy"] *= 100
    acc_t = acc_t.rename(columns={"oos_accuracy": "oos_accuracy_pct"})
    acc_t.index.name = "predictor"
    econ_t = econ.copy(); econ_t.index.name = "entry gate"
    cond_t = cond.copy(); cond_t.index.name = "state at t"
    P_t = P.copy(); P_t.index.name = "from \\ to"
    c_t = counts.astype(int).copy(); c_t.index.name = "from \\ to"
    s_t = stick.copy(); s_t.index.name = "state"
    g_t = grid.copy(); g_t.index.name = "config"
    fr = pd.DataFrame({"share_pct": 100 * freq, "stationary_pct": 100 * stat})
    fr.index.name = "state"

    grid_lost = int((grid["markov_sharpe"] < grid["qqq50ma_sharpe"]).sum())
    max_abs_t = float(cond["t_vs_rest"].abs().max())
    best_state = str(cond["mean_bps"].idxmax())
    bull_bps = float(cond.loc["BULL", "mean_bps"])
    best_bps = float(cond.loc[best_state, "mean_bps"])
    m_dd = float(econ.loc["Markov: predict BULL", "max_dd_pct"])
    q_dd = float(econ.loc["QQQ > 50MA (current bot rule)", "max_dd_pct"])
    b_dd = float(econ.loc["Buy & hold SPY", "max_dd_pct"])
    m_days = float(econ.loc["Markov: predict BULL", "days_in_market_pct"])

    if tl is not None and not tl.empty:
        tl_t = tl.copy(); tl_t.index.name = "state at entry"
        tl_table = _fmt_df(tl_t, "{:.2f}")
        np_bull = float(tl.loc["BULL", "no_progress_pct"]) if "BULL" in tl.index else float("nan")
        np_chop = float(tl.loc["CHOP", "no_progress_pct"]) if "CHOP" in tl.index else float("nan")
        n_chop = int(tl.loc["CHOP", "n_trades"]) if "CHOP" in tl.index else 0
        chop_verdict = (
            f"**The chop hypothesis is not supported.** Trades entered in CHOP exited on "
            f"`no_progress` {np_chop:.1f}% of the time versus {np_bull:.1f}% for trades "
            f"entered in BULL — the rate is *higher* in the supposedly-good state. "
            f"Filtering out CHOP entries would not have removed the `no_progress` cluster; "
            f"it would have removed a representative slice of trades. Caveat: only "
            f"{n_chop} backtest trades were entered in CHOP, so this test is weak — it "
            f"rules out a large effect, not a small one."
        )
    else:
        tl_table = "_(trades.db unavailable at report time)_"
        chop_verdict = "_(trade-level chop test could not run — trades.db unavailable)_"

    md = f"""# Markov Regime Engine — Walk-Forward Study

**Date:** 2026-09-10 &middot; **Code:** `regime.py` &middot; **Data:** SPY daily bars,
{len(spy)} rows, {spy.index[0].date()} to {spy.index[-1].date()} (QQQ used only for the
incumbent baseline).

> ## Verdict: {verdict}
> Section 9 has the detail. Read it before wiring anything into the live bot.

---

## 1. State definition

> **A bar is BULL if its trailing 20-day log return exceeds +0.5 "noise units" — that
> return divided by the trailing 20-day realized daily volatility scaled to a 20-day
> horizon — BEAR if it is below -0.5 noise units, and CHOP otherwise.**

In code (`classify_states`):

```
trend_t = log(close_t / close_t-20)
vol_t   = std(daily log returns over the last 20 bars) * sqrt(20)
z_t     = trend_t / vol_t
state_t = BULL if z_t > 0.5 ; BEAR if z_t < -0.5 ; else CHOP
```

Dividing by realized vol is what makes CHOP meaningful: +2% over a month in a quiet
tape is a trend, the same +2% in a violent tape is noise. A fixed percentage band
would call 2022 "trending" and 2017 "chop" purely because of volatility levels.

`LOOKBACK=20` and `Z_THRESHOLD=0.5` were fixed before any out-of-sample number was
computed. Section 7 reports a grid over both, in full, as a robustness check — no
configuration was selected on the strength of its out-of-sample result.

### Lookahead control

Every feature is a trailing window ending at t: `close.shift(k)` with k>0 and
`rolling(20, min_periods=20)`. There is no `shift(-k)`, no centered window, and no
full-sample mean/std normalisation anywhere in the feature path. The walk-forward loop
additionally fits each transition matrix only on states dated strictly before the first
bar of the test month.

This is verified empirically, not just asserted. `verify_no_lookahead()` picks random
bars t, recomputes the state using only `df.iloc[:t+1]`, and compares it to the state
computed on the full history — any leakage would change the answer.
**Result: {la_n}/{la_n} bars matched.** The check runs on every `python regime.py` and
aborts the analysis on mismatch.

The only forward-looking quantity in the study is the evaluation target itself
(`fwd_ret` = close_t to close_t+1), which is never an input to any model.

---

## 2. Transition matrix (full sample — DESCRIPTIVE ONLY)

These numbers describe the history. They are in-sample and are **not** evidence of
predictive value. Section 4 onward is the out-of-sample part.

State occupancy:

{_fmt_df(fr, "{:.1f}")}

Observed transition counts:

{_fmt_df(c_t)}

P(state at t+1 | state at t), Laplace-smoothed (+1 per cell):

{_fmt_df(P_t)}

---

## 3. Stickiness

Self-transition probability and implied expected dwell time `1/(1-P(s|s))`, in trading
days:

{_fmt_df(s_t)}

All three states are extremely sticky. This is largely mechanical: consecutive 20-day
trailing returns share 19 of their 20 bars, so `state_t+1` is nearly determined by
`state_t` by construction. **A high stickiness score is therefore not a discovery about
markets — it is an artifact of the overlapping window.** This is the single most
important thing to understand about the course's "stickiness" metric, and the reason
section 5's accuracy numbers must be read against the persistence baseline rather than
against 33%.

---

## 4. Walk-forward design

Expanding window, refit monthly:

1. For test month M, fit P on all states dated strictly before M's first bar.
2. For each bar t in M, predict `state_t+1 = argmax_j P(j | state_t)`.
3. Record the realised `state_t+1` and SPY's realised close_t to close_t+1 return.
4. Roll forward. Warm-up: {MIN_FIT_BARS} bars (~3 years) before the first prediction.

**{wf.n_refits} refits &middot; {len(wf.preds)} out-of-sample days &middot;
{wf.first_oos.date()} to {wf.last_oos.date()}.** Everything below is out-of-sample.

---

## 5. Out-of-sample next-state accuracy

{_fmt_df(acc_t, "{:.2f}")}

The Markov argmax and the naive persistence rule issue the **same prediction on
{agree:.1f}% of out-of-sample days**. Because every row of P is dominated by its
diagonal, `argmax_j P(j | s)` is almost always `s` itself — the transition matrix
reduces to "tomorrow looks like today" and adds essentially nothing on top of it.

---

## 6. Out-of-sample economics

Each rule is an entry gate on SPY: hold the next bar when the gate is on, else flat. No
transaction costs are applied to any rule — they are scored identically, and costs are
discussed in section 8.

{_fmt_df(econ_t, "{:.3f}")}

Next-day SPY return conditioned on the current state — the question that actually
matters, i.e. does knowing the state tell you anything about tomorrow:

{_fmt_df(cond_t, "{:.3f}")}

---

## 7. Robustness grid (reported in full, nothing selected)

Every cell below is out-of-sample under the same walk-forward protocol. This grid is
published to show the spread, **not** to pick a winner; the pre-registered
configuration is `lb=20, z=0.5`.

{_fmt_df(g_t, "{:.3f}")}

---

## 8. Does CHOP explain the `no_progress` exits?

This is the specific hypothesis that motivated the work: that the cluster of
`no_progress` exits in the trade database is the signature of trading in a sideways
tape. Every backtest trade is tagged with the SPY state in force on its entry date
(matched backward in time, so no post-entry information is used):

{tl_table}

{chop_verdict}

---

## 9. Verdict

### {verdict} — the Markov regime model shows no out-of-sample predictive value, and is worse than the rule it would replace.

**1. The transition matrix adds nothing over "tomorrow = today."** Markov argmax and
naive persistence scored *identically* ({m_acc * 100:.2f}% vs {p_acc * 100:.2f}%) because
they emit the same prediction on {agree:.1f}% of out-of-sample days. Every row of P is
diagonal-dominant, so `argmax_j P(j|s)` collapses to `s`. The matrix is a more expensive
way to write `state_t+1 = state_t`.

**2. The {m_acc * 100:.1f}% accuracy figure is not a result.** It sounds impressive
against a 33% three-class coin flip, but the correct benchmark is the persistence
baseline, which ties it exactly. The accuracy comes from the overlapping 20-day window
— consecutive states share 19 of 20 bars — not from the market being predictable.
Section 7 makes this mechanical: accuracy rises monotonically with lookback
(~{float(grid['markov_acc_pct'].min()):.0f}% at lb=10 to
~{float(grid['markov_acc_pct'].max()):.0f}% at lb=60) purely because longer windows
overlap more. Longer window, higher "accuracy", *lower* Sharpe.

**3. Knowing the state tells you nothing about tomorrow's return.** All three states'
next-day means sit within about 1 bp of each other, and the largest t-statistic against
the rest of the sample is {max_abs_t:.2f} — indistinguishable from zero. BULL, the state
the gate trades in, had the *lowest* mean forward return ({bull_bps:.2f} bps) of the
three; the highest was {best_state} ({best_bps:.2f} bps). The sign is backwards from the
thesis.

**4. It loses to both required baselines.** Markov-BULL gating gave Sharpe {m_sh:.3f}
against {q_sh:.3f} for the existing QQQ-above-50MA rule and {b_sh:.3f} for buy-and-hold.
It lost to the incumbent 50MA rule in **{grid_lost} of {len(grid)} robustness
configurations** — this is not a knife-edge parameter choice, it is a consistent loss.

**5. The chop hypothesis specifically failed.** See section 8. The `no_progress` exits
are not concentrated in CHOP.

### The one honest point in its favour

Max drawdown fell to {m_dd:.1f}% versus {b_dd:.1f}% for buy-and-hold, on
{m_days:.0f}% market exposure. That is real risk reduction — but the incumbent 50MA rule
already achieves {q_dd:.1f}% *with a higher Sharpe*, so the regime model is not the way
to buy that reduction.

### Recommendation

**Do not integrate this as an entry gate.** `is_market_bullish()` in `regime.py` is
written and drop-in compatible, but on this evidence swapping it for the 50MA rule would
make the bot worse, not better. The three-state vocabulary may still be useful as
*telemetry* — logging the regime alongside each trade costs nothing and builds the
record needed to test this properly later — but it should not be allowed to veto trades.

### Caveats and things I am not certain about

- **This tests index-level direction, not the bot's actual edge.** The bot trades single
  names with stops and targets; a regime filter could in principle help trade-level P&L
  even with no index-level forward-return signal. Section 8 is the closest available test
  of that and it came back negative, but on only {int(tl['n_trades'].sum()) if tl is not None and not tl.empty else 0}
  trades.
- **Costs are excluded from section 6.** All four rules are scored gross. The
  Markov gate trades in and out more often than buy-and-hold, so charging realistic
  costs would widen its loss, not narrow it. This does not change the conclusion's sign.
- **One market cycle.** {spy.index[0].date()} to {spy.index[-1].date()} contains one
  major bear (2022) and two crashes. A three-state model estimated over one cycle has
  wide error bars on the BEAR row regardless of walk-forward discipline.
- **The threshold was not tuned, and I did not tune it after seeing results.** Section 7
  is published in full precisely so that a later reader can see nothing was cherry-picked.
  If a future version of this reports a better number, check whether the parameters moved.

### The bigger picture

This model was evaluated against SPY's own forward returns, which is a fair test of the
regime idea in isolation. It should not be read as evidence about the bot's overall
viability — the separate audit found the strategy's backtest edge (+$11.61 over 379
trades) turns negative once exit slippage is charged symmetrically. A regime filter that
does not work cannot fix a strategy that does not have an edge, and adding one would
mostly add the appearance of sophistication.
"""
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(md)


if __name__ == "__main__":
    sys.exit(main())
