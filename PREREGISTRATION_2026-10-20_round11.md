# Pre-registration — round 11: quality score, cash-flow yield, and blends of the strongest prior signals (2026-10-20)

Written and committed BEFORE any round-11 code or results. All data
is already cached locally from rounds 8–10 (SEC EDGAR point-in-time
panels); this round runs no new crawls.

## Conventions (identical to rounds 8–10 unless stated)

- Universe L: the same 87 large caps. Universe S: current S&P
  SmallCap 600 list (survivorship-biased, disclosed as before).
- Month-end signals from the latest SEC filing with `filed` ≤
  month-end (point-in-time, earliest filing per fiscal period);
  fills at next open (Universe L) / next-close adjusted convention
  (Universe S, as rounds 5/9). Costs 5 bps per side.
- In-sample 2016-01-01 → 2023-07-06 is context only; verdicts on
  OOS 2023-07-07 onward only.
- PASS requires all three: OOS annualised excess vs benchmark > 0,
  one-sided excess t ≥ Bonferroni bar, OOS Sharpe > benchmark
  Sharpe. 45 strategies will have been tested after this round, so
  the bar is **t ≥ 3.29**.
- Benchmarks: SPY (Universe L), IWM (Universe S).

## Hypotheses

**H40 — Piotroski-style quality score (Universe L, top 26, SPY).**
Eight binary signals from the latest two filed fiscal years in
`panel_l_v2.csv` + `panel_gp.csv`, one point each: (1) net income
> 0; (2) operating cash flow > 0; (3) OCF > net income (cash-backed
earnings); (4) ROA improved vs prior FY; (5) asset growth below the
eligible-universe median (discipline, inverse of the H37 signal);
(6) gross margin improved vs prior FY (GP panel); (7) asset
turnover (revenue ÷ assets) improved vs prior FY; (8) shares
outstanding did not increase vs prior FY (no dilution). Rank by
total score, tie-break by earnings yield (NI ÷ market cap). Names
missing any component are ineligible; eligibility counts disclosed.
This is a quality composite in Piotroski's spirit, adapted to the
fields the cached panels carry — not the literal 9-point F-score
(the panels hold no current-ratio or long-term-debt split).

**H41 — Operating cash-flow yield (Universe L, top 26, SPY).**
Rank by trailing filed-FY operating cash flow ÷ market cap,
descending. The cash-earnings counterpart to H29's accrual
earnings yield: if the market underprices cash generation rather
than reported earnings, this is where it shows.

**H42 — Cash-value blend (Universe L, top 26, SPY).**
Equal-weight rank blend of three previously-tested single signals:
earnings yield (H29), gross profitability (H36), total shareholder
yield (H38). Distinct from H31 (book-to-market + earnings yield +
ROE). Rationale: each leg prices a different cash stream; the blend
tests whether their combination diversifies away the single-factor
noise that kept each leg under the bar.

**H43 — Small-cap value blend (Universe S, top 60, IWM).**
Equal-weight rank blend of earnings yield (H32) and book-to-market
(H33) on `panel_smallcap.csv` — the two small-cap legs with
positive headline OOS excess in round 9, combined once, as
registered here. Survivorship bias in Universe S is the standing
prime suspect for any flattering result and will be stated in the
verdict either way.

## Falsification and stopping rules

- Each hypothesis is tested exactly once, as written. No re-tuning,
  no component shopping after seeing results; data-build limits are
  disclosed, never worked around by changing the registered rule.
- A PASS deploys a $2,000 paper forward-test book automatically
  (per Shaf's standing autonomy grant); a FAIL retires the
  hypothesis permanently.
- If all four fail, the fundamentals programme has then tested the
  canonical value/quality/cash factors singly and blended, on two
  universes, and the next frontier decision (new data axis vs
  defensive/absolute-return designs) gets written up before any
  round 12 is registered.
