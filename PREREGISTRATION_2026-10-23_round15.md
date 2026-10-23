# Pre-registration — round 15: small-cap insider cluster buying (2026-10-23)

Written and committed BEFORE any round-15 code or results, per the
discipline in `FRONTIER_DECISION_2026-10-20.md`.

## Why this round exists

53 strategies tested, 0 pass. Closed/retired: price momentum
(family), calendar effects, small-cap price factors, EDGAR
fundamentals value/quality/cash in all forms (both universes,
single + blended + combined), insider Form 4 **net** buying in
large caps (H39), FRED yield-curve regime, defensive multi-asset
inverse-vol, FINRA short interest level/change, 13F manager
breadth, PEAD (H4), payout events (H50/H51). A further round
needs a genuinely new axis or an honest stop. This round tests
the one candidate below that survives a feasibility scout with
free, public, point-in-time data.

## Candidate axes scouted, and the verdicts

- **(a) Options-implied information — REJECTED (infeasible).**
  No free source offers point-in-time historical option chains,
  put/call ratios or IV term structure for a 2016–2026 equity
  universe. Cboe DataShop history is a paid product; free vendor
  tiers expose current snapshots or ~2 years of summary history
  only — far short of the registered window, and a
  current-snapshot archive would be look-ahead. The frontier
  decision already flagged this ("no free historical options
  data of usable quality"); the 2026-10-23 re-scout confirms it
  is still true.
- **(b) News sentiment via GDELT — REJECTED (mapping not
  point-in-time-valid).** GDELT's article tone is real and free,
  but GKG organisation mentions are company *names*, not
  tickers: there is no stable historical name→ticker map for
  Universe S, common-word names (and renamed/merged issuers)
  make matches ambiguous, and tone is article-level, not
  company-attributed. A signal built on guessed mappings would
  not meet this programme's evidentiary standard.
- **(c) Market breadth/internals regime — REJECTED (not a new
  axis).** Advance/decline and %-above-trend are transforms of
  the same cached price bars every price round already used,
  and %-above-trend is cross-sectional trend — adjacent to the
  price-momentum family closed in round 7. Calling it a new
  data axis would be relabelling, so it is not run.
- **(d) Insider Form 4 CLUSTER buying in small caps — CHOSEN.**
  See below.
- **(e) 10-K / earnings-call text sentiment — REJECTED for
  this round (weaker feasibility).** Earnings-call transcripts
  are not in EDGAR at all. 10-K text is public and
  filing-date-stamped, but the signal is annual (one observation
  per name-year, stale up to 12 months), needs a dictionary and
  section-extraction choices with no house precedent, and sits
  on the same EDGAR-fundamentals axis rounds 8–12 exhausted.
  Ranked below (d) on data structure and signal density; not
  run.

## Why (d) is a new test, not a re-run of H39

H39 (round 10) failed in **Universe L**: net (P−S) dollars over
6 months scaled by market cap, and the signal was too sparse to
fill the book — median **5** qualifying names/month against 26
slots, the rest filled by largest-market-cap names. H52 differs
on every registered dimension: **universe** (S, ~600 names, not
L), **event definition** (a *cluster*: ≥3 **distinct**
reporting owners with open-market **purchases** in the window —
sales are never netted), **window** (90 days, not 6 months),
and **ranking** (buyer breadth first, not net dollars). The
mechanism is the cluster-buying result in the insider
literature (Cohen–Malloy–Pomorski; Ali–Wei): independent
insiders buying together is the informative event, and small
caps are where clusters are dense enough to test it. Data
route is also new to the programme: the SEC's structured
**Insider Transactions Data Sets** (quarterly bulk ZIPs of
as-filed Forms 3/4/5), not the per-filing XML crawl of round 10.

## Conventions

- **Universe S**: the current S&P SmallCap 600 list (603 tickers,
  `data/smallcap/tickers.csv`), cached Yahoo bars, adjclose
  basis — the rounds 5/9 small-cap setup, including its
  disclosed **survivorship bias** (today's list; names that
  failed or were acquired since 2016 are absent, biasing
  results upward; a PASS would earn only a paper forward test).
- **Engine**: round-5 small-cap engine. Monthly: signal at
  month-end close; positions earn returns from the **next
  session's close** onward (adjclose basis — the registered
  small-cap deviation from the open-fill convention; no open
  prices are used). 5 bps per side on turnover. Starting cash
  $2,000. Benchmark: **IWM** buy & hold.
- **Price eligibility** (round-5 rule): a name is eligible at a
  month-end only with ≥252 sessions of bar history and a
  non-missing adjclose on the signal date.
- In-sample 2016-01-01 → 2023-07-06 is context only; verdicts on
  OOS 2023-07-07 onward only.
- **PASS** requires all three legs: OOS annualised excess vs
  IWM > 0, one-sided excess t ≥ Bonferroni bar, OOS Sharpe >
  IWM Sharpe. 54 strategies will have been tested after this
  round, so the bar is **t ≥ 3.33** (house method; realised
  value printed in the results file).
- **Control** (context only; the PASS legs decide): the
  round-5 horizon-matched random-entry control — 200 random
  same-size draws per rebalance from the price-eligible
  Universe S pool on the same entry/exit dates, gross
  per-rebalance returns, Welch t, fixed seed. Any
  horizon-mismatch or selection artifact in the control will
  be flagged explicitly, as in round 14.
- A FAIL retires the hypothesis permanently. The hypothesis is
  tested exactly once, as written. Per this round's tasking,
  **no book is deployed from this run regardless of verdict**;
  a PASS is reported up, not deployed.

## Hypothesis

**H52 — Small-cap insider cluster buying (new axis: SEC
Form 4 cluster breadth, Universe S).**

Data build, fixed in advance:

- Source: SEC Insider Transactions Data Sets, quarterly ZIPs
  (public, free, no key), every archive whose filings fall in
  2015-10-01 → the latest available quarter at build time.
  Tables used: `SUBMISSION` (accession, filing date, submission
  type, issuer trading symbol), `REPORTINGOWNER` (accession,
  reporting-owner CIK), `NONDERIV_TRANS` (accession,
  transaction code, acquired/disposed code, shares, price).
- Keep **original Form 4 submissions only** (submission type
  exactly `4`); amendments (`4/A`) are excluded to avoid double
  counting — the round-10 convention — and Forms 3/5 are out
  of scope.
- A **qualifying purchase** is a non-derivative transaction
  with code `P` (open-market/private purchase),
  acquired/disposed code `A`, shares > 0 and price > 0. Its
  dollar value is shares × price. A filing is a *purchase
  filing* for an issuer if it contains ≥1 qualifying purchase.
- Issuer identity is the **as-filed trading symbol** in
  `SUBMISSION`, normalised only by `.` → `-` (Yahoo class
  tickers, e.g. `BF.B` → `BF-B`) and matched to Universe S.
  Symbols that do not match the current Universe S list are
  ignored (ticker changes are absorbed by the disclosed
  survivorship caveat, never back-filled).
- **Point-in-time rule**: a filing is usable only for signal
  dates on/after its `FILING_DATE` (the date it became public
  in EDGAR). Transaction dates are never used for timing.
- **Coverage cutoff**: let `LASTDATE` be the maximum
  `FILING_DATE` among original Form 4 submissions in the
  downloaded archives. Signals are computed for month-ends
  ≤ `LASTDATE`; at the first month-end after `LASTDATE` the
  book targets cash and stays in cash — a stale cluster is
  never traded on incomplete coverage. `LASTDATE` and the
  number of archives used are printed in the results.

Signal and book, at each month-end signal date `D`:

- Window: filings with `FILING_DATE` in (`D` − 90 days, `D`].
- For each price-eligible Universe S name: `n_buyers` = number
  of **distinct reporting-owner CIKs** on its purchase filings
  in the window (a joint filing counts each listed owner; one
  owner with many filings counts once); `buy_usd` = summed
  qualifying purchase dollars in the window; `last_filed` =
  latest purchase-filing date in the window.
- **Cluster-eligible**: `n_buyers` ≥ 3.
- Rank cluster-eligible names by `n_buyers` descending, then
  `buy_usd` descending, then `last_filed` descending, then
  ticker A–Z. Long the **top 60** (≈10% of Universe S, the
  round-9 small-cap book size), equal weight. If 1–59 names
  are eligible, hold all of them equal-weight; if none, hold
  cash.

Rationale, registered in advance: a single insider purchase is
noisy (10b5-1 plans, token buys); three or more independent
insiders committing their own money in the same 90 days is the
cluster event the literature identifies as informative, and it
should be most visible in small caps, where analyst coverage
is thin and insider information advantage is largest. If the
effect is real and under-reacted to at a monthly horizon, the
cluster book beats IWM out-of-sample; if H39's failure was
really "insider buying carries no signal anywhere", H52 fails
too and the insider axis closes in both universes.

## Known caveats, registered in advance

- The bulk data sets are as-filed extracts; the SEC warns they
  may contain filer errors and are no substitute for the source
  filings. Fields are used exactly as filed.
- Form 4 purchases made under pre-arranged 10b5-1 plans are
  **not** filtered: the structured plan flag exists only from
  2023 in these data sets, so filtering would treat eras
  unequally. The cluster requirement (≥3 distinct owners) is
  the registered mitigation.
- The data sets include some non-common equity (units,
  preferred) non-derivative purchases under an issuer's symbol;
  no security-title filter is applied — the round-10
  convention — so a cluster is an issuer-level event, as
  registered.
- Survivorship bias (Universe S) applies in full and is the
  standing prime suspect for any strong-looking result, as it
  was for H33/H43.
