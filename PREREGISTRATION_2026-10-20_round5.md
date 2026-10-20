# Round 5 pre-registration — small-cap wave (H15–H19)

Written and committed BEFORE any round-5 code runs or results are seen
(2026-10-20). Owner directive this round: maximum research speed — test
many strategies, real numbers only, no tuning after the fact. Previous
rounds: 16 strategies tested, 0 beat their benchmark. Cumulative test
count after this round: 21. Bonferroni one-sided t-bar ≈ 3.03 (exact
value computed in code).

## Data and universe

- **Universe S:** the current S&P SmallCap 600 constituent list (~603
  tickers, Wikipedia). **Survivorship caveat:** today's list excludes
  names that failed or were acquired since 2016, biasing backtests
  upward. Any PASS earns only a paper forward test — same rule as
  universe L in rounds 1–4.
- **Bars:** Yahoo Finance daily chart API (split/dividend-adjusted
  closes). Window 2016-01-01 onward. A name is eligible only once it has
  ≥252 sessions of history; missing data excludes a name that month.
- **Benchmark:** IWM total return over the same window.
- **Split:** in-sample 2016-01-01 → 2023-07-06 is context only.
  Verdicts on out-of-sample (2023-07-07 onward) only.
- **Costs/fills:** 5 bps per side. Monthly rules: signal at month-end
  close, positions earn returns from the NEXT session's close onward
  (adjclose basis, disclosed deviation from the rounds 1–4 open-fill
  convention — no open prices are used anywhere in this round).

## Hypotheses (all monthly, first session of the month, equal weight)

- **H15 — small-cap momentum 6-1.** Rank by return over months t−6…t−1
  (skip the most recent month). Hold top 30.
- **H16 — small-cap short-term reversal.** Rank by prior 1-month
  return, worst first. Hold bottom 30 for one month.
- **H17 — 52-week-high proximity.** Rank by close ÷ trailing 252-session
  max close. Hold top 30.
- **H18 — small-cap low volatility.** Rank by 60-session return
  standard deviation, lowest first. Hold lowest 30.
- **H19 — momentum + low-vol blend.** Average of the H15 rank and the
  H18 rank. Hold top 30 by blended rank.

## Controls and verdicts

- Random-entry control for the stock-picking rules H15 and H17: 200
  random 30-name draws on the same rebalance dates; Welch t-test of
  strategy per-rebalance returns vs control.
- **PASS** requires ALL of: OOS annualised excess return vs IWM > 0,
  one-sided t on OOS daily excess returns ≥ the Bonferroni bar, and
  OOS Sharpe above IWM's Sharpe. Anything else is a FAIL, final for
  that rule as specified — no re-tuning on this data.
- A PASS earns a paper forward-test book deployed through the GitHub
  pipeline, with its own forward pre-registration at deploy time and a
  first formal read after ~3 months of trading. A PASS never by itself
  authorises live-money trading.

## Standing rules (unchanged)

- 5 bps per side, benchmark discipline, OOS-only verdicts, one test per
  hypothesis, results published either way.
