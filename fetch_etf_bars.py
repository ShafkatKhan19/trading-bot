# ============================================================
#  fetch_etf_bars.py — Round 7 data step.
#  Daily bars 2015-06-01 -> today from the Yahoo Finance v8 chart
#  API for the H25 rotation universe (SPY, QQQ, IWM, TLT, GLD).
#  One CSV per ticker under data/etf/bars/ (Date, Open, High, Low,
#  Close, AdjClose), cached (existing files are skipped). Same
#  pattern as fetch_smallcap_bars.py.
# ============================================================

import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests

START = int(datetime(2015, 6, 1, tzinfo=timezone.utc).timestamp())
END = int(datetime.now(timezone.utc).timestamp()) + 86400
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"}
DIR = os.path.join("data", "etf", "bars")
TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
DELAY = 0.2


def fetch_one(ticker):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={START}&period2={END}&interval=1d&events=history")
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"]
    if not res:
        raise ValueError("empty result")
    res = res[0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    tz = res["meta"].get("exchangeTimezoneName", "America/New_York")
    dates = (pd.to_datetime(res["timestamp"], unit="s", utc=True)
             .tz_convert(tz).normalize().tz_localize(None))
    df = pd.DataFrame({"Date": dates, "Open": q["open"], "High": q["high"],
                       "Low": q["low"], "Close": q["close"], "AdjClose": adj})
    df = df.dropna(subset=["AdjClose"]).drop_duplicates("Date").sort_values("Date")
    if df.empty:
        raise ValueError("no usable rows")
    return df


def main():
    os.makedirs(DIR, exist_ok=True)
    for t in TICKERS:
        path = os.path.join(DIR, f"{t}.csv")
        if os.path.exists(path):
            print(f"  {t}: cached, skipped")
            continue
        err = None
        for attempt in range(2):                      # retry once
            try:
                df = fetch_one(t)
                df.to_csv(path, index=False)
                print(f"  {t}: {len(df)} rows "
                      f"{df['Date'].iloc[0].date()} -> {df['Date'].iloc[-1].date()}")
                err = None
                break
            except Exception as e:                    # noqa: BLE001 - log and continue
                err = f"{type(e).__name__}: {e}"
                time.sleep(1.0)
        if err is not None:
            print(f"  {t}: FAILED {err}")
        time.sleep(DELAY)


if __name__ == "__main__":
    main()
