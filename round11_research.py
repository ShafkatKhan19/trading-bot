# ============================================================
#  round11_research.py — Tests PREREGISTRATION_2026-10-20_
#  round11.md
#
#  H40 Piotroski-style quality score   H41 OCF yield
#  H42 cash-value blend (EY+GP+SHY)     H43 small-cap value
#                                        blend (EY+B/M)
#
#  Written AFTER the pre-registration commit. All data is
#  cached from rounds 8-10; no new crawls. H40-H42: universe
#  L, monthly engine identical to rounds 3/8 (signals at
#  month-end close, fills at next open, 5 bps/side, top 26
#  equal weight, benchmark SPY buy & hold). Fundamentals are
#  SEC EDGAR FY facts, strictly point-in-time (usable only
#  on/after `filed`; earliest filing per period). H43 uses the
#  round-5/9 small-cap engine (Yahoo adjclose, signal at
#  month-end, returns from the next session's close, 5 bps/
#  side, top 60, benchmark IWM). No random-entry controls
#  for the universe-L books (rounds 8-10 slow-turnover
#  caveat); H43 keeps the round-9 horizon-matched control.
#    python round11_research.py
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
import round9_research as r9
import round10_research as r10
from round2_data import L

COST = r1.COST            # 5 bps per side, pre-registered
CASH0 = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-10)
EVAL_START = "2016-01-01"
N_TESTS = 45              # cumulative hypotheses through round 11
TOP_L = 26
TOP_S = 60
CTRL_NOTE = ("not reported: pre-registered slow-turnover caveat "
             "(rounds 8-10)")


# ── statistics (house conventions, rounds 9/10) ──────────────
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


def _latest_idx(g, col, asof):
    return g[col].searchsorted(asof, side="right") - 1


def _valid_px(px):
    return px is not None and np.isfinite(px) and px > 0


# ── H40: quality score components ────────────────────────────
# Assets of a given fiscal year, from panel_l_v2 rows carrying
# an assets fact (usable on the fact's own filed_assets date —
# the round-10 H36 pairing convention). One row per
# (ticker, fy_end) in the panel.
ASSET_FY = {}
for _t, _g in r10.ASSETS.items():
    ASSET_FY[_t] = {r.fy_end: (r.filed_assets, r.assets)
                    for r in _g.itertuples()}


def h40_components(t, asof, px):
    """The eight registered binary components for one name, or
    None if any component is not computable (prereg: names
    missing any component are ineligible). Component 5 (asset
    growth vs median) is cross-sectional and added by the
    snapshot; this returns the raw asset growth instead."""
    g = r9.FUND_V2.get(t)
    if g is None or not _valid_px(px):
        return None
    idx = _latest_idx(g, "filed_all", asof)
    if idx < 1:
        return None
    prev = r10._year_ago(g, idx)
    if prev is None:
        return None
    cur = g.iloc[idx]
    if cur["assets"] <= 0 or prev["assets"] <= 0 or cur["shares"] <= 0:
        return None
    gg = r10.GP.get(t)
    if gg is None:
        return None
    j = _latest_idx(gg, "filed", asof)
    if j < 1:
        return None
    gprev = r10._year_ago(gg, j)
    if gprev is None:
        return None
    gcur = gg.iloc[j]
    if gcur["revenue"] <= 0 or gprev["revenue"] <= 0:
        return None
    afy = ASSET_FY.get(t, {})
    a_cur = afy.get(gcur["fy_end"])
    a_prev = afy.get(gprev["fy_end"])
    if a_cur is None or a_prev is None:
        return None
    if a_cur[0] > asof or a_prev[0] > asof:
        return None            # that FY's assets not yet public
    if a_cur[1] <= 0 or a_prev[1] <= 0:
        return None
    ni, ocf = cur["net_income"], cur["ocf"]
    gm_cur = (gcur["revenue"] - gcur["cogs"]) / gcur["revenue"]
    gm_prev = (gprev["revenue"] - gprev["cogs"]) / gprev["revenue"]
    return {
        "c1": bool(ni > 0),
        "c2": bool(ocf > 0),
        "c3": bool(ocf > ni),
        "c4": bool(ni / cur["assets"]
                   > prev["net_income"] / prev["assets"]),
        "ag": float(cur["assets"] / prev["assets"] - 1.0),
        "c6": bool(gm_cur > gm_prev),
        "c7": bool(gcur["revenue"] / a_cur[1]
                   > gprev["revenue"] / a_prev[1]),
        "c8": bool(cur["shares"] <= prev["shares"]),
        "ep": float(ni / (px * cur["shares"])),
    }


ELIG = {"H40": [], "H41": [], "H42": [], "H42_legs": []}


def snapshot_h40(asof, mc_row):
    cands = {}
    for t in L:
        c = h40_components(t, asof, mc_row.get(t))
        if c is not None:
            cands[t] = c
    ELIG["H40"].append(len(cands))
    if len(cands) < TOP_L:
        return {}
    med_ag = float(np.median([c["ag"] for c in cands.values()]))
    rows = {}
    for t, c in cands.items():
        score = (c["c1"] + c["c2"] + c["c3"] + c["c4"]
                 + (c["ag"] < med_ag) + c["c6"] + c["c7"] + c["c8"])
        rows[t] = {"score": int(score), "ep": c["ep"]}
    df = pd.DataFrame(rows).T
    top = df.sort_values(by=["score", "ep"], ascending=[False, False],
                         kind="mergesort").index[:TOP_L]
    return {t: 1.0 / len(top) for t in top}


def snapshot_h41(asof, mc_row):
    out = {}
    for t in L:
        g = r9.FUND_V2.get(t)
        if g is None:
            continue
        idx = _latest_idx(g, "filed_all", asof)
        if idx < 0:
            continue
        r = g.iloc[idx]
        px = mc_row.get(t)
        if r["shares"] <= 0 or not _valid_px(px):
            continue
        out[t] = r["ocf"] / (px * r["shares"])
    ELIG["H41"].append(len(out))
    return out


def snapshot_h42(asof, mc_row):
    ey_df = r8.snapshot(asof, mc_row)             # H29 as tested
    ey = ey_df["ep"] if "ep" in ey_df else pd.Series(dtype=float)
    gp = pd.Series(r10.snapshot_h36(asof))        # H36 as tested
    sy = pd.Series(r10.snapshot_h38(asof, mc_row))  # H38 as tested
    ELIG["H42_legs"].append((len(ey), len(gp), len(sy)))
    names = ey.index.intersection(gp.index).intersection(sy.index)
    ELIG["H42"].append(len(names))
    if len(names) < TOP_L:
        return {}
    df = pd.DataFrame({"ep": ey[names], "gp": gp[names], "sy": sy[names]})
    blend = (df["ep"].rank(ascending=False, method="min")
             + df["gp"].rank(ascending=False, method="min")
             + df["sy"].rank(ascending=False, method="min")) / 3.0
    top = blend.sort_values(kind="mergesort").index[:TOP_L]
    return {t: 1.0 / len(top) for t in top}


def make_choose_l(kind):
    def choose(k, mc, asof):
        mc_row = mc[L].iloc[k]
        if kind == "H40":
            snap = snapshot_h40(asof, mc_row)
            return snap          # weights already, or {} if empty
        if kind == "H41":
            snap = snapshot_h41(asof, mc_row)
            if len(snap) < TOP_L:
                return {}
            s = pd.Series(snap)
            top = s.sort_values(ascending=False,
                                kind="mergesort").index[:TOP_L]
            return {t: 1.0 / len(top) for t in top}
        return snapshot_h42(asof, mc_row)   # H42
    return choose


# ── H43: small-cap value blend (round-9 engine) ──────────────
def run_smallcap_blend(px):
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
        snap = r9.snapshot_sc(d, mc.loc[d], pe)
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

    periods, sig_of = [], {}
    for k, e, x in sched:
        snap = snaps[me_dates[k]]
        if snap:
            df = pd.DataFrame(snap).T
            blend = (df["ep"].rank(ascending=False, method="min")
                     + df["bm"].rank(ascending=False, method="min")) / 2.0
            picks = list(blend.sort_values(kind="mergesort")
                         .index[:TOP_S])
        else:
            picks = []
        periods.append((e, x, picks))
        sig_of[e] = me_dates[k]
    eq_full, records = r5.simulate(px, periods)
    for rec, (e, x, _) in zip(records, periods):
        rec["signal"] = sig_of[e]
    return eq_full, records, elig_by_date


def main():
    report = {"n_tests_cumulative": N_TESTS,
              "coverage": {
                  "v2_tickers": len(r9.FUND_V2),
                  "gp_tickers": len(r10.GP),
                  "assets_tickers": len(r10.ASSETS),
                  "div_tickers": len(r10.DIV),
                  "sc_tickers": len(r9.FUND_SC)}}

    # ── universe L: H40, H41, H42 ────────────────────────────
    opens, closes = r8.load_prices()
    eq_spy = r8.spy_bh(opens, closes)
    _, spy_oos = oos_split(eq_spy)
    sb = r1.stats(spy_oos)
    print(f"SPY B&H OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")
    report["SPY_BH"] = dict(oos=dict(cagr=sb["cagr"], sharpe=sb["sharpe"],
                                     max_dd=sb["max_dd"]))

    for name in ["H40", "H41", "H42"]:
        eq, tr = r8.run_monthly(opens, closes, make_choose_l(name))
        is_eq, oos_eq = oos_split(eq)
        v, fails, s, t, bar = verdict(oos_eq, spy_oos, "SPY")
        si = r1.stats(is_eq)
        print(f"{name}: exits {len(tr)} | IS CAGR {si['cagr']:+6.1%} "
              f"Sharpe {si['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
              f"Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
              f"(bar {bar:.2f}) maxDD {s['max_dd']:5.1%} -> {v}"
              + (f" [{'; '.join(fails)}]" if fails else ""))
        print("   (no random-entry control: pre-registered "
              "slow-turnover caveat)")
        entry = dict(
            verdict=v, fails=fails,
            oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                     bar=bar, max_dd=s["max_dd"], trades=len(tr)),
            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
            control=None, control_note=CTRL_NOTE)
        if ELIG[name]:
            entry["eligible_names_per_month"] = dict(
                min=min(ELIG[name]), median=int(np.median(ELIG[name])),
                max=max(ELIG[name]))
        if name == "H42" and ELIG["H42_legs"]:
            legs = ELIG["H42_legs"]
            entry["leg_eligible_names_per_month"] = {
                leg: dict(min=min(x[i] for x in legs),
                          median=int(np.median([x[i] for x in legs])),
                          max=max(x[i] for x in legs))
                for i, leg in enumerate(["earnings_yield",
                                         "gross_profitability",
                                         "shareholder_yield"])}
        report[name] = entry

    # ── small caps: H43 ──────────────────────────────────────
    px, bench = r5.load_panel()
    days = px.index
    print(f"Small-cap panel {days[0].date()} -> {days[-1].date()}, "
          f"{px.shape[1]} stocks with bars")
    eval_days = days[days >= pd.Timestamp(EVAL_START)]
    eq_bench = CASH0 * (1 - COST) * bench / bench.loc[eval_days[0]]
    eq_bench = eq_bench.reindex(eval_days)
    _, bench_oos = oos_split(eq_bench)
    sbb = r1.stats(bench_oos)
    print(f"IWM B&H OOS: CAGR {sbb['cagr']:+.1%} Sharpe {sbb['sharpe']:.2f} "
          f"maxDD {sbb['max_dd']:.1%}")
    report["IWM_BH"] = dict(oos=dict(cagr=sbb["cagr"],
                                     sharpe=sbb["sharpe"],
                                     max_dd=sbb["max_dd"]))

    eq_full, records, elig_by_date = run_smallcap_blend(px)
    eq = eq_full.reindex(eval_days).ffill().fillna(CASH0)
    is_eq, oos_eq = oos_split(eq)
    v, fails, s, t, bar = verdict(oos_eq, bench_oos, "IWM")
    si = r1.stats(is_eq)
    ct, nper, m_real, m_ctrl = r5.control(records, px, elig_by_date)
    print(f"H43: rebalances {len(records)} | IS CAGR {si['cagr']:+6.1%} "
          f"Sharpe {si['sharpe']:5.2f} | OOS CAGR {s['cagr']:+6.1%} "
          f"Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
          f"(bar {bar:.2f}) maxDD {s['max_dd']:5.1%} -> {v}"
          + (f" [{'; '.join(fails)}]" if fails else ""))
    print(f"   control (horizon-matched, same-month random 60-name "
          f"draws from the same eligible pool): {nper} rebalances, "
          f"strategy gross {m_real:+.2%}/rebalance vs random "
          f"{m_ctrl:+.2%}, Welch t {ct:+.2f}")
    report["H43"] = dict(
        verdict=v, fails=fails,
        oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                 bar=bar, max_dd=s["max_dd"], rebalances=len(records)),
        is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
        control=dict(welch_t=ct, n_rebalances=nper,
                     strat_gross_per_rebalance=m_real,
                     ctrl_gross_per_rebalance=m_ctrl,
                     method="round-5 control: 200 random same-size "
                            "draws per rebalance from the same "
                            "fundamental-eligible pool, same entry/"
                            "exit dates (horizon-matched)"))

    with open("data/round11_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round11_report.json")


if __name__ == "__main__":
    main()
