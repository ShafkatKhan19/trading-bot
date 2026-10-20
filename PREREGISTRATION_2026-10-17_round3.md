# Pre-registration — round 3: momentum (2026-10-17)

Written and committed **before** any round-3 code, download or result.
Follows the same discipline as rounds 1-2: hypotheses from published
literature, fixed published parameters, tested once, never re-tuned.

## Why momentum, and why this universe

Ten strategies have been tested honestly (H1-H8 plus the two intraday
books); none beat SPY buy & hold out-of-sample. The gaps in coverage are
the two most-cited cross-sectional/time-series momentum results, which
have never been tested in this repo. All three rules below are published
and pre-date 2016, so 2016+ is post-publication for every parameter.

Universe **L** = the 87 large-cap stocks in `round2_data.py` (bars
2016-01-04 → 2026-09-25, split/dividend adjusted, SIP). Signals at
month-end close *t*; fills at the next open (*t+1*). Costs 5 bps/side,
same as round 2. Long-only, cash-account compatible (no shorting).

## Known limitation (disclosed upfront)

L was selected in 2026, so it is a survivors' universe: absolute
returns are inflated. The binding tests are therefore *relative* —
each strategy must beat SPY buy & hold on a risk-adjusted basis with
t ≥ 2.88 out-of-sample, and must also beat an equal-weight buy & hold
of L itself. Beating only the inflated absolute level proves nothing.

## Hypotheses (exactly three)

**H9 — Time-series momentum, 12-1** (Moskowitz, Ooi & Pedersen, 2012,
"Time Series Momentum", *JFE* 103).
At each month-end: for each stock in L, compute its return over months
*t-12* to *t-1* (skip the most recent month, as in the paper). Hold
next month every stock with a positive 12-1 return; hold cash for the
rest of the sleeve. Equal-weight across held names. Rebalance monthly.

**H10 — Cross-sectional momentum, 6-1** (Jegadeesh & Titman, 1993,
"Returns to Buying Winners and Selling Losers", *JF* 48).
At each month-end: rank L by past 6-month return skipping the most
recent month. Go long the top quintile (≈17 stocks), equal weight, hold
one month. No short leg (cash account). Rebalance monthly.

**H11 — Dual momentum** (Antonacci, 2014 *Dual Momentum Investing*).
At each month-end: compute the 12-month return of SPY and of every
stock in L. Hold next month the single asset with the highest 12-month
return — but only if that return is positive; otherwise hold cash
(the absolute filter stands in for T-bills, which this account cannot
hold directly). Rebalance monthly. One position at a time.

## Measurement

- In-sample 2016-01-04 → 2023-07-06 and out-of-sample 2023-07-06 →
  2026-09-25, same split as round 2. In-sample is shown for context
  only; **the verdict uses OOS only**.
- Benchmarks: SPY buy & hold; equal-weight buy & hold of L (rebalanced
  monthly, same costs).
- Random-entry control for H10 (the stock-picking rule): the same
  stocks, same hold lengths, entered on random month-ends (seed
  20261017, 2,000 draws). H10 must clear control t ≥ 2.0, as in round 2.
- Thirteen strategies will then have been tested (H1-H8, two intraday
  books, H9-H11). The OOS t bar is **2.88** (two-sided p < 0.05/13,
  Bonferroni).

## Verdict rule (all must hold, OOS, net of costs)

1. t-stat ≥ 2.88 on OOS daily excess returns vs SPY.
2. Sharpe > SPY buy & hold OOS Sharpe.
3. Max drawdown < SPY buy & hold OOS max drawdown.
4. For H10: random-entry control t ≥ 2.0.

Anything failing any bar is a FAIL. Per this pre-registration, no
round-3 strategy is re-tuned or re-tested on this data, whatever the
outcome.
