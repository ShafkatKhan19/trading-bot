# Results — pre-registered round 14: corporate payout-event announcements (2026-10-23)

Pre-registration: `PREREGISTRATION_2026-10-23_round14.md` (committed
`12555dd` locally / `5391686` on GitHub before any round-14 code or
result). Code: `round14_research.py`; data build:
`fetch_payout_events.py`. 5 bps per side everywhere; in-sample
2016-01-04 → 2023-07-06 is context only; verdicts on OOS
2023-07-07 onward. Fifty-three strategies have now been tested
all-time, so the Bonferroni OOS t bar is **3.35** as registered
(the house t formula at the realised OOS daily df prints 3.32;
no verdict is within reach of either number). Full output:
`data/round14_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| SPY buy & hold (benchmark) | +20.6% | 1.32 | — | 18.8% | — |
| H50 Buyback authorizations (8-K) | +18.5% | 1.29 | −0.41 | 18.2% | **FAIL** (excess, t, Sharpe) |
| H51 Dividend increases / initiations | +19.3% | 1.42 | −0.27 | 15.1% | **FAIL** (excess, t) |

PASS required all three: OOS annualised excess vs SPY > 0,
excess t ≥ bar, and OOS Sharpe above SPY's.

**H50** fails all three legs. The 26 most recent buyback
authorizers (trailing-12-month window; 683 events across 74
tickers, eligible names per month min 22 / median 29) returned
+18.5%/yr against SPY's +20.6% — a −2.1%/yr excess with
t −0.41 — and a Sharpe of 1.29, just below SPY's 1.32. The
authorization-announcement drift documented in the older
literature does not survive contact with this universe and
window: recent authorizers are simply a rotating cast of
large, cash-rich companies, and in a mega-cap-led bull that
cast slightly lags the index it mostly overlaps. In-sample
context: H50 +14.9% (Sharpe 0.83).

**H51** fails on excess and t. Dividend raisers and initiators
(983 raise/initiation events, 138 of them initiations, across
73 tickers; eligible names per month min 34 / median 49)
returned +19.3%/yr — a −1.3%/yr excess, t −0.27 — with a
Sharpe of 1.42 that did beat SPY's 1.32 and the round's lowest
drawdown (15.1%). The book is smoother than the index and
makes slightly less money: the familiar defensive-tilt shape
(H37, H46), not an edge. A dividend raise, as first reported
in a 10-Q/K filing, carries no harvestable drift at this
horizon. In-sample context: H51 +15.7% (Sharpe 0.88).

**On the controls — read this before the numbers.** The
round-8 random-entry control prints eye-catching figures for
both books (H50: real +21.7%/trade vs random +0.7%, Welch
t +6.05; H51: +26.8% vs +1.4%, t +4.29). They are the known
horizon artifact, not corroboration: a "trade" in these
low-turnover monthly books closes only when a name leaves the
book, so real trades span months to years of a rising market,
while control holds are a fixed ~1 month. The control is not
horizon-matched — which is exactly why rounds 9–13 stopped
reporting it for slow books — and it is disclosed here, per
this round's registration, with that warning attached. The
deciding statistics are the daily excess series above, and
they are unambiguous: both books' daily excess means are
negative. No near-miss is claimed.

**Tally: 53 strategies tested all-time, 0 pass.**

## Data routes and coverage (as registered, with disclosures)

**H50 — EDGAR full-text search + Archives documents.**
Route: `efts.sec.gov/LATEST/search-index`, form 8-K, phrase
"repurchase program", one query per company CIK (the backend
intermittently returns HTTP 200 with an error payload; the
fetch retried until a real `hits` payload arrived, as
registered). 3,008 candidate documents all-time; 1,410 with
file dates on/after 2015-01-01 were fetched from EDGAR
Archives (0 failures) and passed through the registered
sentence rule (repurchase mention + "authoriz"/"increas" +
a dollar amount + no "previously announced"): 804 filings
qualified, deduped to **683 events** (same company, same
amount, within 365 days = one event) across 74 of 87 tickers,
2015-01-14 → 2026-10-20. Disclosures: (a) the exact-phrase
query has recall limits — XOM and ADP return zero candidates
(hyphenated "share-repurchase program" and other phrasings
are not matched), so those names can never enter the H50
book; the query was registered in advance and was not widened
after the fact. (b) The parsed amount is used only as the
dedupe identity, never as a signal input; a few amounts are
implausible as program sizes (multi-amount sentences), which
can split or merge an event at the margin but cannot move an
event's date. (c) Event date is the filing's `file_date`;
signals were usable only at that day's close, fills at the
next open — no look-ahead.

**H51 — EDGAR XBRL company-concept API.** Route:
`data.sec.gov/api/xbrl/companyconcept`, tag
`CommonStockDividendsPerShareDeclared` (USD/shares),
quarterly facts only (period span 80–100 days; the tag also
carries cumulative YTD and full-year spans, excluded as
registered), earliest-filed fact per period. **3,057
quarterly DPS facts across 73 of 87 tickers.** Eight names
have no usable tag history (AMZN, XOM, NFLX, ADBE, UPS, NEE,
SO, ISRG): four pay no dividend; four pay but do not report
this tag in this unit form — either way they are simply never
eligible, as the registration provided. Raises and initiations
were derived strictly from as-filed values in period order
(a resumption after a $0 declaration counts as an
initiation). One registered caveat bears repeating: declared
DPS is nominal, so splits mechanically lower it — splits can
mask a raise but cannot fabricate one. The most prominent
initiation in the window, GOOGL's (first declared DPS,
period ending 2024-06-30, first filed 2024-07-24), is in the
data and was eligible on schedule.

**Raw caches stay VM-local** (`data/payout/raw_docs/`,
1,409 documents, and the FTS hit index); both event files are
regenerable via `fetch_payout_events.py` and are pushed with
these results.

## What this closes

The corporate payout-event axis — buyback authorization
announcements and dividend increase/initiation announcements,
the two event types with the cleanest mechanisms in the
literature — has now been tested once, exactly as registered,
and neither produces a provable edge: both books trail SPY on
return with negative daily excess t-stats. The standing
programme result after fourteen rounds: **53 mechanical
strategies tested, 0 pass**; the two live paper forward tests
(H1, H10) remain the other evidentiary track, and any further
round still needs a genuinely new data axis.
