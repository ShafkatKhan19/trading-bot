# Results — pre-registered round 7: index dip-buying, ETF rotation, weekly reversal, vol-scaled momentum (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round7.md` (committed
before any round-7 code or result). Code: `round7_research.py`.
Costs 5 bps per side everywhere. Signals at close, fills at next
open where open prices exist (SPY CSV / universe L); the Yahoo leg
(H25) follows the round-5 adjclose convention. In-sample
2016-01-01 → 2023-07-06 is context only; verdicts on OOS
2023-07-07 onward. Twenty-nine strategies have now been tested, so
the Bonferroni OOS t bar is **3.14**. Full output:
`data/round7_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark, L panel) | +20.6% | 1.32 | — | 18.8% | — |
| SPY buy & hold (benchmark, SPY_1Day.csv) | +19.0% | 1.23 | — | 19.0% | — |
| SPY buy & hold (benchmark, Yahoo adjclose) | +20.0% | 1.29 | — | 18.8% | — |
| H24 SPY dip-buying, RSI(2) | +6.2% | 0.70 | -1.88 | 8.5% | **FAIL** (excess, t, Sharpe) |
| H25 ETF tactical rotation | +22.2% | 1.08 | +0.27 | 21.6% | **FAIL** (t, Sharpe) |
| H26 large-cap weekly reversal | +15.8% | 0.93 | -0.58 | 17.4% | **FAIL** (excess, t, Sharpe) |
| H27 vol-scaled momentum | +12.6% | 1.13 | -1.45 | 13.1% | **FAIL** (excess, t, Sharpe) |

PASS required all three: OOS annualised excess vs the hypothesis's
benchmark > 0, excess t ≥ 3.14, and OOS Sharpe above the
benchmark's. None of the four passes. (The three SPY benchmark rows
differ only in dataset: the Alpaca L panel runs to 2026-09-25,
SPY_1Day.csv to 2026-09-09, the Yahoo cache to 2026-10-19. H24 is
graded against the CSV row, H26/H27 against the panel row, H25
against the Yahoo row.)

## Notes

- **H24 — dip-buying the index is calm and pointless.** 127 round
  trips over the full window; the book was invested only ~24% of
  OOS sessions and its max drawdown was just 8.5% — but it earned
  +6.2%/yr while the index it sat out earned +19.0%/yr, and the
  in-sample leg was slightly negative (−0.6%/yr). RSI(2) entries
  were Wilder-smoothed, as Connors specifies. Between H1
  (stock-level) and H24 (index-level), the RSI(2) pullback family
  has now failed at both levels of the market.
- **H25 — the round's only positive excess, and still not an
  edge.** Rotation beat SPY buy & hold by +2.3%/yr OOS, spending
  42% of months in QQQ, 28% in GLD, 17% in IWM, just 4% in SPY
  itself, across 130 monthly periods and 49 switches. But the
  excess t is +0.27 against a 3.14 bar — statistically
  indistinguishable from luck — and the Sharpe (1.08) is *below*
  SPY's (1.29) with a deeper drawdown (21.6% vs 18.8%): the extra
  return was bought with disproportionate extra risk. FAIL on two
  of the three bars.
- **H26 — weekly reversal drowns in its own turnover.** The
  published frequency looked respectable in-sample (+15.5%/yr) and
  stayed positive OOS (+15.8%/yr), but SPY did +20.6%/yr and the
  excess t is −0.58. 558 weekly rebalances produced 7,287 position
  exits; even at 5 bps per side that churn is a heavy, permanent
  tax. Reversal has now failed monthly in small caps (H16 — still
  the closest any reversal test has come) and weekly in large caps.
- **H27 — risk-scaling momentum cuts return, not risk-adjusted
  pain, and closes the momentum family.** The scale did its
  mechanical job (mean invested fraction 0.67, range 0.50–1.26,
  above 1.0 in only 7% of months; max drawdown 13.1% vs plain H10's
  14.4% in round 3) — but OOS CAGR fell from H10's +19.6%/yr to
  +12.6%/yr while Sharpe *also* slipped (1.13 vs H10's 1.17 and
  SPY's 1.32). The Barroso–Santa-Clara claim does not survive this
  universe at these costs. Per the pre-registration's
  family-closing rule, **the momentum family is now closed**: no
  further momentum variants will be tested. H10's live paper
  forward test is unaffected — it was pre-registered separately
  and runs to its 2027-04-17 grade.

## Data notes

- H24: `data/SPY_1Day.csv`, 2,684 sessions, 2016-01-06 →
  2026-09-09. One position at a time, full capital; exit at the
  next open after a close with RSI(2) > 70 or once 5 sessions have
  been held, whichever first.
- H25: Yahoo total-return (adjclose) cache fetched 2026-10-20 by
  `fetch_etf_bars.py` into `data/etf/bars/` — SPY, QQQ, IWM, TLT,
  GLD, 2,864 sessions each, 2015-06-01 → 2026-10-19, no gaps.
  Evaluation from 2016-01-01 per the round-5 convention; 6-1
  formation identical to H15 (month-end closes, skip the most
  recent month); a month is held in cash only when the best 6-1
  momentum is non-positive (3% of months, all pre-OOS).
- H26/H27: universe L bars (87 names + SPY, Alpaca-adjusted),
  panel 2016-01-04 → 2026-09-25. H26 signals on the last session
  of each ISO week, formation = prior 5 sessions close-to-close,
  Monday (next-session) open fills. H27 reuses round 3's
  `h10_choose` verbatim for selection; the scale is computed at
  each rebalance from the selected basket's equal-weight daily
  returns over the trailing 126 sessions and applied literally,
  including above 1.0 (the engine therefore carries no cash cap on
  buys; a negative cash balance is the margin the formula implies,
  exercised in 7% of months, max scale 1.26). A documented
  fallback (scale 1.0 if fewer than 60 return observations exist)
  covers the earliest rebalances.

## Code fixes during the run

None. The script ran once, end to end, as written; no rule and no
code was changed after results were seen.

## Tally

Twenty-nine strategies tested honestly across seven rounds; none
has beaten its benchmark out-of-sample on the registered bars.
Per the pre-registration, none of H24–H27 is re-tuned or re-tested
on this data, and the momentum family (H9–H11, H15, H19, H22, H25,
H27) is closed to further variants.
