# Results — pre-registered round 3: momentum (2026-10-17)

Pre-registration: `PREREGISTRATION_2026-10-17_round3.md` (commit a1d98cb,
written before any round-3 code or result). Code: `round3_research.py`.
Costs 5 bps/side. In-sample 2016-01-04 → 2023-07-06; out-of-sample (OOS)
2023-07-06 → 2026-09-25, same split as round 2. Thirteen strategies have
now been tested, so the OOS t bar is **2.88**. Full output:
`data/round3_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess vs SPY) | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +20.6% | 1.32 | — | 18.8% | — |
| EW large-cap buy & hold | +10.1% | 0.90 | — | 13.8% | — |
| H9 time-series momentum 12-1 | +17.8% | 1.45 | -0.66 | 14.4% | **FAIL** (t < 2.88) |
| H10 cross-sectional momentum 6-1 | +19.6% | 1.17 | -0.12 | 19.4% | **FAIL** (t, Sharpe, drawdown) |
| H11 dual momentum | +70.8% | 1.30 | +1.82 | 41.9% | **FAIL** (t < 2.88; drawdown) |

## Notes

- **H9** is the only strategy yet tested with a higher OOS Sharpe than
  SPY (1.45 vs 1.32) and a lower drawdown (14.4% vs 18.8%), but its
  daily excess returns vs SPY are negative on average (t -0.66): it is a
  smoother ride to a worse destination. FAIL per the registered rule.
- **H10** clears the random-entry control decisively: +5.80%/trade vs
  +1.15%/trade on the same stocks entered on random month-ends (Welch
  t 5.06, 579 trades). The momentum ranking genuinely picks better
  stocks than chance — but the winners are high-beta names, and the
  portfolio still trails SPY risk-adjusted (Sharpe 1.17, drawdown
  19.4%). A real signal that does not survive the benchmark bar. FAIL.
  (Caveat as in round 2: overlapping monthly holds of the same stocks
  make per-trade returns not fully independent, overstating the
  control t somewhat.)
- **H11** earned +70.8%/yr OOS by riding single-stock momentum, but with
  a 41.9% max drawdown across only 27 lifetime trades. The excess t of
  1.82 does not clear 2.88, and a 42% drawdown is untradeable at this
  account size regardless. FAIL.
- The equal-weight large-cap benchmark (+10.1%, Sharpe 0.90) confirms
  the disclosed survivorship effect cuts the other way here: even the
  inflated universe cannot beat SPY on this window.

## Tally

Thirteen strategies tested honestly across three rounds; none has
beaten SPY buy & hold out-of-sample on the registered bars. The
standing instruction remains: the bot trades SPY buy & hold, with H1
in paper forward test. Per the pre-registration, none of H9-H11 is
re-tuned or re-tested on this data.
