# ============================================================
#  fetch_smallcap_bars.py — Round 5 data step 2.
#  Daily bars 2015-06-01 -> today from the Yahoo Finance v8 chart
#  API for every ticker in data/smallcap/tickers.csv plus IWM
#  (the round-5 benchmark). One CSV per ticker under
#  data/smallcap/bars/ (Date, Open, High, Low, Close, AdjClose),
#  cached (existing files are skipped). Writes
#  data/smallcap/manifest.json with success/failure counts.
# ============================================================

import json
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
DIR = os.path.join("data", "smallcap", "bars")
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
    tickers = pd.read_csv(os.path.join("data", "smallcap", "tickers.csv"))["ticker"].tolist()
    todo = tickers + ["IWM"]
    ok, failed, rows = [], [], {}
    for i, t in enumerate(todo):
        path = os.path.join(DIR, f"{t}.csv")
        if os.path.exists(path):
            ok.append(t)
            rows[t] = sum(1 for _ in open(path)) - 1
            continue
        err = None
        for attempt in range(2):                      # retry once
            try:
                df = fetch_one(t)
                df.to_csv(path, index=False)
                ok.append(t)
                rows[t] = len(df)
                err = None
                break
            except Exception as e:                    # noqa: BLE001 - log and continue
                err = f"{type(e).__name__}: {e}"
                time.sleep(1.0)
        if err is not None:
            failed.append({"ticker": t, "error": err})
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(todo)} done, {len(failed)} failed", flush=True)
        time.sleep(DELAY)
    manifest = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "Yahoo Finance v8 chart API, adjclose basis",
        "universe": "S&P SmallCap 600 constituents (Wikipedia, fetched same day)",
        "window_requested": "2015-06-01 -> today",
        "n_listed": len(tickers),
        "n_ok": len([t for t in ok if t != "IWM"]),
        "n_failed": len([f for f in failed if f["ticker"] != "IWM"]),
        "benchmark_IWM": "ok" if "IWM" in ok else "FAILED",
        "failed": failed,
        "rows_per_ticker": rows,
    }
    with open(os.path.join("data", "smallcap", "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"done: {manifest['n_ok']} ok, {manifest['n_failed']} failed, "
          f"IWM {manifest['benchmark_IWM']} -> data/smallcap/manifest.json")


if __name__ == "__main__":
    main()
