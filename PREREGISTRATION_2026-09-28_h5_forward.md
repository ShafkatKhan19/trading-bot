# Pre-registration — H5 paper forward test (2026-09-28)

Written and committed **before** the first forward-test session.
H5 failed round 2 (`RESULTS_2026-09-28_round2.md`) only on its random-entry
control (Welch t 1.72 < 2.0); the suspected cause is survivorship in
universe L. Every headline from 2026-09-28 on is data H5 has never seen,
and survivorship cannot favour it forward, because L is fixed as of today.

## Rules — unchanged from `PREREGISTRATION_2026-09-27_round2.md`
- Universe: the same 87 stocks L (`round2_data.L`).
- Event: an Alpaca/Benzinga news item whose symbols include the stock and
  whose headline matches `\bupgrades?\b` and not `\bdowngrades?\b`
  (case-insensitive; `round2_research.UP` / `DOWN`).
- Entry: the first session open after publication. For session D, the
  events are those published from the previous session's 09:30 ET up to D's
  09:30 ET. Hold 10 trading days, then exit at the open.
- Max 10 positions at 10% of book equity (previous close) each;
  first-come by publication time; one position per stock.

## Execution (paper only, never live)
- `daily_runner.py` book "h5", $2,000 virtual capital, same Alpaca paper
  account as "index" and "h1". Orders go at DAILY_RUN_TIME (09:35 ET), not
  exactly at the open; the fill vs quote is logged in `data/books/fills.csv`.
- Every event the runner sees is logged to `data/books/h5_events.csv` with
  what it did (entered / held / slots full / order failed) as an audit
  trail. A failed order is retried on the next same-day run.
- A missed session is not made up: its events are never entered late.
- The event test below rebuilds events from the Alpaca news archive with
  `round2_research.h5_events`, so it depends on neither the runner's log,
  its uptime, nor free slots.

## Single evaluation — on or after 2027-03-31, once
Events with entry dates 2026-09-28 → 2027-03-17 (so every 10-day hold is
complete). Returns come from daily open prices, 5 bps per side, exactly as
`round2_research.trade_returns`; the control is
`round2_research.control_events` over the same window, seed 20260927.

PASS requires ALL:
1. ≥ 100 events in the window
2. Mean event return beats the control's mean, Welch t ≥ **2.0**
3. The h5 book's daily-return Sharpe ≥ the index book's over the same period
   (`data/books/equity_log.csv`)

No peeking rule: the verdict is computed once, on that date. The dashboard
shows the book's equity along the way, but that is not a verdict, and no
rule changes mid-test. A PASS makes H5 eligible for a sizing decision, not
live trading.
