# ============================================================
#  fetch_fundamentals_div.py — dividends panel for
#  PREREGISTRATION_2026-10-20_round10.md (H38): FY common
#  dividends paid from EDGAR, primary tag
#  PaymentsOfDividendsCommonStock, fallback
#  DividendsCommonStockPaid (per ticker, the primary tag is
#  used whenever it yields any FY rows). Same point-in-time
#  build as round 8 (FY 10-K frames, 300-400 day spans,
#  earliest `filed` per period). Output:
#    data/fundamentals/panel_div.csv
#    python fetch_fundamentals_div.py
# ============================================================

import os

import pandas as pd

import fetch_fundamentals as ff
from fetch_fundamentals_gp import CIK_SETS, merged_concept, robust_get
from round2_data import L

OUT = os.path.join("data", "fundamentals")
PRIMARY = "PaymentsOfDividendsCommonStock"
FALLBACK = "DividendsCommonStockPaid"

ff.get = robust_get


def main():
    tick = ff.get("https://www.sec.gov/files/company_tickers.json")
    cik_of = {v["ticker"]: int(v["cik_str"]) for v in tick.values()}

    panel, used = [], {}
    for t in L:
        cik = cik_of.get(t)
        if cik is None:
            print(f"  {t:<6} no CIK, skipped")
            continue
        def _facts(tag):
            if t in CIK_SETS:  # successor-entity merge, see GP build
                return ff.fy_duration_facts(merged_concept(
                    t, CIK_SETS[t], "us-gaap", tag))
            return ff.fy_duration_facts(ff.fetch_concept(
                t, cik, "us-gaap", tag))

        facts = _facts(PRIMARY)
        tag = PRIMARY
        if not facts:
            facts = _facts(FALLBACK)
            tag = FALLBACK if facts else None
        if tag:
            used[t] = tag
        for end in sorted(facts):
            panel.append({"ticker": t, "fy_end": end,
                          "filed": facts[end]["filed"],
                          "dividends": facts[end]["val"]})
        print(f"  {t:<6} dividends[{tag}] FY periods: {len(facts)}",
              flush=True)

    df = pd.DataFrame(panel)
    df.to_csv(os.path.join(OUT, "panel_div.csv"), index=False)
    print(f"\nPanel rows: {len(df)}")
    print(f"Tickers with >=1 FY dividends row: {df.ticker.nunique()}/87")
    from collections import Counter
    print(f"Tag used: {Counter(used.values())}")
    reach = df.groupby("ticker")["fy_end"].min()
    print(f"Tickers reaching back to FY ending <= 2017-12-31: "
          f"{int((reach <= '2017-12-31').sum())}/87")
    none_at_all = [t for t in L if t not in used]
    if none_at_all:
        print(f"No dividends under either tag (treated as 0 in "
              f"H38, disclosed): {none_at_all}")


if __name__ == "__main__":
    main()
