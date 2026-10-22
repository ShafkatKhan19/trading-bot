# ============================================================
#  fetch_shortinterest.py — FINRA consolidated short interest
#  for PREREGISTRATION_2026-10-21_round13.md (H47/H48).
#
#  Source: FINRA Query API (public, no key), dataset
#  otcMarket/consolidatedShortInterest — the same biweekly
#  settlement snapshots FINRA publishes under Rule 4560
#  (mid-month and month-end settlement dates). One request
#  series per symbol; raw JSON cached per symbol under
#  data/shortinterest/raw/ so re-runs only fetch what is
#  missing. Derived panel: data/shortinterest/si_panel.csv
#  with one row per (symbol, settlement_date).
#
#  Coverage note: the API's consolidated history begins with
#  the 2017-12-29 settlement (verified 2026-10-22) — that is
#  the start of the obtainable point-in-time series; the
#  research script discloses the resulting window.
#    python fetch_shortinterest.py
# ============================================================

import json
import os
import time

import pandas as pd
import requests

from round2_data import L

URL = ("https://api.finra.org/data/group/otcMarket/name/"
       "consolidatedShortInterest")
FIELDS = ["settlementDate", "symbolCode", "issueName",
          "marketClassCode", "currentShortPositionQuantity",
          "previousShortPositionQuantity",
          "averageDailyVolumeQuantity", "daysToCoverQuantity",
          "changePreviousNumber", "changePercent",
          "revisionFlag", "stockSplitFlag"]
RAW = os.path.join("data", "shortinterest", "raw")
PANEL = os.path.join("data", "shortinterest", "si_panel.csv")
PAGE = 1000


def fetch_symbol(sym):
    path = os.path.join(RAW, f"{sym}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows, offset = [], 0
    while True:
        body = {"fields": FIELDS,
                "domainFilters": [{"fieldName": "symbolCode",
                                   "values": [sym]}],
                "offset": offset, "limit": PAGE}
        for attempt in range(4):
            try:
                r = requests.post(URL, json=body,
                                  headers={"Accept": "application/json"},
                                  timeout=90)
                r.raise_for_status()
                page = r.json()
                total = int(r.headers.get("record-total", len(page)))
                break
            except Exception as e:
                if attempt == 3:
                    raise
                print(f"  {sym} offset {offset}: retry {attempt + 1} "
                      f"({e})", flush=True)
                time.sleep(5 * (attempt + 1))
        rows.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
    os.makedirs(RAW, exist_ok=True)
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def main():
    os.makedirs(RAW, exist_ok=True)
    frames = []
    for i, sym in enumerate(L, 1):
        rows = fetch_symbol(sym)
        df = pd.DataFrame(rows)
        df["settlement_date"] = pd.to_datetime(df["settlementDate"])
        frames.append(df)
        print(f"[{i}/{len(L)}] {sym}: {len(df)} snapshots "
              f"{df['settlement_date'].min().date()} -> "
              f"{df['settlement_date'].max().date()}", flush=True)
        time.sleep(0.2)
    all_df = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "symbol": all_df["symbolCode"],
        "settlement_date": all_df["settlement_date"].dt.date,
        "short_shares": all_df["currentShortPositionQuantity"],
        "prev_short_shares": all_df["previousShortPositionQuantity"],
        "avg_daily_volume": all_df["averageDailyVolumeQuantity"],
        "days_to_cover": all_df["daysToCoverQuantity"],
        "revision_flag": all_df["revisionFlag"],
        "stock_split_flag": all_df["stockSplitFlag"],
    }).sort_values(["symbol", "settlement_date"])
    out.to_csv(PANEL, index=False)
    print(f"Wrote {PANEL}: {len(out)} rows, "
          f"{out['symbol'].nunique()} symbols, settlements "
          f"{out['settlement_date'].min()} -> {out['settlement_date'].max()}")


if __name__ == "__main__":
    main()
