# ============================================================
#  round4_research.py — Tests PREREGISTRATION_2026-10-17_round4.md
#
#  H12 Halloween indicator / "Sell in May" (Bouman-Jacobsen 2002)
#  H13 pre-holiday effect (Ariel 1990)
#  H14 Santa Claus rally (Hirsch, Stock Trader's Almanac)
#
#  Written AFTER the pre-registration commit. SPY only, long-only,
#  fills at the open, 5 bps/side. Verdict on OOS only.
#    python round4_research.py
# ============================================================

import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

import daily_research as r1

COST   = r1.COST          # 5 bps per side, pre-registered
CASH0  = 2000.0
IS_END = "2023-07-06"     # OOS starts here (same split as rounds 2-3)
MIN_T  = 2.96             # Bonferroni over 16 strategies

# Good Fridays 2016-2026 (hardcoded; computus-verified)
GOOD_FRIDAYS = {date(y, m, d) for y, m, d in [
    (2016, 3, 25), (2017, 4, 14), (2018, 3, 30), (2019, 4, 19),
    (2020, 4, 10), (2021, 4, 2), (2022, 4, 15), (2023, 4, 7),
    (2024, 3, 29), (2025, 4, 18), (2026, 4, 3)]}


def nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
    return d


def last_weekday(year, month, weekday):
    d = (date(year, month + 1, 1) - timedelta(days=1)) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def observed(d):
    """NYSE observed date: Sat holiday -> Fri before; Sun -> Mon after."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(year):
    h = {observed(date(year, 1, 1)),                    # New Year's Day
         nth_weekday(year, 1, 0, 3),                    # MLK Day
         nth_weekday(year, 2, 0, 3),                    # Presidents' Day
         last_weekday(year, 5, 0),                      # Memorial Day
         observed(date(year, 7, 4)),                    # Independence Day
         nth_weekday(year, 9, 0, 1),                    # Labor Day
         nth_weekday(year, 11, 3, 4),                   # Thanksgiving
         observed(date(year, 12, 25))}                  # Christmas
    h |= {g for g in GOOD_FRIDAYS if g.year == year}
    if year >= 2022:                                    # Juneteenth, NYSE from 2022
        h.add(observed(date(year, 6, 19)))
    return h


def load_spy():
    df = pd.read_csv("data/SPY_1Day.csv", parse_dates=["timestamp"])
    df["date"] = df["timestamp"].dt.tz_convert("America/New_York").dt.date
    df = df.set_index(pd.DatetimeIndex(df["date"])).sort_index()
    return df["open"], df["close"]


def simulate(opens, closes, hold):
    """hold[i] True -> be long SPY during day i (enter at open, exit at the
    open of the first non-hold day). Equity marked at each close."""
    b, eq, n_trades = r1.Book(CASH0, COST), [], 0
    holding = False
    for i in range(len(closes)):
        if hold[i] and not holding:
            b.trade("SPY", b.cash / (opens.iloc[i] * (1 + COST)), opens.iloc[i])
            holding, n_trades = True, n_trades + 1
        elif not hold[i] and holding:
            b.trade("SPY", -b.sh["SPY"], opens.iloc[i])
            holding = False
        eq.append(b.cash + b.sh.get("SPY", 0.0) * closes.iloc[i])
    return pd.Series(eq, index=closes.index), n_trades


def oos_split(eq):
    cut = eq.index.searchsorted(pd.Timestamp(IS_END))
    return eq.iloc[:cut + 1], eq.iloc[cut:]


def excess_t(strat_oos, spy_oos):
    r = strat_oos.pct_change().dropna()
    m = spy_oos.pct_change().dropna()
    x = (r - m).dropna()
    n, sd = len(x), x.std(ddof=1)
    return float(x.mean() / (sd / math.sqrt(n))) if sd > 0 and n > 1 else 0.0


def verdict(name, strat_oos, spy_oos):
    s, b = r1.stats(strat_oos), r1.stats(spy_oos)
    t = excess_t(strat_oos, spy_oos)
    fails = []
    if t < MIN_T:
        fails.append(f"excess-t {t:.2f} < {MIN_T}")
    if s["sharpe"] < b["sharpe"]:
        fails.append(f"Sharpe {s['sharpe']:.2f} < SPY {b['sharpe']:.2f}")
    if s["max_dd"] > b["max_dd"]:
        fails.append(f"maxDD {s['max_dd']:.1%} > SPY {b['max_dd']:.1%}")
    return ("PASS" if not fails else "FAIL"), fails, s, t


def main():
    opens, closes = load_spy()
    days = closes.index
    day_dates = [d.date() for d in days]
    print(f"SPY data {day_dates[0]} -> {day_dates[-1]}, {len(days)} sessions")

    # H12: long Nov-Apr, cash May-Oct
    hold_h12 = np.array([d.month in (11, 12, 1, 2, 3, 4) for d in day_dates])

    # H13: long only on the last trading day before a NYSE holiday
    holidays = set()
    for y in range(2015, 2027):
        holidays |= nyse_holidays(y)
    pre_hol = set()
    for h in holidays:
        prior = [i for i, d in enumerate(day_dates) if d < h]
        if prior:
            pre_hol.add(day_dates[prior[-1]])
    hold_h13 = np.array([d in pre_hol for d in day_dates])

    # H14: long last 5 trading days of the year + first 2 of the next
    santa = set()
    for y in range(2016, 2027):
        dec = [d for d in day_dates if d.year == y and d.month == 12]
        jan = [d for d in day_dates if d.year == y + 1 and d.month == 1]
        santa |= set(dec[-5:]) | set(jan[:2])
    hold_h14 = np.array([d in santa for d in day_dates])

    eq_spy = CASH0 * closes / closes.iloc[0]
    _, spy_oos = oos_split(eq_spy)
    sb = r1.stats(spy_oos)
    print(f"SPY buy&hold OOS: CAGR {sb['cagr']:+.1%} Sharpe {sb['sharpe']:.2f} maxDD {sb['max_dd']:.1%}")

    report = {}
    for name, hold in [("H12", hold_h12), ("H13", hold_h13), ("H14", hold_h14)]:
        eq, n_tr = simulate(opens, closes, hold)
        is_eq, oos_eq = oos_split(eq)
        v, fails, s, t = verdict(name, oos_eq, spy_oos)
        si = r1.stats(is_eq)
        print(f"{name}: trades {n_tr} | IS CAGR {si['cagr']:+6.1%} Sharpe {si['sharpe']:5.2f} | "
              f"OOS CAGR {s['cagr']:+6.1%} Sharpe {s['sharpe']:5.2f} t(excess) {t:+5.2f} "
              f"maxDD {s['max_dd']:5.1%} exposure {s['exposure']:.0%} -> {v}"
              + (f" [{'; '.join(fails)}]" if fails else ""))
        report[name] = dict(verdict=v, fails=fails, trades=n_tr,
                            oos=dict(cagr=s["cagr"], sharpe=s["sharpe"], t_excess=t,
                                     max_dd=s["max_dd"], exposure=s["exposure"]),
                            is_=dict(cagr=si["cagr"], sharpe=si["sharpe"]))
    with open("data/round4_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote data/round4_report.json")


if __name__ == "__main__":
    main()
