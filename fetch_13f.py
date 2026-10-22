# ============================================================
#  fetch_13f.py — SEC Form 13F Data Sets build for
#  PREREGISTRATION_2026-10-21_round13.md (H49).
#
#  Source: SEC "Form 13F Data Sets" (bulk quarterly ZIPs of
#  as-filed structured 13F-HR submissions), sec.gov — public,
#  no key. Stages (each resumable; re-runs skip finished
#  outputs):
#    1. inventory + download of every filing-window ZIP from
#       2015Q3 through the Jun-Aug 2026 file -> data/13f/raw/
#    2. winners: across ALL zips' SUBMISSION tables, per
#       (manager CIK, period of report) the latest 13F-HR or
#       13F-HR/A filing with FILING_DATE <= period end + 50
#       calendar days (the pre-registration's availability
#       rule applied to amendments too: a later amendment is
#       NOT usable for that quarter's signal).
#    3. name pairs: over winner filings' INFOTABLE rows
#       (SSHPRNAMTTYPE == 'SH', no put/call), share-weighted
#       (CUSIP, NAMEOFISSUER) and (CUSIP, TITLEOFCLASS) pairs
#       -> data/13f/namepairs_by_zip/, combined on build.
#    4. CUSIP map: Universe L tickers matched to CUSIPs whose
#       recorded issuer name matches the expected name (see
#       EXPECTED below; class hints for GOOGL/V/MA/CMCSA).
#       Multiple CUSIPs per ticker are unioned (CUSIP changes
#       and successor issues). -> data/13f/cusip_map.csv
#    5. holdings: INFOTABLE re-scanned, winner rows with a
#       mapped CUSIP aggregated to (period, manager CIK,
#       CUSIP) share sums -> data/13f/holdings_panel.csv
#    python fetch_13f.py
# ============================================================

import bisect
import io
import os
import re
import sys
import time
import zipfile

import pandas as pd
import requests

from round2_data import L

SEC = "https://www.sec.gov"
PAGE = SEC + "/data-research/sec-markets-data/form-13f-data-sets"
UA = {"User-Agent": "iTrade research research@example.com"}
BASE = os.path.join("data", "13f")
RAW = os.path.join(BASE, "raw")
PAIRS_DIR = os.path.join(BASE, "namepairs_by_zip")
HOLD_DIR = os.path.join(BASE, "holdings_by_zip")
CUTOFF_DAYS = 50          # pre-registered availability rule

# Expected 13F issuer names per Universe L ticker (as filed;
# matched punctuation-insensitively; extra stems cover known
# historical name variants). Class hint = substring the modal
# TITLEOFCLASS must contain (share-class disambiguation).
EXPECTED = {
    "AAPL": (["APPLE INC"], None), "MSFT": (["MICROSOFT CORP"], None),
    "AMZN": (["AMAZON COM INC"], None),
    "GOOGL": (["ALPHABET INC"], "CL A"),
    "JNJ": (["JOHNSON & JOHNSON"], None),
    "JPM": (["JPMORGAN CHASE & CO"], None),
    "XOM": (["EXXON MOBIL CORP"], None),
    "PG": (["PROCTER & GAMBLE CO"], None),
    "V": (["VISA INC"], "CL A"), "MA": (["MASTERCARD INC"], "CL A"),
    "HD": (["HOME DEPOT INC", "THE HOME DEPOT INC"], None),
    "CVX": (["CHEVRON CORP"], None),
    "PFE": (["PFIZER INC"], None),
    "KO": (["COCA COLA CO", "THE COCA COLA CO"], None),
    "PEP": (["PEPSICO INC"], None), "MRK": (["MERCK & CO INC"], None),
    "ABBV": (["ABBVIE INC"], None),
    "BAC": (["BANK AMERICA CORP", "BANK OF AMERICA CORP",
             "BANK AMER CORP", "BK OF AMERICA CORP"], None),
    "WMT": (["WALMART INC", "WAL MART STORES INC"], None),
    "DIS": (["WALT DISNEY CO", "DISNEY WALT CO"], None),
    "CSCO": (["CISCO SYSTEMS INC", "CISCO SYS INC"], None),
    "INTC": (["INTEL CORP"], None),
    "VZ": (["VERIZON COMMUNICATIONS INC"], None),
    "T": (["AT&T INC"], None), "ORCL": (["ORACLE CORP"], None),
    "CMCSA": (["COMCAST CORP"], "CL A"),
    "NFLX": (["NETFLIX INC"], None), "ADBE": (["ADOBE INC",
    "ADOBE SYSTEMS INC"], None), "CRM": (["SALESFORCE INC",
    "SALESFORCE COM INC"], None), "NKE": (["NIKE INC"], "CL B"),
    "MCD": (["MCDONALDS CORP"], None),
    "MDT": (["MEDTRONIC PLC"], None), "UNH": (["UNITEDHEALTH GROUP INC"], None),
    "ABT": (["ABBOTT LABORATORIES", "ABBOTT LABS"], None),
    "TMO": (["THERMO FISHER SCIENTIFIC INC"], None),
    "AMGN": (["AMGEN INC"], None),
    "HON": (["HONEYWELL INTERNATIONAL INC", "HONEYWELL INTL INC"], None),
    "UNP": (["UNION PACIFIC CORP", "UNION PAC CORP"], None),
    "UPS": (["UNITED PARCEL SERVICE INC"], "CL B"),
    "LOW": (["LOWES COMPANIES INC", "LOWES COS INC"], None),
    "SBUX": (["STARBUCKS CORP"], None),
    "IBM": (["INTERNATIONAL BUSINESS MACHINES CORP",
             "INTERNATIONAL BUSINESS MACHS",
             "INTL BUSINESS MACHINES CORP"], None),
    "QCOM": (["QUALCOMM INC"], None),
    "TXN": (["TEXAS INSTRUMENTS INC", "TEXAS INSTRS INC"], None),
    "AVGO": (["BROADCOM INC", "BROADCOM LTD",
              "AVAGO TECHNOLOGIES LTD", "AVAGO TECHNOLOGIES"], None),
    "NVDA": (["NVIDIA CORP"], None),
    "COST": (["COSTCO WHOLESALE CORP", "COSTCO WHSL CORP"], None),
    "WFC": (["WELLS FARGO & CO"], None),
    "C": (["CITIGROUP INC"], None), "GS": (["GOLDMAN SACHS GROUP INC"], None),
    "MS": (["MORGAN STANLEY"], None), "BLK": (["BLACKROCK INC"], None),
    "AXP": (["AMERICAN EXPRESS CO"], None),
    "CAT": (["CATERPILLAR INC"], None), "DE": (["DEERE & CO"], None),
    "MMM": (["3M CO", "3M COMPANY"], None),
    "GE": (["GENERAL ELECTRIC CO", "GE AEROSPACE"], None),
    "BA": (["BOEING CO", "THE BOEING CO"], None),
    "LMT": (["LOCKHEED MARTIN CORP"], None),
    "GD": (["GENERAL DYNAMICS CORP"], None),
    "NOC": (["NORTHROP GRUMMAN CORP"], None),
    "LLY": (["LILLY ELI & CO", "ELI LILLY & CO"], None),
    "BMY": (["BRISTOL MYERS SQUIBB CO"], None),
    "GILD": (["GILEAD SCIENCES INC"], None),
    "CVS": (["CVS HEALTH CORP"], None),
    "MO": (["ALTRIA GROUP INC"], None),
    "PM": (["PHILIP MORRIS INTERNATIONAL INC",
            "PHILIP MORRIS INTL INC"], None),
    "MDLZ": (["MONDELEZ INTERNATIONAL INC", "MONDELEZ INTL INC"], None),
    "CL": (["COLGATE PALMOLIVE CO"], None),
    "KMB": (["KIMBERLY CLARK CORP"], None),
    "TGT": (["TARGET CORP"], None),
    "AMT": (["AMERICAN TOWER CORP"], None),
    "SPG": (["SIMON PROPERTY GROUP INC", "SIMON PPTY GROUP INC"], None),
    "NEE": (["NEXTERA ENERGY INC"], None),
    "DUK": (["DUKE ENERGY CORP"], None),
    "SO": (["SOUTHERN CO", "THE SOUTHERN CO"], None),
    "D": (["DOMINION ENERGY INC", "DOMINION RESOURCES INC"], None),
    "EXC": (["EXELON CORP"], None), "COP": (["CONOCOPHILLIPS"], None),
    "SLB": (["SCHLUMBERGER LTD", "SLB LTD"], None),
    "EOG": (["EOG RESOURCES INC", "EOG RES INC"], None),
    "OXY": (["OCCIDENTAL PETROLEUM CORP", "OCCIDENTAL PETE CORP"], None),
    "F": (["FORD MOTOR CO", "FORD MTR CO"], None),
    "GM": (["GENERAL MOTORS CO", "GENERAL MTRS CO"], None),
    "ADP": (["AUTOMATIC DATA PROCESSING INC",
             "AUTOMATIC DATA PROCESSING IN"], None),
    "INTU": (["INTUIT INC"], None),
    "ISRG": (["INTUITIVE SURGICAL INC"], None),
}
assert set(EXPECTED) == set(L), set(L) ^ set(EXPECTED)


STOPWORDS = {"AND", "THE", "NEW", "OF"}
SUFFIX_CANON = {"CORPORATION": "CO", "COMPANY": "CO", "CORP": "CO",
                "INCORPORATED": "INC", "LIMITED": "LTD"}


def norm(s):
    """Token form of an issuer name: split on non-alphanumerics,
    drop stopwords, canonicalise corporate suffixes. Matching
    (build_map) is token-prefix in either direction, so filer
    variants like 'APPLE INC COM' or 'WAL MART STORES INC'
    match their stems while 'SOUTHERN COPPER CORP' cannot
    match the stem 'SOUTHERN CO'."""
    toks = [SUFFIX_CANON.get(t, t)
            for t in re.findall(r"[A-Z0-9]+", str(s).upper())]
    return tuple(t for t in toks if t not in STOPWORDS)


# ── stage 1: inventory + download ────────────────────────────
def inventory():
    html = requests.get(PAGE, headers=UA, timeout=60).text
    hrefs = sorted(set(re.findall(r'href="([^"]*form13f[^"]*\.zip)"',
                                  html, flags=re.I)))
    keep = []
    for h in hrefs:
        name = h.rsplit("/", 1)[-1]
        m = re.match(r"(\d{4})q([1-4])_form13f\.zip", name, flags=re.I)
        if m:
            if (int(m.group(1)), int(m.group(2))) >= (2015, 3):
                keep.append((name, SEC + h))
        elif "_form13f" in name.lower():
            keep.append((name, SEC + h))   # 2024+ date-range files
    return keep


def download_all(files):
    os.makedirs(RAW, exist_ok=True)
    for name, url in files:
        path = os.path.join(RAW, name)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            continue
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
            except Exception as e:
                print(f"  {name}: retry {attempt + 1} ({e})", flush=True)
                time.sleep(10 * (attempt + 1))
        print(f"  downloaded {name} "
              f"({os.path.getsize(path) / 1e6:.0f} MB)", flush=True)
        time.sleep(0.3)
    return [os.path.join(RAW, n) for n, _ in files]


# ── stage 2: amendment winners (global, cutoff-applied) ──────
def member(zf, suffix):
    for n in zf.namelist():
        if n.upper().endswith(suffix):
            return n
    raise KeyError(suffix)


def parse_dates(s):
    return pd.to_datetime(s, format="%d-%b-%Y")


def build_winners(zips):
    out = os.path.join(BASE, "winners.csv")
    if os.path.exists(out):
        return pd.read_csv(out, dtype={"accession": str, "cik": str,
                                       "period": str})
    frames = []
    for zp in zips:
        with zipfile.ZipFile(zp) as zf:
            sub = pd.read_csv(io.BytesIO(zf.read(member(zf, "SUBMISSION.TSV"))),
                              sep="\t", dtype=str)
        sub = sub[sub["SUBMISSIONTYPE"].isin(["13F-HR", "13F-HR/A"])]
        frames.append(sub[["ACCESSION_NUMBER", "FILING_DATE",
                           "CIK", "PERIODOFREPORT"]])
    all_sub = pd.concat(frames, ignore_index=True)
    all_sub = all_sub.drop_duplicates("ACCESSION_NUMBER")
    all_sub["filing_date"] = parse_dates(all_sub["FILING_DATE"])
    all_sub["period_end"] = parse_dates(all_sub["PERIODOFREPORT"])
    all_sub = all_sub[all_sub["filing_date"]
                      <= all_sub["period_end"] + pd.Timedelta(days=CUTOFF_DAYS)]
    all_sub = all_sub.sort_values(["CIK", "period_end", "filing_date",
                                   "ACCESSION_NUMBER"])
    win = all_sub.groupby(["CIK", "period_end"], as_index=False).tail(1)
    res = pd.DataFrame({
        "accession": win["ACCESSION_NUMBER"],
        "cik": win["CIK"],
        "period": win["period_end"].dt.strftime("%Y-%m-%d"),
        "filing_date": win["filing_date"].dt.strftime("%Y-%m-%d")})
    res.to_csv(out, index=False)
    print(f"winners: {len(res)} (manager, period) filings, periods "
          f"{res['period'].min()} -> {res['period'].max()}", flush=True)
    return res


# ── stages 3/5: INFOTABLE scans ──────────────────────────────
INFO_COLS = ["ACCESSION_NUMBER", "NAMEOFISSUER", "TITLEOFCLASS",
             "CUSIP", "VALUE", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"]


def scan_infotable(zp, winners, want_cusips=None):
    """Yield aggregated frames from one zip's INFOTABLE over
    winner filings only. want_cusips=None -> name/title pairs;
    else -> (period, cik, cusip, shares) holdings sums."""
    tag = os.path.basename(zp)
    pair_frames, hold = [], {}
    with zipfile.ZipFile(zp) as zf:
        name = member(zf, "INFOTABLE.TSV")
        with zf.open(name) as fh:
            for chunk in pd.read_csv(
                    fh, sep="\t", usecols=INFO_COLS, chunksize=400_000,
                    dtype={"ACCESSION_NUMBER": str, "CUSIP": str,
                           "NAMEOFISSUER": str, "TITLEOFCLASS": str,
                           "SSHPRNAMTTYPE": str, "PUTCALL": str},
                    low_memory=False):
                chunk = chunk[chunk["ACCESSION_NUMBER"].isin(winners)]
                if chunk.empty:
                    continue
                chunk = chunk[(chunk["SSHPRNAMTTYPE"] == "SH")
                              & (chunk["PUTCALL"].isna()
                                 | (chunk["PUTCALL"] == ""))]
                if chunk.empty:
                    continue
                if want_cusips is None:
                    # NOTE: pairs are weighted by SSHPRNAMT
                    # (shares), not VALUE — in the as-filed data
                    # VALUE units are mixed across filers (some
                    # report dollars, most thousands), while
                    # share counts are unit-consistent.
                    g = chunk.groupby(["CUSIP", "NAMEOFISSUER"],
                                      as_index=False)["SSHPRNAMT"].sum()
                    g = g.rename(columns={"SSHPRNAMT": "SHARES"})
                    g["KIND"] = "NAME"
                    t = chunk.groupby(["CUSIP", "TITLEOFCLASS"],
                                      as_index=False)["SSHPRNAMT"].sum()
                    t.columns = ["CUSIP", "NAMEOFISSUER", "SHARES"]
                    t["KIND"] = "TITLE"
                    pair_frames.append(pd.concat([g, t],
                                                 ignore_index=True))
                else:
                    chunk = chunk.assign(
                        CUSIP=chunk["CUSIP"].str.strip().str.upper())
                    chunk = chunk[chunk["CUSIP"].isin(want_cusips)]
                    if chunk.empty:
                        continue
                    g = chunk.groupby(["ACCESSION_NUMBER", "CUSIP"],
                                      as_index=False)["SSHPRNAMT"].sum()
                    hold[tag] = g if tag not in hold else pd.concat(
                        [hold[tag], g]).groupby(
                        ["ACCESSION_NUMBER", "CUSIP"],
                        as_index=False)["SSHPRNAMT"].sum()
    if want_cusips is None:
        return pd.concat(pair_frames, ignore_index=True) \
            if pair_frames else pd.DataFrame(
                columns=["CUSIP", "NAMEOFISSUER", "VALUE", "KIND"])
    return hold.get(tag, pd.DataFrame(
        columns=["ACCESSION_NUMBER", "CUSIP", "SSHPRNAMT"]))


def stage_pairs(zips, winners):
    os.makedirs(PAIRS_DIR, exist_ok=True)
    for zp in zips:
        tag = os.path.basename(zp).replace(".zip", ".csv")
        out = os.path.join(PAIRS_DIR, tag)
        if os.path.exists(out):
            continue
        df = scan_infotable(zp, set(winners["accession"]))
        df.to_csv(out, index=False)
        print(f"  pairs {tag}: {len(df)} rows", flush=True)


def norm_cusip(s):
    return str(s).strip().upper()


def combined_pairs():
    acc = None
    for f in sorted(os.listdir(PAIRS_DIR)):
        df = pd.read_csv(os.path.join(PAIRS_DIR, f), dtype=str)
        df["SHARES"] = pd.to_numeric(df["SHARES"], errors="coerce")
        df["CUSIP"] = df["CUSIP"].map(norm_cusip)
        df = df[df["CUSIP"].str.len() == 9]
        g = df.groupby(["KIND", "CUSIP", "NAMEOFISSUER"],
                       as_index=False)["SHARES"].sum()
        acc = g if acc is None else pd.concat([acc, g]).groupby(
            ["KIND", "CUSIP", "NAMEOFISSUER"],
            as_index=False)["SHARES"].sum()
        del df, g
    return acc


# ── stage 4: CUSIP map ───────────────────────────────────────
# Filer-reported (name, CUSIP) pairs are noisy: mis-keyed
# CUSIPs (often an ETF's) carry real positions under a company
# name, and every big CUSIP accrues typo variants. Pairs are
# weighted by reported SHARES (VALUE units are mixed across
# filers — some report dollars, most thousands — while share
# counts are unit-consistent). A CUSIP is mapped to a ticker
# only if ALL of these hold:
#   * matching: the CUSIP carries the ticker's issuer name
#     (token-prefix match either direction on the tokenised
#     name — see norm(); the expected stems include the
#     dominant filer abbreviations observed in the data);
#   * size: matched shares >= 1e8 across all quarters;
#   * purity: matched pairs are >= 50% of the CUSIP's total
#     name-pair shares (kills fund CUSIPs, whose reported
#     names span hundreds of issuers);
#   * title: the CUSIP's share-weighted modal TITLEOFCLASS
#     looks like common stock and carries no fund marker;
#   * class hint (GOOGL/V/MA/CMCSA/NKE/UPS) if registered;
#   * dominance: matched shares >= max(5% of the ticker's
#     best CUSIP, 1e8) — keeps genuine era-split CUSIPs (GE
#     pre/post reverse split, AVGO) while dropping typo
#     variants and minor classes.
FUND_MARKERS = ["ETF", "TRUST", "FUND", "INDEX", "S&P", "SPDR",
                "ISHARES", "PROSHARES", "DIREXION", "WISDOMTREE",
                "VANECK", "POWERSHARES", "SELECT SECTOR", "RUSSELL",
                "MSCI", "FTSE", "TTL STK", "PORTFOLIO", "SERIES",
                "INVESCO", "SCHWAB", "DIMENSIONAL", "FIDELITY"]
COMMON_MARKERS = ["COM", "CL A", "CL B", "CLASS", "STK", "SHS",
                  "STOCK", "BEN INT", "ORD", "CAP STK"]


def title_ok(t):
    t = str(t).upper()
    if any(m in t for m in FUND_MARKERS):
        return False
    return any(m in t for m in COMMON_MARKERS)


def build_map(pairs):
    out = os.path.join(BASE, "cusip_map.csv")
    names = pairs[pairs["KIND"] == "NAME"].copy()
    names["nname"] = names["NAMEOFISSUER"].map(norm)
    names = names.groupby(["CUSIP", "nname"],
                          as_index=False)["SHARES"].sum()
    titles = pairs[pairs["KIND"] == "TITLE"]
    modal_title = (titles.sort_values("SHARES")
                   .groupby("CUSIP").tail(1)
                   .set_index("CUSIP")["NAMEOFISSUER"]
                   .str.upper().to_dict())
    total_by_cusip = names.groupby("CUSIP")["SHARES"].sum().to_dict()
    distinct = sorted(set(names["nname"]))
    distinct_set = set(distinct)
    rows, report = [], []
    for t in L:
        stems, hint = EXPECTED[t]
        matched_names = set()
        for stem in stems:
            ns = norm(stem)
            i = bisect.bisect_left(distinct, ns)
            while i < len(distinct) and distinct[i][:len(ns)] == ns:
                matched_names.add(distinct[i])
                i += 1
            for k in range(1, len(ns)):
                if ns[:k] in distinct_set:
                    matched_names.add(ns[:k])
        sub = names[names["nname"].isin(matched_names)]
        cand = sub.groupby("CUSIP")["SHARES"].sum().to_dict()
        kept = {}
        for cusip, val in cand.items():
            if val < 1e8:
                continue
            purity = val / total_by_cusip.get(cusip, val)
            if purity < 0.5:
                continue
            if not title_ok(modal_title.get(cusip, "")):
                continue
            if hint and hint not in modal_title.get(cusip, ""):
                continue
            kept[cusip] = (val, purity)
        if kept:
            leader = max(v for v, _ in kept.values())
            floor = max(0.05 * leader, 1e8)
            kept = {c: v for c, v in kept.items()
                    if v[0] >= floor or v[0] == leader}
        for cusip, (val, purity) in sorted(kept.items()):
            rows.append(dict(ticker=t, cusip=cusip,
                             modal_title=modal_title.get(cusip, ""),
                             matched_shares=val, purity=purity))
        report.append(
            f"{t}: {len(kept)} kept "
            f"{ {c: f'{v[0]:.2e}/p{v[1]:.2f}' for c, v in sorted(kept.items())} }"
            f" (candidates {len(cand)})")
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    print("\n".join(report), flush=True)
    return df


# ── stage 5: holdings panel ──────────────────────────────────
def stage_holdings(zips, winners, cusip_map):
    os.makedirs(HOLD_DIR, exist_ok=True)
    acc_info = winners.set_index("accession")[["cik", "period"]]
    want = set(cusip_map["cusip"])
    for zp in zips:
        tag = os.path.basename(zp).replace(".zip", ".csv")
        out = os.path.join(HOLD_DIR, tag)
        if os.path.exists(out):
            continue
        # per-accession aggregation needs cik: scan with a
        # {accession: cik} mapping encoded via winners dict —
        # scan_infotable maps accession->cik through `winners`
        # argument when it is a dict; here pass the accession
        # set and join afterwards instead.
        df = scan_infotable(zp, set(winners["accession"]),
                            want_cusips=want)
        if len(df):
            df = df.join(acc_info, on="ACCESSION_NUMBER")
            df = df.groupby(["period", "cik", "CUSIP"],
                            as_index=False)["SSHPRNAMT"].sum()
            df.columns = ["period", "manager_cik", "cusip", "shares"]
        df.to_csv(out, index=False)
        print(f"  holdings {tag}: {len(df)} rows", flush=True)
    frames = [pd.read_csv(os.path.join(HOLD_DIR, f),
                          dtype={"manager_cik": str, "cusip": str})
              for f in sorted(os.listdir(HOLD_DIR))
              if os.path.getsize(os.path.join(HOLD_DIR, f)) > 0]
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.groupby(["period", "manager_cik", "cusip"],
                          as_index=False)["shares"].sum()
    panel = panel.merge(cusip_map[["cusip", "ticker"]],
                        on="cusip", how="left")
    panel = panel.sort_values(["period", "ticker", "manager_cik"])
    panel.to_csv(os.path.join(BASE, "holdings_panel.csv"), index=False)
    print(f"holdings panel: {len(panel)} rows, "
          f"{panel['period'].nunique()} periods, "
          f"{panel['ticker'].nunique()} tickers", flush=True)
    return panel


def main():
    files = inventory()
    print(f"inventory: {len(files)} zips", flush=True)
    zips = download_all(files)
    winners = build_winners(zips)
    stage_pairs(zips, winners)
    pairs = combined_pairs()
    pairs.to_csv(os.path.join(BASE, "cusip_name_pairs.csv"), index=False)
    cusip_map = build_map(pairs)
    stage_holdings(zips, winners, cusip_map)
    print("done", flush=True)


if __name__ == "__main__":
    main()
