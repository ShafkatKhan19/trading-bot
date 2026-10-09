# Pre-registration — "picks" AI-infrastructure paper test (2026-10-09)

Written and committed **before** the first picks session (09:35 ET 2026-10-09).

## Hypothesis
The owner's basket of AI-infrastructure stocks (memory, storage, servers,
chips), chosen 2026-10-08 from research on 2026's best performers, keeps
beating SPY over the next three months.

Known bias: the names were picked *because* they already rose 100–600% in
2026. That history proves nothing about the future; only sessions from
2026-10-09 on count.

## Rules (paper only, never live)
- Universe, fixed: SNDK, DELL, MU, MRVL, INTC, AMD, HPE, STX, ARM, WDC,
  AMAT, CBRS (`config.PICKS_SYMBOLS`).
- `daily_runner.py` book "picks", **$10,000 virtual** capital, same Alpaca
  paper account as the other books.
- Entry: at the first run, buy each name with 1/12 of the deposit
  (≈ $833) at market. A buy that fails is retried at the next run.
- Hold. No selling, no rebalancing, no adding names, no stops.

## Single evaluation — on or after 2027-01-08, once
Window: close of the first picks entry date → close of 2027-01-08, using
split- and dividend-adjusted daily closes.

PASS requires BOTH:
1. Basket total return (equal-weight at entry, no rebalancing) > SPY total
   return over the same window.
2. Basket daily-return Sharpe ≥ SPY's over the same window.

The book's own ledger return (actual fills, delayed-quote slippage included)
is reported beside it.

## What a result means
- Twelve highly correlated stocks over ~60 sessions is close to **one bet**
  on AI capex. A PASS is weak evidence; it makes the idea worth a longer
  test, not live money. Live money still requires `golive_gate.py`.
- A FAIL ends this basket. A new basket needs a new pre-registration.

No peeking rule: the dashboard and Andy show the book's value daily, but
that is not a verdict, and no rule changes mid-test.
