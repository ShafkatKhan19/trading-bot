# Results — pre-registered round 9: fundamentals, second wave (2026-10-20)

Pre-registration: `PREREGISTRATION_2026-10-20_round9.md` (committed
before any round-9 code or result). Code: `round9_research.py`;
data builds: `fetch_fundamentals_sc.py` (small-cap panel) and
`fetch_fundamentals_v2.py` (universe-L Assets/OCF extension).
Costs 5 bps per side. H32/H33: S&P SmallCap 600 on Yahoo adjclose,
signal at month-end, returns from the next session's close, top 60
equal weight, benchmark IWM (round-5 conventions). H34/H35:
universe L, month-end closes, fills at next open, top 26 equal
weight, benchmark SPY (rounds 1–4 conventions). In-sample
2016-01-01 → 2023-07-06 is context only; verdicts on OOS
2023-07-07 onward. Thirty-seven strategies have now been tested,
so the Bonferroni OOS t bar is **3.22**. Full output:
`data/round9_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Control t | Verdict |
|---|---|---|---|---|---|---|
| SPY buy & hold (benchmark, H34/H35) | +20.6% | 1.32 | — | 18.8% | — | — |
| IWM buy & hold (benchmark, H32/H33) | +14.1% | 0.74 | — | 27.5% | — | — |
| H32 Small-cap earnings yield | +18.3% | 0.85 | +0.68 | 30.9% | +0.36 | **FAIL** (t) |
| H33 Small-cap book-to-market | +25.3% | 1.05 | +1.48 | 25.0% | +0.93 | **FAIL** (t) |
| H34 Buyback yield (L) | +15.4% | 1.11 | -0.88 | 17.7% | n/a | **FAIL** (excess, t, Sharpe) |
| H35 Low accruals (L) | +13.2% | 1.01 | -1.29 | 17.9% | n/a | **FAIL** (excess, t, Sharpe) |

PASS required all three: OOS annualised excess vs the benchmark
> 0, excess t ≥ 3.22, and OOS Sharpe above the benchmark's. None
of the four passes.

## Point-in-time guarantee

Identical to round 8: every fundamental value is an SEC filing
fact usable only on or after its `filed` date, earliest filing
kept per fiscal period, and a row becomes usable only once ALL
of its facts are public (three facts for H32–H34; five for H35,
including Assets and operating cash flow). Rankings therefore
use exactly what an investor could have known that day.

## Data and coverage

- **Small-cap panel** (`panel_smallcap.csv`): 9,003 fiscal-year
  rows, 7,408 complete. **554 of 603** S&P SmallCap 600 tickers
  have at least one complete FY row; **462** reach back to a
  fiscal year ending ≤ 2017-12-31. Eligibility in the engine
  (complete filed row + ≥252 sessions of prices): median 462
  names per month-end. As pre-registered, coverage is thinner
  than universe L's (74/87 ≈ 85%; here 554/603 ≈ 92% have any
  complete row, but depth is shallower — 91 names have fewer
  than 8 complete FY rows, mostly recent IPOs and spin-offs).
- Four tickers — CWEN.A, HLX, LEG, QRVO — have no CIK in the
  SEC's `company_tickers.json` under either symbol form, so
  they are uncovered by the registered mapping source and
  excluded; another 45 names have filings but no complete FY
  row under the registered tags. The dei cover-share tag
  covered less than half of a name's filings for 65 names,
  which used the pre-registered weighted-average-basic
  fallback, exactly as in round 8.
- **Universe-L extension** (`panel_l_v2.csv`): merging Assets
  and operating cash flow onto the round-8 rows gives 1,058
  rows complete in all five facts across the same **74 of 87**
  tickers (67 reaching back to FY ≤ 2017-12-31). F returns zero
  FY facts under both new tags, consistent with its round-8
  tagging gaps. The five-fact requirement shrinks ROWS (1,058
  vs 1,173 three-fact rows) but not the ticker count.
- **Survivorship caveat, stated loudly for H32/H33:** the
  small-cap universe is TODAY'S S&P SmallCap 600 list. Names
  that failed, were acquired cheap, or were dropped since 2016
  are absent, biasing both books upward — and a value screen
  (H33) is precisely where the missing bankrupt names would
  have hurt most. Treat the small-cap excess returns below as
  upper bounds, not estimates.
- Registered-definition caveat carried from round 8: market
  cap uses adjusted closes × as-filed shares (split-window
  distortion disclosed, not patched).

## Notes

- **H33 (small-cap book-to-market) posts the largest headline
  excess of the entire programme — and still fails.** +25.3%/yr
  against IWM's +14.1%/yr is +11.2%/yr of excess, with a better
  Sharpe (1.05 vs 0.74) and a shallower drawdown (25.0% vs
  27.5%). But the excess t is +1.48 against the 3.22 bar, and
  the horizon-matched control agrees there is little here:
  strategy gross +2.26%/rebalance vs +1.38% for random 60-name
  draws from the same eligible pool, Welch t +0.93. The daily
  excess series is simply too noisy — a small-cap value book
  and IWM diverge enough month to month that 3.3 OOS years
  cannot certify an 11-point gap, and the survivorship bias
  above plausibly manufactures a good part of it. FAIL on the
  registered bar, final.
- **H32 (small-cap earnings yield) is H33's weaker sibling:**
  +18.3%/yr (excess +4.2%/yr), Sharpe 0.85 above IWM's 0.74,
  but t +0.68 and control t +0.36 — the picks beat random
  same-pool draws by a statistically meaningless margin. The
  large-cap version (H29) had the same shape: ahead on return
  and Sharpe, nowhere on evidence.
- **H34 (buyback yield) fails everything and was never close
  OOS:** +15.4%/yr vs SPY's +20.6% (excess −5.2%/yr, t −0.88,
  Sharpe 1.11 < 1.32), despite a respectable in-sample +14.9%.
  Shrinking share counts in large caps mostly identify mature
  mega-caps that lagged a tech-led benchmark. Implementation
  choice, documented per the run instructions: the year-ago
  share count is the FY row whose fiscal year-end falls
  330–400 days before the latest row's (closest to −365); if
  none exists, the most recent FY row ending ≥300 days earlier.
  No control is reported — slow turnover (120 exits) makes the
  round-3 control horizon-mismatched (round-8 caveat).
- **H35 (low accruals) fails everything too:** +13.2%/yr
  (excess −7.4%/yr, t −1.29, Sharpe 1.01), 109 exits. The
  Sloan accruals signal, at annual frequency on large caps
  with point-in-time filings, does not survive contact with a
  2023–2026 benchmark window. No control, same caveat as H34.

## Code fixes during the run

One, in the DATA BUILD only, before any backtest ran: the
first small-cap EDGAR fetch died after 371 of 603 tickers on
an unhandled `ProxyError` (a transient egress-proxy drop;
`requests` exceptions bypass the fetcher's status-code
retries). `fetch_fundamentals_sc.py` now retries connection
errors with backoff and skips-and-logs a ticker whose fetch
ultimately fails instead of aborting the build; the run then
completed with zero failed tickers, reusing the 1,121 cached
raw responses. No strategy rule changed, and the research
script itself ran once, unmodified. The raw caches (43 MB
small-cap, in `data/fundamentals/raw_sc/`, plus the new L
concept files in `raw/`) were left uncommitted — regenerable
with the two fetch scripts.

## Tally

Thirty-seven strategies tested honestly across nine rounds;
none has beaten its benchmark out-of-sample on the registered
bars. Round 9's fundamentals wave repeated round 8's pattern
one size smaller: value-flavoured books (H32/H33) ahead of
their benchmark on return and Sharpe, far behind on statistical
evidence, with controls that decline to corroborate them.
Per the pre-registration, none of H32–H35 is re-tuned or
re-tested on this data, and none has earned a forward test.
