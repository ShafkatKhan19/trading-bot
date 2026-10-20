# ============================================================
#  round9_research.py — Tests PREREGISTRATION_2026-10-20_round9.md
#
#  H32 small-cap earnings yield    H33 small-cap book-to-market
#  H34 buyback yield (univ. L)     H35 low accruals (univ. L)
#
#  Written AFTER the pre-registration commit. Fundamentals are
#  SEC EDGAR fiscal-year facts, strictly point-in-time (a row
#  is usable once ALL its facts are public, i.e. on/after the
#  max of their `filed` dates; earliest filing per period).
#  H32/H33 use the round-5 small-cap engine (Yahoo adjclose,
#  signal at month-end, returns from the next session's close,
#  5 bps/side, benchmark IWM). H34/H35 use the round-3/8
#  universe-L engine (fills at next open, benchmark SPY).
#    python round9_research.py
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
from round2_data import L

COST = r1.COST            # 5 bps per side, pre-registered
CASH0 = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-8)
EVAL_START = "2016-01-01"
N_TESTS = 37              # cumulative hypotheses through round 9
SEED = 20261020
TOP_L = 26                # universe-L books (rounds 3/8)
TOP_S = 60                # small-cap books (~10% of ~600)

PANEL_SC = os.path.join("data", "fundamentals", "panel_smallcap.csv")
PANEL_V2 = os.path.join("data", "fundamentals", "panel_l_v2.csv")


# ── statistics (house conventions) ───────────────────────────
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
    """Bonferroni one-sided bar; same formula as rounds 3-8."""
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


# ============================================================
#  H34 / H35 — universe L, round-3/8 monthly engine
# ============================================================
def load_panel_v2():
    """H35 panel: rows usable once ALL FIVE facts are public."""
    df = pd.read_csv(PANEL_V2, parse_dates=[
        "fy_end", "filed_ni", "filed_eq", "filed_sh",
        "filed_assets", "filed_ocf"])
    df = df.dropna(subset=["net_income", "equity", "shares",
                           "assets", "ocf"])
    df["filed_all"] = df[["filed_ni", "filed_eq", "filed_sh",
                          "filed_assets", "filed_ocf"]].max(axis=1)
    out = {}
    for t, g in df.groupby("ticker"):
        out[t] = g.sort_values("filed_all").reset_index(drop=True)
    return out


FUND_V2 = load_panel_v2()


def _latest(g, asof):
    idx = g["filed_all"].searchsorted(asof, side="right") - 1
    return idx


def snapshot_h34(asof):
    """Buyback yield per name: 1 - shares_now / shares_year_ago.
    Year-ago = the FY row whose fy_end is closest to one year
    before the latest row's fy_end, within [400, 330] days
    before it; fallback (documented in the pre-reg run notes):
    the most recent FY row with fy_end at least 300 days before
    the latest. Only rows filed by `asof` are ever used."""
    out = {}
    for t in L:
        g = r8.FUND.get(t)
        if g is None:
            continue
        idx = _latest(g, asof)
        if idx < 1:
            continue
        latest = g.iloc[idx]
        sh_now = latest["shares"]
        if not np.isfinite(sh_now) or sh_now <= 0:
            continue
        hist = g.iloc[:idx]                      # filed by asof, older rows
        gap = (latest["fy_end"] - hist["fy_end"]).dt.days
        prev = None
        near = hist[(gap >= 330) & (gap <= 400)]
        if len(near):
            j = (gap.loc[near.index] - 365).abs().idxmin()
            prev = hist.loc[j]
        else:
            old = hist[gap >= 300]
            if len(old):
                prev = old.loc[old["fy_end"].idxmax()]
        if prev is None:
            continue
        sh_prev = prev["shares"]
        if not np.isfinite(sh_prev) or sh_prev <= 0:
            continue
        out[t] = 1.0 - sh_now / sh_prev
    return out


def snapshot_h35(asof):
    """Cash-flow accruals per name: (net income - OCF) / assets,
    from the latest FY row public by `asof`."""
    out = {}
    for t in L:
        g = FUND_V2.get(t)
        if g is None:
            continue
        idx = _latest(g, asof)
        if idx < 0:
            continue
        r = g.iloc[idx]
        if r["assets"] <= 0:
            continue
        out[t] = (r["net_income"] - r["ocf"]) / r["assets"]
    return out


def make_choose_l(kind):
    def choose(k, mc, asof):
        snap = snapshot_h34(asof) if kind == "H34" else snapshot_h35(asof)
        if len(snap) < TOP_L:
            return {}
        s = pd.Series(snap)
        top = (s.sort_values(ascending=False, kind="mergesort")
               if kind == "H34" else
               s.sort_values(ascending=True, kind="mergesort"))
        top = top.index[:TOP_L]
        return {x: 1.0 / len(top) for x in top}
    return choose


# ============================================================
#  H32 / H33 — small caps, round-5 engine and conventions
# ============================================================
def load_fundamentals_sc():
    df = pd.read_csv(PANEL_SC, parse_dates=["fy_end", "filed_ni",
                                             "filed_eq", "filed_sh"])
    df = df.dropna(subset=["net_income", "equity", "shares"])
    df["filed_all"] = df[["filed_ni", "filed_eq", "filed_sh"]].max(axis=1)
    out = {}
    for t, g in df.groupby("ticker"):
        out[t] = g.sort_values("filed_all").reset_index(drop=True)
    return out


FUND_SC = load_fundamentals_sc()


def snapshot_sc(asof, mc_row, price_elig):
    """Fundamental snapshot at a month-end: latest FY row public
    by `asof`, positive equity/shares, price-eligible (>=252
    sessions, price present). Market cap = month-end adjclose x
    latest filed shares (round-8/9 registered definition)."""
    rows = {}
    for t, g in FUND_SC.items():
        if t not in mc_row.index or not price_elig.get(t, False):
            continue
        idx = _latest(g, asof)
        if idx < 0:
            continue
        r = g.iloc[idx]
        if r["equity"] <= 0 or r["shares"] <= 0:
            continue
        px = mc_row[t]
        if not np.isfinite(px) or px <= 0:
            continue
        mcap = px * r["shares"]
        rows[t] = {"ep": r["net_income"] / mcap,
                   "bm": r["equity"] / mcap}
    return rows


def run_smallcap(px, bench):
    days = px.index
    me_dates = [g.index[-1] for _, g in px.groupby([days.year, days.month])]
    me_dates = [d for d in me_dates if days.get_loc(d) + 1 < len(days)]
    entry = {d: days[days.get_loc(d) + 1] for d in me_dates}
    hist = px.notna().cumsum()
    mc = px.loc[me_dates]

    snaps, elig_by_date = {}, {}
    for d in me_dates:
        pe = {t: bool(hist.at[d, t] >= r5.MIN_HIST and pd.notna(mc.at[d, t]))
              for t in px.columns}
        snap = snapshot_sc(d, mc.loc[d], pe)
        snaps[d] = snap
        elig_by_date[d] = list(snap)

    sched = []
    for k in range(len(me_dates)):
        e = entry[me_dates[k]]
        x = entry[me_dates[k + 1]] if k + 1 < len(me_dates) else days[-1]
        if e < pd.Timestamp(EVAL_START):
            continue
        sched.append((k, e, x))
    print(f"Small-cap: {len(sched)} monthly rebalances from "
          f"{sched[0][1].date()}; eligible names per month-end: "
          f"min {min(len(elig_by_date[d]) for d in me_dates)}, "
          f"median {int(np.median([len(elig_by_date[d]) for d in me_dates]))}")

    results = {}
    for name, col in [("H32", "ep"), ("H33", "bm")]:
        periods, sig_of = [], {}
        for k, e, x in sched:
            snap = snaps[me_dates[k]]
            ranked = sorted(snap, key=lambda t: snap[t][col],
                            reverse=True)
            periods.append((e, x, ranked[:TOP_S]))
            sig_of[e] = me_dates[k]
        eq_full, records = r5.simulate(px, periods)
        for rec, (e, x, _) in zip(records, periods):
            rec["signal"] = sig_of[e]
        results[name] = (eq_full, records, elig_by_date)
    return results


def main():
    report = {"n_tests_cumulative": N_TESTS}

    # ── universe L: H34, H35 ─────────────────────────────────
    opens, closes = r8.load_prices()
    eq_spy = r8.spy_bh(opens, closes)
    _, spy_oos = oos_split(eq_spy)
    sb = r1.stats(spy_oos)
    print(f"SPY B&H OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")
    report["SPY_BH"] = dict(oos=dict(cagr=sb["cagr"], sharpe=sb["sharpe"],
                                     max_dd=sb["max_dd"]))
    report["fundamentals_v2_coverage"] = {
        "tickers_with_complete_rows": len(FUND_V2),
        "rows_per_ticker": {t: int(len(g)) for t, g in FUND_V2.items()}}

    for name in ["H34", "H35"]:
        eq, tr = r8.run_monthly(opens, closes, make_choose_l(name))
        is_eq, oos_eq = oos_split(eq)
        v, fails, s, t, bar = verdict(oos_eq, spy_oos, "SPY")
        si = r1.stats(is_eq)
        print(f"{name}: exits {len(tr)} | IS CAGR {si['cagr']:+6.1%} "
              f"Sharpe {si['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
              f"Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
              f"(bar {bar:.2f}) maxDD {s['max_dd']:5.1%} -> {v}"
              + (f" [{'; '.join(fails)}]" if fails else ""))
        print(f"   (no random-entry control: slow-turnover book, "
              f"round-8 horizon-mismatch caveat)")
        report[name] = dict(
            verdict=v, fails=fails,
            oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                     bar=bar, max_dd=s["max_dd"], trades=len(tr)),
            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
            control=None,
            control_note="not reported: slow-turnover book; the "
                         "round-3 control is not horizon-matched "
                         "(round-8 caveat)")

    # ── small caps: H32, H33 ─────────────────────────────────
    px, bench = r5.load_panel()
    days = px.index
    print(f"Small-cap panel {days[0].date()} -> {days[-1].date()}, "
          f"{px.shape[1]} stocks with bars")
    report["fundamentals_sc_coverage"] = {
        "tickers_with_complete_rows": len(FUND_SC),
        "rows_per_ticker": {t: int(len(g)) for t, g in FUND_SC.items()}}

    eval_days = days[days >= pd.Timestamp(EVAL_START)]
    eq_bench = CASH0 * (1 - COST) * bench / bench.loc[eval_days[0]]
    eq_bench = eq_bench.reindex(eval_days)
    _, bench_oos = oos_split(eq_bench)
    sbb = r1.stats(bench_oos)
    print(f"IWM B&H OOS: CAGR {sbb['cagr']:+.1%} Sharpe {sbb['sharpe']:.2f} "
          f"maxDD {sbb['max_dd']:.1%}")
    report["IWM_BH"] = dict(oos=dict(cagr=sbb["cagr"], sharpe=sbb["sharpe"],
                                     max_dd=sbb["max_dd"]))

    sc_results = run_smallcap(px, bench)
    for name in ["H32", "H33"]:
        eq_full, records, elig_by_date = sc_results[name]
        eq = eq_full.reindex(eval_days).ffill().fillna(CASH0)
        is_eq, oos_eq = oos_split(eq)
        v, fails, s, t, bar = verdict(oos_eq, bench_oos, "IWM")
        si = r1.stats(is_eq)
        ct, nper, m_real, m_ctrl = r5.control(records, px, elig_by_date)
        print(f"{name}: rebalances {len(records)} | IS CAGR {si['cagr']:+6.1%} "
              f"Sharpe {si['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
              f"Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
              f"(bar {bar:.2f}) maxDD {s['max_dd']:5.1%} -> {v}"
              + (f" [{'; '.join(fails)}]" if fails else ""))
        print(f"   control (horizon-matched, same-month random 60-name "
              f"draws from the same eligible pool): {nper} rebalances, "
              f"strategy gross {m_real:+.2%}/rebalance vs random "
              f"{m_ctrl:+.2%}, Welch t {ct:+.2f}")
        report[name] = dict(
            verdict=v, fails=fails,
            oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                     bar=bar, max_dd=s["max_dd"],
                     rebalances=len(records)),
            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
            control=dict(welch_t=ct, n_rebalances=nper,
                         strat_gross_per_rebalance=m_real,
                         ctrl_gross_per_rebalance=m_ctrl,
                         method="round-5 control: 200 random same-size "
                                "draws per rebalance from the same "
                                "fundamental-eligible pool, same entry/"
                                "exit dates (horizon-matched)"))

    with open("data/round9_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round9_report.json")


if __name__ == "__main__":
    main()
