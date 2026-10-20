# Pre-registration — round 12: the combination test, a macro-regime axis, and a defensive design (2026-10-20)

Written and committed BEFORE any round-12 code or results, per the
frontier decision in `FRONTIER_DECISION_2026-10-20.md`.

## Conventions

- Same engine conventions, cost (5 bps/side), in-sample/OOS split
  (verdicts OOS 2023-07-07 onward only) and point-in-time discipline
  as rounds 8–11. Universe L/S and their panels/bars are the cached
  ones; the only new data is FRED public macro series for H45.
- PASS requires all three legs: OOS annualised excess vs the
  registered benchmark > 0, one-sided excess t ≥ Bonferroni bar,
  OOS Sharpe > benchmark Sharpe. 48 strategies will have been
  tested after this round, so the bar is **t ≥ 3.31**.
- A PASS deploys a $2,000 paper forward-test book automatically;
  a FAIL retires the hypothesis permanently. Each hypothesis is
  tested exactly once, as written.

## Hypotheses

**H44 — Combined value book (the combination test).**
50% of capital in H29's exact large-cap earnings-yield book
(Universe L, top 26, monthly, next-open fills) + 50% in H43's
exact small-cap value blend book (Universe S, top 60, monthly,
next-close adjusted fills), each leg rebalanced on its own
registered schedule, no cross-leg rebalancing beyond the initial
50/50 split of the $2,000 start (leg equity compounds separately;
the combined equity is the sum). Benchmark: the same 50/50 split
between SPY buy & hold and IWM buy & hold. Rationale, registered
in advance: the programme's only two positive-excess signals are
near-independent bets; if both are real, diversification lowers
excess volatility and the combined t can clear the bar even
though neither leg could alone. If either leg is noise, this
fails and the value direction closes entirely.

**H45 — Yield-curve regime switch (new data axis: FRED).**
Monthly. Signal: FRED T10Y2Y (10Y–2Y Treasury spread), using the
prior month-end's value (a full one-month lag, conservative for
release timing). If the lagged spread ≥ 0, hold SPY for the
month; if < 0 (inverted curve), hold TLT (long Treasuries).
Fills at next open on the cached ETF bars; benchmark SPY buy &
hold. One rule, no thresholds to tune: zero is the registered
cut.

**H46 — Multi-asset inverse-volatility (defensive design).**
Monthly rebalance across SPY, TLT, GLD (cached ETF bars). Weights
∝ 1 / trailing-60-session volatility of each asset at the signal
close, long-only, normalised to 100%. Fills at next open.
Benchmark SPY buy & hold, same PASS legs as every other test —
no softer "defensive" bar. This puts the absolute-return design
on record as tested under the programme's single standard.

## Data note

FRED series are public and free (fredgraph CSV, no key). T10Y2Y is
a market-derived spread published daily; the registered one-month
signal lag makes any publication-timing question moot. ETF bars
for SPY/TLT/GLD are already cached under `data/etf/bars/` from
round 7; if TLT history there starts after 2016-01-01, the
evaluation window for H45/H46 starts at the first date all needed
series exist, disclosed in the results.
