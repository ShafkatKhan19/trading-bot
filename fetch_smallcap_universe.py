# ============================================================
#  fetch_smallcap_universe.py — Round 5 data step 1.
#  Current S&P SmallCap 600 constituents from Wikipedia ->
#  data/smallcap/tickers.csv (raw symbol + Yahoo format).
#  Survivorship caveat: today's list, per PREREGISTRATION_2026-10-20_round5.md.
# ============================================================

import os
from io import StringIO

import pandas as pd
import requests

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"}
OUT = os.path.join("data", "smallcap", "tickers.csv")


def main():
    html = requests.get(URL, headers=UA, timeout=60).text
    tables = pd.read_html(StringIO(html))
    tbl = None
    for t in tables:
        cols = [str(c).strip().lower() for c in t.columns]
        if any(c in ("symbol", "ticker") for c in cols):
            tbl, sym_col = t, t.columns[cols.index("symbol")] \
                if "symbol" in cols else t.columns[cols.index("ticker")]
            break
    if tbl is None:
        raise SystemExit("no constituents table found")
    syms = (tbl[sym_col].astype(str).str.strip()
            .replace({"nan": None}).dropna().unique().tolist())
    rows = [{"symbol": s, "ticker": s.replace(".", "-")} for s in sorted(syms)]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"{len(rows)} tickers -> {OUT}")


if __name__ == "__main__":
    main()
