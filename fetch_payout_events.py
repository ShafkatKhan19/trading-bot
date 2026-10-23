# ============================================================
#  fetch_payout_events.py — Data builds for
#  PREREGISTRATION_2026-10-23_round14.md (H50/H51).
#
#  H50: share-repurchase authorization events from EDGAR
#  full-text search (form 8-K, phrase "repurchase program",
#  per company CIK) + the registered sentence rule applied to
#  the matched documents fetched from EDGAR Archives:
#  a sentence mentioning repurchase of shares/stock that
#  contains "authoriz" or "increas" and a dollar amount and
#  does NOT contain "previously announced" marks an event;
#  the event amount is the largest dollar figure in the
#  qualifying sentences; same company + same amount within
#  365 days = the same event (earliest filing date kept).
#  Event date = the filing's EDGAR file_date.
#    data/payout/buyback_events.csv
#
#  H51: declared dividends per share from the EDGAR XBRL
#  company-concept API (CommonStockDividendsPerShareDeclared,
#  USD/shares), quarterly facts only (period span 80-100
#  days), earliest-filed fact per fiscal period.
#    data/payout/dividend_facts.csv
#
#  Both routes are public EDGAR, no key. Raw responses are
#  cached under data/payout/ so re-runs are cheap. The FTS
#  backend intermittently returns HTTP 200 with an error
#  payload instead of results; every FTS call retries until
#  a real `hits` payload arrives (registered in advance).
#    python fetch_payout_events.py
# ============================================================

import json
import os
import re
import time

import pandas as pd
import requests

from round2_data import L

OUT = os.path.join("data", "payout")
RAW_DOCS = os.path.join(OUT, "raw_docs")
UA = {"User-Agent": "iTrade research admin@example.com"}
FTS = "https://efts.sec.gov/LATEST/search-index"
SLEEP = 0.3
MIN_DOC_DATE = "2015-01-01"   # signals start 2016; 12m window needs 2015


def get(url, **kw):
    for attempt in range(5):
        r = requests.get(url, headers=UA, timeout=60, **kw)
        if r.status_code == 200:
            return r
        time.sleep(1.5 * (attempt + 1))
    r.raise_for_status()


def fts(params):
    """EDGAR FTS with the registered retry rule: an HTTP 200
    payload without `hits` is a backend error, not a result."""
    for attempt in range(12):
        r = requests.get(FTS, params=params, headers=UA, timeout=60)
        if r.status_code == 200:
            j = r.json()
            if "hits" in j:
                return j
        time.sleep(min(2.0 * (attempt + 1), 20.0))
    raise RuntimeError(f"FTS failed after retries: {params}")


def cik_map():
    path = os.path.join(OUT, "company_tickers.json")
    if os.path.exists(path):
        with open(path) as f:
            tick = json.load(f)
    else:
        tick = get("https://www.sec.gov/files/company_tickers.json").json()
        with open(path, "w") as f:
            json.dump(tick, f)
    return {v["ticker"]: int(v["cik_str"]) for v in tick.values()}


# ── H50: buyback authorization events ────────────────────────
AMT_RE = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s?(billion|million|bn|mn)?", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])")


def parse_amounts(sentence):
    out = []
    for num, unit in AMT_RE.findall(sentence):
        v = float(num.replace(",", ""))
        u = (unit or "").lower()
        if u in ("billion", "bn"):
            v *= 1e9
        else:  # million / mn / no unit (filings quote $ millions)
            v *= 1e6
        out.append(v)
    return out


def doc_event_amount(text):
    """Largest $ amount across qualifying sentences, else None."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    best = None
    for sent in SENT_SPLIT.split(text):
        s = sent.lower()
        if "repurchas" not in s:
            continue
        if "authoriz" not in s and "increas" not in s:
            continue
        if "previously announced" in s:
            continue
        amounts = parse_amounts(sent)
        if not amounts:
            continue
        m = max(amounts)
        best = m if best is None else max(best, m)
    return best


def fetch_buybacks(ciks):
    hits_path = os.path.join(OUT, "fts_hits.json")
    if os.path.exists(hits_path):
        with open(hits_path) as f:
            hits = json.load(f)
    else:
        hits = {}
        for t in L:
            rows, frm = [], 0
            while True:
                j = fts({"q": '"repurchase program"', "forms": "8-K",
                         "ciks": f"{ciks[t]:010d}",
                         "from": frm, "size": 100})
                for h in j["hits"]["hits"]:
                    acc, doc = h["_id"].split(":", 1)
                    rows.append({"accession": acc, "doc": doc,
                                 "file_date": h["_source"].get("file_date")})
                total = j["hits"]["total"]["value"]
                frm += len(j["hits"]["hits"])
                if frm >= total or not j["hits"]["hits"]:
                    break
                time.sleep(SLEEP)
            hits[t] = rows
            print(f"  FTS {t:<6} {len(rows)} candidate docs", flush=True)
            time.sleep(SLEEP)
        with open(hits_path, "w") as f:
            json.dump(hits, f)

    events, diag = [], {"candidate_docs": 0, "docs_fetched": 0,
                        "docs_404": 0, "qualifying_filings": 0}
    for t in L:
        filings = {}
        for row in hits.get(t, []):
            if row["file_date"] is None or row["file_date"] < MIN_DOC_DATE:
                continue
            diag["candidate_docs"] += 1
            key = f"{row['accession']}_{row['doc']}"
            path = os.path.join(RAW_DOCS, key + ".txt")
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            else:
                url = (f"https://www.sec.gov/Archives/edgar/data/"
                       f"{ciks[t]}/{row['accession'].replace('-', '')}/"
                       f"{row['doc']}")
                r = requests.get(url, headers=UA, timeout=60)
                if r.status_code != 200:
                    diag["docs_404"] += 1
                    continue
                text = r.text
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                diag["docs_fetched"] += 1
                time.sleep(SLEEP)
            amount = doc_event_amount(text)
            if amount is None:
                continue
            prev = filings.get(row["accession"])
            if prev is None or amount > prev[1]:
                filings[row["accession"]] = (row["file_date"], amount)
        diag["qualifying_filings"] += len(filings)
        # same amount within 365 days = same event (earliest kept)
        kept = []
        for acc, (fdate, amount) in sorted(filings.items(),
                                           key=lambda kv: kv[1][0]):
            d = pd.Timestamp(fdate)
            if any(k[1] == amount and (d - k[0]).days <= 365
                   for k in kept):
                continue
            kept.append((d, amount, acc))
        for d, amount, acc in kept:
            events.append({"ticker": t, "event_date": d.date().isoformat(),
                           "amount_usd": amount, "accession": acc})
        print(f"  H50 {t:<6} filings qualifying "
              f"{len(filings)}, events kept {len(kept)}", flush=True)
    ev = pd.DataFrame(events).sort_values(["event_date", "ticker"])
    ev.to_csv(os.path.join(OUT, "buyback_events.csv"), index=False)
    print(f"H50: {len(ev)} events, {ev['ticker'].nunique()} tickers, "
          f"{ev['event_date'].min()} -> {ev['event_date'].max()}")
    print(f"H50 diagnostics: {diag}")
    return ev, diag


# ── H51: declared dividends per share ────────────────────────
def fetch_dividends(ciks):
    rows = []
    no_tag = []
    for t in L:
        url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
               f"CIK{ciks[t]:010d}/us-gaap/"
               f"CommonStockDividendsPerShareDeclared.json")
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 404:
            no_tag.append(t)
            continue
        r.raise_for_status()
        facts = r.json().get("units", {}).get("USD/shares", [])
        best = {}
        for f in facts:
            if "start" not in f:
                continue
            span = (pd.Timestamp(f["end"])
                    - pd.Timestamp(f["start"])).days
            if not (80 <= span <= 100):
                continue
            key = (f["start"], f["end"])
            if key not in best or f["filed"] < best[key]["filed"]:
                best[key] = f
        for (start, end), f in sorted(best.items()):
            rows.append({"ticker": t, "period_start": start,
                         "period_end": end, "dps": f["val"],
                         "filed": f["filed"], "form": f["form"],
                         "accn": f["accn"]})
        print(f"  H51 {t:<6} quarterly DPS periods {len(best)}",
              flush=True)
        time.sleep(SLEEP)
    df = pd.DataFrame(rows).sort_values(["ticker", "period_end"])
    df.to_csv(os.path.join(OUT, "dividend_facts.csv"), index=False)
    print(f"H51: {len(df)} quarterly DPS facts, "
          f"{df['ticker'].nunique()}/87 tickers; no tag: {no_tag}")
    return df, no_tag


def main():
    os.makedirs(RAW_DOCS, exist_ok=True)
    ciks = cik_map()
    fetch_buybacks(ciks)
    fetch_dividends(ciks)


if __name__ == "__main__":
    main()
