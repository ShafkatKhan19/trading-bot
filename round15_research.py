# ============================================================
#  round15_research.py — Tests PREREGISTRATION_2026-10-23_
#  round15.md
#
#  H52 small-cap insider cluster buying: at each month-end,
#  Universe S names where >=3 distinct reporting owners filed
#  Form 4 open-market purchases (code P) within the trailing
#  90 days (usable only on/after FILING_DATE), ranked by buyer
#  breadth, then purchase dollars, then recency; top 60 equal
#  weight (all of them if 1-59 qualify; cash if none).
#
#  Written AFTER the pre-registration commit (f69879e local /
#  f0af6b6 on GitHub). Engine: round-5 small-cap (Yahoo
#  adjclose, signal at month-end close, returns from the next
#  session's close, 5 bps/side on turnover, benchmark IWM).
#  Price eligibility: >=252 sessions of history + a price on
#  the signal date (round-5 rule). Coverage cutoff per the
#  registration: signals only for month-ends <= LASTDATE (max
#  FILING_DATE in the SEC bulk archives); the book targets
#  cash from the first later month-end. Verdicts OOS
#  2023-07-07 onward; in-sample context only. Control: the
#  round-5 horizon-matched random-draw control (context only).
#    python round15_research.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats as sstats

import daily_research as r1
import round5_research as r5

COST = r1.COST            # 5 bps per side, pre-registered
CASH0 = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-14)
EVAL_START = "2016-01-01"
N_TESTS = 54              # cumulative hypotheses through round 15
BAR_REGISTERED = 3.33     # pre-registered bar (formula checked below)
TOP_S = 60                # ~10% of Universe S (round-9 book size)
WINDOW_DAYS = 90          # trailing cluster window, registered
MIN_BUYERS = 3            # cluster = >=3 distinct owners, registered
SEED = 20261023

FILINGS = os.path.join("data", "insider_sc", "cluster_filings.csv")
COVERAGE = os.path.join("data", "insider_sc", "coverage.json")


# ── statistics (house conventions, rounds 9-14) ──────────────
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
    return float(sstats.t.ppf(1 - 0.05 / (2 * N_TESTS), df=n - 1))


def verdict(strat_oos, bench_oos):
    s, b = r1.stats(strat_oos), r1.stats(bench_oos)
    t, n = excess_t(strat_oos, bench_oos)
    bar = bonf_bar(n)
    ann_excess = s["cagr"] - b["cagr"]
    fails = []
    if ann_excess <= 0:
        fails.append(f"OOS excess CAGR {ann_excess:+.1%} <= 0")
    if t < bar:
        fails.append(f"excess-t {t:.2f} < {bar:.2f}")
    if s["sharpe"] <= b["sharpe"]:
        fails.append(f"Sharpe {s['sharpe']:.2f} <= IWM {b['sharpe']:.2f}")
    return ("PASS" if not fails else "FAIL"), fails, s, t, bar, ann_excess


# ── cluster signal ───────────────────────────────────────────
def load_clusters():
    df = pd.read_csv(FILINGS, parse_dates=["filing_date"])
    out = {}
    for t, g in df.groupby("ticker"):
        g = g.sort_values("filing_date")
        out[t] = {
            "dates": g["filing_date"].to_numpy(),
            "owners": [set(str(o).split(";")) if pd.notna(o) and o
                       else set() for o in g["owners"]],
            "usd": g["buy_usd"].to_numpy(dtype=float),
            "last": g["filing_date"].to_numpy(),
        }
    return out


def cluster_snapshot(cl, asof):
    """{ticker: (n_buyers, buy_usd, last_filed)} for purchase
    filings with FILING_DATE in (asof-90d, asof]."""
    lo = (asof - pd.Timedelta(days=WINDOW_DAYS)).to_datetime64()
    hi = asof.to_datetime64()
    out = {}
    for t, d in cl.items():
        j = np.searchsorted(d["dates"], hi, side="right")
        i = np.searchsorted(d["dates"], lo, side="right")
        if j <= i:
            continue
        owners = set()
        for s in d["owners"][i:j]:
            owners |= s
        out[t] = (len(owners), float(d["usd"][i:j].sum()),
                  pd.Timestamp(d["last"][j - 1]))
    return out


def main():
    with open(COVERAGE) as f:
        cov = json.load(f)
    lastdate = pd.Timestamp(cov["lastdate"])
    cl = load_clusters()
    print(f"Purchase filings: {cov['purchase_filings']} across "
          f"{cov['purchase_tickers']} tickers; LASTDATE {cov['lastdate']} "
          f"({cov['n_archives']} archives, "
          f"{cov['form4_filings_total']} Form 4 filings scanned)")

    px, bench = r5.load_panel()
    days = px.index
    print(f"Small-cap panel {days[0].date()} -> {days[-1].date()}, "
          f"{px.shape[1]} stocks with bars")
    me_dates = [g.index[-1] for _, g in px.groupby([days.year, days.month])]
    me_dates = [d for d in me_dates if days.get_loc(d) + 1 < len(days)]
    entry = {d: days[days.get_loc(d) + 1] for d in me_dates}
    hist = px.notna().cumsum()
    mc = px.loc[me_dates]

    # per-signal-date cluster picks + price-eligible pools
    picks_by_date, elig_pool, elig_counts = {}, {}, {}
    for d in me_dates:
        pool = [t for t in px.columns
                if hist.at[d, t] >= r5.MIN_HIST and pd.notna(mc.at[d, t])]
        elig_pool[d] = pool
        if d > lastdate:
            picks_by_date[d] = []          # coverage cutoff -> cash
            continue
        snap = cluster_snapshot(cl, d)
        rows = [(t, v[0], v[1], v[2]) for t, v in snap.items()
                if t in pool and v[0] >= MIN_BUYERS]
        elig_counts[d] = len(rows)
        rows.sort(key=lambda x: (-x[1], -x[2], -x[3].value, x[0]))
        picks_by_date[d] = [r[0] for r in rows[:TOP_S]]

    sched = []
    for k in range(len(me_dates)):
        e = entry[me_dates[k]]
        x = entry[me_dates[k + 1]] if k + 1 < len(me_dates) else days[-1]
        if e < pd.Timestamp(EVAL_START):
            continue
        sched.append((k, e, x))
    periods, sig_of = [], {}
    for k, e, x in sched:
        periods.append((e, x, picks_by_date[me_dates[k]]))
        sig_of[e] = me_dates[k]
    print(f"{len(sched)} monthly rebalances from {sched[0][1].date()}; "
          f"cluster-eligible names per invested month-end: "
          f"min {min(elig_counts.values())}, median "
          f"{int(np.median(list(elig_counts.values())))}, max "
          f"{max(elig_counts.values())}; months with <{TOP_S} eligible: "
          f"{sum(1 for v in elig_counts.values() if v < TOP_S)} of "
          f"{len(elig_counts)}")

    eq_full, records = r5.simulate(px, periods)
    for rec, (e, x, _) in zip(records, periods):
        rec["signal"] = sig_of[e]
    eval_days = days[days >= pd.Timestamp(EVAL_START)]
    eq = eq_full.reindex(eval_days).ffill().fillna(CASH0)

    eq_bench = CASH0 * (1 - COST) * bench / bench.loc[eval_days[0]]
    eq_bench = eq_bench.reindex(eval_days)
    _, bench_oos = oos_split(eq_bench)
    sb = r1.stats(bench_oos)
    print(f"IWM B&H OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")

    is_eq, oos_eq = oos_split(eq)
    v, fails, s, t, bar, ann_ex = verdict(oos_eq, bench_oos)
    si = r1.stats(is_eq)
    ct, nper, m_real, m_ctrl = r5.control(records, px, elig_pool,
                                          seed=SEED)
    print(f"H52: rebalances {len(records)} | IS CAGR {si['cagr']:+6.1%} "
          f"Sharpe {si['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
          f"(excess {ann_ex:+6.1%}) Sharpe {s['sharpe']:5.2f} "
          f"t(excess) {t:+5.2f} vs bar {bar:.2f} maxDD {s['max_dd']:5.1%} "
          f"-> {v}" + (f" [{'; '.join(fails)}]" if fails else ""))
    print(f"   control (horizon-matched, same-size random draws from "
          f"the price-eligible pool): {nper} rebalances, strategy gross "
          f"{m_real:+.2%}/rebalance vs random {m_ctrl:+.2%}, "
          f"Welch t {ct:+.2f}")

    report = {
        "n_tests_cumulative": N_TESTS,
        "bar_registered": BAR_REGISTERED,
        "coverage": cov,
        "IWM_BH": dict(oos=dict(cagr=sb["cagr"], sharpe=sb["sharpe"],
                                max_dd=sb["max_dd"])),
        "H52": dict(
            verdict=v, fails=fails,
            oos=dict(cagr=s["cagr"], ann_excess=ann_ex,
                     sharpe=s["sharpe"], t_excess=t, bar=bar,
                     max_dd=s["max_dd"], rebalances=len(records)),
            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
            control=dict(welch_t=ct, n_rebalances=nper,
                         strat_gross_per_rebalance=m_real,
                         ctrl_gross_per_rebalance=m_ctrl,
                         method="round-5 control: 200 random same-size "
                                "draws per rebalance from the "
                                "price-eligible Universe S pool, same "
                                "entry/exit dates (horizon-matched)"),
            cluster_eligible_per_month=dict(
                min=int(min(elig_counts.values())),
                median=float(np.median(list(elig_counts.values()))),
                max=int(max(elig_counts.values())),
                months_below_topn=int(sum(
                    1 for x in elig_counts.values() if x < TOP_S)),
                months_total=int(len(elig_counts)))),
    }
    with open("data/round15_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round15_report.json")


if __name__ == "__main__":
    main()
