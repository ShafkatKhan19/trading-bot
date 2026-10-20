# Round 9 pre-registration — fundamentals, second wave (H32–H35)

Written and committed BEFORE any round-9 code runs or results are seen
(2026-10-20, under the owner's standing autonomous-research mandate).
Previous rounds: 33 strategies tested, 0 beat their benchmark. Round 8's
earnings-yield and value books posted the best Sharpe ratios of any
strategy so far but t-stats far below the bar. Cumulative test count
after this round: 37. Bonferroni one-sided t-bar ≈ 3.20 (exact in code).

## Hypotheses

- **H32 — small-cap earnings yield.** Universe S (S&P SmallCap 600,
  round-5 Yahoo bars + sectors file), EDGAR point-in-time panel built
  exactly as round 8 (FY 10-K frames, earliest filed date per period,
  usable only after `filed`). Monthly, rank by FY NetIncomeLoss ÷
  market cap (month-end close × latest filed shares), top 60 (≈10%),
  equal weight. Benchmark: IWM. Round-5 adjclose conventions.
- **H33 — small-cap book-to-market.** Same build and mechanics; rank
  by StockholdersEquity ÷ market cap, top 60. Benchmark: IWM.
- **H34 — buyback yield, universe L.** Round-8 panel only (no new
  fetch). At each month-end use the latest filed FY shares and the FY
  shares filed a year earlier; rank by −(shares_now ÷ shares_year_ago
  − 1) (biggest share-count reduction first), top 26, equal weight.
  Monthly ranking, next-open fills. Benchmark: SPY.
- **H35 — low cash-flow accruals, universe L.** New EDGAR fetch for two
  additional FY tags (Assets, NetCashProvidedByUsedInOperating-
  Activities), same point-in-time build. Accruals = (NetIncomeLoss −
  operating cash flow) ÷ Assets; rank lowest first, top 26, equal
  weight. Monthly, next-open fills. Benchmark: SPY.

## Shared rules

- Costs 5 bps per side. In-sample through 2023-07-06 context only;
  verdicts OOS (2023-07-07 onward) only.
- Eligibility mirrors round 8 (positive equity where the rule uses
  it, non-missing inputs, ≥1 filed FY report); coverage reported.
- PASS requires ALL of: OOS excess return vs benchmark > 0, one-sided
  t ≥ the Bonferroni bar, OOS Sharpe > benchmark Sharpe. FAIL is
  final. A PASS earns only a paper forward test.
- Known data caveats carried from round 8: market cap uses adjusted
  closes × as-filed shares (split-window distortion disclosed);
  small-cap EDGAR coverage will be thinner than large-cap — the
  coverage count is part of the verdict's context, and thin coverage
  is reported, never patched over.
