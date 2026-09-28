# ============================================================
#  h7_research.py — Tests PREREGISTRATION_2026-09-28_h7_intraday_momentum.md
#
#  If SPY is up at 10:00 ET vs the previous regular close, buy at 15:30 and
#  sell at 16:00; otherwise cash. Measured with daily_research's stats and
#  70/30 split, against the same SPY buy-and-hold benchmark as round 2.
#
#    python h7_research.py
# ============================================================

import json
import math
import os
from datetime import datetime, time, timedelta, timezone

import numpy as np
import pandas as pd

import config
import daily_research as r1
from round2_data import ROOT as R2_ROOT

ROOT  = os.path.join("data", "h7")
BARS  = os.path.join(ROOT, "SPY_30Min.pkl")
CAL   = os.path.join(ROOT, "calendar.pkl")
COST  = 0.0005                     # pre-registered: 5 bps per side
DESC_COSTS = (0.0, 0.0001, 0.0002, 0.0010)
MIN_T, MIN_TRADES = 2.77, 100
ET = "America/New_York"


# ── data ──────────────────────────────────────────────────────
def download():
    os.makedirs(ROOT, exist_ok=True)
    if not os.path.exists(BARS):
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
        df = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols="SPY", timeframe=TimeFrame(30, TimeFrameUnit.Minute),
            start=datetime(2015, 12, 1, tzinfo=timezone.utc),
            end=datetime.now(timezone.utc) - timedelta(minutes=20),
            feed=DataFeed.SIP, adjustment=Adjustment.ALL)).df.xs("SPY", level="symbol")
        df.index = df.index.tz_convert(ET)
        df[["open", "high", "low", "close", "volume"]].to_pickle(BARS)
        print(f"  bars: {len(df)} ({df.index[0]} -> {df.index[-1]})")
    if not os.path.exists(CAL):
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetCalendarRequest
        tc = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=True)
        cal = tc.get_calendar(GetCalendarRequest(start=datetime(2015, 12, 1).date(),
                                                 end=datetime.now().date()))
        pd.DataFrame([{"date": pd.Timestamp(c.date), "open": c.open.time(), "close": c.close.time()}
                      for c in cal]).to_pickle(CAL)


# ── strategy ──────────────────────────────────────────────────
def sessions() -> pd.DataFrame:
    """One row per session: prev regular close, 10:00 price, 15:30 open/close."""
    bars = pd.read_pickle(BARS)
    cal = pd.read_pickle(CAL).set_index("date")
    by_start = {(ts.date(), ts.time()): row for ts, row in bars.iterrows()}
    rows, prev_close = [], None
    for d, c in cal.iterrows():
        last_start = (datetime.combine(d, c["close"]) - timedelta(minutes=30)).time()
        first = by_start.get((d.date(), time(9, 30)))
        last = by_start.get((d.date(), last_start))
        full_day = c["close"] == time(16, 0)
        rows.append({"date": d, "full_day": full_day, "prev_close": prev_close,
                     "p1000": first["close"] if first is not None else np.nan,
                     "entry": last["open"] if (last is not None and full_day) else np.nan,
                     "exit": last["close"] if (last is not None and full_day) else np.nan})
        prev_close = last["close"] if last is not None else np.nan
    s = pd.DataFrame(rows).set_index("date")
    s["r1"] = s["p1000"] / s["prev_close"] - 1
    return s


def daily_returns(s: pd.DataFrame, cost: float, side: str = "long") -> pd.Series:
    """Net return of the book each session; 0 when in cash."""
    ok = s["full_day"] & s[["r1", "entry", "exit"]].notna().all(axis=1)
    long_r = s["exit"] * (1 - cost) / (s["entry"] * (1 + cost)) - 1
    short_r = (s["entry"] * (1 - cost) - s["exit"] * (1 + cost)) / s["entry"]
    r = pd.Series(0.0, index=s.index)
    r[ok & (s["r1"] > 0)] = long_r
    if side == "both":
        r[ok & (s["r1"] < 0)] = short_r
    return r


def equity(r: pd.Series, days: pd.DatetimeIndex) -> pd.Series:
    r = r.reindex(days).fillna(0.0)
    return 500.0 * (1 + r).cumprod()


def main():
    download()
    s = sessions()
    spy = pd.read_pickle(os.path.join(R2_ROOT, "bars", "SPY.pkl"))
    bench = r1.run_monthly(spy[["open"]].rename(columns={"open": "SPY"}),
                           spy[["close"]].rename(columns={"close": "SPY"}),
                           lambda i: {"SPY": 1.0}, r1.COST)
    days = bench.index
    bo = r1.stats(r1.split(bench)[1])
    oos_from = r1.split(bench)[1].index[0]

    missing = s.loc[(s.index >= days[0]) & (s.index <= days[-1]) & s.full_day, ["p1000", "entry", "exit"]].isna().any(axis=1)
    print(f"Sessions {len(days)} | full days missing a needed bar: {int(missing.sum())}")
    print(f"OOS from {oos_from.date()} | SPY OOS Sharpe {bo['sharpe']:.2f} | bar t >= {MIN_T}\n")

    r = daily_returns(s, COST)
    eq = equity(r, days)
    s_is, s_oos = r1.stats(r1.split(eq)[0]), r1.stats(r1.split(eq)[1])
    traded = r.reindex(days).fillna(0.0) != 0
    oos_trades = int(traded[days >= oos_from].sum()) - (1 if traded.loc[oos_from] else 0)
    fails = [m for m, bad in (
        (f"t {s_oos['t']:.2f} < {MIN_T}", s_oos["t"] < MIN_T),
        (f"Sharpe {s_oos['sharpe']:.2f} < SPY {bo['sharpe']:.2f}", s_oos["sharpe"] < bo["sharpe"]),
        (f"max DD {s_oos['max_dd']:.1%} > 20%", s_oos["max_dd"] > r1.MAX_DD),
        (f"only {oos_trades} OOS trades", oos_trades < MIN_TRADES)) if bad]
    v = "PASS" if not fails else "FAIL"
    print("H7 intraday momentum (long-only, 5 bps/side)")
    print(r1.fmt("in-sample", s_is)); print(r1.fmt("OUT-OF-SAMPLE", s_oos))
    print(f"  trades total {int(traded.sum())}, OOS {oos_trades}")
    print(f"  VERDICT: {v}" + "".join(f"\n    - {w}" for w in fails) + "\n")

    print("=== Descriptive only ===")
    trade_r = r[r != 0].reindex(days).dropna()
    trade_r = trade_r[trade_r != 0]
    oos_tr = trade_r[trade_r.index > oos_from]
    print(f"Per trade (5 bps): win rate all {(trade_r > 0).mean():.1%}, OOS {(oos_tr > 0).mean():.1%} | "
          f"mean all {trade_r.mean():+.3%}, OOS {oos_tr.mean():+.3%}")
    desc = {}
    for c in DESC_COSTS:
        o = r1.stats(r1.split(equity(daily_returns(s, c), days))[1])
        desc[f"{c * 1e4:g}bps"] = o
        print(f"  cost {c * 1e4:>4g} bps/side  OOS CAGR {o['cagr']:+.1%}  Sharpe {o['sharpe']:.2f}  t {o['t']:+.2f}")
    both = r1.stats(r1.split(equity(daily_returns(s, COST, "both"), days))[1])
    print(f"  long/short (paper's version, not tradeable here) OOS CAGR {both['cagr']:+.1%}  "
          f"Sharpe {both['sharpe']:.2f}  t {both['t']:+.2f}")
    py = {int(y): round(float(g.iloc[-1] / g.iloc[0] - 1), 4) for y, g in eq.groupby(eq.index.year)}
    pb = {int(y): round(float(g.iloc[-1] / g.iloc[0] - 1), 4) for y, g in bench.groupby(bench.index.year)}
    print("  per year  H7: " + " ".join(f"{y}:{v:+.1%}" for y, v in py.items()))
    print("  per year SPY: " + " ".join(f"{y}:{v:+.1%}" for y, v in pb.items()))

    with open(os.path.join(ROOT, "report.json"), "w") as f:
        json.dump({"verdict": v, "fails": fails, "in_sample": s_is, "oos": s_oos, "oos_trades": oos_trades,
                   "spy_oos": bo, "by_cost_oos": desc, "long_short_oos": both,
                   "per_year": py, "missing_bar_days": int(missing.sum())}, f, indent=2, default=float)
    print(f"\n-> {ROOT}/report.json")


if __name__ == "__main__":
    main()
