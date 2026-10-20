# Pre-registration — round 4: calendar anomalies (2026-10-17)

**STATUS: APPROVED by Shaf on 2026-10-20 ("create new strategies...
lets try that"), as-is. Committed before any round-4 code or result.**

Follows the same discipline as rounds 1-3: hypotheses from published
literature, fixed published parameters, tested once, never re-tuned.
This round asks a genuinely different question from rounds 1-3
(momentum/trend/fundamental-drift rules): do the famous calendar
anomalies survive on SPY?

## Why calendar anomalies, and why this universe

Thirteen strategies have been tested honestly (H1-H11 plus two intraday
books); none beats SPY buy & hold out-of-sample. The remaining gap in
coverage is the most-cited family of calendar anomalies, all published
well before 2016, all testable on the SPY daily bars already in this
repo (`data/SPY_1Day.csv`, 2016-01-06 → 2026-09-09). No new data is
needed. Each rule is a fixed published recipe — no parameters to tune.

Universe: SPY only, long-only, cash-account compatible (no shorting).
Signal at close *t*; fills at the next open (*t+1*). Costs 5 bps/side,
same as rounds 2-3. When a rule says "cash", the sleeve holds cash
(the account cannot hold T-bills directly).

## Hypotheses (exactly three)

**H12 — Halloween indicator / "Sell in May"** (Bouman & Jacobsen, 2002,
"The Halloween Indicator, 'Sell in May and Go Away'", *AER* 92).
Hold SPY from the November-April "winter" half-year; hold cash
May-October. Signal at the October/April month-end close; fills at the
next open. Two round-trips per year.

**H13 — Pre-holiday effect** (Ariel, 1990, "High Stock Returns Before
Holidays", *JFE* 27).
Hold SPY only on the trading day immediately preceding a NYSE holiday;
hold cash on all other days. NYSE holidays 2016-2026 hardcoded:
New Year's Day, MLK Day, Presidents' Day, Good Friday, Memorial Day,
Juneteenth (from 2022), Independence Day, Labor Day, Thanksgiving,
Christmas. When the holiday falls on a weekend, the preceding Friday is
the observed holiday and Thursday is the pre-holiday day (exchange
calendar convention). ~8-9 one-day holds per year.

**H14 — Santa Claus rally** (Hirsch, *Stock Trader's Almanac*).
Hold SPY over the last 5 trading days of the calendar year plus the
first 2 trading days of the new year ("Santa Claus rally" window as
published); hold cash the rest of the year. Two round-trips per year,
7 trading days of exposure.

## Measurement

- In-sample 2016-01-06 → 2023-07-06 and out-of-sample 2023-07-06 →
  2026-09-09, same split as rounds 2-3. In-sample is shown for context
  only; **the verdict uses OOS only**.
- Benchmark: SPY buy & hold over the same window.
- Sixteen strategies will then have been tested (H1-H11, two intraday
  books, H12-H14). The OOS t bar is **2.96** (two-sided p < 0.05/16,
  Bonferroni).

## Verdict rule (all must hold, OOS, net of costs)

1. t-stat ≥ 2.96 on OOS daily excess returns vs SPY.
2. Sharpe > SPY buy & hold OOS Sharpe.
3. Max drawdown < SPY buy & hold OOS max drawdown.

Anything failing any bar is a FAIL. Per this pre-registration, no
round-4 strategy is re-tuned or re-tested on this data, whatever the
outcome.

## Honest prior (disclosed upfront)

These are the most famous and most arbitraged anomalies in the
literature; the base rate for a PASS here is low. Three more FAILs
would still be useful evidence: 16 honest tests with zero market-beaters
is itself the finding, and it would settle the open question toward
hardening the current SPY + paper-test setup instead of hunting for a
16th idea.
