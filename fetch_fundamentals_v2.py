# ============================================================
#  fetch_fundamentals_v2.py — extend the round-8 universe-L
#  panel with two more FY facts for PREREGISTRATION_
#  2026-10-20_round9.md (H35): Assets (instant) and
#  NetCashProvidedByUsedInOperatingActivities (duration),
#  same point-in-time build as fetch_fundamentals.py (FY
#  annual frames, 300-400 day spans for duration facts,
#  earliest `filed` per fiscal period). Merged onto the
#  round-8 panel rows on (ticker, fy_end); panel.csv is NOT
#  overwritten. Output:
#    data/fundamentals/panel_l_v2.csv
#    python fetch_fundamentals_v2.py
# ============================================================

import os

import pandas as pd

import fetch_fundamentals as ff
from round2_data import L

OUT = os.path.join("data", "fundamentals")


def main():
    tick = ff.get("https://www.sec.gov/files/company_tickers.json")
    cik_of = {v["ticker"]: int(v["cik_str"]) for v in tick.values()}

    extra = {}
    for t in L:
        cik = cik_of.get(t)
        if cik is None:
            print(f"  {t:<6} no CIK, skipped")
            continue
        assets = ff.fy_instant_facts(ff.fetch_concept(
            t, cik, "us-gaap", "Assets"))
        ocf = ff.fy_duration_facts(ff.fetch_concept(
            t, cik, "us-gaap",
            "NetCashProvidedByUsedInOperatingActivities"))
        for end in sorted(set(assets) | set(ocf)):
            extra[(t, end)] = {
                "filed_assets": assets.get(end, {}).get("filed"),
                "assets": assets.get(end, {}).get("val"),
                "filed_ocf": ocf.get(end, {}).get("filed"),
                "ocf": ocf.get(end, {}).get("val")}
        print(f"  {t:<6} Assets FY periods: {len(assets)}  "
              f"OCF FY periods: {len(ocf)}", flush=True)

    df = pd.read_csv(os.path.join(OUT, "panel.csv"))
    for col in ("filed_assets", "assets", "filed_ocf", "ocf"):
        df[col] = None
    hit = 0
    for i, r in df.iterrows():
        e = extra.get((r["ticker"], r["fy_end"]))
        if e is None:
            continue
        hit += 1
        for col, v in e.items():
            df.at[i, col] = v
    df.to_csv(os.path.join(OUT, "panel_l_v2.csv"), index=False)

    full = df.dropna(subset=["net_income", "equity", "shares",
                             "assets", "ocf"])
    print(f"\nPanel rows: {len(df)}; rows with Assets or OCF facts: {hit}")
    print(f"Rows complete incl. Assets+OCF: {len(full)}")
    print(f"Tickers with >=1 such row: {full.ticker.nunique()}/87")
    reach = full.groupby("ticker")["fy_end"].min()
    print(f"Tickers reaching back to FY ending <= 2017-12-31: "
          f"{int((reach <= '2017-12-31').sum())}/87")


if __name__ == "__main__":
    main()
