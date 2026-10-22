# Pre-registration — round 13: short positioning and institutional holdings (2026-10-21)

Written and committed BEFORE any round-13 code or results, per the
discipline in `FRONTIER_DECISION_2026-10-20.md`.

## Why this round exists

Round 12 closed the mechanical factor programme: 48 tested, 0
pass; momentum, calendar, value/quality/cash fundamentals (both
universes, single + blended + combined), insider buying, macro
regime, defensive multi-asset — all retired. The only open tracks
are the two live paper forward tests (H1, H10) and **genuinely new
data axes**. This round tests two axes never touched by the
programme: regulated short-positioning data (FINRA) and
institutional holdings data (13F). Neither was ruled out by the
frontier decision (which excluded intraday, options, and
non-public information). Post-earnings drift was already tested
and failed (H4, round 2) and is not revisited.

## Conventions

- Same engine conventions, cost (5 bps/side), in-sample/OOS split
  (verdicts OOS 2023-07-07 onward only) and point-in-time discipline
  as rounds 8–12. Universe L (87 large caps); cached daily bars.
- PASS requires all three legs: OOS annualised excess vs the
  registered benchmark > 0, one-sided excess t ≥ Bonferroni bar,
  OOS Sharpe > benchmark Sharpe. 51 strategies will have been
  tested after this round, so the bar is **t ≥ 3.32** (house
  method, same as rounds 11–12; realised value printed in the
  results file).
- A PASS deploys a $2,000 paper forward-test book automatically;
  a FAIL retires the hypothesis permanently. Each hypothesis is
  tested exactly once, as written. No family-closing rule is
  attached to this round; each hypothesis stands alone.

## Hypotheses

**H47 — Short-interest level (new axis: FINRA short positioning).**
Monthly rebalance on the last trading session of the month. Signal:
short interest as % of shares outstanding from the latest
FINRA-published snapshot as of the rebalance date. FINRA publishes
biweekly: mid-month snapshot (settlement the 15th) and end-of-month
snapshot, each published on the 7th business day after its
settlement date — so at a month-end rebalance the latest *published*
snapshot is the mid-month snapshot of the same month. Long the 26
Universe-L names with the lowest SI % of shares outstanding, equal
weight, next-open fills. Benchmark: SPY buy & hold. Rationale,
registered in advance: the Miller (1977) overpricing hypothesis —
heavily shorted stocks are overpriced relative to fundamentals;
a long-only book that systematically avoids the most-shorted names
harvests the avoidance side of that premium.

**H48 — Short-interest change (crowding/covering flow).**
Monthly rebalance, same schedule and fills as H47. Signal: change
in SI % of shares outstanding between the two most recent
FINRA-published snapshots as of the rebalance date (mid-month vs
end-of-previous-month). Long the 26 names with the largest
*decrease* in short interest, equal weight, next-open fills.
Benchmark: SPY buy & hold. Rationale, registered in advance: a
falling short count is covering-driven buying pressure plus
improving informed sentiment — a positioning-flow mechanism,
distinct from H47's level mechanism and not a price-momentum
variant (round 7 closed price momentum only; this signal is
short-position flow).

**H49 — 13F institutional consensus (new axis: holdings).**
Quarterly rebalance on the first trading session of March, June,
September and December. Signal: net manager breadth — (# of
13F-HR reporting managers increasing reported shares in the name
quarter-over-quarter) minus (# decreasing) — from EDGAR 13F-HR
filings, amendments resolved by taking each manager's latest
filing per quarter. Availability rule: quarter Q's data is usable
only from Q-end + 50 calendar days (45-day filing deadline plus a
5-day safety margin), so the March rebalance uses Q4 data, June
uses Q1, and so on. Long the 26 names with the highest net
breadth, equal weight, next-open fills. Benchmark: SPY buy & hold.
Rationale, registered in advance: institutional 13F flow is
informed capital revealing itself with a lag; consensus additions
across many independent managers should predict outperformance if
the information is real and not yet fully priced. This is a
holdings axis — not price, fundamentals, or macro — and is
untouched by all 48 prior tests.

## Data notes

- FINRA short interest: public, free, no key; historical files per
  FINRA's published schedule. Coverage starts at 2016-01-01 if all
  needed series exist then; otherwise the evaluation window starts
  at the first date all series exist, disclosed in the results.
- 13F-HR: public EDGAR filings, parsed with the rounds 8–10 EDGAR
  infrastructure extended to the 13F-HR form; manager identity by
  CIK. Same coverage rule as above.
