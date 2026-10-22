# Results — pre-registered round 13: short positioning (FINRA) and institutional holdings (13F) (2026-10-21)

Pre-registration: `PREREGISTRATION_2026-10-21_round13.md` (committed
`bf28dcb` before any round-13 code or result). Code:
`round13_research.py`; data builds: `fetch_shortinterest.py`,
`fetch_13f.py`. 5 bps per side everywhere; in-sample
2016-01-01 → 2023-07-06 is context only; verdicts on OOS
2023-07-07 onward. Fifty-one strategies have now been tested
all-time, so the Bonferroni OOS t bar is **3.32** as registered
(the house t formula at the realised OOS daily df prints 3.31;
no verdict is within reach of either number). Full output:
`data/round13_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +20.6% | 1.32 | — | 18.8% | — |
| H47 Short-interest level (FINRA) | +23.2% | 1.73 | +0.42 | 16.4% | **FAIL** (t) |
| H48 Short-interest change (FINRA) | +16.1% | 1.24 | −0.75 | 17.2% | **FAIL** (excess, t, Sharpe) |
| H49 13F institutional net breadth | +21.6% | 1.54 | +0.15 | 17.4% | **FAIL** (t) |

PASS required all three: OOS annualised excess vs SPY > 0,
excess t ≥ bar, and OOS Sharpe above SPY's.

**H47** is a near-miss of the now-familiar shape: the
least-shorted 26 names beat SPY on return (+23.2% vs +20.6%),
on Sharpe (1.73 vs 1.32) and on drawdown (16.4% vs 18.8%), but
the daily excess is far too noisy to prove anything — t +0.42
against a 3.31 bar. The book is a low-turnover mega-cap quality
tilt (299 trades over 73 invested monthly rebalances), and in
this OOS window that tilt happened to pay; at the programme's
evidentiary standard it is indistinguishable from luck. It
joins H29 and H44 on the near-miss shelf and is retired as
registered. In-sample context: H47 +8.4% (Sharpe 0.58).

**H48** fails everything: the largest-decrease-in-short-interest
book returned +16.1%/yr (−4.6%/yr excess), Sharpe 1.24 below
SPY's 1.32, t −0.75, on heavy churn (1,246 trades — the change
signal reshuffles the book almost every month). Covering flow,
as registered, is not a return signal at this horizon.
In-sample context: H48 +8.5% (Sharpe 0.57).

**H49** is the round's second near-miss: consensus institutional
buying beat SPY on return (+21.6% vs +20.6%) and Sharpe (1.54
vs 1.32) with 43 quarterly rebalances and a median 4,732
managers changing positions per quarter behind each breadth
reading — and its excess t is +0.15. A one-percentage-point
annual edge spread over quarterly rebalances carries almost no
statistical weight against daily noise; the 13F consensus axis,
tested exactly as registered, does not clear the bar and is
retired. In-sample context: H49 +14.7% (Sharpe 0.87).

**Tally: 51 strategies tested all-time, 0 pass.**

## Data routes and coverage (as registered, with disclosures)

**FINRA short interest (H47/H48).** Route used: FINRA's public
Query API, consolidated short interest dataset (no key) —
`fetch_shortinterest.py`. All 87 Universe-L symbols returned
history: 18,357 biweekly snapshots, settlements
2017-12-29 → 2026-09-15 (18,270 usable after the
publication-lag filter). The API's consolidated history begins
with the 2017-12-29 settlement, so the pre-registration's
coverage contingency triggered: the SI evaluation window
starts January 2018 and both books hold cash through 2017
(first invested rebalance 2018-01-31). Publication rule as
implemented: a snapshot is usable from the 7th trading session
strictly after its settlement date — the registered "7th
business day" rendered on the trading calendar, which is
conservative around market holidays. The registered
expectation holds in the data: in 81% of name-months the
latest published snapshot at a month-end rebalance is the
same month's mid-month snapshot; in the rest, settlement or
publication shifted over a weekend/holiday and the prior
snapshot is used. SI % = short shares ÷ the latest as-filed
shares outstanding public by the rebalance date (cached EDGAR
fundamentals panel, `filed_sh`, the registered convention).
That panel carries no as-filed share count for XOM, KO, ABT,
GD, MDLZ or F, so those six names are never SI-eligible;
eligible names per invested month: min 77, median 79 of 87 —
always far above the 26 the books need. H48's change is
computed on that same as-of share count for both snapshots
(change in short shares scaled by the latest as-filed shares),
as written in the research script before the run. Rebalance
count: the house monthly engine (rounds 3/8 mechanics) signals
on month-end trading sessions — 90 signal dates in the window,
73 of them invested (Jan 2018 onward).

**13F (H49).** Route used: the SEC's quarterly "Form 13F Data
Sets" bulk TSV archives on sec.gov (45 quarterly files,
2015Q3–2026Q2 filing windows) — no per-filing crawling.
Filings were resolved exactly per the registration: for each
(manager CIK, period of report), the latest 13F-HR or
13F-HR/A with filing date ≤ period end + 50 days (265,251
winner filings). The derived holdings panel
(`data/13f/holdings_panel.csv`) holds 7,720,825
(period, manager, ticker) share sums over 45 canonical
quarter-end periods, 2015-06-30 → 2026-06-30, with 3,139 →
7,414 distinct managers per period. Coverage spot checks:
recent-quarter reported shares run ≈ 0.65–0.79 of shares
outstanding (AAPL 0.65, BAC 0.75, GE 0.76, BLK 0.79,
AVGO 0.79) — the expected institutional-ownership range.

**Ticker ↔ CUSIP mapping** was resolved from the filings
themselves: share-weighted (CUSIP, issuer-name) pairs over
winner filings' common-stock rows. (Pairs are weighted by
reported shares, not VALUE: in the as-filed data VALUE units
are mixed across filers — some report dollars, most
thousands — while share counts are unit-consistent.) A CUSIP
maps to a ticker only if its issuer name token-matches the
ticker's expected name (stems include the dominant filer
abbreviations observed in the data, e.g. "BANK AMER CORP",
"CISCO SYS INC", "AUTOMATIC DATA PROCESSING IN"), the matched
names are ≥ 50% of the CUSIP's reported shares, its modal
TITLEOFCLASS is a common-stock title with no fund markers,
any registered share-class hint holds (GOOGL/V/MA/CMCSA
"CL A", NKE/UPS "CL B"), and matched shares are ≥ 5% of the
ticker's leading CUSIP. Result: 90 CUSIPs covering all 87
tickers — one each except GE (369604103 pre-split and
369604301 after the 2021 reverse split), AVGO (Y09827109
Broadcom Ltd era and 11135F101), and BLK (09247X101 plus
09290D101, which carries ≈ 15% of BlackRock's reported shares
under the same issuer name and "COM" title — unioned and
counted once per manager after the per-ticker share sum).

**13F coverage notes.** (a) AVGO is absent from the panel's
first two periods and GOOGL from the first (2015-06-30) —
the pre-acquisition Broadcom Corp era is outside the map —
so the first breadth reading (2015-12-31, feeding the
in-sample March-2016 rebalance) counts AVGO's Q4 holders as
new; all 87 names are present from 2015-12-31 and every OOS
reading is unaffected. (b) The as-published dataset shows a
uniform ≈ 15% dip in reported shares at period 2026-03-31
across names (late filings and amendments not yet in the
snapshot); it feeds only the June-2026 rebalance, is a sign
count's input rather than a level, and is disclosed rather
than adjusted. (c) Breadth uses as-filed reported shares per
the registration, so in a split quarter the splitting name
mechanically reads as mass decreases (GE 2021 reverse split,
NVDA/AVGO splits); the artifact costs that name that
quarter's ranking instead of fabricating breadth elsewhere.

## What this closes

Both genuinely-new data axes named in the frontier decision
are now tested, once each, exactly as registered: regulated
short positioning (level and change) and institutional
holdings breadth. Neither produced a provable edge. The
standing programme result after thirteen rounds: 51
mechanical strategies tested, 0 pass; the two live paper
forward tests (H1, H10) remain the other evidentiary track.
