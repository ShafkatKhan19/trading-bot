# Results — pre-registered round 11: quality score, cash-flow yield, and blends of the strongest prior signals (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round11.md` (committed
before any round-11 code or result). Code: `round11_research.py`.
All data cached from rounds 8–10 — no new crawls. Universe L:
month-end signals, fills at next open, top 26 equal weight, 5 bps
per side, benchmark SPY. Universe S (H43): round-5/9 conventions,
top 60, benchmark IWM. In-sample 2016-01-01 → 2023-07-06 is context
only; verdicts on OOS 2023-07-07 onward. Forty-five strategies
have now been tested, so the Bonferroni OOS t bar is **3.29** as
registered (the house t formula at the realised OOS daily df
prints 3.27; no verdict is within reach of either number). Full
output: `data/round11_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark, H40–H42) | +20.6% | 1.32 | — | 18.8% | — |
| IWM buy & hold (benchmark, H43) | +14.1% | 0.74 | — | 27.5% | — |
| H40 Quality score (Piotroski-style) | +16.3% | 1.30 | −0.71 | 14.1% | **FAIL** (excess, t, Sharpe) |
| H41 Operating cash-flow yield | +19.3% | 1.39 | −0.20 | 14.2% | **FAIL** (excess, t) |
| H42 Cash-value blend (EY+GP+SHY) | +17.9% | 1.33 | −0.53 | 15.7% | **FAIL** (excess, t) |
| H43 Small-cap value blend (EY+B/M) | +20.3% | 0.92 | +0.90 | 27.0% | **FAIL** (t) |

PASS required all three: OOS annualised excess vs benchmark > 0,
excess t ≥ bar, and OOS Sharpe above the benchmark's. None of the
four passes. In-sample context: H40 +15.3% (Sharpe 0.90), H41
+17.2% (0.95), H42 +18.5% (1.01), H43 +15.2% (0.65). Two
leg-winners, no passes: H41 and H42 both beat SPY's Sharpe (1.39
and 1.33 vs 1.32) with materially lower drawdowns, but both still
returned *less* than SPY out of sample (−1.3%/yr and −2.8%/yr).
H43 is the round's mirror of H33: a real headline excess over IWM
(+6.2%/yr) and a better Sharpe, dead on the t bar (0.90 vs 3.29)
with its horizon-matched control uncorroborated (Welch t +0.31) —
and Universe S is survivorship-biased, the registered prime
suspect for exactly this pattern. Blending did not rescue the
legs: H42 (+17.9%, Sharpe 1.33) finished well behind round 8's
earnings-yield leg alone (H29: +23.7%, Sharpe 1.52); the weaker
gross-profitability and shareholder-yield legs diluted it.

**Tally: 45 strategies tested all-time, 0 pass.**

Per the pre-registration's stopping rule, the fundamentals
programme has now tested the canonical value/quality/cash factors
singly and blended, on two universes. The next-frontier decision
(new data axis vs defensive/absolute-return designs) is written up
before any round 12 is registered.

## Point-in-time guarantee

Identical discipline to rounds 8–10 — every value is an SEC filing
fact usable only on or after its `filed` date, earliest filing
kept per fiscal period, each input on its own filed date where a
hypothesis combines panels (the round-10 H36 convention). H40's
asset-turnover component pairs the GP panel's revenue for a fiscal
year with the assets of the *same* fiscal year from
`panel_l_v2.csv`, usable only once those assets were filed
(`filed_assets` ≤ month-end): 713 of 773 complete GP rows have
such a match; a name missing either year's pairing is ineligible,
as registered ("names missing any component are ineligible").

## Data and coverage

- **Panels reused as built in rounds 8–10** (see those results
  files for tag chains and build limits): `panel_l_v2.csv` (74 of
  87 tickers with complete five-fact FY rows), `panel_gp.csv` (58
  tickers with revenue+COGS), `panel_div.csv` (39 tickers),
  `panel_smallcap.csv` (554 tickers with complete FY rows).
- **H40 eligibility** (all eight components computable): median
  **48 names per month-end** (min 26, max 51) of 87 — the binding
  constraints are GP-panel coverage (58 tickers) and the two-filed-
  FY requirement in both panels. Component 5's median asset growth
  is taken over this eligible set each month-end, as registered.
- **H41 eligibility**: median **68 names per month-end** (min 61,
  max 74) — the five-fact v2 panel is the only constraint.
- **H42 eligibility**: intersection of the three legs as tested in
  rounds 8/10 — earnings yield (median 63 names/month), gross
  profitability (57), shareholder yield (69) — leaving a median of
  **44 names per month-end** (min 28, max 47) rankable on all
  three. Equal-weight blend of the three min-ranks (round-8 H31
  convention).
- **H43 eligibility**: median **462 names per month-end** on the
  fundamental snapshot (round-9 convention: ≥252 sessions of bars,
  price present, complete FY row public). Horizon-matched control
  (round-5 method, 200 random same-size draws per rebalance from
  the same eligible pool): strategy gross +1.65%/rebalance vs
  random +1.38%, Welch t **+0.31** over 125 rebalances — the
  blend's stock-picking is not corroborated beyond the pool's own
  return, same signature as H32/H33 in round 9.
- **No random-entry controls for H40–H42**: the rounds 8–10
  slow-turnover caveat, as in rounds 9/10 for universe-L books.

## Adaptations and quirks (faithful readings, not rule changes)

1. **H40 asset turnover pairing.** The panels carry revenue (GP
   panel) and assets (v2 panel) on separate filed dates with no
   shared row, so "revenue ÷ assets" is computed per fiscal year
   by matching `fy_end` across the two panels, each input usable
   on its own filed date — the maximal faithful reading of the
   registered rule, and the same per-input convention round 10
   registered for H36. Disclosed here per programme practice.
2. **H40 share-count component** (no dilution) compares as-filed
   shares year over year and therefore inherits the panels' known
   split-window caveat (round 8: market cap uses adjusted closes
   × as-filed shares). No split adjustment was invented for it;
   H34/H38 used the same share data the same way.
3. **Bonferroni bar.** The pre-registration states 3.29; the
   house formula used in every round since round 3
   (t-quantile at 1 − 0.05/(2·45), df = OOS days − 1) evaluates
   to 3.27 at this round's realised df. The highest excess t in
   the round is +0.90, so the discrepancy decides nothing; it is
   recorded here rather than silently harmonised.
