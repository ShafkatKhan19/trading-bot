# Results — pre-registered round 5: small-cap wave (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round5.md` (committed
before any round-5 code or result). Code: `round5_research.py`.
Universe S: current S&P SmallCap 600 constituents, Yahoo daily bars,
adjclose basis throughout. Monthly, equal weight, top/bottom 30,
signal at month-end close, positions earn returns from the next
session's close onward, 5 bps/side on turnover. Benchmark: IWM.
In-sample 2016-01-01 → 2023-07-06 is context only; verdicts on OOS
2023-07-06 → 2026-10-19 (split at the 2023-07-06 close, as rounds
2–4). Twenty-one strategies have now been tested, so the Bonferroni
OOS t bar is **3.05**. Full output: `data/round5_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess vs IWM) | Max DD | Exposure | Verdict |
|---|---|---|---|---|---|---|
| IWM buy & hold (benchmark) | +14.1% | 0.74 | — | 27.5% | 100% | — |
| H15 small-cap momentum 6-1 | +9.1% | 0.44 | -0.22 | 32.4% | 100% | **FAIL** (excess, t, Sharpe) |
| H16 small-cap 1-month reversal | +15.3% | 0.64 | +0.31 | 34.1% | 100% | **FAIL** (t, Sharpe) |
| H17 52-week-high proximity | +7.7% | 0.51 | -0.98 | 18.2% | 100% | **FAIL** (excess, t, Sharpe) |
| H18 small-cap low volatility | +7.6% | 0.62 | -0.81 | 16.0% | 100% | **FAIL** (excess, t, Sharpe) |
| H19 momentum + low-vol blend | +9.6% | 0.66 | -0.73 | 22.7% | 100% | **FAIL** (excess, t, Sharpe) |

PASS required all three: OOS annualised excess vs IWM > 0, excess
t ≥ 3.05, and OOS Sharpe above IWM's 0.74. None of the five clears
even one bar outright except H16 on excess return alone.

## Random-entry controls (H15, H17)

200 random 30-name draws per rebalance from the same eligible pool,
same dates; gross per-rebalance returns both sides (the control
isolates stock picking; headline numbers above are net of costs).
125 invested rebalances (the first 5 monthly periods, entries
Jan–May 2016, sat in cash — no name yet had the registered 252
sessions of history).

| Control | Strategy gross /rebalance | Random gross /rebalance | Welch t |
|---|---|---|---|
| H15 | +2.06% | +1.38% | +0.71 |
| H17 | +0.80% | +1.38% | -0.78 |

H15's picks point the right way but t +0.71 is no evidence (H10's
large-cap control cleared at t 5.06). H17's picks did *worse* than
random draws from the same pool.

## Data manifest

603 tickers listed (Wikipedia S&P SmallCap 600, fetched 2026-10-20);
602 downloaded in full, 1 failed (CWEN-A — Yahoo returns 404 for that
symbol); IWM benchmark downloaded. 2,864 sessions, 2015-06-01 →
2026-10-19; ~593 names eligible at the most recent signal. Full
manifest: `data/smallcap/manifest.json`.

## Survivorship caveat

Universe S is **today's** constituent list. Names that failed or
were acquired since 2016 are absent, which biases every number in
this round upward — in-sample and out-of-sample alike. Per the
pre-registration, a PASS would have earned only a paper forward
test. There was no PASS, so the caveat changes no verdict: even
with the bias running in their favour, all five trailed IWM
out-of-sample.

## Notes

- Four of the five have *negative* excess t-statistics — they did
  not narrowly miss; they trailed the benchmark outright. Only H16
  (short-term reversal) finished ahead of IWM at all (+1.2%/yr),
  with t +0.31 against a 3.05 bar and a lower Sharpe (0.64 vs 0.74).
- The in-sample → out-of-sample collapse is the round's signature:
  H15 +26.3%/yr in-sample → +9.1% OOS; H16 +30.1% → +15.3%. The
  in-sample figures are inflated by the survivorship bias above
  (and still came with ~52% maximum drawdowns in-sample).
- H18 did the one thing low-volatility promises — the smallest
  drawdown of the round (16.0% vs IWM's 27.5%) — and paid for it
  with the joint-worst return (+7.6%/yr, excess −6.5%).
- Conventions, for the record: the 6-1 formation is closes at
  t−1 vs t−6 (skip the most recent month), identical to H10 in
  round 3; turnover cost is 5 bps × Σ|target − drifted weight| at
  each rebalance; a held name with a missing price is marked at its
  last available adjclose inside the holding period.

## Tally

Twenty-one strategies tested honestly across five rounds; none has
beaten its benchmark out-of-sample on the registered bars. Per the
pre-registration, none of H15–H19 is re-tuned or re-tested on this
data.
