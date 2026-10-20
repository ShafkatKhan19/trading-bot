# Results — pre-registered round 10: fundamentals, third wave + insider buying (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round10.md` (committed
before any round-10 code or result). Code: `round10_research.py`;
data builds: `fetch_fundamentals_gp.py` (revenue/COGS panel),
`fetch_fundamentals_div.py` (dividends panel), `fetch_insider.py`
(Form 4 panel). Universe L, month-end signals, fills at next open,
top 26 equal weight, 5 bps per side, benchmark SPY (rounds 1–4/8/9
conventions). In-sample 2016-01-01 → 2023-07-06 is context only;
verdicts on OOS 2023-07-07 onward. Forty-one strategies have now
been tested, so the Bonferroni OOS t bar is **3.25**. Full output:
`data/round10_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +20.6% | 1.32 | — | 18.8% | — |
| H36 Gross profitability | +14.7% | 1.17 | −1.01 | 14.3% | **FAIL** (excess, t, Sharpe) |
| H37 Low asset growth | +18.3% | 1.46 | −0.38 | 13.1% | **FAIL** (excess, t) |
| H38 Shareholder yield | +15.5% | 1.22 | −0.81 | 15.5% | **FAIL** (excess, t, Sharpe) |
| H39 Insider net buying | +15.3% | 1.16 | −1.30 | 17.2% | **FAIL** (excess, t, Sharpe) |

PASS required all three: OOS annualised excess vs SPY > 0, excess
t ≥ 3.25, and OOS Sharpe above SPY's. None of the four passes; all
four have *negative* OOS excess. In-sample context: H36 +18.4%
(Sharpe 1.04), H37 +17.6% (1.00), H38 +14.3% (0.79), H39 +15.4%
(0.85). H37 is the round's only leg-winner: Sharpe 1.46 > SPY 1.32
and the lowest drawdown (13.1%), but it still returned 2.4%/yr
*less* than SPY out of sample, so it fails on excess and t. Round
8's near-miss pattern (H28/H29 beating SPY on CAGR and Sharpe, dead
only on the t bar) did not repeat: this wave never got ahead of the
benchmark in the first place.

**Tally: 41 strategies tested all-time, 0 pass.**

## Point-in-time guarantee

Fundamentals: identical discipline to rounds 8/9 — every value is
an SEC filing fact usable only on or after its `filed` date,
earliest filing kept per fiscal period. H36's snapshot uses each
input's own latest filed FY with `filed` ≤ month-end (the pre-reg's
default reading; gross profit pairs the GP panel's revenue/COGS,
whose `filed` is the later of the two source filings, with Assets
from `panel_l_v2.csv` on their own `filed` dates). Insider data:
a filing is usable only from its SEC acceptance datetime — public
Form 4 data only, no non-public information of any kind. H39's
trailing-6-month window sums filings by **exact acceptance date**
≤ month-end (documented refinement over calendar-month buckets:
identical information set, no up-to-3-day month-boundary leak).

## Data and coverage

- **GP panel** (`data/fundamentals/panel_gp.csv`): 1,466 fiscal-year
  rows, **773 complete** (revenue and COGS), covering **58 of 87**
  universe-L tickers; 57 reach back to a fiscal year ending
  ≤ 2017-12-31. Revenue tag usage (per fiscal period): Revenues
  663 rows, SalesRevenueNet 418, RevenueFromContractWithCustomer-
  ExcludingAssessedTax 382. COGS: CostOfGoodsAndServicesSold 491,
  CostOfRevenue 285. No revenue under any chain tag: KO, GS, MDLZ.
  No COGS under either tag: 29 tickers — financials, utilities and
  services names that do not report a cost-of-revenue line,
  including XOM and BLK (verified: no COGS concept filed under the
  registered tags at their operating CIKs). Those names are simply
  ineligible for H36; the engine saw a median of 57 eligible names
  per month-end (min 34 in the earliest months).
- **Dividend panel** (`data/fundamentals/panel_div.csv`): 622
  fiscal-year rows, **39 of 87** tickers, all via the primary tag
  PaymentsOfDividendsCommonStock (the DividendsCommonStockPaid
  fallback never fired); 36 reach FY ≤ 2017-12-31. Per the
  pre-registration, names with no dividend row are encoded as
  dividends = 0 in H38, not dropped. One registered-tag limit: JNJ
  returns 404 for the primary tag at its correct CIK (200406) —
  EDGAR holds no such frame for it — so JNJ is encoded as a
  non-payer here despite paying dividends in reality. No
  tag-shopping was done to work around this; it is a data-build
  limit of the registered tag chain, disclosed here.
- **Insider panel** (`data/insider/filing_net.csv`,
  `data/insider/monthly_net.csv`): **90,906 Form 4 filings parsed**
  of 90,910 listed across all 87 CIKs (2015-01-01 onward); **4
  parse failures** (all V, logged in `parse_failures.csv`); a full
  per-ticker reconciliation (list vs parsed + failed) accounts for
  every filing. 22,778 filings contain open-market purchase/sale
  (codes P/S) transactions; **all 87 tickers** have some P/S
  activity. The monthly aggregation has 6,426 ticker-months. Raw
  XML is cached locally under `data/insider/xml/` and not
  committed (size); the per-CIK filing lists are committed under
  `data/insider/filing_lists/`.
- **H39's fill rule dominated the book.** Names with a positive
  trailing-6-month net-buy score per month-end: median **5**, max
  **11**, min 0 — never the 26 needed. The pre-registered
  market-cap fill therefore fired in **all 90 of 90 months** (max
  fill 26 slots). As registered, H39 mostly tested "a handful of
  insider-buying names plus the largest caps by market cap", and
  even that blend lagged SPY by 5.3%/yr out of sample. The sparsity
  is a fact about large-cap insider open-market buying (most Form
  4 volume is option exercises and grants, codes excluded by the
  registration), reported here rather than tuned around.

## Build corrections and quirks (data-build fixes, not rule changes)

1. **GP fallback applied per fiscal period, not per ticker.** The
   literal first reading took the whole ticker history from the
   first chain tag yielding any FY rows. Filers switched revenue
   tags at ASC 606 adoption (2018–19), which stranded post-2018
   periods and left only 387 complete rows. Applying the registered
   chain per period (same tags, same order) yields the registered
…[truncated 3049 chars]