# Results — pre-registered round 8: fundamental factors from SEC filings (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round8.md` (committed
before any round-8 code or result). Code: `round8_research.py`,
data build: `fetch_fundamentals.py`. Costs 5 bps per side. Monthly
ranking on month-end closes, fills at next open, top 26 equal
weight — the rounds 1–4 universe-L conventions. In-sample
2016-01-01 → 2023-07-06 is context only; verdicts on OOS
2023-07-07 onward. Thirty-three strategies have now been tested,
so the Bonferroni OOS t bar is **3.18**. Full output:
`data/round8_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Control t | Verdict |
|---|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +20.6% | 1.32 | — | 18.8% | — | — |
| H28 Value (book-to-market) | +21.5% | 1.45 | +0.11 | 17.7% | +1.68 | **FAIL** (t) |
| H29 Earnings yield | +23.7% | 1.52 | +0.43 | 17.1% | +1.89 | **FAIL** (t) |
| H30 Quality (ROE) | +13.6% | 1.02 | -1.49 | 16.9% | +4.40 | **FAIL** (excess, t, Sharpe) |
| H31 Value + quality blend | +20.3% | 1.36 | -0.07 | 17.8% | +1.86 | **FAIL** (excess, t) |

PASS required all three: OOS annualised excess vs SPY > 0, excess
t ≥ 3.18, and OOS Sharpe above SPY's. None of the four passes.

## Point-in-time guarantee

This round's data carries the strongest honesty guarantee so far.
Every fundamental value is an SEC filing fact usable only on or
after its `filed` date; where amendments or later filings restated
a fiscal period, only the EARLIEST filing was kept, so no
future-restated number ever enters a ranking. A fiscal-year row
became usable only once all three of its facts (net income,
equity, shares) were public. Rankings at each month-end therefore
use exactly what an investor could have known that day.

## Data and coverage

- Panel: 1,479 fiscal-year rows across the 87 universe-L names,
  1,173 of them complete (all three facts). **74 of 87 tickers**
  have at least one usable FY row; **68 of 87** reach back to a
  fiscal year ending ≤ 2017-12-31 (i.e. filings from the 2016–2018
  era). Complete rows per usable ticker: median 18, range 2–20.
- Eligibility in the engine (latest complete filed row, positive
  equity): 60–68 names at every month-end from January 2016 on —
  the top-26 books were fully invested for all 129 months, never
  cash-dragged by missing data.
- Thirteen names are never eligible, all for EDGAR tagging
  reasons, none for performance reasons: XOM, KO, ABT, GD and
  MDLZ return no usable FY facts under the registered tags at
  their CIKs; CAT and SPG have no `NetIncomeLoss` /
  `StockholdersEquity` concept at all (404); F's equity and
  weighted-average-share concepts are empty and JNJ's, PG's, T's
  and VZ's equity concepts carry no usable 10-K FY frames; V's
  `NetIncomeLoss` concept is empty. Sparse but usable: AVGO and
  BLK (2 complete rows each — their CIK concept history starts
  late), EXC (4), GOOGL (4), TGT (6), MA (6), EOG (7), SO (3).
- One filer quirk the construction had to defend against: some
  10-K XBRL instances (e.g. Southern Company) carry
  quarterly-duration `NetIncomeLoss` facts stamped fp="FY". The
  registered 300–400-day span requirement excludes them, which is
  why SO contributes only 3 usable years.

## Notes

- **H28 and H29 are the closest fundamental results — ahead on
  return and Sharpe, nowhere on evidence.** Value (+21.5%/yr,
  Sharpe 1.45) and earnings yield (+23.7%/yr, Sharpe 1.52) both
  beat SPY buy & hold (+20.6%/yr, 1.32) on the two headline
  numbers, with slightly shallower drawdowns. But the excess
  t-statistics are +0.11 and +0.43 against a 3.18 bar: the daily
  excess-return series are far too noisy for the gaps to be
  distinguishable from luck. These books also turn over very
  slowly (H28 recorded only 53 exits in 10.75 years), so the OOS
  window contains few independent bets. Encouraging is not
  evidence; both FAIL on the registered bar and are final.
- **H30 (ROE) fails everything, and its control number is an
  artifact — read this before the table.** Quality earned
  +17.9%/yr in-sample and +13.6%/yr OOS against SPY's +20.6%/yr
  (excess t −1.49, Sharpe 1.02 < 1.32). The control t of +4.40
  does NOT contradict that: the round-3 control holds random
  names for ~1 month, while these books hold their picks for
  months to years, so the control's per-trade comparison
  (+43%/trade real vs +1%/trade random for H30; +159%/trade for
  the near-static H28) measures holding length, not picking
  skill. The controls are reported exactly as pre-registered,
  but for low-turnover books they are not horizon-matched and
  are not evidence of an edge. Verdicts rest on the three
  registered bars, which no hypothesis meets.
- **H31 (blend) lands between its parents and inherits the
  failure:** +20.3%/yr is a hair under SPY (excess −0.3%/yr),
  Sharpe 1.36 is a hair over, t −0.07 is nothing. Averaging a
  strong ranking with a weak one produced a mediocre one.
- **Adjustment caveat (registered definition, disclosed not
  patched):** market cap is the pre-registered latest close ×
  latest filed shares. The price panel is split- and
  dividend-adjusted while filed share counts are as-reported,
  so a name's market cap is distorted between a split and its
  next 10-K (AAPL 2020, NVDA 2021/2024, AVGO 2024, WMT 2024)
  and drifts with cumulative dividend adjustment. H30's ROE
  uses no prices or shares and is unaffected.

## Code fixes during the run

One, made while building the data and before any backtest ran:
the dei cover shares fact's `end` is the cover date (days after
the fiscal year-end), so shares initially joined on period end
and almost never matched. Shares now join their fiscal-year row
through the filing that reported them (matched on `filed`). No
strategy rule was changed, and no code changed after results
were seen. The 6.7 MB raw EDGAR JSON cache (267 files) was left
uncommitted — it is regenerable with `fetch_fundamentals.py`.

## Tally

Thirty-three strategies tested honestly across eight rounds;
none has beaten its benchmark out-of-sample on the registered
bars. Per the pre-registration, none of H28–H31 is re-tuned or
re-tested on this data. The fundamental axis produced the
round's closest headline numbers (H28/H29) but, like every
family before it, no result that survives the evidence bar —
only a forward test could say more, and none has earned one.
