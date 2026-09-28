# Pre-registration — H8 turn-of-month SPY (2026-09-28)

Written and committed **before** any H8 code or out-of-sample result.

## Disclosure
`STUDIES_2026-09-28.md` (study 3) looked at SPY's return by trading day
around month end on the **in-sample years only** (2016-01-04 → 2023-07-05).
It showed mixed support (day +1 strong, the last day slightly negative).
The rule below is **not** taken from that study: it is the standard window
from the literature, fixed regardless of which in-sample days looked best.
The out-of-sample years (2023-07-06 → 2026-09-25) have not been examined for
H8 in any form.

Sources: Ariel (1987), "A monthly effect in stock returns", *JFE* 18;
Lakonishok & Smidt (1988), *RFS* 1; McConnell & Xu (2008), "Equity returns
at the turn of the month", *Financial Analysts Journal* 64(2).

## Multiple testing
Ten strategies will have been tested (H1-H8 plus the two intraday books).
The out-of-sample t-stat bar is **2.81** (two-sided p < 0.05/10, Bonferroni).

## Rule
- **Window:** the last trading day of each month through the 3rd trading
  day of the next month (McConnell & Xu's [-1, +3]), i.e. four sessions.
- **Trade:** buy SPY with the full book at the **close of the
  second-to-last trading day** of the month; sell at the **close of the 3rd
  trading day** of the next month. Cash (0%) at all other times.
- Trading days come from the exchange calendar (holidays and early closes
  count as sessions).
- Fills at the daily close, split and dividend adjusted (Alpaca SIP daily
  bars, `data/round2/bars/SPY.pkl`). **Costs: 5 bps per side.**
- Signal is calendar-only, so delayed data is irrelevant. In paper/live it
  would be a market order shortly before the close (not the 09:35 run).

## Split and verdict (same as rounds 1-2 and H7)
Evaluation 2016-01-04 → 2026-09-25, daily equity. First 70% of trading days
in-sample (reported), last 30% out-of-sample (decides). PASS requires ALL:
1. OOS t-stat of mean daily net return ≥ **2.81**
2. OOS Sharpe ≥ SPY buy-and-hold OOS Sharpe
3. OOS max drawdown ≤ 20%

No minimum trade count: with one trade a month (~38 out of sample), H8 is
judged on its daily returns, like H2, H3 and H6.

## Descriptive only — never used to pick
Mean return per window vs other days, win rate per window, results at
0 / 2 / 10 bps per side, per-year returns, and the alternative
"turn-of-month in SPY, otherwise also SPY" comparison (i.e. how much of
SPY's total return fell in the window).

If H8 fails, its window is not re-tuned and re-tested on this data.
