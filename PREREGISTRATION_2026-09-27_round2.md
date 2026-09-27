# Pre-registration — round 2 (2026-09-27)

Written and committed **before** any round-2 code, download or result.
Round 1 (`PREREGISTRATION_2026-09-27_daily.md`, H1-H3) all failed vs SPY.
Capital raised to $2,000 (cash account, long-only, no leverage).

## Multiple testing
Six strategies will have been tested (H1-H6). The out-of-sample t-stat bar
rises from 2.4 to **2.64** (two-sided p < 0.05/6, Bonferroni).

## Universe for event strategies (H4, H5)
**L** = 86 US large caps that were already large in 2016 and still trade
under the same ticker (ticker changes like FB→META excluded to avoid data
splicing): AAPL MSFT AMZN GOOGL JNJ JPM XOM PG V MA HD CVX PFE KO PEP MRK
ABBV BAC WMT DIS CSCO INTC VZ T ORCL CMCSA NFLX ADBE CRM NKE MCD MDT UNH ABT
TMO AMGN HON UNP UPS LOW SBUX IBM QCOM TXN AVGO NVDA COST WFC C GS MS BLK AXP
CAT DE MMM GE BA LMT GD NOC LLY BMY GILD CVS MO PM MDLZ CL KMB TGT AMT SPG
NEE DUK SO D EXC COP SLB EOG OXY F GM ADP INTU ISRG.
**Known bias:** picked in 2026, so companies that failed or were acquired
since 2016 are missing (survivorship). To separate a real signal from "these
stocks went up", every event strategy is also compared with a **control**:
the same stocks, same holding period, entered on the same count of random
non-event days (fixed seed). A signal must beat its control, not just zero.

## Hypotheses
Signals use information available before the fill; fills at the next open;
**5 bps per side** (measured spreads are ~0.3-1.6 bps half-spread, so this is
conservative).

**H4 — Post-earnings announcement drift.** Event = earnings with
Surprise(%) > 0 (yfinance) AND reaction-day close-to-close return > 0.
Reaction day = the report date if released before 12:00 ET, else the next
session. Buy at the open after the reaction day; hold 20 trading days.
Max 10 positions, 10% of equity each; if more events than slots, largest
surprise first.

**H5 — Analyst upgrade drift.** Event = an Alpaca/Benzinga news item whose
symbols include the stock and whose headline matches `\bupgrades?\b`
(case-insensitive) and does not match `\bdowngrades?\b`. Buy at the next
session open after publication (items published before 09:30 ET → that day's
open); hold 10 trading days. Max 10 positions, 10% each; first-come.

**H6 — Volatility-managed SPY** (Moreira & Muir, 2017, no leverage).
At each month-end: weight = min(1, 0.15 / realized vol), realized vol =
annualized stdev of SPY's last 21 daily returns. Rest in cash (0%).

## Split and verdict (same as round 1)
Evaluation 2016-01-04 → 2026-09-25; first 70% of trading days in-sample
(reported), last 30% out-of-sample (decides). PASS requires ALL:
1. OOS t-stat of mean daily net return ≥ **2.64**
2. OOS Sharpe ≥ SPY buy-and-hold OOS Sharpe
3. OOS max drawdown ≤ 20%
4. H4/H5: ≥ 100 OOS trades AND mean OOS trade return beats the control's
   mean by a margin with t ≥ 2.0 (Welch)

## "Understanding" analyses — descriptive only, never used to pick
For H1-H6: per-year returns, the five worst drawdowns, and results split by
market regime (SPY above/below its 200-day average).
H1 sensitivity grid (RSI threshold 5/10/15 × exit SMA 3/5/10 × max hold
5/10/20). This shows whether H1's out-of-sample result is fragile. It is
**not** used to choose parameters; H1's registered rules do not change.
