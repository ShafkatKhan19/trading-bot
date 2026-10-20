# Results — pre-registered round 12: the combination test, a macro-regime axis, and a defensive design (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round12.md` (committed
before any round-12 code or result), per the frontier decision in
`FRONTIER_DECISION_2026-10-20.md`. Code: `round12_research.py`.
5 bps per side everywhere; in-sample 2016-01-01 → 2023-07-06 is
context only; verdicts on OOS 2023-07-07 onward. Forty-eight
strategies are now registered all-time, so the Bonferroni OOS t bar
is **3.31** as registered (the house t formula at the realised OOS
daily df prints 3.29; no verdict is within reach of either number).
Full output: `data/round12_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| 50/50 SPY/IWM buy & hold (benchmark, H44) | +18.6% | 1.12 | — | 21.6% | — |
| SPY buy & hold, ETF bars (benchmark, H46) | +20.0% | 1.29 | — | 18.8% | — |
| H44 Combined value book (50% H29 + 50% H43) | +23.4% | 1.27 | +0.76 | 21.0% | **FAIL** (t) |
| H45 Yield-curve regime switch (SPY/TLT) | +11.3% | 0.73 | −1.18 | 18.9% | **FAIL** (excess, t, Sharpe) |
| H46 Multi-asset inverse-vol (SPY/TLT/GLD) | +13.4% | 1.34 | −1.00 | 9.9% | **FAIL** (excess, t) |

PASS required all three: OOS annualised excess vs benchmark > 0,
excess t ≥ bar, and OOS Sharpe above the benchmark's.

**H44** is the combination test, and it is the round's near-miss:
the combined book beat its blended benchmark on return (+23.4% vs
+18.6%, +4.8%/yr excess) and on Sharpe (1.27 vs 1.12), and the
diversification thesis worked in the direction registered — the
combined t (+0.76) sits above the large-cap leg's own t (+0.43) —
but nowhere near far enough: +0.76 against a 3.31 bar. Two weak
signals combined produce a somewhat less weak signal, not a
proven one. Per the pre-registered rule ("if either leg is
noise, this fails and the value direction closes entirely"),
**the value direction is now closed**: eleven value/quality/cash
factor tests across two universes, singly and blended, produced
zero passes. In-sample context: H44 +16.3% (Sharpe 0.80).

**H46** did exactly what a defensive design is supposed to do —
Sharpe 1.34 vs SPY's 1.29 and half the drawdown (9.9% vs 18.8%) —
and still fails, because the programme's single standard also
requires beating SPY on return: +13.4%/yr is −6.5%/yr of excess
in a mega-cap bull window, t −1.00. The defensive design is now
on record as tested under the same bar as everything else, not
assumed. Mean realised weights were near-equal thirds (SPY 33%,
TLT 35%, GLD 32%) over 134 invested monthly rebalances.
In-sample context: H46 +7.0% (Sharpe 0.79).

**H45** spent 25 of its 136 monthly signals in TLT with only
2 switches — the curve was inverted through much of 2022–24, so
the rule sat in bonds for a long stretch of the equity bull and
gave back far more than the episodes it avoided cost it: OOS
+11.3%/yr vs SPY +20.0%, Sharpe 0.73 vs 1.29, t −1.18. It fails
all three legs, and the macro-regime idea as registered — one
spread, one zero cut, monthly — is retired with it. In-sample
context: H45 +10.0% (Sharpe 0.60).

**Tally: 48 strategies tested all-time, 0 pass.**

## H45 completion note (data arrived after the first run)

H45's only input is FRED's T10Y2Y series via fredgraph CSV
(public, no key). During the round's first execution on
2026-10-20 that endpoint was unreachable from this VM: repeated
direct fetches (full history and date-limited variants, over
~25 minutes) all timed out with zero bytes received, and the
text-fetch route returned HTTP 403; the run therefore recorded
H45 as not tested, with this disclosure. Later the same day the
endpoint recovered, the genuine series (1976-06-01 → 2026-10-20,
12,593 observations) was saved to `data/macro/T10Y2Y.csv`, and
the registered implementation ran **unchanged** — no substitute
or reconstructed spread was ever used. In that completing run,
H44 and H46 reproduced their first-run numbers to the last
digit (max |Δ| = 0.00), confirming the completion changed
nothing but H45's empty cell.

## Reconstruction verification (H44's legs)

H44's legs were not reimplemented. They were run through the
original code paths at their native $2,000 — H29 via
`round8_research.run_monthly` + `make_choose("H29")`, H43 via
`round11_research.run_smallcap_blend` — then halved and summed
(both engines are exactly linear in starting capital: fractional
shares, purely proportional costs; the benchmark legs were
halved identically). The reconstruction is exact: each leg's OOS
CAGR, Sharpe and excess t reproduce the published round-8 and
round-11 reports to the last digit (max |Δ| = 0.00 across all
six numbers — H29: +23.69%, 1.524, +0.43; H43: +20.32%, 0.916,
+0.90). The combined book is therefore built from verified
parts. The combined calendar is the intersection of the two
legs' sessions: 2,698 sessions, 2016-01-04 → 2026-09-25 (the
universe-L calendar; the small-cap panel covers every one of
those sessions in range).

## Data notes (H46)

- **No evaluation-window trim was needed.** The cached ETF bars
  (round 7, Yahoo) start 2015-06-01 for all of SPY/TLT/GLD, six
  months before the 2016-01-01 evaluation start, so the
  pre-registration's contingency did not trigger. H46's book
  runs from June 2015 (in cash until the first signal close with
  60 trailing returns, late August 2015); reported statistics
  use the ≥ 2016-01-01 window, the round-11 presentation.
- **Adjusted prices for next-open fills.** The bars carry raw
  OHLC plus AdjClose. Fills and marks use dividend-adjusted
  prices throughout: AdjClose for closes, and opens scaled by
  the day's AdjClose/Close ratio (the adjustment factor Yahoo
  applies to that day's close). Without this, TLT/SPY dividend
  months would fake losses at every ex-date.
- **H46 volatility** is the standard deviation (ddof=1) of the
  trailing 60 daily adjusted-close returns ending at the signal
  close, per asset; weights ∝ 1/vol, long-only, normalised.
- The SPY benchmark for H46 is buy & hold on the same ETF bars
  through the round-8 `spy_bh` path (OOS +20.0%, Sharpe 1.29 —
  a touch below the universe-L bars' +20.6%/1.32; different
  vendor/adjustment source, disclosed in round 7 as well).

## What this closes

Per the frontier decision's terms: the value direction is
closed (H44), the defensive design is tested and failed on the
return leg (H46), and the macro-regime axis (H45) was tested
once FRED access recovered and failed on all three legs. The
programme's standing
result after twelve rounds: no mechanical strategy tested has
beaten its benchmark at the pre-registered evidentiary standard,
and the two live paper forward tests (H1, H10) remain the
programme's other evidentiary track.
