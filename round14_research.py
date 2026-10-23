# ============================================================
#  round14_research.py — Tests
#  PREREGISTRATION_2026-10-23_round14.md
#
#  H50 share-repurchase authorizations (EDGAR 8-K event text)
#  H51 dividend increases / initiations (EDGAR XBRL declared
#      DPS, earliest-filed per quarterly period)
#
#  Written AFTER the pre-registration commit (12555dd local /
#  5391686 on GitHub). Both books run on the round-8 monthly
#  engine (signals at month-end close, fills at next open,
#  5 bps/side, benchmark SPY). Eligibility: the name's latest
#  payout event was public within the trailing 12 months at
#  the signal date (H50: EDGAR file_date of the authorization
#  filing; H51: earliest filed date of the raise/initiation
#  fact). Verdicts OOS 2023-07-07 onward; in-sample context
#  only. Random-entry control per round 8 (the book's own
#  traded names, random month-ends, Welch t), reported for
#  context; the registered PASS legs decide.
#    python round14_research.py
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
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-13)
N_TESTS = 53              # cumulative hypotheses through round 14
BAR_REGISTERED = 3.35     # pre-registered bar (formula checked below)
TOP_N = 26                # top ~30% of 87
WINDOW_DAYS = 365         # trailing-12-month eligibility, registered
SEED = 20261023

BB_PATH = os.path.join("data", "payout", "buyback_events.csv")
DIV_PATH = os.path.join("data", "payout", "dividend_facts.csv")


# ── statistics (house conventions, rounds 9-13) ────────────
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
    """Bonferroni one-sided bar; same formula as rounds 3-13."""
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


def random_control(trades, opens, closes, me_days, days):
    """Round-8 control, verbatim method: same stocks, same
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


# ── H50: buyback authorization events ────────────────────────
def load_buyback_events():
    df = pd.read_csv(BB_PATH, parse_dates=["event_date"])
    out = {}
    for t, g in df.groupby("ticker"):
        out[t] = sorted(g["event_date"])
    return out


def make_choose_h50(events, diag):
    def choose(k, mc, asof):
        rows = []
        for t in L:
            evs = events.get(t)
            if not evs:
                continue
            past = [e for e in evs if e <= asof]
            if not past:
                continue
            latest = past[-1]
            if (asof - latest).days <= WINDOW_DAYS:
                rows.append((latest, t))
        diag["eligible"].append(len(rows))
        if not rows:
            return {}
        rows.sort(key=lambda x: (-x[0].value, x[1]))
        top = rows[:TOP_N]
        return {t: 1.0 / len(top) for _, t in top}
    return choose


# ── H51: dividend raise / initiation events ──────────────────
def load_dividend_events():
    """Events per ticker: (filed date, kind, pct increase).
    Raise: DPS strictly above the immediately preceding
    period's. Initiation: positive DPS with no fact whose
    period ends in the prior 24 months (8 quarters)."""
    df = pd.read_csv(DIV_PATH, parse_dates=["period_end", "filed"])
    events, coverage = {}, {}
    for t, g in df.groupby("ticker"):
        g = g.sort_values("period_end").reset_index(drop=True)
        coverage[t] = len(g)
        evs = []
        for i, row in g.iterrows():
            end, dps = row["period_end"], float(row["dps"])
            if dps <= 0:
                continue
            prior = g[g["period_end"] < end]
            recent = prior[prior["period_end"]
                           > end - pd.DateOffset(months=24)]
            if len(recent) == 0:
                if i > 0 or len(prior) == 0:
                    evs.append((row["filed"], "initiation", None))
                continue
            prev_dps = float(recent.sort_values("period_end")
                             .iloc[-1]["dps"])
            if prev_dps <= 0:
                # resumption after a $0 declaration = initiation
                evs.append((row["filed"], "initiation", None))
            elif dps > prev_dps:
                evs.append((row["filed"], "raise",
                            dps / prev_dps - 1.0))
        if evs:
            events[t] = sorted(evs, key=lambda e: e[0])
    return events, coverage


def make_choose_h51(events, diag):
    def choose(k, mc, asof):
        rows = []
        for t in L:
            evs = events.get(t)
            if not evs:
                continue
            past = [e for e in evs if e[0] <= asof]
            if not past:
                continue
            filed, kind, pct = past[-1]
            if (asof - filed).days <= WINDOW_DAYS:
                rows.append((filed, kind, pct, t))
        diag["eligible"].append(len(rows))
        if not rows:
            return {}
        rows.sort(key=lambda x: (0 if x[1] == "initiation" else 1,
                                 -(x[2] if x[2] is not None else 1e9),
                                 -x[0].value, x[3]))
        top = rows[:TOP_N]
        return {t: 1.0 / len(top) for _, _, _, t in top}
    return choose


def main():
    opens, closes = r8.load_prices()
    days = closes.index
    print(f"Prices {days[0].date()} -> {days[-1].date()}, "
          f"{len(L)} stocks + SPY")
    mc = closes.resample("ME").last()
    me_days = [days.get_loc(d) for d in mc.index if d in closes.index]
    me_days = [i for i in me_days if i + 1 < len(days)]

    eq_spy = r8.spy_bh(opens, closes)
    _, spy_oos = oos_split(eq_spy)
    sb = r1.stats(spy_oos)
    print(f"SPY B&H OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} "
          f"maxDD {sb['max_dd']:.1%}")
    report = {"n_tests_cumulative": N_TESTS,
              "bar_registered": BAR_REGISTERED,
              "SPY_BH": dict(oos=dict(cagr=sb["cagr"],
                                      sharpe=sb["sharpe"],
                                      max_dd=sb["max_dd"]))}

    bb = load_buyback_events()
    n_bb = sum(len(v) for v in bb.values())
    print(f"H50 events: {n_bb} across {len(bb)} tickers")
    report["h50_coverage"] = {"events": int(n_bb),
                              "tickers": len(bb)}

    div_events, div_cov = load_dividend_events()
    n_div = sum(len(v) for v in div_events.values())
    n_init = sum(1 for v in div_events.values() for e in v
                 if e[1] == "initiation")
    print(f"H51 events: {n_div} ({n_init} initiations) across "
          f"{len(div_events)} tickers; DPS facts cover "
          f"{len(div_cov)}/87 tickers")
    report["h51_coverage"] = {"events": int(n_div),
                              "initiations": int(n_init),
                              "tickers_with_events": len(div_events),
                              "tickers_with_facts": len(div_cov)}

    for name, make, extra_cov in (
            ("H50", make_choose_h50, None),
            ("H51", make_choose_h51, None)):
        events = bb if name == "H50" else div_events
        diag = {"eligible": []}
        eq, tr = r8.run_monthly(opens, closes, make(events, diag))
        is_eq, oos_eq = oos_split(eq)
        v, fails, s, t, bar = verdict(oos_eq, spy_oos, "SPY")
        si = r1.stats(is_eq)
        ct, cn, m_real, m_ctrl = random_control(tr, opens, closes,
                                                me_days, days)
        elig = diag["eligible"]
        print(f"{name}: trades {len(tr)} | eligible/month "
              f"min {min(elig)} median {int(np.median(elig))} | "
              f"control {cn} trades, real {m_real:+.2%}/trade vs "
              f"random {m_ctrl:+.2%}/trade, Welch t {ct:+.2f}")
        print(f"   IS : CAGR {si['cagr']:+6.1%} Sharpe {si['sharpe']:5.2f}")
        print(f"   OOS: CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} "
              f"t(excess) {t:+5.2f} (bar {bar:.2f}) maxDD {s['max_dd']:5.1%} "
              f"-> {v}" + (f" [{'; '.join(fails)}]" if fails else ""))
        report[name] = dict(
            verdict=v, fails=fails,
            oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                     bar=bar, max_dd=s["max_dd"], trades=len(tr)),
            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]),
            control=dict(t=ct, n=cn, mean_real=m_real,
                         mean_ctrl=m_ctrl),
            eligible_per_month=dict(min=int(min(elig)),
                                    median=float(np.median(elig)),
                                    max=int(max(elig))))

    with open("data/round14_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round14_report.json")


if __name__ == "__main__":
    main()
