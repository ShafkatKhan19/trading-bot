# Round 10 pre-registration — profitability, investment, payout, insider buying (H36–H39)

Written and committed BEFORE any round-10 code runs or results are
seen (2026-10-20, under the owner's standing autonomous-research
mandate). Previous rounds: 37 strategies tested, 0 beat their
benchmark. Cumulative test count after this round: 41. Bonferroni
one-sided t-bar ≈ 3.24 (exact value computed in code).

All four hypotheses: universe L, monthly ranking, equal weight,
signals at month-end close, fills at next open, 5 bps per side,
benchmark SPY buy & hold, in-sample through 2023-07-06 context only,
verdicts OOS only, EDGAR point-in-time discipline exactly as rounds
8–9 (FY 10-K frames, earliest filed date per period, usable only
after `filed`). PASS requires ALL of: OOS excess return > 0,
one-sided t ≥ the Bonferroni bar, OOS Sharpe > SPY Sharpe. FAIL is
final. A PASS earns only a paper forward test.

- **H36 — gross profitability (Novy-Marx).** New EDGAR fetch with
  tag fallback chains (revenue: SalesRevenueNet →
  RevenueFromContractWithCustomerExcludingAssessedTax → Revenues;
  COGS: CostOfGoodsAndServicesSold → CostOfRevenue). Gross profit =
  revenue − COGS; rank by gross profit ÷ Assets (Assets from the
  round-9 v2 panel), highest first, top 26. Names with no usable
  revenue/COGS tags are ineligible; coverage reported.
- **H37 — low asset growth (Fama–French investment factor).** Round-9
  v2 panel only. Rank by FY Assets ÷ prior-FY Assets − 1 (latest
  filed pair at each month-end), LOWEST growth first, top 26.
- **H38 — total shareholder yield.** Dividends: new EDGAR fetch,
  FY PaymentsOfDividendsCommonStock (fallback
  DividendsCommonStockPaid). Yield = (FY dividends + buyback dollars)
  ÷ market cap, where buyback dollars = max(0, shares_year_ago −
  shares_now) × month-end close (share counts from the round-8
  panel, H34's matching). Highest first, top 26.
- **H39 — insider net buying (legal, public Form 4 filings).** New
  build from SEC submissions data: for each universe-L CIK, all
  Form 4 filings 2015→2026; parse each filing's transactions, keep
  transaction code P (open-market purchase) and S (open-market sale)
  with shares × price; a filing is usable on its SEC acceptance date.
  Monthly signal = trailing-6-month (net bought shares × price) ÷
  market cap, using only filings accepted ≤ month-end. Rank highest
  first, top 26; names with no filings in the window score 0 and are
  eligible only if fewer than 26 names have positive scores (in that
  case fill by market cap, documented). Coverage reported: filings
  parsed, names with any P/S activity.
