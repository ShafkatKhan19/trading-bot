# ============================================================
#  fetch_fundamentals_gp.py — gross-profitability panel for
#  PREREGISTRATION_2026-10-20_round10.md (H36): FY revenue
#  and COGS from EDGAR with the pre-registered tag fallback
#  chains (revenue: SalesRevenueNet ->
#  RevenueFromContractWithCustomerExcludingAssessedTax ->
#  Revenues; COGS: CostOfGoodsAndServicesSold ->
#  CostOfRevenue). The chain is applied PER FISCAL PERIOD:
#  for each period-end, the highest-priority chain tag that
#  reports that period wins. (Build interpretation, noted in
#  the round-10 results: filers switched tags mid-history at
#  ASC 606 adoption — e.g. AAPL/MSFT SalesRevenueNet ends in
#  2017 while their COGS runs to 2025 — so a single per-
#  ticker tag would leave most periods unusable. Chain
#  order, tag set and FY rules are exactly as registered.)
#  Same point-in-time build as round 8
#  (FY 10-K frames, 300-400 day spans, earliest `filed` per
#  period). A row's `filed` is the date BOTH facts were
#  public (max of the two filed dates). Output:
#    data/fundamentals/panel_gp.csv
#    python fetch_fundamentals_gp.py
# ============================================================

import os
import json
import time

import pandas as pd
import requests

import fetch_fundamentals as ff
from round2_data import L

OUT = os.path.join("data", "fundamentals")
REV_CHAIN = ["SalesRevenueNet",
             "RevenueFromContractWithCustomerExcludingAssessedTax",
             "Revenues"]
COGS_CHAIN = ["CostOfGoodsAndServicesSold", "CostOfRevenue"]


def robust_get(url):
    """ff.get with connection-error retries (round-9 lesson)."""
    for attempt in range(4):
        try:
            r = requests.get(url, headers=ff.UA, timeout=30)
        except requests.exceptions.RequestException:
            time.sleep(2.0 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        time.sleep(1.5 * (attempt + 1))
    return None


ff.get = robust_get  # fetch_concept picks this up at call time

# Successor-entity CIK splits (data-build correction, verified
# against the submissions API 2026-10-20): the SEC ticker map
# points XOM at a 2026 successor shell and BLK at the post-2024
# parent, while FY history lives under the operating
# predecessors. For these tickers the concept facts of BOTH
# issuer CIKs are merged before the FY filters (earliest
# `filed` per period then applies across the union).
CIK_SETS = {"XOM": [34088, 2115436], "BLK": [1364742, 2012383]}


def merged_concept(t, ciks, taxonomy, tag):
    """Concept JSON with units merged across issuer CIKs;
    cached per CIK as <TICKER>_<TAG>_cik<CIK>.json."""
    merged = None
    for cik in ciks:
        path = os.path.join(ff.RAW, f"{t}_{tag}_cik{cik}.json")
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
        else:
            url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
                   f"CIK{cik:010d}/{taxonomy}/{tag}.json")
            time.sleep(ff.SLEEP)
            data = robust_get(url)
            if data is not None:
                with open(path, "w") as f:
                    json.dump(data, f)
        if not data or "units" not in data:
            continue
        if merged is None:
            merged = {"units": {}}
        for unit, facts in data["units"].items():
            merged["units"].setdefault(unit, []).extend(facts)
    return merged


def fetch_for(t, cik, tag):
    if t in CIK_SETS:
        return merged_concept(t, CIK_SETS[t], "us-gaap", tag)
    return ff.fetch_concept(t, cik, "us-gaap", tag)


def chain_facts(t, cik, chain):
    """Per-period fallback: for each period-end, the first
    chain tag reporting that period wins. Returns
    (facts_by_end, tag_used_by_end)."""
    per_tag = []
    for tag in chain:
        per_tag.append((tag, ff.fy_duration_facts(fetch_for(
            t, cik, tag))))
    facts, used = {}, {}
    for tag, d in per_tag:
        for end, f in d.items():
            if end not in facts:
                facts[end] = f
                used[end] = tag
    return facts, used


def main():
    tick = ff.get("https://www.sec.gov/files/company_tickers.json")
    cik_of = {v["ticker"]: int(v["cik_str"]) for v in tick.values()}

    panel, used_rev, used_cogs = [], {}, {}
    for t in L:
        cik = cik_of.get(t)
        if cik is None:
            print(f"  {t:<6} no CIK, skipped")
            continue
        rev, rused = chain_facts(t, cik, REV_CHAIN)
        cogs, cused = chain_facts(t, cik, COGS_CHAIN)
        used_rev.update({(t, e): tag for e, tag in rused.items()})
        used_cogs.update({(t, e): tag for e, tag in cused.items()})
        for end in sorted(set(rev) | set(cogs)):
            fr = rev.get(end, {}).get("filed")
            fc = cogs.get(end, {}).get("filed")
            panel.append({
                "ticker": t, "fy_end": end,
                "filed": max(x for x in (fr, fc) if x) if (fr or fc)
                         else None,
                "revenue": rev.get(end, {}).get("val"),
                "cogs": cogs.get(end, {}).get("val")})
        n_full = sum(1 for r in panel if r["ticker"] == t
                     and r["revenue"] is not None
                     and r["cogs"] is not None)
        print(f"  {t:<6} rev periods: {len(rev)}  "
              f"cogs periods: {len(cogs)}  complete: {n_full}",
              flush=True)

    df = pd.DataFrame(panel)
    df.to_csv(os.path.join(OUT, "panel_gp.csv"), index=False)
    full = df.dropna(subset=["revenue", "cogs"])
    print(f"\nPanel rows: {len(df)}; complete (rev+cogs): {len(full)}")
    print(f"Tickers with >=1 complete FY row: {full.ticker.nunique()}/87")
    reach = full.groupby("ticker")["fy_end"].min()
    print(f"Tickers reaching back to FY ending <= 2017-12-31: "
          f"{int((reach <= '2017-12-31').sum())}/87")
    from collections import Counter
    print(f"Revenue tag used (per period): {Counter(used_rev.values())}")
    print(f"COGS tag used (per period): {Counter(used_cogs.values())}")
    have_rev = {t for t, _ in used_rev}
    have_cogs = {t for t, _ in used_cogs}
    if len(have_rev) < len(L):
        print(f"No revenue tag yielded FY rows: "
              f"{[t for t in L if t not in have_rev]}")
    if len(have_cogs) < len(L):
        print(f"No COGS tag yielded FY rows: "
              f"{[t for t in L if t not in have_cogs]}")


if __name__ == "__main__":
    main()
