# ============================================================
#  round6_research.py — Tests PREREGISTRATION_2026-10-20_round6.md
#
#  H20 overnight-only SPY          H22 small-cap sector momentum
#  H21 pairs trading, universe L   H23 large-cap low volatility
#
#  Written AFTER the pre-registration commit. Costs 5 bps per side
#  everywhere. Signals at close, fills at next open where opens
#  exist (SPY / universe L); the small-cap leg follows the round-5
#  adjclose convention. In-sample through 2023-07-06 is context
#  only; verdicts on OOS (2023-07-07 onward) only. PASS requires
#  OOS excess CAGR > 0 AND excess t >= Bonferroni bar (cumulative
#  25 tests) AND OOS Sharpe above the benchmark's.
#    python round6_research.py
# ============================================================

import json
import math
import os
from io import StringIO

import numpy as np
import pandas as pd
import requests
from scipy import stats as sstats

import daily_research as r1
import round3_research as r3
import round5_research as r5
from round2_data import L

COST       = r1.COST      # 5 bps per side, pre-registered
CASH0      = 2000.0
IS_END     = "2023-07-06"  # OOS starts here (same split as rounds 2-5)
EVAL_START = "2016-01-01"  # round-5 convention (small-cap leg)
N_TESTS    = 25           # cumulative hypotheses through round 6
PAIR_SLOTS = 20           # H21: pairs selected / max concurrent
PAIR_CAP   = 2            # H21: each name in at most 2 pairs
ZWINDOW    = 60           # H21: spread normalisation window (sessions)
Z_ENTER    = 2.0          # H21: entry threshold
HARD_EXIT  = 20           # H21: sessions after which a pair trade is closed


# ── statistics (house conventions, rounds 3-5) ────────────────
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
    formula as rounds 3-5 (2.88 @ 13, 2.96 @ 16, 3.05 @ 21)."""
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


# ── H20: overnight-only SPY (local SPY_1Day.csv OHLC) ─────────
def h20():
    df = pd.read_csv(os.path.join("data", "SPY_1Day.csv"),
                     parse_dates=["timestamp"])
    idx = pd.DatetimeIndex([t.tz_convert("America/New_York").date()
                            for t in df["timestamp"]])
    df = df.set_index(idx).sort_index()
    o, c = df["open"], df["close"]
    days = df.index
    # night return earned into day t (t >= 1): bought at close t-1,
    # sold at open t, 5 bps charged on each side of the round trip
    night = o.values[1:] * (1 - COST) / (c.values[:-1] * (1 + COST)) - 1
    eq = pd.Series(CASH0 * np.cumprod(np.concatenate([[1.0], 1 + night])),
                   index=days)
    # benchmark: SPY buy & hold from the same CSV (first open, one cost)
    sh = CASH0 / (o.iloc[0] * (1 + COST))
    eq_b = sh * c
    print(f"H20 data: SPY_1Day.csv {days[0].date()} -> {days[-1].date()}, "
          f"{len(days)} sessions")
    return eq, eq_b


# ── H21: pairs trading on universe L ──────────────────────────
def h21(opens, closes):
    days = closes.index
    px, op = closes[L], opens[L]
    # formation screen: in-sample daily-return correlation only
    is_px = px.loc[days[days <= pd.Timestamp(IS_END)]]
    corr = is_px.pct_change().corr()
    cand = sorted(((corr.iloc[i, j], L[i], L[j])
                   for i in range(len(L)) for j in range(i + 1, len(L))),
                  key=lambda x: -x[0])
    pairs, used = [], {}
    for cv, a, b in cand:
        if used.get(a, 0) >= PAIR_CAP or used.get(b, 0) >= PAIR_CAP:
            continue
        pairs.append((a, b, float(cv)))
        used[a], used[b] = used.get(a, 0) + 1, used.get(b, 0) + 1
        if len(pairs) == PAIR_SLOTS:
            break
    print(f"H21 screen: {len(pairs)} pairs, corr "
          f"{min(p[2] for p in pairs):.2f}..{max(p[2] for p in pairs):.2f}: "
          + ", ".join(f"{a}/{b}" for a, b, _ in pairs))
    # z of log price ratio, trailing 60-session mean/stdev
    logp = np.log(px)
    zser = {}
    for pi, (a, b, _) in enumerate(pairs):
        s = logp[a] - logp[b]
        zser[pi] = (s - s.rolling(ZWINDOW).mean()) / s.rolling(ZWINDOW).std()

    book = r1.Book(CASH0, COST)
    state, pend_x, pend_e = {}, {}, {}   # pair -> open trade / exit / entry
    eq, n_trades, max_conc = [], 0, 0
    for i in range(len(days)):
        o, cprev = op.iloc[i], closes.iloc[i - 1] if i > 0 else None
        for pi in list(pend_x):                       # exits at open
            st = state.pop(pi)
            for s, q in st["shares"].items():
                book.trade(s, -q, o[s])
            n_trades += 1
        pend_x.clear()
        for pi, sgn in pend_e.items():                # entries at open
            a, b, _ = pairs[pi]
            slot = book.value(cprev) / PAIR_SLOTS    # equity at decision close
            qa, qb = -sgn * slot / o[a], sgn * slot / o[b]
            book.trade(a, qa, o[a])
            book.trade(b, qb, o[b])
            state[pi] = dict(fill_i=i, sign=sgn, shares={a: qa, b: qb})
        pend_e.clear()
        max_conc = max(max_conc, len(state))
        eq.append(book.value(closes.iloc[i]))
        if i == len(days) - 1:
            break
        for pi in range(len(pairs)):                  # decisions at close i
            z = zser[pi].iloc[i]
            if math.isnan(z):
                continue
            if pi in state:
                st = state[pi]
                crossed = np.sign(z) == 0 or np.sign(z) == -st["sign"]
                if crossed or (i - st["fill_i"]) >= HARD_EXIT:
                    pend_x[pi] = True
            elif abs(z) > Z_ENTER and len(state) + len(pend_e) < PAIR_SLOTS:
                pend_e[pi] = 1 if z > 0 else -1
    print(f"H21: {n_trades} round trips, max concurrent {max_conc}")
    return pd.Series(eq, index=days), pairs, n_trades, max_conc


# ── H22: small-cap sector momentum (round-5 machinery) ────────
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"}
SECTORS_CSV = os.path.join("data", "smallcap", "sectors.csv")


def load_sector_map():
    """ticker (Yahoo format) -> GICS sector. Cached to sectors.csv;
    refetched from the Wikipedia constituent table when absent."""
    if os.path.exists(SECTORS_CSV):
        m = pd.read_csv(SECTORS_CSV)
        return dict(zip(m["ticker"], m["sector"]))
    html = requests.get(WIKI_URL, headers=UA, timeout=60).text
    tbl = None
    for t in pd.read_html(StringIO(html)):
        cols = [str(c).strip().lower() for c in t.columns]
        if "symbol" in cols and any("sector" in c for c in cols):
            tbl = t
            sym_c = t.columns[cols.index("symbol")]
            sec_c = t.columns[[i for i, c in enumerate(cols)
                               if "sector" in c][0]]
            break
    if tbl is None:
        raise SystemExit("no constituents table with a sector column found")
    rows = [{"ticker": str(s).strip().replace(".", "-"),
             "sector": str(g).strip()}
            for s, g in zip(tbl[sym_c], tbl[sec_c])
            if str(s).strip() not in ("nan", "")]
    pd.DataFrame(rows).drop_duplicates("ticker").to_csv(SECTORS_CSV,
                                                        index=False)
    print(f"H22: sector map for {len(rows)} tickers -> {SECTORS_CSV}")
    return {r["ticker"]: r["sector"] for r in rows}


def h22(px, bench):
    days = px.index
    me_dates, entry, sig, elig = r5.build_signals(px)
    sec_of = load_sector_map()
    sectors = sorted({sec_of[t] for t in px.columns if t in sec_of})
    mom = sig["mom"]
    sched, held_counts = [], []
    for k in range(len(me_dates)):
        e = entry[me_dates[k]]
        x = entry[me_dates[k + 1]] if k + 1 < len(me_dates) else days[-1]
        if e < pd.Timestamp(EVAL_START):
            continue
        sched.append((k, e, x))
    periods = []
    for k, e, x in sched:
        d = me_dates[k]
        pool = elig.loc[d]
        smom = {}
        for g in sectors:
            names = [t for t in px.columns
                     if sec_of.get(t) == g and pool.get(t, False)
                     and pd.notna(mom.at[d, t])]
            if names:
                smom[g] = float(mom.loc[d, names].mean())
        top3 = sorted(smom, key=lambda g: -smom[g])[:3]
        picks = [t for t in px.columns
                 if sec_of.get(t) in top3 and pool.get(t, False)]
        periods.append((e, x, picks))
        held_counts.append(len(picks))
    eq_full, records = r5.simulate(px, periods)
    eval_days = days[days >= pd.Timestamp(EVAL_START)]
    eq = eq_full.reindex(eval_days).ffill().fillna(CASH0)
    eq_bench = CASH0 * (1 - COST) * bench / bench.loc[eval_days[0]]
    eq_bench = eq_bench.reindex(eval_days)
    print(f"H22: {len(sectors)} sectors mapped, {len(records)} rebalances, "
          f"avg {np.mean(held_counts):.0f} names held")
    return eq, eq_bench, len(records), float(np.mean(held_counts))


# ── H23: large-cap low volatility (rounds 1-4 monthly engine) ─
def h23(opens, closes):
    vol = closes[L].pct_change().rolling(60).std()

    def choose(k, mc):
        day = mc.index[k]
        if day not in vol.index:
            return {}
        v = vol.loc[day].dropna()
        if len(v) < 26:
            return {}
        low = v.sort_values(kind="mergesort").index[:26]
        return {s: 1.0 / len(low) for s in low}

    return r3.run_monthly(opens, closes, choose)


def main():
    report = {}

    # SPY benchmark from the universe-L panel (H21/H23), round-3 style
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

    # H20
    eq20, eq20_b = h20()
    _, b20_oos = oos_split(eq20_b)
    s20b = r1.stats(b20_oos)
    print(f"SPY buy&hold (CSV) OOS: CAGR {s20b['cagr']:+.1%} "
          f"Sharpe {s20b['sharpe']:.2f} maxDD {s20b['max_dd']:.1%}")
    report["H20"] = report_line("H20", eq20, eq20_b, "SPY")

    # H21
    eq21, pairs, n21, conc21 = h21(opens, closes)
    report["H21"] = report_line("H21", eq21, eq_spy, "SPY")
    report["H21"]["pairs"] = [f"{a}/{b} (r={cv:.3f})" for a, b, cv in pairs]
    report["H21"]["oos"]["round_trips_total"] = n21
    report["H21"]["oos"]["max_concurrent"] = conc21

    # H23
    eq23, tr23 = h23(opens, closes)
    report["H23"] = report_line("H23", eq23, eq_spy, "SPY",
                                extra=f" | exits {len(tr23)}")
    report["H23"]["oos"]["position_exits"] = int(len(tr23))

    # H22 (round-5 panel; IWM benchmark)
    px, bench = r5.load_panel()
    eq22, eq22_b, nreb22, avgheld22 = h22(px, bench)
    _, iwm_oos = oos_split(eq22_b)
    si = r1.stats(iwm_oos)
    print(f"IWM buy&hold OOS: CAGR {si['cagr']:+.1%} Sharpe {si['sharpe']:.2f} "
          f"maxDD {si['max_dd']:.1%}")
    report["IWM_BH"] = dict(oos=dict(cagr=si["cagr"], sharpe=si["sharpe"],
                                     max_dd=si["max_dd"]))
    report["H22"] = report_line("H22", eq22, eq22_b, "IWM")
    report["H22"]["oos"]["rebalances"] = nreb22
    report["H22"]["oos"]["avg_names_held"] = avgheld22

    with open("data/round6_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round6_report.json")


if __name__ == "__main__":
    main()
