# ============================================================
#  fetch_fundamentals_sc.py — SEC EDGAR point-in-time FY panel
#  for the S&P SmallCap 600, for PREREGISTRATION_2026-10-20_
#  round9.md (H32/H33). Build rules IDENTICAL to round 8's
#  fetch_fundamentals.py: FY 10-K/20-F/40-F frames only,
#  duration spans 300-400 days, earliest `filed` per fiscal
#  period, dei cover shares joined on `filed` (wavg-basic
#  fallback if the cover tag covers < half a name's filings).
#  Universe: data/smallcap/tickers.csv (symbol = SEC ticker,
#  ticker = Yahoo-format used by the price cache). Output:
#    data/fundamentals/raw_sc/<TICKER>_<TAG>.json  raw cache
#    data/fundamentals/panel_smallcap.csv          tidy panel
#    python fetch_fundamentals_sc.py
# ============================================================

import math
import os
import time

import pandas as pd
import requests

import fetch_fundamentals as ff

OUT = os.path.join("data", "fundamentals")
RAW_SC = os.path.join(OUT, "raw_sc")
ff.RAW = RAW_SC  # point the shared fetcher's cache at raw_sc/


def robust_get(url):
    """ff.get with retries on connection errors (a transient
    proxy drop killed the first run after 371 tickers; the raw
    cache makes restarts cheap). 404 still returns None."""
    for attempt in range(6):
        try:
            r = requests.get(url, headers=ff.UA, timeout=30)
        except requests.RequestException:
            time.sleep(3.0 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"GET failed after retries: {url}")


ff.get = robust_get  # fetch_concept resolves `get` in ff's namespace


def build_ticker(sec_ticker, yahoo_ticker, cik):
    """One name's FY rows, exactly the round-8 construction."""
    ni = ff.fy_duration_facts(ff.fetch_concept(
        yahoo_ticker, cik, "us-gaap", "NetIncomeLoss"))
    eq = ff.fy_instant_facts(ff.fetch_concept(
        yahoo_ticker, cik, "us-gaap", "StockholdersEquity"))
    ends = sorted(set(ni) | set(eq))
    rows = [{"ticker": yahoo_ticker, "fy_end": end,
             "filed_ni": ni.get(end, {}).get("filed"),
             "filed_eq": eq.get(end, {}).get("filed"),
             "filed_sh": None, "shares_src": None,
             "net_income": ni.get(end, {}).get("val"),
             "equity": eq.get(end, {}).get("val"),
             "shares": None} for end in ends]
    note = None
    dei = ff.dei_shares_by_filed(ff.fetch_concept(
        yahoo_ticker, cik, "dei", "EntityCommonStockSharesOutstanding"))
    matched = 0
    for row in rows:
        for fkey in ("filed_ni", "filed_eq"):
            f = dei.get(row[fkey] or "")
            if f is not None:
                row["shares"] = f["val"]
                row["filed_sh"] = f["filed"]
                row["shares_src"] = "dei_cover"
                matched += 1
                break
    if rows and matched < math.ceil(0.5 * len(rows)):
        wavg = ff.fy_duration_facts(ff.fetch_concept(
            yahoo_ticker, cik, "us-gaap",
            "WeightedAverageNumberOfSharesOutstandingBasic"))
        for row in rows:
            f = wavg.get(row["fy_end"])
            row["shares"] = f["val"] if f else None
            row["filed_sh"] = f["filed"] if f else None
            row["shares_src"] = "us-gaap_wavg_basic" if f else None
        note = (f"dei cover matched {matched}/{len(rows)} "
                f"filings; wavg-basic fallback used")
    return rows, note


def main():
    os.makedirs(RAW_SC, exist_ok=True)
    tick = ff.get("https://www.sec.gov/files/company_tickers.json")
    cik_of = {v["ticker"]: int(v["cik_str"]) for v in tick.values()}

    uni = pd.read_csv(os.path.join("data", "smallcap", "tickers.csv"))
    panel, missing_cik, notes = [], [], {}
    for _, u in uni.iterrows():
        sec_t, yah_t = u["symbol"], u["ticker"]
        cik = cik_of.get(sec_t)
        if cik is None and "-" in sec_t:
            cik = cik_of.get(sec_t.replace("-", "."))
        if cik is None:
            missing_cik.append(sec_t)
            continue
        try:
            rows, note = build_ticker(sec_t, yah_t, cik)
        except Exception as e:  # one bad name must not kill the build
            print(f"  {sec_t:<8} FETCH FAILED ({type(e).__name__}: "
                  f"{str(e)[:120]}); skipped, no panel rows", flush=True)
            notes[sec_t] = f"fetch failed: {type(e).__name__}"
            continue
        if note:
            notes[sec_t] = note
        panel.extend(rows)
        n_full = sum(1 for r in rows if all(
            r[k] is not None for k in ("net_income", "equity", "shares")))
        print(f"  {sec_t:<8} CIK {cik:<8} FY periods: {len(rows)} "
              f"complete: {n_full}", flush=True)

    df = pd.DataFrame(panel)
    df.to_csv(os.path.join(OUT, "panel_smallcap.csv"), index=False)

    usable = df.dropna(subset=["net_income", "equity", "shares"])
    cov = usable.groupby("ticker")["fy_end"].agg(["min", "count"])
    reach = int((cov["min"] <= "2017-12-31").sum())
    print(f"\nPanel rows: {len(df)}; complete rows: {len(usable)}")
    print(f"Universe tickers: {len(uni)}")
    print(f"Tickers with >=1 complete FY row: "
          f"{usable.ticker.nunique()}/{len(uni)}")
    print(f"Tickers whose complete data reaches back to a FY ending "
          f"<= 2017-12-31: {reach}/{len(uni)}")
    if missing_cik:
        print(f"No CIK in SEC map ({len(missing_cik)}): {missing_cik}")
    for t, n in sorted(notes.items()):
        print(f"NOTE {t}: {n}")
    sparse = cov[cov["count"] < 8].index.tolist()
    if sparse:
        print(f"Sparse complete history (<8 FY rows): {len(sparse)} "
              f"names: {sparse[:40]}")


if __name__ == "__main__":
    main()
