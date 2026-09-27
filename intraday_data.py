# ============================================================
#  intraday_data.py — Historical bar cache for intraday_backtest.py
#
#  Downloads SIP (consolidated, all-exchange) bars from Alpaca and caches
#  them under data/intraday/ as pickles. SIP history is free on the Basic
#  data plan; only the most recent 15 minutes are blocked. Includes
#  pre/post-market bars (04:00-20:00 ET), which the CRT 08:00 box needs.
#
#    python intraday_data.py                 # default range, all symbols
#    python intraday_data.py 2024-01-01      # custom start
# ============================================================

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import config

logger = logging.getLogger(__name__)

CACHE_DIR     = os.path.join("data", "intraday")
DEFAULT_START = "2024-01-01"
CONTEXT_SYMBOLS = [config.REGIME_TICKER, config.VIX_TICKER]


def _client():
    return StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)


def _path(symbol: str, tf: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol}_{tf}.pkl")


def _fetch(client, symbol: str, tf, start: datetime, end: datetime) -> pd.DataFrame:
    # Split-adjusted so a split inside the window is not a fake 50% gap.
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end,
                           feed=DataFeed.SIP, adjustment=Adjustment.SPLIT)
    df = client.get_stock_bars(req).df
    if isinstance(df.index, pd.MultiIndex):
        df = df.xs(symbol, level="symbol")
    return df[["open", "high", "low", "close", "volume"]]


def download(start: str = DEFAULT_START, symbols=None) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    client = _client()
    t0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    # SIP within the last 15 minutes is refused on the free plan.
    t1 = datetime.now(timezone.utc) - timedelta(minutes=20)
    symbols = symbols or (list(config.TICKERS) + CONTEXT_SYMBOLS)

    for sym in symbols:
        # Daily bars start a year earlier so 50-day MAs exist on day one.
        jobs = [("1Day", TimeFrame.Day, t0 - timedelta(days=400))]
        if sym not in CONTEXT_SYMBOLS:
            jobs.append(("5Min", TimeFrame(5, TimeFrameUnit.Minute), t0 - timedelta(days=10)))
        for name, tf, s in jobs:
            path = _path(sym, name)
            if os.path.exists(path):
                logger.info(f"{sym} {name}: cached")
                continue
            df = _fetch(client, sym, tf, s, t1)
            df.to_pickle(path)
            logger.info(f"{sym} {name}: {len(df):,} bars {df.index[0]} -> {df.index[-1]}")


def load(symbol: str, tf: str) -> pd.DataFrame:
    """Cached bars with an ET index."""
    df = pd.read_pickle(_path(symbol, tf))
    df.index = df.index.tz_convert("America/New_York")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    download(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_START)
