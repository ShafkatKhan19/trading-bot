# Results — pre-registered round 2 (2026-09-28)

Pre-registration: `PREREGISTRATION_2026-09-27_round2.md` (commits 46f3289,
60eb409, made before any code or data). Code: `round2_data.py`,
`round2_research.py` (commit 5ba6f1e, before any result). Costs 5 bps/side.
In-sample 2016-01-04 → 2023-07-06; out-of-sample (OOS) 2023-07-06 → 2026-09-25.
Six strategies tested across both rounds, so the OOS t bar is **2.64**.
Full output: `data/round2/report.json`.

| OOS, net of costs | CAGR | Sharpe | t | Max DD | vs random-entry control | Verdict |
|---|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +20.6% | 1.32 | 2.37 | 18.7% | — | — |
| H4 earnings drift | +13.4% | 1.40 | 2.51 | 11.5% | +1.86% vs +1.22%/trade, t 1.33 | **FAIL** (t < 2.64; control t < 2.0) |
| H5 upgrade drift | +29.6% | 2.13 | 3.82 | 12.4% | +1.11% vs +0.64%/trade, t 1.72 | **FAIL** (control t < 2.0) |
| H6 vol-managed SPY | +18.1% | 1.31 | 2.35 | 16.0% | — | **FAIL** (t < 2.64; Sharpe < SPY) |

**No strategy passed.** H5 cleared the t, Sharpe and drawdown bars, but the
same stocks entered on random days earned +0.64% per trade against H5's
+1.11%. Most of H5's return comes from the universe — large caps picked in
2026, i.e. survivors — not from the upgrade signal, and the remaining
+0.47%/trade is not distinguishable from noise (Welch t 1.72). This is the
case the control was registered for. Overlapping holds of the same stock
make the per-trade returns not fully independent, which if anything
overstates the control t-stats above.

H4 earned +4.5%/yr in-sample (Sharpe 0.41), so its OOS strength is not a
stable edge. H6 matched SPY rather than beat it: it cut 2022's loss
(-14.8% vs -18.6%) and gave the difference back in up years.

## Descriptive analyses (not used to decide anything)

- By market regime (SPY vs its 200-day average, 603 days below): only H1
  had a higher Sharpe below the average than above it (0.84 vs 0.39); H2 and
  H3 lost most of their return there (-4.8% and +1.5%/yr).
- H1 sensitivity grid (27 variants): OOS Sharpe ranges 0.64-1.45; the
  RSI<10 row sits at 1.14-1.45, around SPY's 1.32. The registered rules are
  not a fragile outlier, and no variant would clear the t bar.

## Data note

The first news download capped every symbol at 50 headlines (alpaca-py's
`limit` is a total across pages), leaving only Jan-Sep 2026. Fixed to
`limit=None` before any result existed (commit 5ba6f1e); the archive now
holds 294,365 unique headlines, 15k-34k per year from 2015. A pandas dtype
bug in the descriptive regime split crashed the first run after the
verdicts printed; the fix changed no verdict.

## Next

Per the pre-registration, none of these is re-tuned or re-tested on this
data. The bot stays on SPY buy & hold, with H1 in paper forward test. A
fair test of H5 needs a new pre-registration on a universe without
survivorship (historical index membership), or a paper forward test from
2026-09-28.
