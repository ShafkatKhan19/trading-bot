# ============================================================
#  round2_data.py — Data for PREREGISTRATION_2026-09-27_round2.md
#
#  data/round2/bars/<SYM>.pkl   daily bars, split+dividend adjusted (SIP)
#  data/round2/earnings.pkl     yfinance earnings dates + surprise, all of L
#  data/round2/news.pkl         Alpaca/Benzinga headline archive for L
#
#  All cached; re-running only fetches what is missing.
#    python round2_data.py
# ============================================================

import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

import config

ROOT = os.path.join("data", "round2")
START = datetime(2015, 1, 1, tzinfo=timezone.utc)

L = ("AAPL MSFT AMZN GOOGL JNJ JPM XOM PG V MA HD CVX PFE KO PEP MRK ABBV BAC WMT DIS "
     "CSCO INTC VZ T ORCL CMCSA NFLX ADBE CRM NKE MCD MDT UNH ABT TMO AMGN HON UNP UPS "
     "LOW SBUX IBM QCOM TXN AVGO NVDA COST WFC C GS MS BLK AXP CAT DE MMM GE BA LMT GD "
     "NOC LLY BMY GILD CVS MO PM MDLZ CL KMB TGT AMT SPG NEE DUK SO D EXC COP SLB EOG "
     "OXY F GM ADP INTU ISRG").split()
assert len(L) == 87, len(L)


def bars():
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    os.makedirs(os.path.join(ROOT, "bars"), exist_ok=True)
    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    todo = [s for s in L + ["SPY"] if not os.path.exists(os.path.join(ROOT, "bars", f"{s}.pkl"))]
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        df = client.get_stock_bars(StockBarsRequest(symbol_or_symbols=chunk, timeframe=TimeFrame.Day,
                                                    start=START, end=end, feed=DataFeed.SIP,
                                                    adjustment=Adjustment.ALL)).df
        for s in chunk:
            d = df.xs(s, level="symbol")
            d.index = pd.DatetimeIndex([t.tz_convert("America/New_York").date() for t in d.index])
            d[["open", "high", "low", "close", "volume"]].to_pickle(os.path.join(ROOT, "bars", f"{s}.pkl"))
        print(f"  bars: {min(i + 20, len(todo))}/{len(todo)}", flush=True)


def earnings():
    path = os.path.join(ROOT, "earnings.pkl")
    if os.path.exists(path):
        return
    import yfinance as yf
    frames = []
    for s in L:
        for attempt in range(3):
            try:
                e = yf.Ticker(s).get_earnings_dates(limit=60).reset_index()
                e.columns = ["ts", "eps_est", "eps", "surprise_pct"]
                e["symbol"] = s
                frames.append(e)
                break
            except Exception as ex:
                print(f"  earnings {s} attempt {attempt + 1} failed: {ex}")
                time.sleep(3)
        time.sleep(0.5)
    df = pd.concat(frames, ignore_index=True)
    df.to_pickle(path)
    print(f"  earnings: {len(df)} rows, {df.symbol.nunique()} symbols")


def news():
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    path = os.path.join(ROOT, "news.pkl")
    part = os.path.join(ROOT, "news_parts")
    os.makedirs(part, exist_ok=True)
    nc = NewsClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    for n, s in enumerate(L):
        out = os.path.join(part, f"{s}.pkl")
        if os.path.exists(out):
            continue
        rows, tok = [], None
        while True:
            for attempt in range(5):
                try:
                    r = nc.get_news(NewsRequest(symbols=s, start=START, end=end, limit=None,
                                                page_token=tok, include_content=False))
                    break
                except Exception as ex:
                    time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"news {s}: repeated failures")
            for it in r.data.get("news", []):
                rows.append({"id": it.id, "created_at": it.created_at, "headline": it.headline,
                             "symbols": ",".join(it.symbols), "source": it.source})
            tok = r.next_page_token
            if not tok:
                break
            time.sleep(0.31)                      # stay under 200 requests/minute
        pd.DataFrame(rows).to_pickle(out)
        print(f"  news {n + 1}/{len(L)} {s}: {len(rows)} items", flush=True)
    df = pd.concat([pd.read_pickle(os.path.join(part, f"{s}.pkl")) for s in L], ignore_index=True)
    df.drop_duplicates("id").to_pickle(path)
    print(f"  news: {len(df)} items total")


if __name__ == "__main__":
    bars(); earnings(); news()
