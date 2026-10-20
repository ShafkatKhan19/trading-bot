# Round 7 pre-registration — index dip-buying, ETF rotation, weekly reversal, vol-scaled momentum (H24–H27)

Written and committed BEFORE any round-7 code runs or results are seen
(2026-10-20). Previous rounds: 25 strategies tested, 0 beat their
benchmark. Cumulative test count after this round: 29. Bonferroni
one-sided t-bar ≈ 3.13 (exact value computed in code).

## Shared rules

- Costs 5 bps per side. Signals at close, fills at next session's open
  (Yahoo-sourced series follow the round-5 adjclose convention).
- In-sample through 2023-07-06 is context only; verdicts on OOS
  (2023-07-07 onward) only.
- PASS requires ALL of: OOS annualised excess return vs the stated
  benchmark > 0, one-sided t on OOS excess returns ≥ the Bonferroni
  bar, and OOS Sharpe above the benchmark's Sharpe. FAIL is final.
  A PASS earns only a paper forward test.

## Hypotheses

- **H24 — SPY dip-buying (Connors RSI(2) on the index).** Data:
  SPY_1Day.csv. When SPY's 2-day RSI < 10 at the close, buy at the
  next open with full capital. Exit at the next open after a close
  with RSI(2) > 70, or after 5 sessions held, whichever first. One
  position at a time. Benchmark: SPY buy & hold. (H1 applied RSI(2)
  to individual stocks; this tests the index version.)
- **H25 — ETF tactical rotation.** Universe: SPY, QQQ, IWM, TLT, GLD
  (Yahoo total-return series). Monthly: rank by 6-1 momentum (months
  t−6…t−1); hold the single best if its 6-1 momentum is positive,
  otherwise hold cash. Benchmark: SPY buy & hold.
- **H26 — large-cap weekly reversal.** Universe L. Each Friday close:
  rank by prior 5-session return, worst first; buy the worst 17 at
  Monday's open, equal weight, hold exactly one week. Benchmark: SPY.
  (The original Jegadeesh reversal claim, at its published frequency;
  H16 tested the monthly small-cap version.)
- **H27 — volatility-scaled momentum, universe L.** H10's exact 6-1
  top-17 monthly selection, but the invested fraction is scaled by
  min(1.5, max(0.5, 10% ÷ the momentum basket's trailing 126-session
  annualised volatility)), remainder in cash. Benchmark: SPY. This is
  the Barroso–Santa-Clara risk-management claim. **Family-closing
  rule:** if H27 fails, the momentum family is closed — no further
  momentum variants will be tested (H10's live forward test continues
  regardless; it was pre-registered separately).

## Data notes

- Universe L bars and SPY_1Day.csv are the repo's existing local
  datasets. TLT and GLD are fetched from Yahoo for this round
  (adjclose, cached like the round-5 small-cap bars).
