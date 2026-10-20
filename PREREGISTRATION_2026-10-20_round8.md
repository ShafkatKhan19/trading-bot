# Round 8 pre-registration — fundamental factors from SEC filings (H28–H31)

Written and committed BEFORE any round-8 code runs or results are seen
(2026-10-20). Previous rounds: 29 strategies tested, 0 beat their
benchmark; the price-based families (momentum, reversal, low-vol,
calendar, technical) are exhausted or closed. This round opens a new
data axis: company fundamentals. Cumulative test count after this
round: 33. Bonferroni one-sided t-bar ≈ 3.17 (exact value in code).

## Data — SEC EDGAR, strictly point-in-time

- Source: SEC EDGAR XBRL company-concept API (free, public filings).
  Ticker→CIK map from SEC's published company_tickers.json.
- Facts used, fiscal-year (10-K) frames only: NetIncomeLoss,
  StockholdersEquity, EntityCommonStockSharesOutstanding
  (or WeightedAverageNumberOfSharesOutstandingBasic if the cover tag
  is missing for a name).
- **Point-in-time rule:** a value is usable only on/after its SEC
  `filed` date. Rankings at each month-end use the latest FY value
  whose filing date is ≤ that month-end. No restated-future data, no
  fiscal-period-end peeking. This is the strongest honesty guarantee
  in any round so far.
- Universe: L (87 large caps). Eligibility at a ranking date:
  positive stockholders' equity, non-missing FY net income, ≥1 filed
  annual report. Coverage count is reported with the results.
- Market cap at ranking date = latest close × latest filed shares.

## Shared rules

- Monthly ranking, first session of the month, hold top 26 (≈30%)
  equal weight, signals at month-end close, fills at next open,
  5 bps per side — the rounds 1–4 universe-L conventions.
- In-sample through 2023-07-06 context only; verdicts OOS only.
- Benchmark: SPY buy & hold.
- Random-entry controls (round-3 method) computed for all four
  hypotheses and reported; PASS requires the three standing bars:
  OOS excess return > 0, one-sided t ≥ Bonferroni bar, OOS Sharpe >
  SPY Sharpe. FAIL is final. A PASS earns only a paper forward test.

## Hypotheses

- **H28 — Value (book-to-market).** Rank by StockholdersEquity ÷
  market cap, highest first.
- **H29 — Earnings yield.** Rank by FY NetIncomeLoss ÷ market cap,
  highest first.
- **H30 — Quality (ROE).** Rank by FY NetIncomeLoss ÷
  StockholdersEquity, highest first.
- **H31 — Value + quality blend.** Average of the H28 rank and the
  H30 rank; hold the top 26 by blended rank.
