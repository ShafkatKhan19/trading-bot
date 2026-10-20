# ============================================================
#  round10_research.py — Tests PREREGISTRATION_2026-10-20_
#  round10.md
#
#  H36 gross profitability   H37 low asset growth
#  H38 total shareholder yield   H39 insider net buying
#
#  Written AFTER the pre-registration commit. All four:
#  universe L, monthly engine identical to rounds 3/8 (signals
#  at month-end close, fills at next open, 5 bps/side, top 26
#  equal weight, benchmark SPY buy & hold). Fundamentals are
#  SEC EDGAR FY facts, strictly point-in-time (usable only
#  on/after `filed`; earliest filing per period). H39 uses
#  public Form 4 filings, usable on their SEC acceptance
#  date; the signal sums the per-filing records in
#  data/insider/filing_net.csv by exact acceptance date
#  (monthly_net.csv is the committed monthly aggregate of
#  the same records — exact dates avoid a month-boundary
#  leak of up to 3 days). No random-entry controls this
#  round (pre-registered slow-turnover caveat).
#    python round10_research.py
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
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-9)
N_TESTS = 41              # cumulative hypotheses through round 10
TOP_L = 26

FD = os.path.join("data", "fundamentals")
PANEL_GP = os.path.join(FD, "panel_gp.csv")
PANEL_V2 = os.path.join(FD, "panel_l_v2.csv")
PANEL_DIV = os.path.join(FD, "panel_div.csv")
FILING_NET = os.path.join("data", "insider", "filing_net.csv")
MONTHLY_NET = os.path.join("data", "insider", "monthly_net.csv")


# ── statistics (house conventions, rounds 3-9) ───────────────
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


# ── panels ───────────────────────────────────────────────────
def _by_ticker(df, sort_col):
    out = {}
    for t, g in df.groupby("ticker"):
        out[t] = g.sort_values(sort_col).reset_index(drop=True)
    return out


def load_gp():
    """Rows with both revenue and COGS; usable once both were
    public (panel `filed` = max of the two filed dates)."""
    df = pd.read_csv(PANEL_GP, parse_dates=["fy_end", "filed"])
    df = df.dropna(subset=["revenue", "cogs", "filed"])
    return _by_ticker(df, "filed")


def load_assets():
    """Assets rows from the round-9 v2 panel; usable on the
    assets fact's own filed date."""
    df = pd.read_csv(PANEL_V2, parse_dates=["fy_end", "filed_assets"])
    df = df.dropna(subset=["assets", "filed_assets"])
    return _by_ticker(df, "filed_assets")


def load_div():
    df = pd.read_csv(PANEL_DIV, parse_dates=["fy_end", "filed"])
    return _by_ticker(df, "filed")


GP = load_gp()
ASSETS = load_assets()
DIV = load_div()


def _latest_row(g, col, asof):
    idx = g[col].searchsorted(asof, side="right") - 1
    return g.iloc[idx] if idx >= 0 else None


def _year_ago(g, idx):
    """H34 matching: the FY row whose fy_end is closest to one
    year before row idx's fy_end within [330, 400] days;
    fallback: most recent row ending >=300 days earlier.
    Rows are the ones filed by the as-of date (iloc[:idx+1])."""
    latest = g.iloc[idx]
    hist = g.iloc[:idx]
    if not len(hist):
        return None
    gap = (latest["fy_end"] - hist["fy_end"]).dt.days
    near = hist[(gap >= 330) & (gap <= 400)]
    if len(near):
        j = (gap.loc[near.index] - 365).abs().idxmin()
        return hist.loc[j]
    old = hist[gap >= 300]
    if len(old):
        return old.loc[old["fy_end"].idxmax()]
    return None


def shares_pair(t, asof):
    """(shares_now, shares_year_ago) from the round-8 panel."""
    g = r8.FUND.get(t)
    if g is None:
        return None
    idx = g["filed_all"].searchsorted(asof, side="right") - 1
    if idx < 1:
        return None
    prev = _year_ago(g, idx)
    if prev is None:
        return None
    sh_now, sh_prev = g.iloc[idx]["shares"], prev["shares"]
    if not (np.isfinite(sh_now) and np.isfinite(sh_prev)) \
            or sh_now <= 0 or sh_prev <= 0:
        return None
    return sh_now, sh_prev


ELIG = {"H36": [], "H37": [], "H38": [], "H39_pos": [], "H39_fill": []}


def snapshot_h36(asof):
    out = {}
    for t in L:
        g = GP.get(t)
        a = ASSETS.get(t)
        if g is None or a is None:
            continue
        r = _latest_row(g, "filed", asof)
        ra = _latest_row(a, "filed_assets", asof)
        if r is None or ra is None or ra["assets"] <= 0:
            continue
        out[t] = (r["revenue"] - r["cogs"]) / ra["assets"]
    return out


def snapshot_h37(asof):
    out = {}
    for t in L:
        a = ASSETS.get(t)
        if a is None:
            continue
        idx = a["filed_assets"].searchsorted(asof, side="right") - 1
        if idx < 1:
            continue
        prev = _year_ago(a, idx)
        if prev is None or prev["assets"] <= 0:
            continue
        out[t] = a.iloc[idx]["assets"] / prev["assets"] - 1.0
    return out


def snapshot_h38(asof, mc_row):
    out = {}
    for t in L:
        sp = shares_pair(t, asof)
        if sp is None:
            continue
        sh_now, sh_prev = sp
        px = mc_row.get(t)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        div = 0.0
        g = DIV.get(t)
        if g is not None:
            r = _latest_row(g, "filed", asof)
            if r is not None:
                div = r["dividends"]
        buyback = max(0.0, sh_prev - sh_now) * px
        out[t] = (div + buyback) / (px * sh_now)
    return out


# ── H39 insider data ─────────────────────────────────────────
def load_insider():
    df = pd.read_csv(FILING_NET, parse_dates=["acceptance_date"])
    out = {}
    for t, g in df.groupby("ticker"):
        g = g.sort_values("acceptance_date")
        dates = g["acceptance_date"].values
        csum = np.concatenate([[0.0], np.cumsum(g["net_usd"].values)])
        out[t] = (dates, csum)
    return out


INS = load_insider()


def insider_window_net(t, asof):
    """Net P-minus-S USD with acceptance in (asof-6mo, asof]."""
    dates, csum = INS.get(t, (None, None))
    if dates is None:
        return 0.0
    start = (asof - pd.DateOffset(months=6)).to_datetime64()
    hi = np.searchsorted(dates, asof.to_datetime64(), side="right")
    lo = np.searchsorted(dates, start, side="right")
    return float(csum[hi] - csum[lo])


def choose_h39(k, mc, asof):
    mc_row = mc[L].iloc[k]
    scores, mcaps = {}, {}
    for t in L:
        g = r8.FUND.get(t)
        if g is None:
            continue
        idx = g["filed_all"].searchsorted(asof, side="right") - 1
        if idx < 0:
            continue
        sh = g.iloc[idx]["shares"]
        px = mc_row.get(t)
        if not np.isfinite(sh) or sh <= 0 or px is None \
                or not np.isfinite(px) or px <= 0:
            continue
        mcaps[t] = px * sh
        scores[t] = insider_window_net(t, asof) / mcaps[t]
    pos = sorted((t for t in scores if scores[t] > 0),
                 key=lambda t: scores[t], reverse=True)
    picks = pos[:TOP_L]
    n_fill = 0
    if len(picks) < TOP_L:
        rest = sorted((t for t in scores if t not in picks),
                      key=lambda t: mcaps[t], reverse=True)
        n_fill = min(TOP_L - len(picks), len(rest))
        picks += rest[:n_fill]
    ELIG["H39_pos"].append(len(pos))
    ELIG["H39_fill"].append(n_fill)
    if len(picks) < TOP_L:
        return {}
    return {t: 1.0 / len(picks) for t in picks}


def make_choose(kind):
    def choose(k, mc, asof):
        if kind == "H36":
            snap = snapshot_h36(asof)
            asc = False
        elif kind == "H37":
            snap = snapshot_h37(asof)
            asc = True
        else:  # H38
            snap = snapshot_h38(asof, mc[L].iloc[k])
            asc = False
        ELIG[kind].append(len(snap))
        if len(snap) < TOP_L:
            return {}
        s = pd.Series(snap)
        top = s.sort_values(ascending=asc, kind="mergesort").index[:TOP_L]
        return {t: 1.0 / len(top) for t in top}
    return choose


def main():
    opens, closes = r8.load_prices()
    eq_spy = r8.spy_bh(opens, closes)
    _, spy_oos = oos_split(eq_spy)
    sb = r1.stats(spy_oos)
    print(f"SPY B&H OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")

    report = {"n_tests_cumulative": N_TESTS,
              "SPY_BH": dict(oos=dict(cagr=sb["cagr"],
                                      sharpe=sb["sharpe"],
                                      max_dd=sb["max_dd"])),
              "coverage": {
                  "gp_tickers": len(GP),
                  "assets_tickers": len(ASSETS),
                  "div_tickers": len(DIV),
                  "insider_tickers_in_filing_net": len(INS)}}
    if os.path.exists(MONTHLY_NET):
        mn = pd.read_csv(MONTHLY_NET)
        report["coverage"]["insider_monthly_rows"] = len(mn)
        report["coverage"]["insider_tickers_any_activity"] = \
            int(mn["ticker"].nunique())
        fn = pd.read_csv(FILING_NET)
        report["coverage"]["insider_filings_parsed"] = len(fn)
        report["coverage"]["insider_filings_with_ps"] = int(
            ((fn["n_p_tx"] + fn["n_s_tx"]) > 0).sum())
    fp = os.path.join("data", "insider", "parse_failures.csv")
    if os.path.exists(fp):
        report["coverage"]["insider_parse_failures"] = \
            max(0, sum(1 for _ in open(fp)) - 1)

    runners = [("H36", make_choose("H36")), ("H37", make_choose("H37")),
               ("H38", make_choose("H38")), ("H39", choose_h39)]
    for name, choose in runners:
        eq, tr = r8.run_monthly(opens, closes, choose)
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
            control=None,
            control_note="not reported: pre-registered slow-"
                         "turnover caveat (round 8/9)")
        if name in ("H36", "H37", "H38") and ELIG[name]:
            entry["eligible_names_per_month"] = dict(
                min=min(ELIG[name]), median=int(np.median(ELIG[name])),
                max=max(ELIG[name]))
        if name == "H39":
            entry["positive_score_names_per_month"] = dict(
                min=min(ELIG["H39_pos"]),
                median=int(np.median(ELIG["H39_pos"])),
                max=max(ELIG["H39_pos"]))
            entry["fill_slots_per_month"] = dict(
                months_with_fill=int(sum(1 for x in ELIG["H39_fill"]
                                         if x > 0)),
                total_months=len(ELIG["H39_fill"]),
                max_fill=max(ELIG["H39_fill"]))
        report[name] = entry

    with open("data/round10_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round10_report.json")


if __name__ == "__main__":
    main()
