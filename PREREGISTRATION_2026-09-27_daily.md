# Pre-registration — lower-frequency strategies (2026-09-27)

Written and committed **before** any of these strategies was coded or run.
The intraday books (15-min swing, CRT) failed out-of-sample: gross edge ≈ 0
and ~6–8 trades/day, so costs dominate. This tests whether a small set of
**low-frequency, published** rules does better. Nothing below is tuned; all
parameters are the published defaults.

## Why these, and why ETFs
- **ETFs, not the 20-stock watchlist.** The watchlist was picked in 2026 and
  is full of names that went up (NVDA, PLTR, …). Testing on it rewards
  hindsight. Broad and sector ETFs have no such survivorship bias, are
  fractionable, and have ~1 bp spreads.
- **Daily bars, trade at the next open.** Signals use completed daily bars,
  so the free 15-min-delayed SIP feed is enough. No real-time data needed.
- All three rules were published before 2014, so 2016+ is post-publication.

## Hypotheses (exactly three)
Universe **U** = SPY, QQQ, IWM, DIA + sector ETFs XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB.
Sectors **S** = the nine sector ETFs above.
Signals at close *t*; fills at the open of *t+1*.

**H1 — RSI(2) pullback in an uptrend** (Connors & Alvarez, 2008).
Buy when close > SMA(200) and RSI(2) < 10. Sell at the next open after the
first close > SMA(5), or after 10 trading days. At most 5 positions, 20% of
equity each; if more signals than free slots, take the lowest RSI(2). No stop.

**H2 — 200-day trend filter on SPY** (Faber, 2007, daily variant).
At each month-end: hold SPY if close > SMA(200), else cash (0% return).

**H3 — Sector momentum with trend filter** (Faber-style relative strength).
At each month-end: rank S by 126-day total return; hold the top 3 at 1/3
each, but any of the three that is below its SMA(200) is held as cash.

## Test design
- Data: Alpaca daily SIP bars, split- and dividend-adjusted, 2015-01 → 2026-09-25.
  Evaluation starts 2016-01-04 (SMA(200) warm-up).
- Costs: **5 bps per side** on every fill (sensitivity also at 2 and 10 bps).
- Split: first 70% of trading days in-sample (reported only), last 30%
  out-of-sample (decides the verdict). No parameter is fitted on either.
- Benchmark: SPY buy-and-hold over the same days.

## Verdict — PASS requires ALL, out-of-sample, net of costs
1. t-stat of mean daily net return ≥ **2.4** (≈ p < 0.05/3, Bonferroni for three tests)
2. Sharpe ratio ≥ SPY buy-and-hold Sharpe (otherwise just buy SPY)
3. Max drawdown ≤ **20%**
4. H1 only: ≥ 100 out-of-sample trades

A strategy that fails is not re-tuned and re-tested on the same data.
