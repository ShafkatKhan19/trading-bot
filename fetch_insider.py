# ============================================================
#  fetch_insider.py — insider Form 4 net buying build for
#  PREREGISTRATION_2026-10-20_round10.md (H39).
#
#  For each universe-L CIK: list Form 4 filings (form == "4"
#  exactly; amendments 4/A excluded to avoid double counting)
#  from the SEC submissions API, recent block plus every
#  history file it references, keeping filings accepted from
#  2015-01-01 on. Fetch each filing's ownership XML from the
#  Archives, parse nonDerivativeTable transactions, keep
#  transaction codes P (open-market purchase) and S (open-
#  market sale), value = shares x price. A filing's usable
#  date is its SEC acceptance date. Outputs:
#    data/insider/filing_lists/<TICKER>.json  cached lists
#    data/insider/xml/<accession>.xml         raw cache (not
#                                             committed)
#    data/insider/filing_net.csv  per-filing net USD
#    data/insider/monthly_net.csv per-ticker-month net USD
#  The run is resumable: filings already in filing_net.csv
#  (or logged as parse failures) are skipped.
#    python fetch_insider.py
# ============================================================

import csv
import json
import os
import time
import xml.etree.ElementTree as ET

import requests

from round2_data import L

OUT = os.path.join("data", "insider")
LISTS = os.path.join(OUT, "filing_lists")
XMLD = os.path.join(OUT, "xml")
UA = {"User-Agent": "iTrade research admin@example.com"}
SLEEP = 0.30  # ~3.3 req/s (lowered from 0.21 after a read-timeout stall)
SINCE = "2015-01-01"

SESSION = requests.Session()
SESSION.headers.update(UA)


def get(url, want_json=False):
    """GET with retries on connection errors and 5xx/429."""
    for attempt in range(4):
        try:
            r = SESSION.get(url, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"    conn error ({type(e).__name__}), retry "
                  f"{attempt + 1}", flush=True)
            time.sleep(2.0 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r.json() if want_json else r.text
        if r.status_code == 404:
            return None
        time.sleep(2.0 * (attempt + 1))
    return None


# Successor-entity CIK splits (data-build correction, verified
# against the submissions API 2026-10-20): the SEC ticker map
# points XOM at ExxonMobil Holdings Corp (CIK 2115436, filings
# only from 2026-07) and BLK at the post-2024 parent (CIK
# 2012383), while the filing history lives under the operating
# predecessors below. Form 4s are taken from BOTH issuers,
# deduped by accession.
CIK_SETS = {"XOM": [34088, 2115436], "BLK": [1364742, 2012383]}


def cik_map():
    tick = get("https://www.sec.gov/files/company_tickers.json",
               want_json=True)
    return {v["ticker"]: int(v["cik_str"]) for v in tick.values()}


def _rows_from_block(block):
    n = len(block.get("accessionNumber", []))
    out = []
    for i in range(n):
        out.append({
            "accession": block["accessionNumber"][i],
            "form": block["form"][i],
            "filing_date": block["filingDate"][i],
            "acceptance": block["acceptanceDateTime"][i],
            "primary_doc": block["primaryDocument"][i]})
    return out


def _filings_for_cik(cik):
    base = get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
               want_json=True)
    rows = _rows_from_block(base["filings"]["recent"])
    for hf in base["filings"].get("files", []):
        if hf["filingTo"] < SINCE:
            continue
        time.sleep(SLEEP)
        sub = get(f"https://data.sec.gov/submissions/{hf['name']}",
                  want_json=True)
        if sub:
            rows += _rows_from_block(sub)
    return rows


def filing_list(ticker, cik):
    """All Form 4 filings accepted >= SINCE, cached per ticker.
    For CIK_SETS tickers the list merges every issuer CIK."""
    path = os.path.join(LISTS, f"{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows, seen = [], set()
    for c in CIK_SETS.get(ticker, [cik]):
        for r in _filings_for_cik(c):
            if r["accession"] not in seen:
                seen.add(r["accession"])
                r["issuer_cik"] = c
                rows.append(r)
    keep = [r for r in rows if r["form"] == "4"
            and r["acceptance"][:10] >= SINCE]
    keep.sort(key=lambda r: r["acceptance"])
    with open(path, "w") as f:
        json.dump(keep, f)
    return keep


def parse_form4(xml_text):
    """(net_usd, n_p, n_s) from P/S non-derivative transactions,
    or None if the document does not parse."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    net, n_p, n_s = 0.0, 0, 0
    for tx in root.iter("nonDerivativeTransaction"):
        code = tx.findtext("transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue
        try:
            sh = float(tx.findtext(
                "transactionAmounts/transactionShares/value"))
            px = float(tx.findtext(
                "transactionAmounts/transactionPricePerShare/value"))
        except (TypeError, ValueError):
            continue
        if code == "P":
            net += sh * px
            n_p += 1
        else:
            net -= sh * px
            n_s += 1
    return net, n_p, n_s


def main():
    os.makedirs(LISTS, exist_ok=True)
    os.makedirs(XMLD, exist_ok=True)
    cik_of = cik_map()

    done = set()
    net_path = os.path.join(OUT, "filing_net.csv")
    if os.path.exists(net_path):
        with open(net_path) as f:
            for row in csv.DictReader(f):
                done.add(row["accession"])
    fail_path = os.path.join(OUT, "parse_failures.csv")
    if os.path.exists(fail_path):
        with open(fail_path) as f:
            for row in csv.DictReader(f):
                done.add(row["accession"])

    net_f = open(net_path, "a", newline="")
    net_w = csv.writer(net_f)
    if os.path.getsize(net_path) == 0:
        net_w.writerow(["ticker", "accession", "acceptance_date",
                        "net_usd", "n_p_tx", "n_s_tx"])
    fail_f = open(fail_path, "a", newline="")
    fail_w = csv.writer(fail_f)
    if os.path.getsize(fail_path) == 0:
        fail_w.writerow(["ticker", "accession", "reason"])

    total, parsed, failed = 0, 0, 0
    for t in L:
        cik = cik_of.get(t)
        if cik is None:
            print(f"  {t:<6} no CIK, skipped", flush=True)
            continue
        fl = filing_list(t, cik)
        todo = [r for r in fl if r["accession"] not in done]
        print(f"  {t:<6} CIK {cik:<8} Form 4 filings: {len(fl)} "
              f"(to fetch: {len(todo)})", flush=True)
        for r in todo:
            total += 1
            acc = r["accession"]
            nodash = acc.replace("-", "")
            xpath = os.path.join(XMLD, f"{nodash}.xml")
            if os.path.exists(xpath):
                with open(xpath) as f:
                    text = f.read()
            else:
                doc = r["primary_doc"]
                if "/" in doc:  # e.g. xslF345X06/form4.xml -> raw XML
                    doc = doc.split("/")[-1]
                time.sleep(SLEEP)
                text = get("https://www.sec.gov/Archives/edgar/data/"
                           f"{r.get('issuer_cik', cik)}/{nodash}/{doc}")
                if text is not None:
                    with open(xpath, "w") as f:
                        f.write(text)
            res = parse_form4(text) if text else None
            if res is None:
                fail_w.writerow([t, acc, "fetch/parse failed"])
                fail_f.flush()
                failed += 1
                continue
            net, n_p, n_s = res
            net_w.writerow([t, acc, r["acceptance"][:10],
                            f"{net:.2f}", n_p, n_s])
            net_f.flush()
            parsed += 1
    net_f.close()
    fail_f.close()
    print(f"\nFilings fetched this run: {total}, parsed: {parsed}, "
          f"failed: {failed}")

    # monthly aggregation from the full per-filing file
    import pandas as pd
    df = pd.read_csv(net_path, parse_dates=["acceptance_date"])
    df["month"] = df["acceptance_date"].dt.strftime("%Y-%m")
    act = df[(df["n_p_tx"] + df["n_s_tx"]) > 0]
    m = (act.groupby(["ticker", "month"])
         .agg(net_usd=("net_usd", "sum"), n_filings=("accession", "count"))
         .reset_index().sort_values(["ticker", "month"]))
    m.to_csv(os.path.join(OUT, "monthly_net.csv"), index=False)
    print(f"Monthly rows: {len(m)}; tickers with any P/S activity: "
          f"{act.ticker.nunique()}/87; total filings with P/S tx: "
          f"{len(act)} of {len(df)} parsed overall")
    fp = os.path.join(OUT, "parse_failures.csv")
    if os.path.exists(fp):
        print(f"Parse failures logged overall: "
              f"{sum(1 for _ in open(fp)) - 1}")


if __name__ == "__main__":
    main()
