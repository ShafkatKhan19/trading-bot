# ============================================================
#  quote_spreads.py â€” Per-symbol bid/ask spread, measured from SIP quotes
#
#  Replaces the flat per-side cost guess with what each symbol actually
#  costs to cross. Samples every quote in a WINDOW-second slice at
#  SAMPLE_TIMES on each of the last N_SESSIONS sessions (full-day quote
#  history for 23 names would be tens of GB). Raw samples are cached in
#  data/quotes/, the summary in data/spreads.json.
#
#  Half-spread = (ask - bid) / 2 / mid â€” the cost of one market fill
#  against the mid. Crossed/locked or zero-size quotes are dropped.
#  "open" bucket is before 10:00 ET, when spreads are widest.
#
#    python quote_spreads.py
# ============================================================

import json
import logging
import os
from datetime import datetime, time, timedelta

import pandas as pd

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest

import config
from intraday_data import load
from robustness_backtest import REMOVED

logger = logging.getLogger(__name__)

N_SESSIONS   = 20
WINDOW       = timedelta(seconds=5)
SAMPLE_TIMES = [time(9, 35), time(9, 45)] + [time(h, m) for h in range(10, 16)
                                             for m in (0, 30)]
SYMBOLS      = list(config.TICKERS) + list(REMOVED)
QUOTE_DIR    = os.path.join("data", "quotes")
OUT_JSON     = os.path.join("data", "spreads.json")
ET           = "America/New_York"


def bucket(t: time) -> str:
    return "open" if t < time(10, 0) else "day"


def sample_sessions() -> list:
    qqq = load(config.REGIME_TICKER, "1Day")
    return [ts.date() for ts in qqq.index[-N_SESSIONS:]]


def fetch(client, d, t) -> pd.DataFrame:
    path = os.path.join(QUOTE_DIR, f"{d}_{t.strftime('%H%M')}.pkl")
    if os.path.exists(path):
        return pd.read_pickle(path)
    start = pd.Timestamp(datetime.combine(d, t), tz=ET).tz_convert("UTC")
    req = StockQuotesRequest(symbol_or_symbols=SYMBOLS, start=start.to_pydatetime(),
                             end=(start + WINDOW).to_pydatetime(), feed=DataFeed.SIP)
    df = client.get_stock_quotes(req).df
    if df.empty:
        return df
    df = df.reset_index()[["symbol", "timestamp", "bid_price", "ask_price", "bid_size", "ask_size"]]
    df["session"], df["bucket"] = d, bucket(t)
    df.to_pickle(path)
    return df


def summarise(q: pd.DataFrame) -> dict:
    q = q[(q.bid_price > 0) & (q.ask_price > q.bid_price) & (q.bid_size > 0) & (q.ask_size > 0)].copy()
    q["half_spread"] = (q.ask_price - q.bid_price) / (q.ask_price + q.bid_price)
    # Median within each 5s window first, so one quote-heavy window can't dominate.
    w = q.groupby(["symbol", "session", "bucket", q.timestamp.dt.floor("h")])["half_spread"].median().reset_index()
    out = {}
    for sym, g in w.groupby("symbol"):
        out[sym] = {
            "half_spread_median": float(g.half_spread.median()),
            "half_spread_p90":    float(g.half_spread.quantile(0.9)),
            "open":               float(g[g.bucket == "open"].half_spread.median()),
            "day":                float(g[g.bucket == "day"].half_spread.median()),
            "windows":            int(len(g)),
        }
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    os.makedirs(QUOTE_DIR, exist_ok=True)
    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    sessions = sample_sessions()
    frames = []
    for d in sessions:
        for t in SAMPLE_TIMES:
            frames.append(fetch(client, d, t))
        logger.info(f"{d}: {sum(len(f) for f in frames):,} quotes so far")
    spreads = summarise(pd.concat(frames, ignore_index=True))
    meta = {"sessions": [str(sessions[0]), str(sessions[-1])], "window_s": WINDOW.seconds,
            "sample_times": [t.strftime("%H:%M") for t in SAMPLE_TIMES]}
    with open(OUT_JSON, "w") as f:
        json.dump({"meta": meta, "symbols": spreads}, f, indent=2)

    print(f"\n{'symbol':<6} {'median':>8} {'open':>8} {'day':>8} {'p90':>8}   (half-spread, bps)")
    for s, v in sorted(spreads.items(), key=lambda kv: kv[1]["half_spread_median"]):
        print(f"{s:<6} {v['half_spread_median'] * 1e4:8.2f} {v['open'] * 1e4:8.2f} "
              f"{v['day'] * 1e4:8.2f} {v['half_spread_p90'] * 1e4:8.2f}")


if __name__ == "__main__":
    main()
