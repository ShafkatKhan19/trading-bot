# Pre-registration — H10 paper forward test (2026-10-17)

Written and committed **before** the forward test begins. This is the
only honest next step for H10 after round 3: its backtest failed the
benchmark bars, but its stock-picking cleared the random-entry control
(Welch t 5.06, 579 trades, +5.80%/trade vs +1.15%/trade). A forward
test on unseen data decides whether that signal is real.

## Rule (identical to the backtested H10)

- Universe L (87 large caps, `round2_data.L`).
- On the **first trading session of each month**: rank L by 6-month
  return skipping the most recent month, using completed daily closes.
  Hold the top 17, equal weight. Sell anything held that is no longer
  in the top 17.
- Paper only. Never runs in live mode. Paper capital $2,000
  (`H10_PAPER_CAPITAL = ACCOUNT_CAPITAL`), matching the index book it
  is compared against.
- Fills at market on the rebalance session; no lookahead (signals use
  completed closes only).

## Grade date: 2027-04-17

On or after 2027-04-17, grade the forward window (first rebalance →
grade date) against the `index` book (SPY buy & hold, same deposits):

- **PASS** iff H10 Sharpe > index Sharpe AND H10 total return > index
  total return over the forward window, with the book having run on
  ≥80% of trading sessions (no long outages).
- Otherwise **FAIL**. A FAIL retires H10 permanently — no re-tuning,
  no second forward test of the same rule.

## What a PASS would mean

A PASS does not authorize live trading by itself. It authorizes exactly
one thing: a proposal to the owner to consider a second, longer forward
test or a small live allocation — the owner's call, with Andy's review.
