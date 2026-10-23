# ============================================================
#  fetch_insider_clusters.py — insider cluster build for
#  PREREGISTRATION_2026-10-23_round15.md (H52).
#
#  Source: SEC "Insider Transactions Data Sets" — quarterly
#  bulk ZIPs of as-filed Forms 3/4/5 (public, free, no key).
#  Stages (resumable; cached zips and finished outputs are
#  skipped):
#    1. inventory + download of every form345 ZIP with filings
#       from 2015Q4 on -> data/insider_sc/raw/
#    2. per-zip scan: original Form 4 submissions only (type
#       exactly "4"; 4/A excluded, round-10 convention) whose
#       as-filed issuer symbol normalises ('.' -> '-') into
#       Universe S; a filing is a PURCHASE filing if it holds
#       >=1 non-derivative transaction with code P, acquired
#       code A, shares > 0 and price > 0.
#    3. outputs:
#       data/insider_sc/cluster_filings.csv — one row per
#         purchase filing: ticker, filing_date (the SEC
#         FILING_DATE = first public date), accession, the
#         distinct reporting-owner CIKs listed on the filing,
#         summed qualifying purchase USD, # P transactions.
#       data/insider_sc/coverage.json — archives used, total
#         Form 4 count, LASTDATE (max FILING_DATE over ALL
#         original Form 4 submissions, the pre-registered
#         coverage cutoff), purchase-filing counts.
#    python fetch_insider_clusters.py
# ============================================================

import io
import json
import os
import re
import time
import zipfile

import pandas as pd
import requests

SEC = "https://www.sec.gov"
PAGE = SEC + "/data-research/sec-markets-data/insider-transactions-data-sets"
UA = {"User-Agent": "iTrade research research@example.com"}
BASE = os.path.join("data", "insider_sc")
RAW = os.path.join(BASE, "raw")
OUT_FILINGS = os.path.join(BASE, "cluster_filings.csv")
OUT_COVERAGE = os.path.join(BASE, "coverage.json")
MIN_Q = (2015, 4)          # filings from 2015-10-01 seed the
                           # trailing-90d window for Jan-2016


def universe():
    t = pd.read_csv(os.path.join("data", "smallcap", "tickers.csv"))
    return set(t["ticker"].astype(str).str.strip().str.upper())


def inventory():
    html = requests.get(PAGE, headers=UA, timeout=60).text
    hrefs = sorted(set(re.findall(r'href="([^"]*form345[^"]*\.zip)"',
                                  html, flags=re.I)))
    keep = []
    for h in hrefs:
        name = h.rsplit("/", 1)[-1]
        m = re.match(r"(\d{4})q([1-4])_form345\.zip", name, flags=re.I)
        if m:
            if (int(m.group(1)), int(m.group(2))) >= MIN_Q:
                keep.append((name, SEC + h))
        elif "_form345" in name.lower():
            keep.append((name, SEC + h))   # date-range named files
    return keep


def download_all(files):
    os.makedirs(RAW, exist_ok=True)
    paths = []
    for name, url in files:
        path = os.path.join(RAW, name)
        if not (os.path.exists(path) and os.path.getsize(path) > 1_000_000):
            tmp = path + ".part"
            for attempt in range(4):
                try:
                    with requests.get(url, headers=UA, timeout=300,
                                      stream=True) as r:
                        r.raise_for_status()
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_content(1 << 20):
                                f.write(chunk)
                    os.rename(tmp, path)
                    break
                except Exception as e:  # noqa: BLE001 - retry log
                    print(f"  {name}: retry {attempt + 1} ({e})",
                          flush=True)
                    time.sleep(10 * (attempt + 1))
            print(f"  downloaded {name} "
                  f"({os.path.getsize(path) / 1e6:.1f} MB)", flush=True)
            time.sleep(0.3)
        paths.append(path)
    return paths


def member(zf, suffix):
    for n in zf.namelist():
        if n.upper().endswith(suffix):
            return n
    raise KeyError(suffix)


def pick(df, *names):
    for n in names:
        if n in df.columns:
            return n
    raise KeyError(f"none of {names} in {list(df.columns)}")


def parse_dates(s):
    return pd.to_datetime(s, format="%d-%b-%Y", errors="coerce")


def scan_zip(zp, uni):
    """-> (filing rows df, n_form4, lastdate, n_bad_dates)"""
    with zipfile.ZipFile(zp) as zf:
        sub = pd.read_csv(io.BytesIO(zf.read(member(zf, "SUBMISSION.TSV"))),
                          sep="\t", dtype=str, low_memory=False)
        type_col = pick(sub, "DOCUMENT_TYPE", "FORM_TYPE",
                        "SUBMISSIONTYPE")
        sym_col = pick(sub, "ISSUERTRADINGSYMBOL", "ISSUER_TRADING_SYMBOL")
        sub = sub[sub[type_col] == "4"].copy()
        sub["fdate"] = parse_dates(sub["FILING_DATE"])
        n_bad = int(sub["fdate"].isna().sum())
        sub = sub.dropna(subset=["fdate"])
        n_form4 = len(sub)
        lastdate = sub["fdate"].max() if n_form4 else None
        sub["ticker"] = (sub[sym_col].astype(str).str.strip().str.upper()
                         .str.replace(".", "-", regex=False))
        sub = sub[sub["ticker"].isin(uni)]
        if sub.empty:
            return pd.DataFrame(), n_form4, lastdate, n_bad
        info = {r.ACCESSION_NUMBER: (r.ticker, r.fdate)
                for r in sub.itertuples()}

        # qualifying purchases per accession
        buy = {}
        name = member(zf, "NONDERIV_TRANS.TSV")
        with zf.open(name) as fh:
            for chunk in pd.read_csv(
                    fh, sep="\t", chunksize=400_000, dtype=str,
                    usecols=["ACCESSION_NUMBER", "TRANS_CODE",
                             "TRANS_ACQUIRED_DISP_CD", "TRANS_SHARES",
                             "TRANS_PRICEPERSHARE"], low_memory=False):
                chunk = chunk[chunk["ACCESSION_NUMBER"].isin(info)]
                if chunk.empty:
                    continue
                chunk = chunk[(chunk["TRANS_CODE"] == "P")
                              & (chunk["TRANS_ACQUIRED_DISP_CD"] == "A")]
                if chunk.empty:
                    continue
                sh = pd.to_numeric(chunk["TRANS_SHARES"], errors="coerce")
                px = pd.to_numeric(chunk["TRANS_PRICEPERSHARE"],
                                   errors="coerce")
                chunk = chunk.assign(usd=sh * px)
                chunk = chunk[(sh > 0) & (px > 0)]
                if chunk.empty:
                    continue
                g = chunk.groupby("ACCESSION_NUMBER")["usd"].agg(
                    ["sum", "count"])
                for acc, row in g.iterrows():
                    s0, c0 = buy.get(acc, (0.0, 0))
                    buy[acc] = (s0 + float(row["sum"]),
                                c0 + int(row["count"]))
        if not buy:
            return pd.DataFrame(), n_form4, lastdate, n_bad

        # distinct reporting owners per purchase filing
        owners = {}
        name = member(zf, "REPORTINGOWNER.TSV")
        with zf.open(name) as fh:
            for chunk in pd.read_csv(
                    fh, sep="\t", chunksize=400_000, dtype=str,
                    usecols=["ACCESSION_NUMBER", "RPTOWNERCIK"],
                    low_memory=False):
                chunk = chunk[chunk["ACCESSION_NUMBER"].isin(buy)]
                for acc, grp in chunk.groupby("ACCESSION_NUMBER"):
                    owners.setdefault(acc, set()).update(
                        grp["RPTOWNERCIK"].astype(str))
        rows = []
        for acc, (usd, ntx) in buy.items():
            ticker, fdate = info[acc]
            rows.append({
                "ticker": ticker,
                "filing_date": fdate.strftime("%Y-%m-%d"),
                "accession": acc,
                "owners": ";".join(sorted(owners.get(acc, set()))),
                "buy_usd": round(usd, 2),
                "n_p_tx": ntx})
        return (pd.DataFrame(rows), n_form4, lastdate, n_bad)


def main():
    uni = universe()
    print(f"Universe S: {len(uni)} tickers", flush=True)
    files = inventory()
    print(f"archives on SEC page from {MIN_Q}: {len(files)}", flush=True)
    if not files:
        raise SystemExit("no form345 archives found — route broken")
    zips = download_all(files)

    if os.path.exists(OUT_FILINGS) and os.path.exists(OUT_COVERAGE):
        print("outputs already exist; nothing to do")
        return
    frames, tot_f4, bad_tot, lastdate = [], 0, 0, None
    for zp in zips:
        df, n4, ld, nbad = scan_zip(zp, uni)
        tot_f4 += n4
        bad_tot += nbad
        if ld is not None and (lastdate is None or ld > lastdate):
            lastdate = ld
        if not df.empty:
            frames.append(df)
        print(f"  {os.path.basename(zp)}: Form 4 filings {n4}, "
              f"Universe-S purchase filings {len(df)}", flush=True)
    out = (pd.concat(frames, ignore_index=True)
           .drop_duplicates("accession")
           .sort_values(["filing_date", "ticker", "accession"]))
    os.makedirs(BASE, exist_ok=True)
    out.to_csv(OUT_FILINGS, index=False)
    cov = {"archives": [n for n, _ in files],
           "n_archives": len(files),
           "form4_filings_total": int(tot_f4),
           "form4_bad_filing_dates": int(bad_tot),
           "lastdate": lastdate.strftime("%Y-%m-%d"),
           "purchase_filings": int(len(out)),
           "purchase_tickers": int(out["ticker"].nunique()),
           "filing_date_min": out["filing_date"].min(),
           "filing_date_max": out["filing_date"].max(),
           "total_buy_usd": float(out["buy_usd"].sum())}
    with open(OUT_COVERAGE, "w") as f:
        json.dump(cov, f, indent=2)
    print(json.dumps(cov, indent=2))


if __name__ == "__main__":
    main()
