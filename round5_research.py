# ============================================================
#  round5_research.py — Tests PREREGISTRATION_2026-10-20_round5.md
#
#  H15 small-cap momentum 6-1        H18 small-cap low volatility
#  H16 small-cap 1-month reversal    H19 momentum + low-vol blend
#  H17 52-week-high proximity
#
#  Written AFTER the pre-registration commit. Universe S = current
#  S&P SmallCap 600 list (SURVIVORSHIP-BIASED upward, disclosed).
#  Yahoo adjclose basis throughout. Monthly: signal at month-end
#  close, positions earn returns from the NEXT session's close
#  onward (registered deviation from the open-fill convention).
#  5 bps per side on turnover. Benchmark: IWM. Verdicts OOS only.
#    python round5_research.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats as sstats

import daily_research as r1

COST       = r1.COST      # 5 bps per side, pre-registered
CASH0      = 2000.0
IS_END     = "2023-07-06"  # OOS starts here (same split as rounds 2-4)
EVAL_START = "2016-01-01"
N_TESTS    = 21           # cumulative hypotheses through round 5
TOPN       = 30
MIN_HIST   = 252          # sessions of history required for eligibility
N_DRAWS    = 200          # random-entry control draws per rebalance
SEED       = 20261020
BARS       = os.path.join("data", "smallcap", "bars")


# ── data ──────────────────────────────────────────────────────
def load_panel():
    tickers = pd.read_csv(os.path.join("data", "smallcap", "tickers.csv"))["ticker"].tolist()
    iwm = pd.read_csv(os.path.join(BARS, "IWM.csv"), parse_dates=["Date"])
    bench = iwm.set_index("Date")["AdjClose"].sort_index()
    days = bench.index                       # IWM sessions = master calendar
    cols = {}
    for t in tickers:
        p = os.path.join(BARS, f"{t}.csv")
        if not os.path.exists(p):
            continue
        s = pd.read_csv(p, parse_dates=["Date"]).set_index("Date")["AdjClose"]
        cols[t] = s.reindex(days)
    px = pd.DataFrame(cols, index=days).sort_index()
    return px, bench


# ── signals ───────────────────────────────────────────────────
def build_signals(px):
    """Month-end signal frame pieces, all computed on data up to the
    signal close only. Returns (me_dates, entry_dates, sig) where sig
    maps hypothesis -> DataFrame indexed by month-end date."""
    days = px.index
    me_dates = [g.index[-1] for _, g in px.groupby([days.year, days.month])]
    me_dates = [d for d in me_dates if days.get_loc(d) + 1 < len(days)]
    mc = px.loc[me_dates]                                # month-end closes
    hist = px.notna().cumsum()                          # sessions of history
    elig = (hist.loc[me_dates] >= MIN_HIST) & mc.notna()  # eligible at signal

    mom = mc.shift(1) / mc.shift(6) - 1                  # H15: months t-6..t-1
    rev = mc / mc.shift(1) - 1                           # H16: prior 1 month
    hi = px / px.rolling(252, min_periods=227).max()     # H17: vs 252d max
    vol = px.pct_change().rolling(60, min_periods=54).std()  # H18: 60d vol
    sig = {"mom": mom, "rev": rev,
           "hi": hi.loc[me_dates], "vol": vol.loc[me_dates]}
    entry = {d: days[days.get_loc(d) + 1] for d in me_dates}
    return me_dates, entry, sig, elig


def picks_for(name, k, me_dates, sig, elig):
    """Up to TOPN names for hypothesis `name` at month-end index k."""
    d = me_dates[k]
    pool = elig.loc[d]
    if name == "H19":
        m, v = sig["mom"].loc[d], sig["vol"].loc[d]
        both = pool & m.notna() & v.notna()
        if both.sum() == 0:
            return []
        blend = (m[both].rank(ascending=False, method="min")
                 + v[both].rank(ascending=True, method="min")) / 2
        return list(blend.sort_values(kind="mergesort").index[:TOPN])
    key, asc = {"H15": ("mom", False), "H16": ("rev", True),
                "H17": ("hi", False), "H18": ("vol", True)}[name]
    s = sig[key].loc[d]
    s = s[pool & s.notna()]
    if len(s) == 0:
        return []
    return list(s.sort_values(ascending=asc, kind="mergesort").index[:TOPN])


# ── simulation ────────────────────────────────────────────────
def simulate(px, periods):
    """periods: list of (entry_date, exit_date, picks). Positions are
    bought at the entry close (first session after the signal month-
    end) and marked on adjclose, forward-filled inside a holding
    period only for marking a halted name. Turnover cost at 5 bps per
    side is charged at each rebalance on |target - drifted| weights.
    Returns (daily equity over px.index, per-period records)."""
    pxf = px.ffill()
    eq = pd.Series(np.nan, index=px.index, dtype=float)
    shares, cash_val, records = {}, CASH0, []
    for entry, exit_, picks in periods:
        # drop picks with no usable entry price; split weight over rest
        live = [s for s in picks if pd.notna(px.at[entry, s])]
        prev_val = (sum(q * pxf.at[entry, s] for s, q in shares.items())
                    if shares else cash_val)
        eq.loc[entry] = prev_val            # mark at entry close, pre-trade
        drift = ({s: q * pxf.at[entry, s] / prev_val for s, q in shares.items()}
                 if shares and prev_val > 0 else {})
        tgt = {s: 1.0 / len(live) for s in live} if live else {}
        turn = sum(abs(tgt.get(s, 0.0) - drift.get(s, 0.0))
                   for s in set(tgt) | set(drift))
        net_val = prev_val * (1 - COST * turn)
        shares = {s: tgt[s] * net_val / px.at[entry, s] for s in live}
        if not shares:
            cash_val = net_val
        window = px.index[(px.index > entry) & (px.index <= exit_)]
        for d in window:
            eq.loc[d] = (sum(q * pxf.at[d, s] for s, q in shares.items())
                         if shares else net_val)
        gross = (float(np.mean([pxf.at[exit_, s] / px.at[entry, s] - 1
                                for s in live])) if live else 0.0)
        records.append(dict(entry=entry, exit=exit_, picks=live,
                            net=float(eq.loc[exit_] / prev_val - 1)
                            if prev_val > 0 else 0.0,
                            gross=gross, turnover=float(turn)))
    return eq.ffill().fillna(CASH0), records


def control(records, px, elig_by_date, seed=SEED):
    """200 random same-size draws per rebalance from the same eligible
    pool (valid entry and exit prices required). Welch t of strategy
    per-rebalance GROSS returns vs per-rebalance control mean returns
    (gross both sides: the control isolates stock picking, costs are
    already in the headline net numbers)."""
    rng = np.random.default_rng(seed)
    pxf = px.ffill()
    strat, ctrl = [], []
    for rec in records:
        e, x, picks = rec["entry"], rec["exit"], rec["picks"]
        if not picks:
            continue
        pool = [s for s in elig_by_date[rec["signal"]]
                if pd.notna(px.at[e, s]) and pd.notna(pxf.at[x, s])]
        if len(pool) < len(picks):
            continue
        rets = np.array([pxf.at[x, s] / px.at[e, s] - 1 for s in pool])
        draws = [float(np.mean(rets[rng.choice(len(pool), size=len(picks),
                                               replace=False)]))
                 for _ in range(N_DRAWS)]
        strat.append(rec["gross"])
        ctrl.append(float(np.mean(draws)))
    t = float(sstats.ttest_ind(strat, ctrl, equal_var=False).statistic) \
        if len(strat) > 1 else 0.0
    return t, len(strat), float(np.mean(strat)), float(np.mean(ctrl))


# ── statistics (house conventions, rounds 3-4) ────────────────
def oos_split(eq):
    cut = eq.index.searchsorted(pd.Timestamp(IS_END))
    return eq.iloc[:cut + 1], eq.iloc[cut:]


def excess_t(strat_oos, bench_oos):
    r = strat_oos.pct_change().dropna()
    m = bench_oos.pct_change().dropna()
    x = (r - m).dropna()
    n, sd = len(x), x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(n))) if sd > 0 and n > 1 else 0.0, n


def t_bar(n):
    """Bonferroni bar over N_TESTS cumulative hypotheses; reproduces
    the round-3 (2.88 @ 13) and round-4 (2.96 @ 16) values."""
    return float(sstats.t.ppf(1 - 0.05 / (2 * N_TESTS), df=n - 1))


def verdict(strat_oos, bench_oos):
    s, b = r1.stats(strat_oos), r1.stats(bench_oos)
    t, n = excess_t(strat_oos, bench_oos)
    bar = t_bar(n)
    ann_excess = s["cagr"] - b["cagr"]
    fails = []
    if ann_excess <= 0:
        fails.append(f"OOS ann. excess {ann_excess:+.1%} <= 0")
    if t < bar:
        fails.append(f"excess-t {t:.2f} < bar {bar:.2f}")
    if s["sharpe"] <= b["sharpe"]:
        fails.append(f"Sharpe {s['sharpe']:.2f} <= IWM {b['sharpe']:.2f}")
    return ("PASS" if not fails else "FAIL"), fails, s, t, bar, ann_excess


def main():
    px, bench = load_panel()
    days = px.index
    print(f"Panel {days[0].date()} -> {days[-1].date()}, "
          f"{px.shape[1]} stocks with bars, {len(days)} sessions")
    me_dates, entry, sig, elig = build_signals(px)
    elig_by_date = {d: list(elig.columns[elig.loc[d]]) for d in me_dates}

    # shared monthly schedule: period k runs entry_k -> entry_{k+1}
    sched = []
    for k in range(len(me_dates)):
        e = entry[me_dates[k]]
        x = entry[me_dates[k + 1]] if k + 1 < len(me_dates) else days[-1]
        if e < pd.Timestamp(EVAL_START):
            continue
        sched.append((k, e, x))
    print(f"{len(sched)} monthly rebalances from {sched[0][1].date()}")

    eval_days = days[days >= pd.Timestamp(EVAL_START)]
    eq_bench = CASH0 * (1 - COST) * bench / bench.loc[eval_days[0]]
    eq_bench = eq_bench.reindex(eval_days)
    _, bench_oos = oos_split(eq_bench)
    sb = r1.stats(bench_oos)
    print(f"IWM buy&hold OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")

    with open(os.path.join("data", "smallcap", "manifest.json")) as f:
        manifest = json.load(f)

    report = {"IWM_BH": dict(oos=dict(cagr=sb["cagr"], sharpe=sb["sharpe"],
                                       max_dd=sb["max_dd"])),
              "manifest": {k: manifest[k] for k in
                           ("n_listed", "n_ok", "n_failed", "benchmark_IWM")}}
    for name in ["H15", "H16", "H17", "H18", "H19"]:
        periods, sig_of = [], {}
        for k, e, x in sched:
            p = picks_for(name, k, me_dates, sig, elig)
            periods.append((e, x, p))
            sig_of[e] = me_dates[k]
        eq_full, records = simulate(px, periods)
        for rec, (e, x, _) in zip(records, periods):
            rec["signal"] = sig_of[e]
        eq = eq_full.reindex(eval_days).ffill().fillna(CASH0)
        is_eq, oos_eq = oos_split(eq)
        v, fails, s, t, bar, ann_ex = verdict(oos_eq, bench_oos)
        si = r1.stats(is_eq)
        line = (f"{name}: rebalances {len(records)} | IS CAGR {si['cagr']:+6.1%} "
                f"Sharpe {si['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
                f"(excess {ann_ex:+6.1%}) Sharpe {s['sharpe']:5.2f} "
                f"t(excess) {t:+5.2f} vs bar {bar:.2f} maxDD {s['max_dd']:5.1%} "
                f"-> {v}" + (f" [{'; '.join(fails)}]" if fails else ""))
        print(line)
        entry_ = dict(verdict=v, fails=fails,
                      oos=dict(cagr=s["cagr"], ann_excess=ann_ex, sharpe=s["sharpe"],
                               t_excess=t, t_bar=bar, max_dd=s["max_dd"],
                               exposure=s["exposure"], rebalances=len(records)),
                      is_=dict(cagr=si["cagr"], sharpe=si["sharpe"],
                               max_dd=si["max_dd"]))
        if name in ("H15", "H17"):
            ct, nper, m_real, m_ctrl = control(records, px, elig_by_date)
            print(f"  {name} control: {nper} rebalances, strategy gross "
                  f"{m_real:+.2%}/rebalance vs random {m_ctrl:+.2%}, "
                  f"Welch t {ct:+.2f}")
            entry_["control"] = dict(welch_t=ct, n_rebalances=nper,
                                     strat_gross_per_rebalance=m_real,
                                     ctrl_gross_per_rebalance=m_ctrl,
                                     draws_per_rebalance=N_DRAWS)
        report[name] = entry_
    with open("data/round5_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round5_report.json")


if __name__ == "__main__":
    main()
