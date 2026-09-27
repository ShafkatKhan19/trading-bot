# Results — pre-registered low-frequency ETF test (2026-09-27)

Pre-registration: `PREREGISTRATION_2026-09-27_daily.md` (commit eb6dfbd, made
before any code). Code: `daily_research.py`. Costs 5 bps/side. In-sample
2016-01-04 → 2023-07-06; out-of-sample (OOS) 2023-07-06 → 2026-09-25.

| OOS, net of costs | CAGR | Sharpe | t | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +20.6% | 1.32 | 2.37 | 18.7% | — |
| H1 RSI(2) pullback | +8.8% | 1.28 | 2.29 | 6.8% | **FAIL** (t < 2.4; Sharpe < SPY) |
| H2 SPY 200-day trend | +12.0% | 1.01 | 1.82 | 10.0% | **FAIL** (t < 2.4; Sharpe < SPY) |
| H3 sector momentum | +7.0% | 0.55 | 0.98 | 18.2% | **FAIL** (t < 2.4; Sharpe < SPY) |

**No strategy beat simply holding SPY.** H1 came closest out-of-sample but
earned only +0.9%/yr in-sample (2016-2023, Sharpe 0.16), so its recent
strength is not a stable edge. H1 and H2 did cut drawdowns (6.8% and 10% vs
18.7%) at the price of much lower returns.

Engine check: zero-cost buy & hold reproduces SPY's adjusted-close CAGR
(15.1%, 2016-2026) exactly.

Per the pre-registration, none of these is re-tuned and re-tested on this
data. H1 may be forward-tested in paper from 2026-09-28 — data it has never
seen — using the rules exactly as registered.
