# ============================================================
#  round12_research.py — Tests PREREGISTRATION_2026-10-20_
#  round12.md
#
#  H44 combined value book        H45 yield-curve regime
#  H46 multi-asset inverse-vol
#
#  Written AFTER the pre-registration commit. H44 reconstructs
#  its two legs through the ORIGINAL code paths — H29 via
#  round8_research (universe L, top 26 earnings yield, next-
#  open fills) and H43 via round11_research.run_smallcap_blend
#  (universe S, top 60 EY+B/M blend, round-5 adjclose engine) —
#  each on its native $2,000, halved and summed (both engines
#  are exactly linear in starting capital: fractional shares,
#  purely proportional costs). Benchmark: the same halving of
#  each leg's own round benchmark (SPY B&H from round 8, IWM
#  B&H in round-11 construction). Leg OOS stats are checked
#  against the published round-8/round-11 reports.
#  H45/H46 run on the cached Yahoo ETF bars (round 7) with
#  dividend-adjusted prices (AdjClose; opens scaled by the
#  AdjClose/Close ratio) and next-open fills through a
#  schedule-driven copy of the round-3/8 monthly engine.
#  H45's only new data is FRED T10Y2Y (public, no key), saved
#  under data/macro/. 5 bps/side everywhere; verdicts OOS
#  2023-07-07 onward; in-sample is context only.
#    python round12_research.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats as sstats

import daily_research as r1
import round5_research as r5
import round8_research as r8
import round11_research as r11

COST = r1.COST            # 5 bps per side, pre-registered
CASH0 = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-11)
EVAL_START = "2016-01-01"
N_TESTS = 48              # cumulative hypotheses through round 12
BAR_REGISTERED = 3.31     # pre-registered bar (formula checked below)
ETF_DIR = os.path.join("data", "etf", "bars")
FRED_CSV = os.path.join("data", "macro", "T10Y2Y.csv")
CTRL_NOTE = ("not reported: combination of two already-tested "
             "books (H44) / single-asset timing and defensive "
             "books follow the rounds 7-11 no-control convention")


# ── statistics (house conventions, rounds 9-11) ──────────────
def oos_split(eq):
    cut = eq.index.searchsorted(pd.Timestamp(IS_END))
    return eq.iloc[:cut + 1], eq.iloc[cut:]


def excess_t(strat_oos, bench_oos):
    r = strat_oos.pct_change().dropna()
    m = bench_oos.pct_change().dropna()
    x = (r - m).dropna()
    n, sd = len(x), x.std(ddof=1)
    return (float(x.mean() / (sd / math.sqrt(n)))
            if sd > 0 and n > 1 else 0.0), n


def bonf_bar(n):
    """Bonferroni one-sided bar; same formula as rounds 3-11."""
    return float(sstats.t.ppf(1 - 0.05 / (2 * N_TESTS), df=n - 1))


def verdict(strat_oos, bench_oos, bench_name):
    s, b = r1.stats(strat_oos), r1.stats(bench_oos)
    t, n = excess_t(strat_oos, bench_oos)
    bar = bonf_bar(n)
    fails = []
    if s["cagr"] <= b["cagr"]:
        fails.append(f"OOS excess CAGR {s['cagr'] - b['cagr']:+.1%} <= 0")
    if t < bar:
        fails.append(f"excess-t {t:.2f} < {bar:.2f}")
    if s["sharpe"] <= b["sharpe"]:
        fails.append(f"Sharpe {s['sharpe']:.2f} <= {bench_name} "
                     f"{b['sharpe']:.2f}")
    return ("PASS" if not fails else "FAIL"), fails, s, t, bar


def entry_for(v, fails, s, t, bar, is_eq, extra=None):
    si = r1.stats(is_eq)
    e = dict(verdict=v, fails=fails,
             oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                      bar=bar, max_dd=s["max_dd"]),
             is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
             control=None, control_note=CTRL_NOTE)
    if extra:
        e.update(extra)
    return e


# ── H44: legs through the original code paths ────────────────
def h44_legs():
    # Leg 1: H29 exactly as round 8 tested it ($2,000 native).
    opens_l, closes_l = r8.load_prices()
    eq_h29, _tr = r8.run_monthly(opens_l, closes_l,
                                 r8.make_choose("H29"))
    eq_spy = r8.spy_bh(opens_l, closes_l)

    # Leg 2: H43 exactly as round 11 tested it ($2,000 native).
    px, bench = r5.load_panel()
    eq_full, _records, _elig = r11.run_smallcap_blend(px)
    eval_days = px.index[px.index >= pd.Timestamp(EVAL_START)]
    eq_h43 = eq_full.reindex(eval_days).ffill().fillna(CASH0)
    eq_iwm = CASH0 * (1 - COST) * bench / bench.loc[eval_days[0]]
    eq_iwm = eq_iwm.reindex(eval_days)
    return eq_h29, eq_spy, eq_h43, eq_iwm


def leg_check(name, eq, bench_eq, published):
    """Reconstructed leg OOS stats vs the published report."""
    _, oos = oos_split(eq)
    _, boos = oos_split(bench_eq)
    s = r1.stats(oos)
    t, _n = excess_t(oos, boos)
    got = dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t)
    delta = {k: abs(got[k] - published[k]) for k in got}
    print(f"{name} reconstruction: CAGR {got['cagr']:+.2%} "
          f"(published {published['cagr']:+.2%}), Sharpe "
          f"{got['sharpe']:.3f} (published {published['sharpe']:.3f}), "
          f"t {got['t_excess']:+.3f} (published "
          f"{published['t_excess']:+.3f}); max |delta| "
          f"{max(delta.values()):.2e}")
    return got, delta


# ── H45/H46: ETF bars, adjusted prices, next-open fills ──────
def load_etf():
    op, cl = {}, {}
    for t in ["SPY", "TLT", "GLD"]:
        df = pd.read_csv(os.path.join(ETF_DIR, f"{t}.csv"),
                         parse_dates=["Date"]).set_index("Date")
        df = df.sort_index()
        ratio = df["AdjClose"] / df["Close"]
        op[t] = df["Open"] * ratio          # dividend-adjusted open
        cl[t] = df["AdjClose"]              # dividend-adjusted close
    opens = pd.DataFrame(op).sort_index()
    closes = pd.DataFrame(cl).sort_index()
    return opens, closes


def run_monthly_sched(opens, closes, sched):
    """Round-3/8 monthly engine mechanics driven by an explicit
    schedule of (fill_index, target weights): at each fill
    session, exits first at the open, then entries/top-ups at
    the open with buys capped at available cash; equity marked
    at every close. (r8.run_monthly with the schedule hoisted
    out of the choose callback.)"""
    days = closes.index
    b, eq, trades = r1.Book(CASH0, COST), [], []
    held, ptr = {}, 0
    for i in range(len(days)):
        if ptr < len(sched) and i == sched[ptr][0]:
            tgt, o = sched[ptr][1], opens.iloc[i]
            prev_eq = b.value(closes.iloc[i - 1])
            for s in list(held):
                if s not in tgt:
                    e_i, e_px, q = held.pop(s)
                    b.trade(s, -q, o[s])
                    trades.append(dict(
                        symbol=s, entry=days[e_i].date().isoformat(),
                        exit=days[i].date().isoformat(),
                        net=float(o[s] * (1 - COST)
                                  / (e_px * (1 + COST)) - 1)))
            for s, w in tgt.items():
                want = w * prev_eq / o[s]
                have = held[s][2] if s in held else 0.0
                d = want - have
                if d > 0:
                    d = min(d, max(0.0, b.cash) / (o[s] * (1 + COST)))
                if abs(d) > 1e-9:
                    b.trade(s, d, o[s])
                    held[s] = (held[s][0], held[s][1], held[s][2] + d) \
                        if s in held else (i, o[s], d)
            for s in list(held):
                if abs(held[s][2]) < 1e-9:
                    del held[s]
            ptr += 1
        eq.append(b.value(closes.iloc[i]))
    return pd.Series(eq, index=days), pd.DataFrame(trades)


def month_end_idx(days):
    mc = days.to_series().groupby([days.year, days.month]).last()
    idx = [days.get_loc(d) for d in mc.values if d in days]
    return [i for i in idx if i + 1 < len(days)]


def load_fred():
    raw = pd.read_csv(FRED_CSV)
    date_col, val_col = raw.columns[0], raw.columns[1]
    s = pd.Series(pd.to_numeric(raw[val_col], errors="coerce").values,
                  index=pd.to_datetime(raw[date_col])).sort_index()
    return s.dropna()


def h45(days, fred):
    """Schedule + regime record. Signal for the month following
    month-end k: T10Y2Y as of the PRIOR calendar month-end
    (last observation on or before it) — a full one-month lag."""
    me = month_end_idx(days)
    sched, regime = [], []
    for i in me:
        d = days[i]
        prev_me = pd.Timestamp(d.year, d.month, 1) - pd.Timedelta(days=1)
        j = fred.index.searchsorted(prev_me, side="right") - 1
        if j < 0:
            continue
        val = float(fred.iloc[j])
        asset = "SPY" if val >= 0 else "TLT"
        sched.append((i + 1, {asset: 1.0}))
        regime.append(dict(signal_month_end=d.date().isoformat(),
                           lagged_spread=val, hold=asset))
    return sched, regime


def h46(closes):
    """Schedule: weights ∝ 1/trailing-60-session vol at the
    signal close; cash until all three assets have 60 returns."""
    days = closes.index
    rets = closes.pct_change()
    me = month_end_idx(days)
    sched, weights_hist = [], []
    for i in me:
        if i < 60:
            sched.append((i + 1, {}))
            continue
        vol = rets.iloc[i - 59:i + 1].std(ddof=1)
        if vol.isna().any() or (vol <= 0).any():
            sched.append((i + 1, {}))
            continue
        inv = 1.0 / vol
        w = inv / inv.sum()
        tgt = {t: float(w[t]) for t in ["SPY", "TLT", "GLD"]}
        sched.append((i + 1, tgt))
        weights_hist.append(tgt)
    return sched, weights_hist


def main():
    report = {"n_tests_cumulative": N_TESTS,
              "bar_registered": BAR_REGISTERED}

    # ── H44 ──────────────────────────────────────────────────
    eq_h29, eq_spy_l, eq_h43, eq_iwm = h44_legs()
    pub8 = json.load(open("data/round8_report.json"))["H29"]["oos"]
    pub11 = json.load(open("data/round11_report.json"))["H43"]["oos"]
    got29, d29 = leg_check("H29 leg", eq_h29, eq_spy_l,
                           dict(cagr=pub8["cagr"], sharpe=pub8["sharpe"],
                                t_excess=pub8["t_excess"]))
    got43, d43 = leg_check("H43 leg", eq_h43, eq_iwm,
                           dict(cagr=pub11["cagr"],
                                sharpe=pub11["sharpe"],
                                t_excess=pub11["t_excess"]))
    report["H44_leg_reconstruction"] = {
        "H29": dict(reconstructed=got29,
                    max_abs_delta=max(d29.values())),
        "H43": dict(reconstructed=got43,
                    max_abs_delta=max(d43.values())),
        "method": "legs run at native $2,000 through the original "
                  "round-8 / round-11 code paths, halved and "
                  "summed; engines are exactly linear in starting "
                  "capital (fractional shares, proportional "
                  "costs). Benchmark legs halved identically."}

    common = eq_h29.index.intersection(eq_h43.index)
    eq44 = (0.5 * eq_h29.reindex(common).ffill()
            + 0.5 * eq_h43.reindex(common).ffill())
    bench44 = (0.5 * eq_spy_l.reindex(common).ffill()
               + 0.5 * eq_iwm.reindex(common).ffill())
    print(f"H44 combined calendar: {common[0].date()} -> "
          f"{common[-1].date()}, {len(common)} sessions")
    is44, oos44 = oos_split(eq44)
    bis44, boos44 = oos_split(bench44)
    bb = r1.stats(boos44)
    print(f"Blend B&H OOS: CAGR {bb['cagr']:+.1%} "
          f"Sharpe {bb['sharpe']:.2f} maxDD {bb['max_dd']:.1%}")
    report["BLEND_BH"] = dict(oos=dict(cagr=bb["cagr"],
                                       sharpe=bb["sharpe"],
                                       max_dd=bb["max_dd"]))
    v, fails, s, t, bar = verdict(oos44, boos44, "blend")
    si = r1.stats(is44)
    print(f"H44: IS CAGR {si['cagr']:+6.1%} Sharpe {si['sharpe']:5.2f} | "
          f"OOS CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} "
          f"t(excess) {t:+5.2f} (bar {bar:.2f}) maxDD {s['max_dd']:5.1%} "
          f"-> {v}" + (f" [{'; '.join(fails)}]" if fails else ""))
    report["H44"] = entry_for(v, fails, s, t, bar, is44)

    # ── H45 / H46 ────────────────────────────────────────────
    opens, closes = load_etf()
    days = closes.index
    print(f"ETF bars {days[0].date()} -> {days[-1].date()}, "
          f"{len(days)} sessions (SPY/TLT/GLD, adjusted)")
    fred = load_fred() if os.path.exists(FRED_CSV) else None
    if fred is not None:
        print(f"FRED T10Y2Y {fred.index[0].date()} -> "
              f"{fred.index[-1].date()}, {len(fred)} observations")
    report["data"] = dict(
        etf_start=days[0].date().isoformat(),
        etf_end=days[-1].date().isoformat(),
        fred_start=(fred.index[0].date().isoformat()
                    if fred is not None else None),
        fred_end=(fred.index[-1].date().isoformat()
                  if fred is not None else None),
        fred_obs=(int(len(fred)) if fred is not None else 0))

    eq_bench_etf = r8.spy_bh(opens, closes)
    ev = days >= pd.Timestamp(EVAL_START)
    bench_ev = eq_bench_etf[ev]
    _, bench_oos = oos_split(bench_ev)
    sb = r1.stats(bench_oos)
    print(f"SPY B&H (ETF bars) OOS: CAGR {sb['cagr']:+.1%} "
          f"Sharpe {sb['sharpe']:.2f} maxDD {sb['max_dd']:.1%}")
    report["SPY_BH_ETF"] = dict(oos=dict(cagr=sb["cagr"],
                                         sharpe=sb["sharpe"],
                                         max_dd=sb["max_dd"]))

    # H45 — runs only if the fetched FRED series is on disk. On
    # 2026-10-20 the fredgraph endpoint was unreachable from this
    # VM (repeated zero-byte timeouts on direct fetch; the text-
    # fetch route returned HTTP 403), so no series could be
    # saved and H45 is recorded NOT TESTED rather than run on
    # substitute data. h45() above is the registered
    # implementation, ready to run unchanged when the series
    # exists. See RESULTS_2026-10-20_round12.md.
    if os.path.exists(FRED_CSV):
        sched45, regime = h45(days, fred)
        eq45_full, tr45 = run_monthly_sched(opens, closes, sched45)
        eq45 = eq45_full[ev]
        is45, oos45 = oos_split(eq45)
        v, fails, s, t, bar = verdict(oos45, bench_oos, "SPY")
        n_tlt = sum(1 for r in regime if r["hold"] == "TLT")
        n_switch = sum(1 for a, b in zip(regime, regime[1:])
                       if a["hold"] != b["hold"])
        si = r1.stats(is45)
        print(f"H45: {len(regime)} monthly signals, {n_tlt} in TLT, "
              f"{n_switch} switches | IS CAGR {si['cagr']:+6.1%} "
              f"Sharpe {si['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
              f"Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
              f"(bar {bar:.2f}) maxDD {s['max_dd']:5.1%} -> {v}"
              + (f" [{'; '.join(fails)}]" if fails else ""))
        report["H45"] = entry_for(
            v, fails, s, t, bar, is45,
            extra=dict(months_total=len(regime), months_tlt=n_tlt,
                       switches=n_switch, trades=len(tr45),
                       regime=regime))
    else:
        print("H45: NOT TESTED — FRED T10Y2Y series unavailable "
              "(fredgraph unreachable from this VM on 2026-10-20; "
              "see results file). No substitute data used.")
        report["H45"] = dict(
            verdict="NOT TESTED",
            reason="FRED T10Y2Y could not be fetched: repeated "
                   "direct fetches of fredgraph.csv timed out "
                   "with zero bytes received, and the text-fetch "
                   "route returned HTTP 403. No substitute or "
                   "reconstructed series was used, so the "
                   "registered test was not run.")

    # H46
    sched46, weights_hist = h46(closes)
    eq46_full, tr46 = run_monthly_sched(opens, closes, sched46)
    eq46 = eq46_full[ev]
    is46, oos46 = oos_split(eq46)
    v, fails, s, t, bar = verdict(oos46, bench_oos, "SPY")
    mean_w = {a: float(np.mean([w[a] for w in weights_hist]))
              for a in ["SPY", "TLT", "GLD"]}
    si = r1.stats(is46)
    print(f"H46: {len(weights_hist)} invested rebalances, mean weights "
          + ", ".join(f"{a} {mean_w[a]:.0%}" for a in mean_w)
          + f" | IS CAGR {si['cagr']:+6.1%} Sharpe {si['sharpe']:5.2f} "
          f"| OOS CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} "
          f"t(excess) {t:+5.2f} (bar {bar:.2f}) maxDD {s['max_dd']:5.1%} "
          f"-> {v}" + (f" [{'; '.join(fails)}]" if fails else ""))
    report["H46"] = entry_for(
        v, fails, s, t, bar, is46,
        extra=dict(rebalances=len(weights_hist), mean_weights=mean_w,
                   trades=len(tr46)))

    with open("data/round12_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round12_report.json")


if __name__ == "__main__":
    main()
