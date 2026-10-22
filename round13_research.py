# ============================================================
#  round13_research.py — Tests PREREGISTRATION_2026-10-21_
#  round13.md
#
#  H47 short-interest level (FINRA)   H48 short-interest change
#  H49 13F institutional net breadth
#
#  Written AFTER the pre-registration commit. H47/H48 run on
#  the round-8 universe-L monthly engine (signals at month-end
#  close, fills at next open, 5 bps/side, benchmark SPY).
#  Short interest is FINRA's consolidated biweekly series
#  (fetch_shortinterest.py; the Query API's history begins at
#  the 2017-12-29 settlement, so invested rebalances start
#  Jan 2018 — before that the book holds cash, disclosed).
#  A snapshot is usable only once published: publication date
#  = the 7th trading session after its settlement date (the
#  registered "7th business day" rule on the trading
#  calendar). SI% = short shares / latest as-filed shares
#  public by the rebalance date (panel.csv, filed_sh).
#  H49 runs on a schedule-driven copy of the same engine
#  (round-12's run_monthly_sched): quarterly rebalances on
#  the first trading session of Mar/Jun/Sep/Dec, breadth from
#  the SEC 13F data-set build (fetch_13f.py; per-manager
#  latest filing per quarter among filings dated <= quarter
#  end + 50 days, exactly the registered availability rule).
#  Verdicts OOS 2023-07-07 onward; in-sample context only.
#    python round13_research.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats as sstats

import daily_research as r1
import round8_research as r8
from round2_data import L

COST = r1.COST            # 5 bps per side, pre-registered
CASH0 = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-12)
N_TESTS = 51              # cumulative hypotheses through round 13
BAR_REGISTERED = 3.32     # pre-registered bar (formula checked below)
TOP_N = 26                # top ~30% of 87
PUB_LAG_SESSIONS = 7      # registered publication lag (business days)

SI_PANEL = os.path.join("data", "shortinterest", "si_panel.csv")
FUND_PANEL = os.path.join("data", "fundamentals", "panel.csv")
HOLD_PANEL = os.path.join("data", "13f", "holdings_panel.csv")
CTRL_NOTE = ("not reported: slow-turnover monthly/quarterly books "
             "follow the rounds 8-12 no-control convention (the "
             "round-3 control is not horizon-matched)")


# ── statistics (house conventions, rounds 9-12) ──────────────
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
    """Bonferroni one-sided bar; same formula as rounds 3-12."""
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


def entry_for(v, fails, s, t, bar, is_eq, trades=None, extra=None):
    si = r1.stats(is_eq)
    e = dict(verdict=v, fails=fails,
             oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                      bar=bar, max_dd=s["max_dd"], trades=trades),
             is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
             control=None, control_note=CTRL_NOTE)
    if extra:
        e.update(extra)
    return e


# ── H47/H48: FINRA short interest ────────────────────────────
def load_si(days):
    """SI panel with publication dates on the trading calendar:
    pub = the 7th session strictly after the settlement date."""
    si = pd.read_csv(SI_PANEL, parse_dates=["settlement_date"])
    pos = days.searchsorted(si["settlement_date"], side="right")
    pub_idx = pos + (PUB_LAG_SESSIONS - 1)
    ok = pub_idx < len(days)
    si = si[ok].copy()
    si["pub_date"] = days[pub_idx[ok]]
    out = {}
    for t, g in si.groupby("symbol"):
        out[t] = g.sort_values("settlement_date").reset_index(drop=True)
    return out


def load_shares():
    """As-filed shares by ticker: FY rows usable on filed_sh."""
    df = pd.read_csv(FUND_PANEL, parse_dates=["filed_sh"])
    df = df.dropna(subset=["shares", "filed_sh"])
    df = df[df["shares"] > 0]
    out = {}
    for t, g in df.groupby("ticker"):
        out[t] = g.sort_values("filed_sh").reset_index(drop=True)
    return out


SI = None        # filled in main (needs the price calendar)
SHARES = None


def _shares_asof(t, asof):
    g = SHARES.get(t)
    if g is None:
        return None
    idx = g["filed_sh"].searchsorted(asof, side="right") - 1
    if idx < 0:
        return None
    return float(g.iloc[idx]["shares"])


def si_snapshot(asof):
    """Per name: (SI% latest published, SI% change vs the
    previous published snapshot, settlement used)."""
    rows = {}
    for t in L:
        g = SI.get(t)
        if g is None:
            continue
        idx = g["pub_date"].searchsorted(asof, side="right") - 1
        if idx < 0:
            continue
        sh = _shares_asof(t, asof)
        if sh is None:
            continue
        cur = float(g.iloc[idx]["short_shares"]) / sh
        chg = None
        if idx >= 1:
            prev = float(g.iloc[idx - 1]["short_shares"]) / sh
            chg = cur - prev
        rows[t] = {"si": cur, "chg": chg,
                   "settlement": g.iloc[idx]["settlement_date"]}
    return rows


def make_choose_si(kind, diag):
    def choose(k, mc, asof):
        snap = si_snapshot(asof)
        diag["months"] += 1
        diag["elig_min"] = min(diag["elig_min"], len(snap))
        col = "si" if kind == "H47" else "chg"
        s = pd.Series({t: r[col] for t, r in snap.items()
                       if r[col] is not None})
        if kind == "H47":
            # registered expectation: latest published at a
            # month-end is the same month's mid-month snapshot
            # (settlement on the 15th). Count exceptions.
            mid = sum(1 for r in snap.values()
                      if r["settlement"].day <= 16
                      and r["settlement"].month == asof.month
                      and r["settlement"].year == asof.year)
            diag["mid_share"].append(mid / max(len(snap), 1))
        if len(s) < TOP_N:
            return {}
        top = s.sort_values(ascending=True,
                            kind="mergesort").index[:TOP_N]
        if diag["first_invested"] is None:
            diag["first_invested"] = asof
        return {x: 1.0 / len(top) for x in top}
    return choose


# ── H49: 13F net manager breadth ─────────────────────────────
def load_breadth():
    """Net breadth per (signal period, ticker): managers are
    counted over the union of holders in the signal quarter
    and the prior quarter; absence = 0 shares."""
    h = pd.read_csv(HOLD_PANEL, dtype={"manager_cik": str})
    h = h.groupby(["period", "manager_cik", "ticker"],
                  as_index=False)["shares"].sum()
    periods = sorted(h["period"].unique())
    by_period = {}
    for p in periods:
        by_period[p] = (h[h["period"] == p]
                        .set_index(["manager_cik", "ticker"])["shares"])
    breadth, counts = {}, {}
    for prev_p, p in zip(periods, periods[1:]):
        cur = by_period[p]
        prev = by_period[prev_p]
        mgrs = cur.index.union(prev.index)
        d = (cur.reindex(mgrs).fillna(0) - prev.reindex(mgrs).fillna(0))
        d = d[d != 0]
        signs = np.sign(d).groupby(level="ticker").sum()
        breadth[p] = signs.to_dict()
        counts[p] = int(d.index.get_level_values("manager_cik")
                        .nunique())
    return breadth, counts, periods


def run_monthly_sched(opens, closes, sched):
    """Round-12 copy of the round-3/8 engine mechanics driven
    by an explicit (fill_index, target weights) schedule."""
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
                dd = want - have
                if dd > 0:
                    dd = min(dd, max(0.0, b.cash) / (o[s] * (1 + COST)))
                if abs(dd) > 1e-9:
                    b.trade(s, dd, o[s])
                    held[s] = (held[s][0], held[s][1], held[s][2] + dd) \
                        if s in held else (i, o[s], dd)
            for s in list(held):
                if abs(held[s][2]) < 1e-9:
                    del held[s]
            ptr += 1
        eq.append(b.value(closes.iloc[i]))
    return pd.Series(eq, index=days), pd.DataFrame(trades)


def h49_schedule(days, breadth):
    """First session of Mar/Jun/Sep/Dec -> signal quarter is
    the calendar quarter that ended ~2 months earlier (Q-end
    + 50 days availability, per the registration)."""
    sched, used = [], []
    for y in range(2016, 2027):
        for month, (qy, qm) in {3: (y - 1, 12), 6: (y, 3),
                                9: (y, 6), 12: (y, 9)}.items():
            period = f"{qy}-{qm:02d}-" + \
                ("31" if qm in (3, 12) else "30")
            if period not in breadth:
                continue
            first = days[(days.year == y) & (days.month == month)]
            if len(first) == 0:
                continue
            i = days.get_loc(first[0])
            s = pd.Series(breadth[period])
            s = s.reindex([t for t in L if t in s.index])
            if len(s) < TOP_N:
                continue
            top = s.sort_values(ascending=False,
                                kind="mergesort").index[:TOP_N]
            sched.append((i, {x: 1.0 / len(top) for x in top}))
            used.append(period)
    return sched, used


def main():
    global SI, SHARES
    opens, closes = r8.load_prices()
    days = closes.index
    print(f"Prices {days[0].date()} -> {days[-1].date()}, "
          f"{len(L)} stocks + SPY")
    SI = load_si(days)
    SHARES = load_shares()
    n_si = sum(len(g) for g in SI.values())
    print(f"SI panel: {n_si} usable snapshots across "
          f"{len(SI)} symbols (publication-lagged); shares panel "
          f"covers {len(SHARES)}/87 tickers")

    eq_spy = r8.spy_bh(opens, closes)
    _, spy_oos = oos_split(eq_spy)
    sb = r1.stats(spy_oos)
    print(f"SPY B&H OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")
    report = {"n_tests_cumulative": N_TESTS,
              "bar_registered": BAR_REGISTERED,
              "SPY_BH": dict(oos=dict(cagr=sb["cagr"],
                                      sharpe=sb["sharpe"],
                                      max_dd=sb["max_dd"])),
              "si_coverage": {
                  "symbols": len(SI), "snapshots": int(n_si),
                  "shares_panel_tickers": len(SHARES),
                  "first_settlement": min(
                      g["settlement_date"].min() for g in SI.values()
                      ).date().isoformat(),
                  "last_settlement": max(
                      g["settlement_date"].max() for g in SI.values()
                      ).date().isoformat()}}

    # ── H47 / H48 ────────────────────────────────────────────
    for name in ["H47", "H48"]:
        diag = {"months": 0, "elig_min": 10 ** 9,
                "mid_share": [], "first_invested": None}
        eq, tr = r8.run_monthly(opens, closes,
                                make_choose_si(name, diag))
        is_eq, oos_eq = oos_split(eq)
        v, fails, s, t, bar = verdict(oos_eq, spy_oos, "SPY")
        si_stats = r1.stats(is_eq)
        print(f"{name}: rebalances {diag['months']} (first invested "
              f"{diag['first_invested']}), trades {len(tr)} | "
              f"IS CAGR {si_stats['cagr']:+6.1%} Sharpe "
              f"{si_stats['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
              f"Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
              f"(bar {bar:.2f}) maxDD {s['max_dd']:5.1%} -> {v}"
              + (f" [{'; '.join(fails)}]" if fails else ""))
        extra = dict(rebalance_months=diag["months"],
                     first_invested=(diag["first_invested"]
                                     .date().isoformat()
                                     if diag["first_invested"]
                                     is not None else None),
                     min_eligible=diag["elig_min"])
        if name == "H47" and diag["mid_share"]:
            extra["mean_share_latest_is_same_month_mid"] = float(
                np.mean(diag["mid_share"]))
        report[name] = entry_for(v, fails, s, t, bar, is_eq,
                                 trades=len(tr), extra=extra)

    # ── H49 ──────────────────────────────────────────────────
    breadth, mgr_counts, periods = load_breadth()
    print(f"13F: {len(periods)} periods "
          f"{periods[0]} -> {periods[-1]}; breadth quarters "
          f"{len(breadth)}; managers changing positions per "
          f"quarter: median {int(np.median(list(mgr_counts.values())))}")
    sched49, used = h49_schedule(days, breadth)
    eq49, tr49 = run_monthly_sched(opens, closes, sched49)
    is49, oos49 = oos_split(eq49)
    v, fails, s, t, bar = verdict(oos49, spy_oos, "SPY")
    si49 = r1.stats(is49)
    print(f"H49: {len(sched49)} quarterly rebalances "
          f"({used[0]} -> {used[-1]} signals), trades {len(tr49)} | "
          f"IS CAGR {si49['cagr']:+6.1%} Sharpe {si49['sharpe']:5.2f} | "
          f"OOS CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} "
          f"t(excess) {t:+5.2f} (bar {bar:.2f}) maxDD {s['max_dd']:5.1%} "
          f"-> {v}" + (f" [{'; '.join(fails)}]" if fails else ""))
    report["H49"] = entry_for(
        v, fails, s, t, bar, is49, trades=len(tr49),
        extra=dict(rebalances=len(sched49), signal_periods=used,
                   periods_available=len(periods),
                   median_managers_changing=int(np.median(
                       list(mgr_counts.values())))))
    report["breadth_coverage"] = {
        "periods": [str(p) for p in periods],
        "managers_changing_by_period": {str(k): int(v)
                                        for k, v in
                                        mgr_counts.items()}}

    with open("data/round13_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round13_report.json")


if __name__ == "__main__":
    main()
