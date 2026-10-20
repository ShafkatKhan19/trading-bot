# Results — pre-registered round 4: calendar anomalies (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-17_round4.md` (approved by
Shaf 2026-10-20, committed before any round-4 code or result). Code:
`round4_research.py`. SPY only, long-only, fills at the open, 5 bps/side.
In-sample 2016-01-06 → 2023-07-06; OOS 2023-07-06 → 2026-09-09. Sixteen
strategies have now been tested, so the OOS t bar is **2.96**. Full
output: `data/round4_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess vs SPY) | Max DD | Exposure | Verdict |
|---|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +19.0% | 1.23 | — | 19.0% | 100% | — |
| H12 "Sell in May" | +6.8% | 0.60 | -2.22 | 19.0% | 47% | **FAIL** (t, Sharpe) |
| H13 pre-holiday effect | -1.3% | -0.56 | -2.36 | 4.8% | 8% | **FAIL** (loses money) |
| H14 Santa Claus rally | -0.5% | -0.28 | -2.25 | 3.7% | 3% | **FAIL** (loses money) |

## Notes

- The two most famous one-day anomalies are dead on SPY in this window:
  H13 and H14 both lose money net of costs out-of-sample. The tiny
  exposure (8% and 3% of sessions) cannot survive the 5 bps/side drag —
  and in-sample was already near zero (+0.1% and +0.8% CAGR), so these
  were weak even before the OOS test.
- H12 is positive (+6.8%/yr) but trails SPY by a wide margin on every
  bar (t -2.22, Sharpe 0.60 vs 1.23). Sitting in cash half the year in
  the strongest equity window in decades is the cost.
- Sanity: trade counts match the registered recipes (H12 ~2/yr,
  H13 ~9.5/yr, H14 1/yr). No re-tuning; all three are retired.

## Tally

Sixteen strategies tested honestly across four rounds; none has beaten
SPY buy & hold out-of-sample on the registered bars. Per the
pre-registration, none of H12-H14 is re-tuned or re-tested on this data.
