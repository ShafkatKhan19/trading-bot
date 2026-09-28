# Pre-registration — H7 intraday momentum on SPY (2026-09-28)

Written and committed **before** any H7 code, download or result.
Source: Gao, Han, Li & Zhou (2018), "Market intraday momentum", *Journal of
Financial Economics* 129(2): the first half-hour return of SPY predicts its
last half-hour return. Adapted for this account: cash, long-only, $2,000.

## Multiple testing
Nine strategies will have been tested: H1-H6, the two intraday books
(15-min swing, CRT) and H7. The out-of-sample t-stat bar is **2.77**
(two-sided p < 0.05/9, Bonferroni).

## Rule
- **Signal:** r1 = SPY's price at 10:00 ET / previous session's regular
  close − 1 (includes the overnight move, as in the paper).
- **Trade:** if r1 > 0, buy SPY at 15:30 ET and sell at 16:00 ET the same
  day; otherwise stay in cash. At most one round trip a day, full book.
- Sessions that close early (no 15:30 bar) are skipped.
- The signal is known at 10:00, so the free 16-minute-delayed feed is
  enough; no real-time data is needed.

## Data and prices
Alpaca SIP 30-minute bars for SPY, split and dividend adjusted, regular
hours only, 2015-12 → 2026-09-25. Bars are labelled by start time:
- price at 10:00 = close of the 09:30 bar
- previous regular close = close of the previous session's 15:30 bar
- entry = open of the 15:30 bar; exit = close of the 15:30 bar
**Costs: 5 bps per side** (as in rounds 1 and 2; measured SPY half-spreads
are well under 1 bps, so this is conservative).

## Split and verdict (same as rounds 1-2)
Evaluation 2016-01-04 → 2026-09-25, daily equity (cash earns 0). First 70%
of trading days in-sample (reported), last 30% out-of-sample (decides).
PASS requires ALL:
1. OOS t-stat of mean daily net return ≥ **2.77**
2. OOS Sharpe ≥ SPY buy-and-hold OOS Sharpe
3. OOS max drawdown ≤ 20%
4. ≥ 100 OOS trades

## Descriptive only — never used to pick
Win rate and mean return per trade, results at 0 / 1 / 2 / 10 bps per
side, per-year returns, and the paper's symmetric long/short version
(which this cash account cannot trade).

If H7 fails, its rule is not re-tuned and re-tested on this data.
