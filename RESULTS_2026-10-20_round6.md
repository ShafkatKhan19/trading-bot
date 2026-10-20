# Results — pre-registered round 6: overnight, pairs, sectors, large-cap low-vol (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round6.md` (committed
before any round-6 code or result). Code: `round6_research.py`.
Costs 5 bps per side everywhere. Signals at close, fills at next
open where open prices exist (SPY / universe L); the small-cap leg
(H22) follows the round-5 Yahoo adjclose convention. In-sample
2016-01-01 → 2023-07-06 is context only; verdicts on OOS
2023-07-07 onward. Twenty-five strategies have now been tested, so
the Bonferroni OOS t bar is **3.10**. Full output:
`data/round6_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark, L panel) | +20.6% | 1.32 | — | 18.8% | — |
| SPY buy & hold (benchmark, SPY_1Day.csv) | +19.0% | 1.23 | — | 19.0% | — |
| IWM buy & hold (benchmark) | +14.1% | 0.74 | — | 27.5% | — |
| H20 overnight-only SPY | -11.4% | -1.24 | -4.23 | 33.5% | **FAIL** (excess, t, Sharpe) |
| H21 pairs, universe L | +1.0% | 0.30 | -2.24 | 5.7% | **FAIL** (excess, t, Sharpe) |
| H22 small-cap sector momentum | +4.4% | 0.31 | -1.72 | 26.4% | **FAIL** (excess, t, Sharpe) |
| H23 large-cap low volatility | +9.6% | 0.88 | -1.29 | 11.7% | **FAIL** (excess, t, Sharpe) |

PASS required all three: OOS annualised excess vs the hypothesis's
benchmark > 0, excess t ≥ 3.10, and OOS Sharpe above the
benchmark's. None of the four clears any bar. (The two SPY benchmark
rows differ only in dataset: the Alpaca L panel runs to 2026-09-25,
SPY_1Day.csv to 2026-09-09. H20 is graded against the CSV row, H21
and H23 against the panel row, H22 against IWM.)

## Notes

- **H20 — the overnight claim is real gross, dead net.** Gross of
  costs, holding SPY only overnight earned +13.9%/yr OOS with
  Sharpe 1.43 (the intraday-only complement earned +4.4%/yr,
  Sharpe 0.40) — most of SPY's OOS return really did accrue
  overnight. But the registered rule trades *every* session, and
  5 bps per side × 2 sides × ~252 round trips a year is a ~22%/yr
  cost drag. Net: −11.4%/yr, excess t −4.23. The effect is smaller
  than the cost of harvesting it daily. (The "100% exposure" the
  stats routine reports for H20 counts sessions with a nonzero
  return — the book is flat every intraday session by construction.)
- **H21 — pairs behaved like a low-vol parking lot, not an edge.**
  The in-sample correlation screen picked the expected names
  (JPM/BAC r 0.91, V/MA r 0.91, the bank and energy clusters; full
  list in the JSON). 1,102 round trips over the window, max 17
  concurrent, max drawdown just 5.7% — and +1.0%/yr for the
  trouble, excess t −2.24 against SPY. Market-neutral and
  low-risk, simply not profitable enough after 5 bps per side per
  leg to matter against a bull-market benchmark.
- **H22 — sector rotation joins name rotation in the bin.**
  In-sample +17.8%/yr collapsed to +4.4% OOS (excess −9.7%,
  t −1.72), the same in-sample → out-of-sample signature as rounds
  3 and 5. Holding the top-3 momentum sectors (~138 names on
  average) was diversification without an edge. The round-5
  survivorship caveat applies to this leg unchanged.
- **H23 — low-vol did its one job and nothing else.** The smallest
  drawdown of any round-6 strategy (11.7% vs SPY's 18.8%) and a
  respectable +9.6%/yr, but that is −11.0%/yr of excess with
  t −1.29 and Sharpe 0.88 vs 1.32. Between H18 (small-cap) and
  H23 (large-cap), the low-volatility anomaly has now failed on
  both universes: it buys calm, and charges full price for it.

## Data notes

- H20: `data/SPY_1Day.csv`, 2,684 sessions, 2016-01-06 →
  2026-09-09. Equity marks each session after the open sale; the
  next night's buy cost is charged inside that night's multiplier.
- H21/H23: universe L bars (87 names + SPY, Alpaca-adjusted), panel
  2016-01-04 → 2026-09-25. H21 pairs were screened on in-sample
  (≤ 2023-07-06) return correlations only, per the registration;
  the z-score uses a trailing 60-session window; hard exit once 20
  sessions have elapsed since the fill session.
- H22: round-5 small-cap Yahoo cache (602 names). GICS sectors were
  absent from `data/smallcap/tickers.csv`, so the constituent table
  was refetched and the mapping saved to `data/smallcap/sectors.csv`
  (603 tickers, all 11 GICS sectors). Sector momentum is the
  equal-weight average of member names' H15-formation 6-1 momentum
  over eligible names.

## Code fix during the run

One bug, fixed before any verdict was produced: H20's overnight
return initially divided two label-indexed Series and aligned on
dates instead of positions. Changed to positional `.values`
arithmetic and re-run. No rule was changed.

## Tally

Twenty-five strategies tested honestly across six rounds; none has
beaten its benchmark out-of-sample on the registered bars. Per the
pre-registration, none of H20–H23 is re-tuned or re-tested on this
data.
