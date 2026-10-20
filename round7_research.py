# ============================================================
#  round7_research.py — Tests PREREGISTRATION_2026-10-20_round7.md
#
#  H24 SPY dip-buying (Connors RSI(2) on the index)
#  H25 ETF tactical rotation (SPY/QQQ/IWM/TLT/GLD, Yahoo)
#  H26 large-cap weekly reversal (universe L)
#  H27 vol-scaled momentum (universe L, H10 selection x BSC scale)
#
#  Written AFTER the pre-registration commit. Costs 5 bps per side
#  everywhere. Signals at close, fills at next open (SPY CSV and
#  universe L); Yahoo series (H25) follow the round-5 adjclose
#  convention. In-sample through 2023-07-06 is context only;
#  verdicts on OOS (2023-07-07 onward) only. PASS requires OOS
#  excess CAGR > 0 AND excess t >= Bonferroni bar (cumulative 29
#  tests) AND OOS Sharpe above the benchmark's.
#    python round7_research.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats as sstats

import daily_research as r1
import round3_research as r3
import round5_research as r5
from round2_data import L

COST       = r1.COST      # 5 bps per side, pre-registered
CASH0      = 2000.0
IS_END     = "2023-07-06"  # OOS starts here (same split as rounds 2-6)
EVAL_START = "2016-01-01"  # round-5 convention (Yahoo legs)
N_TESTS    = 29           # cumulative hypotheses through round 7
TOP_Q      = 17           # H26/H27: quintile of 87, as in H10
TARGET_VOL = 0.10         # H27: Barroso-Santa-Clara target vol
VOL_WIN    = 126          # H27: trailing sessions for basket vol


# ── statistics (house conventions, rounds 3-6) ────────────────
def oos_split(eq):
    cut = eq.index.searchsorted(pd.Timestamp(IS_END))
    return eq.iloc[:cut + 1], eq.iloc[cut:]


def excess_t(strat_oos, bench_oos):
    r = strat_oos.pct_change().dropna()
    m = bench_oos.pct_change().dropna()
    x = (r - m).dropna()
    n, sd = len(x), x.std(ddof=1)
    t = float(x.mean() / (sd / math.sqrt(n))) if sd > 0 and n > 1 else 0.0
    return t, n


def t_bar(n):
    """Bonferroni bar over N_TESTS cumulative hypotheses; same
    formula as rounds 3-6 (2.88 @ 13, 3.10 @ 25)."""
    return float(sstats.t.ppf(1 - 0.05 / (2 * N_TESTS), df=n - 1))


def verdict(strat_oos, bench_oos, bench_name):
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
        fails.append(f"Sharpe {s['sharpe']:.2f} <= {bench_name} {b['sharpe']:.2f}")
    return ("PASS" if not fails else "FAIL"), fails, s, t, bar, ann_excess


def report_line(name, eq, bench_eq, bench_name, extra=""):
    is_eq, oos_eq = oos_split(eq)
    _, bench_oos = oos_split(bench_eq)
    v, fails, s, t, bar, ann_ex = verdict(oos_eq, bench_oos, bench_name)
    si = r1.stats(is_eq)
    print(f"{name}: IS CAGR {si['cagr']:+6.1%} Sharpe {si['sharpe']:5.2f} "
          f"maxDD {si['max_dd']:5.1%} | OOS CAGR {s['cagr']:+6.1%} "
          f"(excess {ann_ex:+6.1%}) Sharpe {s['sharpe']:5.2f} "
          f"t(excess) {t:+5.2f} vs bar {bar:.2f} maxDD {s['max_dd']:5.1%} "
          f"exposure {s['exposure']:4.0%} -> {v}"
          + (f" [{'; '.join(fails)}]" if fails else "") + extra)
    return dict(verdict=v, fails=fails,
                oos=dict(cagr=s["cagr"], ann_excess=ann_ex, sharpe=s["sharpe"],
                         t_excess=t, t_bar=bar, max_dd=s["max_dd"],
                         exposure=s["exposure"]),
                is_=dict(cagr=si["cagr"], sharpe=si["sharpe"],
                         max_dd=si["max_dd"]))


# ── H24: SPY dip-buying, Connors RSI(2) on the index ──────────
def wilder_rsi(close, n=2):
    """Wilder's RSI: seed avg gain/loss with the simple mean of the
    first n changes, then avg = (avg*(n-1) + current)/n. This is the
    standard RSI Connors uses (and the charting-package default)."""
    d = close.diff()
    gain, loss = d.clip(lower=0.0), -d.clip(upper=0.0)
    ag = np.full(len(d), np.nan)
    al = np.full(len(d), np.nan)
    if len(d) > n:
        ag[n] = gain.iloc[1:n + 1].mean()
        al[n] = loss.iloc[1:n + 1].mean()
        gv, lv = gain.values, loss.values
        for i in range(n + 1, len(d)):
            ag[i] = (ag[i - 1] * (n - 1) + gv[i]) / n
            al[i] = (al[i - 1] * (n - 1) + lv[i]) / n
    rs = np.where(al == 0, np.inf, ag / al)
    rsi = np.where(al == 0, 100.0, 100.0 - 100.0 / (1.0 + rs))
    return pd.Series(np.where(np.isnan(ag), np.nan, rsi), index=close.index)


def h24():
    df = pd.read_csv(os.path.join("data", "SPY_1Day.csv"),
                     parse_dates=["timestamp"])
    idx = pd.DatetimeIndex([t.tz_convert("America/New_York").date()
                            for t in df["timestamp"]])
    df = df.set_index(idx).sort_index()
    o, c = df["open"], df["close"]
    days = df.index
    rsi = wilder_rsi(c, 2)
    cash, shares, entry_i = CASH0, 0.0, None
    eq, n_trades = [], 0
    for i in range(len(days)):
        if entry_i is None:
            # entry decided at yesterday's close, filled at today's open
            if i > 0 and pd.notna(rsi.iloc[i - 1]) and rsi.iloc[i - 1] < 10:
                shares = cash / (o.iloc[i] * (1 + COST))
                cash, entry_i = 0.0, i
        else:
            held = (i - 1) - entry_i + 1      # sessions held at prev close
            r_prev = rsi.iloc[i - 1]
            if (pd.notna(r_prev) and r_prev > 70) or held >= 5:
                cash = shares * o.iloc[i] * (1 - COST)
                shares, entry_i = 0.0, None
                n_trades += 1
        eq.append(cash + shares * c.iloc[i])
    eq = pd.Series(eq, index=days)
    sh = CASH0 / (o.iloc[0] * (1 + COST))      # benchmark: SPY B&H, same CSV
    eq_b = sh * c
    print(f"H24 data: SPY_1Day.csv {days[0].date()} -> {days[-1].date()}, "
          f"{len(days)} sessions; {n_trades} round trips")
    return eq, eq_b, n_trades


# ── H25: ETF tactical rotation (Yahoo adjclose, round-5 conv.) ─
ETF_DIR = os.path.join("data", "etf", "bars")
ETFS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]


def h25():
    cols = {}
    for t in ETFS:
        s = pd.read_csv(os.path.join(ETF_DIR, f"{t}.csv"),
                        parse_dates=["Date"]).set_index("Date")["AdjClose"]
        cols[t] = s.sort_index()
    px = pd.DataFrame(cols).sort_index()
    days = px.index
    me_dates = [g.index[-1] for _, g in px.groupby([days.year, days.month])]
    me_dates = [d for d in me_dates if days.get_loc(d) + 1 < len(days)]
    mc = px.loc[me_dates]
    mom = mc.shift(1) / mc.shift(6) - 1            # months t-6..t-1, as H15
    entry = {d: days[days.get_loc(d) + 1] for d in me_dates}
    periods, held_names = [], []
    for k in range(len(me_dates)):
        e = entry[me_dates[k]]
        x = entry[me_dates[k + 1]] if k + 1 < len(me_dates) else days[-1]
        if e < pd.Timestamp(EVAL_START) or k < 6:
            continue
        m = mom.iloc[k].dropna()
        best = m.idxmax() if len(m) else None
        picks = [best] if best is not None and m[best] > 0 else []
        periods.append((e, x, picks))
        held_names.append(best if picks else "CASH")
    eq_full, records = r5.simulate(px, periods)
    eval_days = days[days >= pd.Timestamp(EVAL_START)]
    eq = eq_full.reindex(eval_days).ffill().fillna(CASH0)
    spy = px["SPY"]
    eq_bench = CASH0 * (1 - COST) * spy / spy.loc[eval_days[0]]
    eq_bench = eq_bench.reindex(eval_days)
    n_switch = sum(1 for a, b in zip(held_names, held_names[1:]) if a != b)
    frac = {t: held_names.count(t) / len(held_names) for t in set(held_names)}
    print(f"H25: {len(records)} monthly periods from {periods[0][0].date()}, "
          f"{n_switch} switches; held mix "
          + ", ".join(f"{t} {f:.0%}" for t, f in sorted(frac.items())))
    return eq, eq_bench, len(records), n_switch, frac


# ── shared engine for H26/H27 (round-3 run_monthly, generalised) ─
def run_sched(opens, closes, sched):
    """sched: list of (fill_index, target weights). At each fill
    index, exits first then entries/top-ups at that session's open.
    Unlike round 3's engine there is NO cash cap on buys: H27's
    registered scale can exceed 1.0 (up to 1.5), so the book may run
    a negative cash balance (margin) exactly as the formula says.
    Costs are charged by r1.Book on every trade."""
    b, eq, trades = r1.Book(CASH0, COST), [], []
    held, ptr = {}, 0   # sym -> (entry_fill_index, entry_price, qty)
    days = closes.index
    for i in range(len(days)):
        if ptr < len(sched) and i == sched[ptr][0]:
            tgt, o = sched[ptr][1], opens.iloc[i]
            prev_eq = b.value(closes.iloc[i - 1])
            for s in list(held):                      # exits first
                if s not in tgt:
                    e_i, e_px, q = held.pop(s)
                    b.trade(s, -q, o[s])
                    trades.append(dict(symbol=s,
                                       entry=days[e_i].date().isoformat(),
                                       exit=days[i].date().isoformat(),
                                       net=float(o[s] * (1 - COST) /
                                                 (e_px * (1 + COST)) - 1)))
            for s, w in tgt.items():                  # entries + top-ups
                want = w * prev_eq / o[s]
                have = held[s][2] if s in held else 0.0
                d = want - have
                if abs(d) > 1e-9:
                    b.trade(s, d, o[s])
                    held[s] = (held[s][0], held[s][1], held[s][2] + d) \
                        if s in held else (i, o[s], d)
            for s in list(held):                      # drop dust
                if abs(held[s][2]) < 1e-9:
                    del held[s]
            ptr += 1
        eq.append(b.value(closes.iloc[i]))
    return pd.Series(eq, index=days), pd.DataFrame(trades)


# ── H26: large-cap weekly reversal (universe L) ───────────────
def h26(opens, closes):
    days = closes.index
    px = closes[L]
    form = px / px.shift(5) - 1                       # prior 5 sessions
    # signal sessions: last session of each ISO week
    iso = pd.DataFrame({"y": days.isocalendar().year.values,
                        "w": days.isocalendar().week.values}, index=days)
    key = iso["y"] * 100 + iso["w"]
    sig_idx = [i for i in range(len(days) - 1) if key.iloc[i + 1] != key.iloc[i]]
    sched = []
    for i in sig_idx:
        f = form.iloc[i].dropna()
        if len(f) < TOP_Q:
            continue
        worst = f.sort_values(kind="mergesort").index[:TOP_Q]
        sched.append((i + 1, {s: 1.0 / len(worst) for s in worst}))
    eq, trades = run_sched(opens, closes, sched)
    print(f"H26: {len(sched)} weekly rebalances, {len(trades)} position exits")
    return eq, trades, len(sched)


# ── H27: vol-scaled momentum (universe L, H10 selection) ──────
def h27(opens, closes):
    days = closes.index
    mc = closes.resample("ME").last()
    me_days = [days.get_loc(d) for d in mc.index if d in closes.index]
    me_days = [i for i in me_days if i + 1 < len(days)]
    me_pos = {d: p for p, d in enumerate(mc.index)}
    rets = closes[L].pct_change()
    sched, scales = [], []
    for i in me_days:
        k = me_pos[days[i]]
        sel_w = r3.h10_choose(k, mc)                  # H10 exactly
        if not sel_w:
            sched.append((i + 1, {}))
            continue
        names = list(sel_w)
        basket = rets[names].iloc[max(0, i - VOL_WIN + 1):i + 1] \
            .mean(axis=1).dropna()
        if len(basket) >= 60 and basket.std(ddof=1) > 0:
            vol = float(basket.std(ddof=1) * math.sqrt(252))
            scale = min(1.5, max(0.5, TARGET_VOL / vol))
        else:
            scale = 1.0       # documented fallback: <60 sessions of history
        scales.append(scale)
        sched.append((i + 1, {s: w * scale for s, w in sel_w.items()}))
    eq, trades = run_sched(opens, closes, sched)
    print(f"H27: {len(scales)} scaled rebalances, mean scale "
          f"{np.mean(scales):.2f}, min {np.min(scales):.2f}, "
          f"max {np.max(scales):.2f}, scale>1 in "
          f"{np.mean([s > 1 for s in scales]):.0%} of months; "
          f"{len(trades)} position exits")
    return eq, trades, scales


def main():
    report = {}

    # SPY benchmark from the universe-L panel (H26/H27), round-3 style
    opens, closes = r3.load()
    days = closes.index
    print(f"Universe L panel {days[0].date()} -> {days[-1].date()}, "
          f"{len(L)} stocks + SPY")
    eq_spy = r3.spy_bh(opens, closes)
    _, spy_oos = oos_split(eq_spy)
    sb = r1.stats(spy_oos)
    print(f"SPY buy&hold OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")
    report["SPY_BH"] = dict(oos=dict(cagr=sb["cagr"], sharpe=sb["sharpe"],
                                     max_dd=sb["max_dd"]))

    # H24 (benchmark: SPY B&H from SPY_1Day.csv)
    eq24, eq24_b, n24 = h24()
    _, b24_oos = oos_split(eq24_b)
    s24b = r1.stats(b24_oos)
    print(f"SPY buy&hold (CSV) OOS: CAGR {s24b['cagr']:+.1%} "
          f"Sharpe {s24b['sharpe']:.2f} maxDD {s24b['max_dd']:.1%}")
    report["SPY_BH_CSV"] = dict(oos=dict(cagr=s24b["cagr"],
                                         sharpe=s24b["sharpe"],
                                         max_dd=s24b["max_dd"]))
    report["H24"] = report_line("H24", eq24, eq24_b, "SPY")
    report["H24"]["oos"]["round_trips_total"] = n24

    # H25 (benchmark: SPY B&H, Yahoo adjclose)
    eq25, eq25_b, nper25, nsw25, frac25 = h25()
    _, b25_oos = oos_split(eq25_b)
    s25b = r1.stats(b25_oos)
    print(f"SPY buy&hold (Yahoo) OOS: CAGR {s25b['cagr']:+.1%} "
          f"Sharpe {s25b['sharpe']:.2f} maxDD {s25b['max_dd']:.1%}")
    report["SPY_BH_YAHOO"] = dict(oos=dict(cagr=s25b["cagr"],
                                           sharpe=s25b["sharpe"],
                                           max_dd=s25b["max_dd"]))
    report["H25"] = report_line("H25", eq25, eq25_b, "SPY")
    report["H25"]["oos"]["periods"] = nper25
    report["H25"]["oos"]["switches"] = nsw25
    report["H25"]["held_mix"] = {t: float(f) for t, f in frac25.items()}

    # H26
    eq26, tr26, nreb26 = h26(opens, closes)
    report["H26"] = report_line("H26", eq26, eq_spy, "SPY",
                                extra=f" | exits {len(tr26)}")
    report["H26"]["oos"]["rebalances"] = nreb26
    report["H26"]["oos"]["position_exits"] = int(len(tr26))

    # H27
    eq27, tr27, scales27 = h27(opens, closes)
    report["H27"] = report_line("H27", eq27, eq_spy, "SPY",
                                extra=f" | exits {len(tr27)}")
    report["H27"]["oos"]["position_exits"] = int(len(tr27))
    report["H27"]["scale"] = dict(mean=float(np.mean(scales27)),
                                  min=float(np.min(scales27)),
                                  max=float(np.max(scales27)),
                                  frac_above_1=float(np.mean(
                                      [s > 1 for s in scales27])))

    with open("data/round7_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round7_report.json")


if __name__ == "__main__":
    main()
