# ============================================================
#  round3_research.py — Tests PREREGISTRATION_2026-10-17_round3.md
#
#  H9  time-series momentum 12-1 (Moskowitz-Ooi-Pedersen 2012)
#  H10 cross-sectional momentum 6-1 (Jegadeesh-Titman 1993)
#  H11 dual momentum (Antonacci 2014)
#
#  Written AFTER the pre-registration commit (a1d98cb). Signals at
#  month-end close, fills at next open, 5 bps/side, long-only.
#    python round3_research.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd
from scipy import stats as sstats

import daily_research as r1
from round2_data import L, ROOT

COST   = r1.COST          # 5 bps per side, pre-registered
CASH0  = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as round 2)
MIN_T  = 2.88             # Bonferroni over 13 strategies
MIN_CTRL_T = 2.0
SEED   = 20261017
TOP_Q  = 17               # top quintile of 87


# ── data ──────────────────────────────────────────────────────
def load():
    syms = list(L) + ["SPY"]
    fr = {s: pd.read_pickle(os.path.join(ROOT, "bars", f"{s}.pkl")) for s in syms}
    opens  = pd.DataFrame({s: f["open"]  for s, f in fr.items()}).sort_index().ffill()
    closes = pd.DataFrame({s: f["close"] for s, f in fr.items()}).sort_index().ffill()
    return opens, closes


# ── monthly engine ────────────────────────────────────────────
def run_monthly(opens, closes, choose):
    """choose(k, mc) -> target weights using month-end closes mc up to k.
    Fills at the open of the first trading day after month-end k."""
    days = closes.index
    mc = closes.resample("ME").last()
    # decision month-ends that have a next trading day to fill on
    me_days = [days.get_loc(d) for d in mc.index if d in closes.index]
    me_days = [i for i in me_days if i + 1 < len(days)]
    # month-end positions in mc for lookbacks
    me_pos = {d: p for p, d in enumerate(mc.index)}

    sched = [(i + 1, choose(me_pos[days[i]], mc)) for i in me_days]

    b, eq, trades = r1.Book(CASH0, COST), [], []
    held, ptr = {}, 0  # sym -> (entry_fill_index, entry_price, qty)
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
                                       net=float(o[s] * (1 - COST) / (e_px * (1 + COST)) - 1)))
            for s, w in tgt.items():                  # entries + top-ups
                want = w * prev_eq / o[s]
                have = held[s][2] if s in held else 0.0
                d = want - have
                if d > 0:
                    d = min(d, max(0.0, b.cash) / (o[s] * (1 + COST)))
                if abs(d) > 1e-9:
                    b.trade(s, d, o[s])
                    held[s] = (held[s][0], held[s][1], held[s][2] + d) if s in held \
                        else (i, o[s], d)
            for s in list(held):                      # drop dust
                if abs(held[s][2]) < 1e-9:
                    del held[s]
            ptr += 1
        eq.append(b.value(closes.iloc[i]))
    return pd.Series(eq, index=days), pd.DataFrame(trades)


# ── hypotheses (exactly as pre-registered) ────────────────────
def h9_choose(k, mc):
    if k < 12:
        return {}
    r = mc[L].iloc[k - 1] / mc[L].iloc[k - 12] - 1
    held = [s for s in L if r[s] > 0]
    return {s: 1.0 / len(held) for s in held} if held else {}


def h10_choose(k, mc):
    if k < 6:
        return {}
    r = mc[L].iloc[k - 1] / mc[L].iloc[k - 6] - 1
    top = r.sort_values(ascending=False).index[:TOP_Q]
    return {s: 1.0 / len(top) for s in top}


def h11_choose(k, mc):
    if k < 12:
        return {}
    r = mc[list(L) + ["SPY"]].iloc[k] / mc[list(L) + ["SPY"]].iloc[k - 12] - 1
    best = r.idxmax()
    return {best: 1.0} if r[best] > 0 else {}


def spy_bh(opens, closes):
    b = r1.Book(CASH0, COST)
    b.trade("SPY", CASH0 / (opens["SPY"].iloc[0] * (1 + COST)), opens["SPY"].iloc[0])
    return pd.Series([b.cash + b.sh["SPY"] * closes["SPY"].iloc[i]
                      for i in range(len(closes))], index=closes.index)


def ew_bh(opens, closes):
    days = closes.index
    mc = closes.resample("ME").last()
    me_days = [days.get_loc(d) for d in mc.index if d in closes.index]
    me_days = [i for i in me_days if i + 1 < len(days)]
    w = {s: 1.0 / len(L) for s in L}
    b = r1.Book(CASH0, COST)
    for i in me_days:
        b.rebalance(w, opens.iloc[i + 1], b.value(closes.iloc[i]))
    return pd.Series([b.value(closes.iloc[i]) for i in range(len(days))], index=days)


# ── statistics ────────────────────────────────────────────────
def oos_split(eq):
    cut = eq.index.searchsorted(pd.Timestamp(IS_END))
    return eq.iloc[:cut + 1], eq.iloc[cut:]


def excess_t(strat_oos, spy_oos):
    r = strat_oos.pct_change().dropna()
    m = spy_oos.pct_change().dropna()
    x = (r - m).dropna()
    n, sd = len(x), x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(n))) if sd > 0 and n > 1 else 0.0


def verdict(name, strat_oos, spy_oos, ctrl_t=None):
    s, b = r1.stats(strat_oos), r1.stats(spy_oos)
    t = excess_t(strat_oos, spy_oos)
    fails = []
    if t < MIN_T:
        fails.append(f"excess-t {t:.2f} < {MIN_T}")
    if s["sharpe"] < b["sharpe"]:
        fails.append(f"Sharpe {s['sharpe']:.2f} < SPY {b['sharpe']:.2f}")
    if s["max_dd"] > b["max_dd"]:
        fails.append(f"maxDD {s['max_dd']:.1%} > SPY {b['max_dd']:.1%}")
    if ctrl_t is not None and ctrl_t < MIN_CTRL_T:
        fails.append(f"control t {ctrl_t:.2f} < {MIN_CTRL_T}")
    return ("PASS" if not fails else "FAIL"), fails, s, b, t


def h10_control(trades, opens, closes, me_days, days):
    """Same stocks, same 1-month holds, random month-ends. Welch t."""
    rng = np.random.default_rng(SEED)
    real, ctrl = [], []
    dec = [i for i in me_days]
    for _, tr in trades.iterrows():
        s = tr["symbol"]
        e = days.get_loc(pd.Timestamp(tr["entry"]))
        x = days.get_loc(pd.Timestamp(tr["exit"]))
        real.append(tr["net"])
        k = dec[rng.integers(0, len(dec))]
        if k + 1 < len(days):
            # 1-month hold from random month-end: entry next open, exit ~21 sessions later
            e2, x2 = k + 1, min(k + 22, len(days) - 1)
            ep, xp = opens[s].iloc[e2], opens[s].iloc[x2]
            ctrl.append(float(xp * (1 - COST) / (ep * (1 + COST)) - 1))
    t = float(sstats.ttest_ind(real, ctrl, equal_var=False).statistic)
    return t, len(real), float(np.mean(real)), float(np.mean(ctrl))


def main():
    opens, closes = load()
    days = closes.index
    print(f"Data {days[0].date()} -> {days[-1].date()}, {len(L)} stocks + SPY")

    mc = closes.resample("ME").last()
    me_days = [days.get_loc(d) for d in mc.index if d in closes.index]
    me_days = [i for i in me_days if i + 1 < len(days)]

    eq_h9, tr_h9 = run_monthly(opens, closes, h9_choose)
    eq_h10, tr_h10 = run_monthly(opens, closes, h10_choose)
    eq_h11, tr_h11 = run_monthly(opens, closes, h11_choose)
    eq_spy = spy_bh(opens, closes)
    eq_ew = ew_bh(opens, closes)

    report = {}
    for name, eq, tr in [("H9", eq_h9, tr_h9), ("H10", eq_h10, tr_h10), ("H11", eq_h11, tr_h11)]:
        is_eq, oos_eq = oos_split(eq)
        _, spy_oos = oos_split(eq_spy)
        ctrl_t = None
        if name == "H10" and len(tr_h10):
            ctrl_t, n_tr, m_real, m_ctrl = h10_control(tr_h10, opens, closes, me_days, days)
            print(f"  H10 control: {n_tr} trades, real {m_real:+.2%}/trade vs "
                  f"random-entry {m_ctrl:+.2%}/trade, Welch t {ctrl_t:+.2f}")
        v, fails, s, b, t = verdict(name, oos_eq, spy_oos, ctrl_t)
        si = r1.stats(is_eq)
        print(f"{name}: OOS {oos_eq.index[0].date()} -> {oos_eq.index[-1].date()} "
              f"| trades {len(tr)}")
        print(f"   IS : CAGR {si['cagr']:+6.1%} Sharpe {si['sharpe']:5.2f} maxDD {si['max_dd']:5.1%}")
        print(f"   OOS: CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
              f"maxDD {s['max_dd']:5.1%} -> {v}"
              + (f" [{'; '.join(fails)}]" if fails else ""))
        report[name] = dict(verdict=v, fails=fails,
                            oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                                     max_dd=s["max_dd"], trades=len(tr)),
                            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]))
    for name, eq in [("SPY_BH", eq_spy), ("EW_L_BH", eq_ew)]:
        is_eq, oos_eq = oos_split(eq)
        s, b = r1.stats(is_eq), r1.stats(oos_eq)
        print(f"{name}: IS CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} | "
              f"OOS CAGR {b['cagr']:+6.1%} Sharpe {b['sharpe']:5.2f} maxDD {b['max_dd']:.1%}")

    with open("data/round3_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round3_report.json")


if __name__ == "__main__":
    main()
