# ============================================================
#  fetch_fundamentals.py — SEC EDGAR point-in-time FY panel
#  for PREREGISTRATION_2026-10-20_round8.md (H28-H31).
#
#  For each universe-L ticker: fiscal-year (10-K / 20-F / 40-F)
#  NetIncomeLoss, StockholdersEquity and shares outstanding
#  from the EDGAR XBRL company-concept API, keeping ONLY the
#  earliest filing per fiscal period (first public availability)
#  and always the `filed` date. Shares join their FY row through
#  the filing that reported them: the dei cover fact's `end` is
#  the cover date (days after fy_end), so it is matched on
#  `filed`, never on `end`. If the cover tag covers fewer than
#  half of a name's FY filings it counts as missing for that
#  name and WeightedAverageNumberOfSharesOutstandingBasic
#  (a duration fact, joined on period end) is used instead,
#  per the pre-registration's fallback. Output:
#    data/fundamentals/raw/<TICKER>_<TAG>.json   raw cache
#    data/fundamentals/panel.csv                 tidy panel
#    python fetch_fundamentals.py
# ============================================================

import json
import math
import os
import time
from datetime import date

import pandas as pd
import requests

from round2_data import L

OUT = os.path.join("data", "fundamentals")
RAW = os.path.join(OUT, "raw")
UA = {"User-Agent": "iTrade research admin@example.com"}
SLEEP = 0.22  # ~5 req/s, SEC fair-access limit is 10/s

ANNUAL_FORMS = {"10-K", "20-F", "40-F"}


def get(url):
    for attempt in range(3):
        r = requests.get(url, headers=UA, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        time.sleep(1.5 * (attempt + 1))
    r.raise_for_status()


def fetch_concept(ticker, cik, taxonomy, tag):
    """Fetch (and cache) one company-concept JSON; None on 404."""
    path = os.path.join(RAW, f"{ticker}_{tag}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
           f"CIK{cik:010d}/{taxonomy}/{tag}.json")
    time.sleep(SLEEP)
    data = get(url)
    if data is not None:
        with open(path, "w") as f:
            json.dump(data, f)
    return data


def unit_rows(data):
    """Flatten all unit arrays of a concept JSON into fact dicts."""
    if not data or "units" not in data:
        return []
    rows = []
    for unit, facts in data["units"].items():
        for f in facts:
            rows.append({**f, "_unit": unit})
    return rows


def _fy(f):
    return f.get("form") in ANNUAL_FORMS and f.get("fp") == "FY"


def _span_ok(f):
    try:
        span = (date.fromisoformat(f["end"])
                - date.fromisoformat(f["start"])).days
    except (KeyError, ValueError):
        return False
    return 300 <= span <= 400


def fy_duration_facts(data):
    """Duration facts (NetIncomeLoss, wavg shares): FY annual
    frames with a 300-400 day span. One row per period-end,
    earliest `filed` wins."""
    best = {}
    for f in unit_rows(data):
        if not _fy(f) or "start" not in f or not _span_ok(f):
            continue
        key = f["end"]
        if key not in best or f["filed"] < best[key]["filed"]:
            best[key] = f
    return best


def fy_instant_facts(data):
    """Instant facts (StockholdersEquity): FY annual frames.
    One row per period-end, earliest `filed` wins."""
    best = {}
    for f in unit_rows(data):
        if not _fy(f) or "start" in f:
            continue
        key = f["end"]
        if key not in best or f["filed"] < best[key]["filed"]:
            best[key] = f
    return best


def dei_shares_by_filed(data):
    """dei cover shares: filed date -> value (the fact's `end`
    is the cover date, so facts are keyed by their filing)."""
    by_filed = {}
    for f in unit_rows(data):
        if not _fy(f) or "start" in f:
            continue
        cur = by_filed.get(f["filed"])
        if cur is None or f["end"] > cur["end"]:
            by_filed[f["filed"]] = f
    return by_filed


def main():
    os.makedirs(RAW, exist_ok=True)
    tick = get("https://www.sec.gov/files/company_tickers.json")
    cik_of = {v["ticker"]: int(v["cik_str"]) for v in tick.values()}

    panel = []
    missing_cik, notes = [], {}
    for t in L:
        cik = cik_of.get(t)
        if cik is None:
            missing_cik.append(t)
            continue
        ni = fy_duration_facts(fetch_concept(
            t, cik, "us-gaap", "NetIncomeLoss"))
        eq = fy_instant_facts(fetch_concept(
            t, cik, "us-gaap", "StockholdersEquity"))
        ends = sorted(set(ni) | set(eq))
        rows = [{"ticker": t, "fy_end": end,
                 "filed_ni": ni.get(end, {}).get("filed"),
                 "filed_eq": eq.get(end, {}).get("filed"),
                 "filed_sh": None, "shares_src": None,
                 "net_income": ni.get(end, {}).get("val"),
                 "equity": eq.get(end, {}).get("val"),
                 "shares": None} for end in ends]

        # Primary source: dei cover shares, joined on filed date.
        dei = dei_shares_by_filed(fetch_concept(
            t, cik, "dei", "EntityCommonStockSharesOutstanding"))
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
        # Fallback (pre-registered): cover tag missing for the
        # name -> weighted-average basic shares, joined on end.
        if rows and matched < math.ceil(0.5 * len(rows)):
            wavg = fy_duration_facts(fetch_concept(
                t, cik, "us-gaap",
                "WeightedAverageNumberOfSharesOutstandingBasic"))
            for row in rows:
                f = wavg.get(row["fy_end"])
                row["shares"] = f["val"] if f else None
                row["filed_sh"] = f["filed"] if f else None
                row["shares_src"] = "us-gaap_wavg_basic" if f else None
            notes[t] = (f"dei cover matched {matched}/{len(rows)} "
                        f"filings; wavg-basic fallback used")
        panel.extend(rows)
        n_full = sum(1 for r in rows if all(
            r[k] is not None for k in ("net_income", "equity", "shares")))
        print(f"  {t:<6} CIK {cik:<8} FY periods: {len(rows)} "
              f"complete: {n_full}", flush=True)

    df = pd.DataFrame(panel)
    df.to_csv(os.path.join(OUT, "panel.csv"), index=False)

    usable = df.dropna(subset=["net_income", "equity", "shares"])
    cov = usable.groupby("ticker")["fy_end"].agg(["min", "count"])
    reach = int((cov["min"] <= "2017-12-31").sum())
    print(f"\nPanel rows: {len(df)}; complete rows: {len(usable)}")
    print(f"Tickers with >=1 complete FY row: {usable.ticker.nunique()}/87")
    print(f"Tickers whose complete data reaches back to a FY ending "
          f"<= 2017-12-31 (filed ~2016-2018): {reach}/87")
    if missing_cik:
        print(f"No CIK in SEC map: {missing_cik}")
    for t, n in sorted(notes.items()):
        print(f"NOTE {t}: {n}")
    sparse = cov[cov["count"] < 8].index.tolist()
    if sparse:
        print(f"Sparse complete history (<8 FY rows): {sparse}")


if __name__ == "__main__":
    main()
