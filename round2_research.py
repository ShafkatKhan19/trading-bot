# ============================================================
#  round2_research.py — Tests PREREGISTRATION_2026-09-27_round2.md
#
#  H4 post-earnings drift, H5 analyst-upgrade drift (both on universe L,
#  each against a random-entry control), H6 volatility-managed SPY; plus
#  the descriptive "understanding" analyses for H1-H6.
#  Reuses daily_research.py's Book / stats / split so both rounds are
#  measured identically.
#
#    python round2_data.py        # first: data
#    python round2_research.py
# ============================================================

import json
import math
import os
import re
from datetime import time as dtime

import numpy as np
import pandas as pd

import daily_research as r1
from round2_data import L, ROOT

COST       = r1.COST
MIN_T      = 2.64
MIN_TRADES = 100
MIN_CTRL_T = 2.0
SEED       = 20260927
MAX_POS, POS_PCT = 10, 0.10
H4_HOLD, H5_HOLD = 20, 10
UP, DOWN = re.compile(r"\bupgrades?\b", re.I), re.compile(r"\bdowngrades?\b", re.I)


# ── data ──────────────────────────────────────────────────────
def load_L():
    fr = {s: pd.read_pickle(os.path.join(ROOT, "bars", f"{s}.pkl")) for s in L + ["SPY"]}
    opens  = pd.DataFrame({s: f["open"] for s, f in fr.items()}).sort_index().ffill()
    closes = pd.DataFrame({s: f["close"] for s, f in fr.items()}).sort_index().ffill()
    return opens, closes


# ── events ────────────────────────────────────────────────────
def h4_events(closes) -> list:
    """(entry_index, symbol, priority) — priority: larger surprise first."""
    e = pd.read_pickle(os.path.join(ROOT, "earnings.pkl")).dropna(subset=["surprise_pct"])
    days, out = closes.index, []
    for _, row in e.iterrows():
        ts = pd.Timestamp(row.ts).tz_convert("America/New_York")
        d = pd.Timestamp(ts.date())
        k = days.searchsorted(d)                       # first session >= report date
        if k >= len(days):
            continue
        if not (days[k] == d and ts.time() < dtime(12, 0)):
            k = k + 1 if days[k] == d else k           # after-noon report -> next session
        if k < 1 or k + 1 >= len(days):
            continue
        s = row.symbol
        react = closes[s].iloc[k] / closes[s].iloc[k - 1] - 1
        if row.surprise_pct > 0 and react > 0:
            out.append((k + 1, s, -float(row.surprise_pct)))
    return out


def h5_events(closes) -> list:
    """(entry_index, symbol, priority) — priority: publication time (first-come)."""
    n = pd.read_pickle(os.path.join(ROOT, "news.pkl"))
    n = n[n.headline.str.contains(UP) & ~n.headline.str.contains(DOWN)]
    days, out, seen = closes.index, [], set()
    for _, row in n.sort_values("created_at").iterrows():
        t = pd.Timestamp(row.created_at).tz_convert("America/New_York")
        d = pd.Timestamp(t.date())
        k = days.searchsorted(d)
        if k < len(days) and days[k] == d and t.time() >= dtime(9, 30):
            k += 1                                      # published after the open -> next open
        if k >= len(days):
            continue
        for s in row.symbols.split(","):
            if s in L and (k, s) not in seen:
                seen.add((k, s))
                out.append((k, s, t.value))
    return out


# ── engines ───────────────────────────────────────────────────
def run_events(opens, closes, events, hold, cost):
    """Portfolio: max MAX_POS positions at POS_PCT of prior-close equity; exit at open after `hold` sessions."""
    days = closes.index
    start = days.searchsorted(pd.Timestamp(r1.EVAL_START))
    by_day = {}
    for k, s, p in events:
        by_day.setdefault(k, []).append((p, s))
    b, eq, held = r1.Book(500.0, cost), [], {}
    for i in range(start, len(days)):
        o = opens.iloc[i]
        prev_eq = b.value(closes.iloc[i - 1])
        for s, (k, q) in list(held.items()):
            if i - k >= hold:
                b.trade(s, -q, o[s]); del held[s]
        for _, s in sorted(by_day.get(i, [])):
            if len(held) >= MAX_POS or s in held:
                continue
            q = min(POS_PCT * prev_eq, max(0.0, b.cash) / (1 + cost)) / o[s]
            if q > 0:
                b.trade(s, q, o[s]); held[s] = (i, q)
        eq.append(b.value(closes.iloc[i]))
    return pd.Series(eq, index=days[start:])


def trade_returns(opens, events, hold, cost, from_i, to_i):
    """Unconstrained per-event returns (every event, no slot limit), entries in [from_i, to_i)."""
    out = []
    for k, s, _ in events:
        if from_i <= k < to_i and k + hold < len(opens):
            out.append((opens[s].iloc[k + hold] * (1 - cost)) / (opens[s].iloc[k] * (1 + cost)) - 1)
    return np.array(out)


def control_events(events, days_n, from_i, to_i, hold, seed):
    """Same count per symbol, random non-event entry days in the same window."""
    rng = np.random.default_rng(seed)
    ev = {}
    for k, s, _ in events:
        if from_i <= k < to_i:
            ev.setdefault(s, set()).add(k)
    out = []
    for s, ks in ev.items():
        pool = np.array([k for k in range(from_i, min(to_i, days_n - hold - 1)) if k not in ks])
        for k in rng.choice(pool, size=min(len(ks), len(pool)), replace=False):
            out.append((int(k), s, 0.0))
    return out


def welch_t(a, b):
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    return (a.mean() - b.mean()) / math.sqrt(va + vb)


def h6_choose(closes):
    ret = closes["SPY"].pct_change()
    vol = ret.rolling(21).std() * math.sqrt(252)
    return lambda i: {"SPY": min(1.0, 0.15 / vol.iloc[i])} if vol.iloc[i] > 0 else {"SPY": 1.0}


# ── H1 sensitivity (descriptive only) ─────────────────────────
def h1_variant(opens, closes, cost, rsi_th, sma_exit, max_hold):
    sma200 = closes.rolling(200).mean(); smaX = closes.rolling(sma_exit).mean()
    rsi2 = closes.apply(lambda c: r1.rsi_wilder(c, 2))
    days = closes.index; start = days.searchsorted(pd.Timestamp(r1.EVAL_START))
    b, eq, held, sells, buys = r1.Book(500.0, cost), [], {}, [], []
    for i in range(start, len(days)):
        o, c = opens.iloc[i], closes.iloc[i]
        prev_eq = b.value(closes.iloc[i - 1])
        for s in sells:
            e_i, q = held.pop(s); b.trade(s, -q, o[s])
        for s in buys:
            q = min(0.20 * prev_eq, max(0.0, b.cash) / (1 + cost)) / o[s]
            if q > 0:
                b.trade(s, q, o[s]); held[s] = (i, q)
        eq.append(b.value(c))
        sells = [s for s, (e_i, _) in held.items() if c[s] > smaX[s].iloc[i] or (i - e_i + 1) >= max_hold]
        free = 5 - (len(held) - len(sells))
        cands = sorted((rsi2[s].iloc[i], s) for s in r1.UNIVERSE
                       if s not in held and c[s] > sma200[s].iloc[i] and rsi2[s].iloc[i] < rsi_th)
        buys = [s for _, s in cands[:max(0, free)]]
    return pd.Series(eq, index=days[start:])


# ── understanding ─────────────────────────────────────────────
def per_year(eq):
    return {int(y): round(float(g.iloc[-1] / g.iloc[0] - 1), 4) for y, g in eq.groupby(eq.index.year)}


def worst_drawdowns(eq, n=5):
    peak = eq.cummax(); dd = eq / peak - 1; out = []
    in_dd = dd < 0
    grp = (in_dd != in_dd.shift()).cumsum()[in_dd]
    for _, seg in dd[in_dd].groupby(grp):
        trough = seg.idxmin()
        out.append({"peak": str(eq.loc[:trough].idxmax().date()), "trough": str(trough.date()),
                    "depth": round(float(seg.min()), 4)})
    return sorted(out, key=lambda x: x["depth"])[:n]


def regime_split(eq, spy):
    r = eq.pct_change().dropna()
    up = (spy > spy.rolling(200).mean()).shift(1).reindex(r.index).fillna(False)
    f = lambda x: {"days": int(len(x)), "ann_return": round(float(x.mean() * 252), 4),
                   "sharpe": round(float(x.mean() / x.std() * math.sqrt(252)), 2) if x.std() > 0 else 0.0}
    return {"spy_above_200d": f(r[up]), "spy_below_200d": f(r[~up])}


def main():
    opens, closes = load_L()
    etf_o, etf_c = r1.load_panel(); etf_o, etf_c = etf_o.dropna(), etf_c.dropna()
    bench = r1.run_monthly(opens[["SPY"]], closes[["SPY"]], lambda i: {"SPY": 1.0}, COST)
    b_is, b_oos = r1.split(bench); bo = r1.stats(b_oos)
    days = closes.index
    oos_i = days.searchsorted(pd.Timestamp(b_oos.index[0])); start_i = days.searchsorted(pd.Timestamp(r1.EVAL_START))
    print(f"OOS from {b_oos.index[0].date()} | SPY OOS Sharpe {bo['sharpe']:.2f} | bar t >= {MIN_T}\n")
    report, curves = {}, {"SPY buy&hold": bench}

    for name, events, hold in (("H4 earnings drift", h4_events(closes), H4_HOLD),
                               ("H5 upgrade drift", h5_events(closes), H5_HOLD)):
        eq = run_events(opens, closes, events, hold, COST); curves[name] = eq
        s_is, s_oos = r1.stats(r1.split(eq)[0]), r1.stats(r1.split(eq)[1])
        ev_oos = trade_returns(opens, events, hold, COST, oos_i, len(days))
        ctrl = control_events(events, len(days), oos_i, len(days), hold, SEED)
        ct_oos = trade_returns(opens, ctrl, hold, COST, oos_i, len(days))
        tc = welch_t(ev_oos, ct_oos) if len(ev_oos) > 1 and len(ct_oos) > 1 else 0.0
        fails = []
        if s_oos["t"] < MIN_T: fails.append(f"t {s_oos['t']:.2f} < {MIN_T}")
        if s_oos["sharpe"] < bo["sharpe"]: fails.append(f"Sharpe {s_oos['sharpe']:.2f} < SPY {bo['sharpe']:.2f}")
        if s_oos["max_dd"] > r1.MAX_DD: fails.append(f"max DD {s_oos['max_dd']:.1%} > 20%")
        if len(ev_oos) < MIN_TRADES: fails.append(f"only {len(ev_oos)} OOS events")
        if tc < MIN_CTRL_T: fails.append(f"vs random-entry control: t {tc:.2f} < {MIN_CTRL_T}")
        v = "PASS" if not fails else "FAIL"
        print(name); print(r1.fmt("in-sample", s_is)); print(r1.fmt("OUT-OF-SAMPLE", s_oos))
        print(f"  events total {len(events)}, OOS {len(ev_oos)} | OOS mean/trade {ev_oos.mean():+.2%} "
              f"vs control {ct_oos.mean():+.2%} (Welch t {tc:+.2f})")
        print(f"  VERDICT: {v}" + "".join(f"\n    - {w}" for w in fails) + "\n")
        report[name] = {"in_sample": s_is, "oos": s_oos, "oos_events": int(len(ev_oos)),
                        "oos_mean_trade": float(ev_oos.mean()), "control_mean_trade": float(ct_oos.mean()),
                        "control_t": float(tc), "verdict": v, "fails": fails}

    eq6 = r1.run_monthly(opens[["SPY"]], closes[["SPY"]], h6_choose(closes), COST); curves["H6 vol-managed SPY"] = eq6
    s_is, s_oos = r1.stats(r1.split(eq6)[0]), r1.stats(r1.split(eq6)[1])
    fails = [m for m, bad in ((f"t {s_oos['t']:.2f} < {MIN_T}", s_oos["t"] < MIN_T),
                              (f"Sharpe {s_oos['sharpe']:.2f} < SPY {bo['sharpe']:.2f}", s_oos["sharpe"] < bo["sharpe"]),
                              (f"max DD {s_oos['max_dd']:.1%} > 20%", s_oos["max_dd"] > r1.MAX_DD)) if bad]
    v = "PASS" if not fails else "FAIL"
    print("H6 vol-managed SPY"); print(r1.fmt("in-sample", s_is)); print(r1.fmt("OUT-OF-SAMPLE", s_oos))
    print(f"  VERDICT: {v}" + "".join(f"\n    - {w}" for w in fails) + "\n")
    report["H6 vol-managed SPY"] = {"in_sample": s_is, "oos": s_oos, "verdict": v, "fails": fails}

    # round-1 curves for the understanding section
    curves["H1 RSI2 pullback"] = r1.run_h1(etf_o, etf_c, COST)[0]
    curves["H2 SPY 200d trend"] = r1.run_monthly(etf_o, etf_c, r1.h2_choose(etf_c), COST)
    curves["H3 sector momentum"] = r1.run_monthly(etf_o, etf_c, r1.h3_choose(etf_c), COST)

    print("=== Understanding (descriptive only) ===\nReturn by year:")
    years = sorted({y for c in curves.values() for y in c.index.year})
    print("  " + f"{'':<20}" + "".join(f"{y:>8}" for y in years))
    for n, c in curves.items():
        py = per_year(c); print("  " + f"{n:<20}" + "".join(f"{py.get(y, float('nan')):>+8.1%}" for y in years))
    print("\nBy market regime (SPY vs its 200-day average), annualized return / Sharpe:")
    spy = closes["SPY"]
    for n, c in curves.items():
        rs = regime_split(c, spy)
        print(f"  {n:<20} above: {rs['spy_above_200d']['ann_return']:+.1%} / {rs['spy_above_200d']['sharpe']:.2f}"
              f"   below: {rs['spy_below_200d']['ann_return']:+.1%} / {rs['spy_below_200d']['sharpe']:.2f}"
              f"   ({rs['spy_below_200d']['days']} days below)")
    print("\nWorst drawdowns:")
    for n, c in curves.items():
        print(f"  {n:<20} " + "; ".join(f"{d['depth']:.1%} ({d['peak']}->{d['trough']})" for d in worst_drawdowns(c, 3)))

    base = r1.stats(r1.split(h1_variant(etf_o, etf_c, COST, 10, 5, 10))[1])
    reg  = r1.stats(r1.split(curves["H1 RSI2 pullback"])[1])
    assert abs(base["sharpe"] - reg["sharpe"]) < 1e-9, "h1_variant must reproduce registered H1"
    print("\nH1 sensitivity, OUT-OF-SAMPLE Sharpe (NOT used to pick parameters; registered = RSI<10, SMA5, 10d):")
    grid = {}
    for th in (5, 10, 15):
        for sx in (3, 5, 10):
            row = []
            for mh in (5, 10, 20):
                sh = r1.stats(r1.split(h1_variant(etf_o, etf_c, COST, th, sx, mh))[1])["sharpe"]
                grid[f"rsi<{th},sma{sx},{mh}d"] = round(sh, 2); row.append(f"{mh}d {sh:5.2f}")
            print(f"  RSI<{th:<2} exit SMA{sx:<2}: " + "  ".join(row))
    report["understanding"] = {"per_year": {n: per_year(c) for n, c in curves.items()},
                               "regime": {n: regime_split(c, spy) for n, c in curves.items()},
                               "worst_drawdowns": {n: worst_drawdowns(c) for n, c in curves.items()},
                               "h1_grid_oos_sharpe": grid, "spy_oos_sharpe": bo["sharpe"]}
    with open(os.path.join(ROOT, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=float)
    print(f"\n-> {ROOT}/report.json")


if __name__ == "__main__":
    main()
