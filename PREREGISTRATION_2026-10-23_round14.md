# Pre-registration — round 14: corporate payout-event announcements (2026-10-23)

Written and committed BEFORE any round-14 code or results, per the
discipline in `FRONTIER_DECISION_2026-10-20.md`.

## Why this round exists

51 strategies tested, 0 pass. Closed: momentum (family), calendar,
price factors, SEC fundamentals value/quality/cash (both universes,
single + blended + combined), insider Form 4 buying, yield-curve
regime, defensive multi-asset, FINRA short interest, 13F breadth.
The remaining honest lever named by the frontier decision is a
**genuinely new data axis**. This round tests one: **corporate
payout-event announcements in SEC filings** — the dates and terms
on which boards publicly commit capital back to shareholders.
Neither a level factor (H38 shareholder yield used trailing
payout *levels*) nor a filing-content signal has ever been tested
by this programme; the event itself is the signal.

Axes considered and rejected, with reasons:

- **Post-earnings-announcement drift keyed to SEC filings** —
  already tested as H4 (round 2, yfinance surprises) and failed;
  round 13's registration explicitly retired it. Not revisited.
- **Analyst estimate revisions** — no free point-in-time
  historical consensus/revision archive exists (current snapshots
  only); using today's consensus history would be look-ahead.
- **8-K item 5.02 officer turnover** — mechanically detectable,
  but the return sign is ambiguous in the literature and the
  event is a governance signal, not a payout commitment; the
  payout events below have the cleaner registered mechanism.

## Conventions

- Universe L (87 large caps, survivorship bias disclosed as in
  every round since round 2); cached daily bars (`round8`
  loader); benchmark SPY buy & hold.
- Monthly engine identical to rounds 3/8/13: signals at
  month-end close, fills at next open, 5 bps per side, long-only,
  equal weight, starting cash $2,000.
- In-sample 2016-01-01 → 2023-07-06 is context only; verdicts on
  OOS 2023-07-07 onward only.
- PASS requires all three legs: OOS annualised excess vs SPY
  > 0, one-sided excess t ≥ Bonferroni bar, OOS Sharpe > SPY
  Sharpe. 53 strategies will have been tested after this round,
  so the bar is **t ≥ 3.35** (house method; realised value
  printed in the results file).
- A random-entry control (round-8 method: the book's own traded
  names, same count of ~1-month holds entered on random
  month-ends, fixed seed, Welch t) is reported for both
  hypotheses for context; the PASS legs above decide.
- A PASS deploys a $2,000 paper forward-test book automatically;
  a FAIL retires the hypothesis permanently. Each hypothesis is
  tested exactly once, as written.

## Hypotheses

**H50 — Share-repurchase authorizations (new axis: 8-K event
text).** Event = an SEC Form 8-K filing by the company whose
text announces a NEW or INCREASED share-repurchase
authorization. Mechanical detection, fixed in advance:
EDGAR full-text search (form 8-K, the phrase "repurchase
program", per company CIK) enumerates candidate documents; a
candidate filing is an event if a sentence in its text (i)
mentions repurchase of shares/stock, (ii) contains "authoriz"
or "increas", (iii) contains a dollar amount, and (iv) does not
contain "previously announced". The event amount is the largest
dollar figure in the qualifying sentences; repeat filings by
the same company with the same amount within 365 days are the
same event (earliest filing date kept). The event date is the
filing's EDGAR `file_date` — the first day the announcement is
public; the signal is usable at that day's close.
Book: at each month-end, eligible names are those whose latest
event is within the trailing 12 months; long the 26 with the
most recent events (ties: earlier filing first, then ticker
A–Z), equal weight. If 1–25 names are eligible, hold all of
them equal-weight; if none, hold cash.
Rationale, registered in advance: an authorization is a public,
costly-to-fake commitment that management believes the stock is
undervalued (Ikenberry–Lakonishok–Vermaelen); the drift, if
real, accrues over the months after announcement, which a
12-month eligibility window harvests.

**H51 — Dividend increases and initiations (new axis: payout
announcements as filed).** Data: EDGAR XBRL company-concept
facts for declared dividends per share
(`CommonStockDividendsPerShareDeclared`, USD/shares), restricted
to quarterly facts (period span 80–100 days — the same tag also
carries cumulative year-to-date and full-year spans, which are
excluded). One value per fiscal period = the earliest-filed
fact for that period (first public availability, the rounds
8–10 convention; later filings restate the same period as
comparatives and are ignored). A
**raise** is a period whose declared DPS is strictly greater
than the immediately preceding period's declared DPS for the
same company; an **initiation** is a positive declared DPS
after at least 8 consecutive periods with no declared-DPS fact
for the company. The event date is the raise/initiation fact's
earliest `filed` date (the 10-Q/K filing that first reports the
declaration — conservative: the signal is only credited once
the filing is public, never at period end).
Book: at each month-end, eligible names are those whose most
recent raise/initiation was first filed within the trailing 12
months. Long the top 26 ranked by: initiations first, then
percentage increase over the prior declared DPS, descending
(ties: most recent filing first, then ticker A–Z), equal
weight. If 1–25 names are eligible, hold all; if none, cash.
Rationale, registered in advance: dividend increases are the
classic costly signal of management's confidence in future cash
flows (Lintner; Asquith–Mullins); initiations are the strongest
form. If the signal is real and under-reacted to, raisers
outperform over the following year.
Known data caveats, registered in advance: declared DPS is
nominal, so a stock split mechanically lowers it — splits can
delay or mask a raise but cannot fabricate one; a small number
of universe names may lack the XBRL tag entirely and are simply
never eligible.

## Data notes

- EDGAR full-text search: public, free, no key
  (`efts.sec.gov/LATEST/search-index`). The backend
  intermittently returns HTTP 200 with an error payload instead
  of results; the fetch script retries until a real `hits`
  payload arrives.
- EDGAR XBRL company-concept API: public, free, no key
  (`data.sec.gov/api/xbrl/companyconcept`), the same route as
  rounds 8–10.
- Coverage contingency (same as round 13): if a series starts
  later than 2016, the evaluation window still starts 2016 with
  the book in cash until the signal exists, disclosed in the
  results.
