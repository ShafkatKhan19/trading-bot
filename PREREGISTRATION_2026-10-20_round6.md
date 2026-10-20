# Round 6 pre-registration — overnight, pairs, sectors, large-cap low-vol (H20–H23)

Written and committed BEFORE any round-6 code runs or results are seen
(2026-10-20). Previous rounds: 21 strategies tested, 0 beat their
benchmark. Cumulative test count after this round: 25. Bonferroni
one-sided t-bar ≈ 3.08 (exact value computed in code).

## Shared rules

- Costs 5 bps per side everywhere. Signals at close, fills at next
  session's open wherever open prices exist (universe L / SPY); the
  small-cap Yahoo data follows the round-5 adjclose convention.
- In-sample through 2023-07-06 is context only; verdicts on OOS
  (2023-07-07 onward) only.
- PASS requires ALL of: OOS annualised excess return vs the stated
  benchmark > 0, one-sided t on OOS excess returns ≥ the Bonferroni
  bar, and OOS Sharpe above the benchmark's Sharpe. FAIL is final for
  the rule as written. A PASS earns only a paper forward test.

## Hypotheses

- **H20 — overnight-only SPY.** Buy SPY at each close, sell at the next
  session's open, every session. Cash during the day. Data: local
  SPY_1Day.csv OHLC. Benchmark: SPY buy & hold. (The published
  overnight-drift claim, tested with honest daily round-trip costs.)
- **H21 — pairs trading, universe L.** Formation screen on in-sample
  data only: among the 87 universe-L names, take the 20 pairs with the
  highest daily-return correlation (each name in at most 2 pairs).
  Trading (full window): spread = log price ratio, normalised by its
  trailing 60-session mean/stdev; enter a dollar-neutral pair trade
  when |z| > 2, exit when z crosses back through 0, hard exit after
  20 sessions. Equal capital per pair slot, max 20 concurrent.
  Benchmark: SPY buy & hold.
- **H22 — small-cap sector momentum.** Universe S (round-5 data, GICS
  sectors from the constituent list). Monthly: rank the 11 sectors by
  equal-weight 6-1 momentum (months t−6…t−1), hold ALL eligible names
  of the top 3 sectors, equal weight. Benchmark: IWM. Distinct from
  the failed H3 (that was large-cap sector ETFs).
- **H23 — large-cap low volatility.** Universe L, monthly: rank by
  60-session return stdev, lowest first, hold lowest 26 (≈30%).
  Benchmark: SPY. (H18 tested low-vol in small caps; the published
  anomaly is primarily a large-cap claim, so it gets its own test.)

## Data notes

- Universe L bars and SPY_1Day.csv are the repo's existing local
  datasets (Alpaca-sourced). Small-cap bars are the round-5 Yahoo
  cache with its disclosed survivorship caveat.
