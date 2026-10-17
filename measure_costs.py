# ============================================================
#  measure_costs.py — Real bid/ask spreads from SIP tick quotes
#
#  The backtests assume a flat 5-10 bps per side. This samples actual NBBO
#  quotes in the daily runner's trading window (09:35-09:45 ET) on random
#  sessions of the last year and writes the per-symbol median half-spread —
#  the cost of crossing the spread with a small market order — to
#  data/costs.json. Tick history is free when older than 15 minutes.
#
#    python measure_costs.py
# ============================================================

import json
import os
import random
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest

import config
import daily_research as research

ET = ZoneInfo("America/New_York")
OUT = os.path.join("data", "costs.json")
N_DAYS, SEED = 20, 20260927
WINDOW = (time(9, 35), time(9, 45))


def main():
    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    _, closes = research.load_panel()
    sessions = [d.date() for d in closes.index if d >= closes.index[-1] - pd.Timedelta(days=365)]
    random.seed(SEED)
    days = sorted(random.sample(sessions, N_DAYS))
    symbols = sorted(set(research.UNIVERSE) | {config.INDEX_SYMBOL})
    rows = []
    for d in days:
        start = datetime.combine(d, WINDOW[0], ET).astimezone(timezone.utc)
        end = datetime.combine(d, WINDOW[1], ET).astimezone(timezone.utc)
        q = client.get_stock_quotes(StockQuotesRequest(symbol_or_symbols=symbols, start=start,
                                                       end=end, feed=DataFeed.SIP)).df.reset_index()
        q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price)]
        mid = (q.bid_price + q.ask_price) / 2
        q["half_bps"] = (q.ask_price - q.bid_price) / 2 / mid * 1e4
        for s, g in q.groupby("symbol"):
            rows.append({"date": d.isoformat(), "symbol": s, "quotes": len(g),
                         "median_half_bps": g.half_bps.median()})
        print(f"  {d}: {len(q):,} quotes")
    df = pd.DataFrame(rows)
    summary = df.groupby("symbol").agg(days=("date", "nunique"), quotes=("quotes", "sum"),
                                       half_spread_bps=("median_half_bps", "median"),
                                       worst_day_bps=("median_half_bps", "max"))
    print(summary.round(2).to_string())
    out = {"measured": datetime.now(ET).isoformat(timespec="seconds"),
           "window_et": f"{WINDOW[0]:%H:%M}-{WINDOW[1]:%H:%M}", "sessions": [str(x) for x in days],
           "half_spread_bps": summary.half_spread_bps.round(3).to_dict(),
           "worst_day_bps": summary.worst_day_bps.round(3).to_dict()}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
