# ============================================================
#  round8_research.py — Tests PREREGISTRATION_2026-10-20_round8.md
#
#  H28 value (book-to-market)      H29 earnings yield
#  H30 quality (ROE)               H31 value+quality blend
#
#  Written AFTER the pre-registration commit. Fundamentals are
#  SEC EDGAR fiscal-year facts, strictly point-in-time: a value
#  is usable only on/after its `filed` date (a row is usable
#  once ALL THREE facts are public). Monthly engine identical
#  to round 3 (signals at month-end close, fills at next open,
#  5 bps/side, long-only). Market cap = month-end close x the
#  latest filed shares, exactly as pre-registered.
#    python round8_research.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats as sstats

import daily_research as r1
from round2_data import L, ROOT

COST = r1.COST            # 5 bps per side, pre-registered
CASH0 = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-7)
N_TESTS = 33              # cumulative hypotheses through round 8
MIN_CTRL_T = 2.0          # reported for context (round-3 convention)
SEED = 20261020
TOP_N = 26                # top ~30% of 87

PANEL = os.path.join("data", "fundamentals", "panel.csv")


# ── data ──────────────────────────────────────────────────────
def load_prices():
    syms = list(L) + ["SPY"]
    fr = {s: pd.read_pickle(os.path.join(ROOT, "bars", f"{s}.pkl"))
          for s in syms}
    opens = pd.DataFrame({s: f["open"] for s, f in fr.items()}
                         ).sort_index().ffill()
    closes = pd.DataFrame({s: f["close"] for s, f in fr.items()}
                          ).sort_index().ffill()
    return opens, closes


def load_fundamentals():
    """Per ticker: usable FY rows sorted by public-availability
    date (= max of the three facts' filed dates)."""
    df = pd.read_csv(PANEL, parse_dates=["fy_end", "filed_ni",
                                         "filed_eq", "filed_sh"])
    df = df.dropna(subset=["net_income", "equity", "shares"])
    df["filed_all"] = df[["filed_ni", "filed_eq", "filed_sh"]].max(axis=1)
    out = {}
    for t, g in df.groupby("ticker"):
        out[t] = g.sort_values("filed_all").reset_index(drop=True)
    return out


FUND = load_fundamentals()


def snapshot(asof, mc_row):
    """Eligible names at a month-end: latest FY row public by
    `asof`, positive equity and shares. Returns ratio frame."""
    rows = {}
    for t in L:
        g = FUND.get(t)
        if g is None:
            continue
        idx = g["filed_all"].searchsorted(asof, side="right") - 1
        if idx < 0:
            continue
        r = g.iloc[idx]
        if r["equity"] <= 0 or r["shares"] <= 0:
            continue
        mcap = mc_row[t] * r["shares"]
        if not np.isfinite(mcap) or mcap <= 0:
            continue
        rows[t] = {"bm": r["equity"] / mcap,
                   "ep": r["net_income"] / mcap,
                   "roe": r["net_income"] / r["equity"]}
    return pd.DataFrame(rows).T


# ── monthly engine (round 3, verbatim mechanics) ─────────────
def run_monthly(opens, closes, choose):
    """choose(k, mc, asof) -> target weights using month-end
    closes mc up to k; asof is the month's last trading day.
    Fills at the open of the first trading day after month-end."""
    days = closes.index
    mc = closes.resample("ME").last()
    me_days = [days.get_loc(d) for d in mc.index if d in closes.index]
    me_days = [i for i in me_days if i + 1 < len(days)]
    me_pos = {d: p for p, d in enumerate(mc.index)}

    sched = [(i + 1, choose(me_pos[days[i]], mc, days[i]))
             for i in me_days]

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


# ── hypotheses (exactly as pre-registered) ────────────────────
def _top(snap, col):
    top = snap[col].sort_values(ascending=False).index[:TOP_N]
    return {s: 1.0 / len(top) for s in top}


def make_choose(kind):
    def choose(k, mc, asof):
        snap = snapshot(asof, mc[L].iloc[k])
        if len(snap) < TOP_N:
            return {}
        if kind == "H28":
            return _top(snap, "bm")
        if kind == "H29":
            return _top(snap, "ep")
        if kind == "H30":
            return _top(snap, "roe")
        # H31: average of H28 and H30 ranks (1 = best)
        r_bm = snap["bm"].rank(ascending=False, method="min")
        r_roe = snap["roe"].rank(ascending=False, method="min")
        blend = (r_bm + r_roe) / 2.0
        top = blend.sort_values(kind="mergesort").index[:TOP_N]
        return {s: 1.0 / len(top) for s in top}
    return choose


def spy_bh(opens, closes):
    b = r1.Book(CASH0, COST)
    b.trade("SPY", CASH0 / (opens["SPY"].iloc[0] * (1 + COST)),
            opens["SPY"].iloc[0])
    return pd.Series([b.cash + b.sh["SPY"] * closes["SPY"].iloc[i]
                      for i in range(len(closes))],
                     index=closes.index)


# ── statistics (round 3/7 conventions) ────────────────────────
def oos_split(eq):
    cut = eq.index.searchsorted(pd.Timestamp(IS_END))
    return eq.iloc[:cut + 1], eq.iloc[cut:]


def excess_series(strat_oos, spy_oos):
    r = strat_oos.pct_change().dropna()
    m = spy_oos.pct_change().dropna()
    return (r - m).dropna()


def excess_t(x):
    n, sd = len(x), x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(n))) if sd > 0 and n > 1 else 0.0


def bonf_bar(n):
    """Bonferroni one-sided bar; same formula as rounds 3-7."""
    return float(sstats.t.ppf(1 - 0.05 / (2 * N_TESTS), df=n - 1))


def random_control(trades, opens, closes, me_days, days):
    """Round-3 h10_control, verbatim method: same stocks, same
    ~1-month holds, random month-ends. Welch t."""
    rng = np.random.default_rng(SEED)
    real, ctrl = [], []
    dec = [i for i in me_days]
    for _, tr in trades.iterrows():
        s = tr["symbol"]
        real.append(tr["net"])
        k = dec[rng.integers(0, len(dec))]
        if k + 1 < len(days):
            e2, x2 = k + 1, min(k + 22, len(days) - 1)
            ep, xp = opens[s].iloc[e2], opens[s].iloc[x2]
            ctrl.append(float(xp * (1 - COST) / (ep * (1 + COST)) - 1))
    t = float(sstats.ttest_ind(real, ctrl, equal_var=False).statistic)
    return t, len(real), float(np.mean(real)), float(np.mean(ctrl))


def main():
    opens, closes = load_prices()
    days = closes.index
    print(f"Prices {days[0].date()} -> {days[-1].date()}, "
          f"{len(L)} stocks + SPY")
    elig = {t: len(g) for t, g in FUND.items()}
    print(f"Fundamentals: {len(FUND)}/87 tickers with >=1 complete "
          f"FY row; median FY rows per ticker "
          f"{int(np.median(list(elig.values())))}")

    mc = closes.resample("ME").last()
    me_days = [days.get_loc(d) for d in mc.index if d in closes.index]
    me_days = [i for i in me_days if i + 1 < len(days)]

    eq_spy = spy_bh(opens, closes)
    _, spy_oos = oos_split(eq_spy)
    b_stats = r1.stats(spy_oos)
    print(f"SPY B&H OOS: CAGR {b_stats['cagr']:+.1%} "
          f"Sharpe {b_stats['sharpe']:.2f} maxDD {b_stats['max_dd']:.1%}")

    report = {"benchmark_oos": b_stats, "n_tests_cumulative": N_TESTS,
              "fundamentals_coverage": {
                  "tickers_with_complete_rows": len(FUND),
                  "rows_per_ticker": {t: int(n)
                                      for t, n in elig.items()}}}
    for name in ["H28", "H29", "H30", "H31"]:
        eq, tr = run_monthly(opens, closes, make_choose(name))
        is_eq, oos_eq = oos_split(eq)
        x = excess_series(oos_eq, spy_oos)
        t = excess_t(x)
        bar = bonf_bar(len(x))
        s = r1.stats(oos_eq)
        ctrl_t, n_tr, m_real, m_ctrl = random_control(
            tr, opens, closes, me_days, days)
        fails = []
        if s["cagr"] <= b_stats["cagr"]:
            fails.append(f"excess CAGR {s['cagr'] - b_stats['cagr']:+.1%} <= 0")
        if t < bar:
            fails.append(f"excess-t {t:.2f} < {bar:.2f}")
        if s["sharpe"] <= b_stats["sharpe"]:
            fails.append(f"Sharpe {s['sharpe']:.2f} <= SPY {b_stats['sharpe']:.2f}")
        v = "PASS" if not fails else "FAIL"
        si = r1.stats(is_eq)
        print(f"{name}: trades {len(tr)} | control {n_tr} trades, "
              f"real {m_real:+.2%}/trade vs random {m_ctrl:+.2%}/trade, "
              f"Welch t {ctrl_t:+.2f}")
        print(f"   IS : CAGR {si['cagr']:+6.1%} Sharpe {si['sharpe']:5.2f} "
              f"maxDD {si['max_dd']:5.1%}")
        print(f"   OOS: CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} "
              f"t(excess) {t:+5.2f} (bar {bar:.2f}) maxDD {s['max_dd']:5.1%} "
              f"-> {v}" + (f" [{'; '.join(fails)}]" if fails else ""))
        report[name] = dict(
            verdict=v, fails=fails,
            oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                     bar=bar, max_dd=s["max_dd"], trades=len(tr)),
            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
            control=dict(t=ctrl_t, n=n_tr, mean_real=m_real,
                         mean_ctrl=m_ctrl))

    with open("data/round8_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round8_report.json")


if __name__ == "__main__":
    main()
