# Results — pre-registered round 15: small-cap insider cluster buying (2026-10-23)

Pre-registration: `PREREGISTRATION_2026-10-23_round15.md`
(committed `f69879e` locally / `f0af6b6` on GitHub before any
round-15 code or result). Code: `round15_research.py`; data
build: `fetch_insider_clusters.py`. 5 bps per side on turnover;
small-cap engine conventions (adjclose basis, signal at
month-end close, returns from the next session's close);
in-sample 2016-01-01 → 2023-07-06 is context only; verdicts on
OOS 2023-07-07 onward. Fifty-four strategies have now been
tested all-time, so the Bonferroni OOS t bar is **3.33** as
registered (the house t formula at the realised OOS daily df
prints 3.32; the verdict is not within reach of either number).
Full output: `data/round15_report.json`.

| OOS, net of costs | CAGR | Sharpe | t(excess) | Max DD | Verdict |
|---|---|---|---|---|---|
| IWM buy & hold (benchmark) | +14.1% | 0.74 | — | 27.5% | — |
| H52 Insider cluster buying (Universe S) | +19.8% | 0.85 | +0.73 | 29.5% | **FAIL** (t) |

PASS required all three: OOS annualised excess vs IWM > 0,
excess t ≥ bar, and OOS Sharpe above IWM's.

**H52 clears two legs and fails the one that matters.** The
cluster book — small caps where ≥3 distinct insiders filed
open-market purchases within the trailing 90 days — returned
+19.8%/yr against IWM's +14.1% (+5.7%/yr excess) with a Sharpe
of 0.85 vs 0.74. But the daily excess t is **+0.73 against a
3.32 bar**: at this programme's evidentiary standard the edge
is indistinguishable from noise, and H52 is retired as
registered. In-sample context: H52 +13.9%/yr (Sharpe 0.60).

**The control does not corroborate — read this before the
headline.** The round-5 control is horizon-matched (200 random
same-size draws per rebalance from the same price-eligible
pool, same entry/exit dates), so it carries none of round 14's
horizon artifact — and it is flat: strategy gross
+1.60%/rebalance vs random +1.41%/rebalance, Welch t **+0.21**.
Picking cluster names at random sizes earned essentially what
picking *any* price-eligible small caps earned. The +5.7%/yr
headline excess is therefore best read as a concentrated,
higher-beta slice of a rising small-cap universe — max
drawdown 29.5% vs IWM's 27.5% — sitting on the disclosed
Universe S survivorship bias, not as evidence that the cluster
event itself carries information. This is the H33/H43 pattern
(small-cap value) repeating on a new axis: positive excess,
better Sharpe, no statistical substance, uncorroborated
control.

**Book structure.** Clusters are denser in small caps than
H39's net-buying signal was in large caps — but still sparse:
cluster-eligible names per month-end **min 0, median 15, max
87** (the max is the March-2020 crash-buying window), and the
top-60 cap bound in only 3 of 136 months. In a typical month
the book is simply *all* current cluster names, ~15 of them,
equal weight — a concentrated book whose ranking rule rarely
gets to rank. One registered month had zero eligible names
(cash). H39's sparsity problem (median 5) is improved 3×, not
solved.

**Tally: 54 strategies tested all-time, 0 pass.** Per the
round's tasking nothing was deployed; a FAIL would have meant
no deployment in any case.

## Data route and coverage (as registered, with disclosures)

**SEC Insider Transactions Data Sets** (quarterly bulk ZIPs of
as-filed Forms 3/4/5; public, free, no key): all **44 archives
from 2015Q4 through 2026Q3** were downloaded and scanned —
**1,984,555 original Form 4 submissions**, of which 9,855 are
Universe S purchase filings (≥1 non-derivative code-P,
acquired, shares > 0, price > 0 transaction) across **555 of
the 603** Universe S tickers, totalling $16.38B of qualifying
purchases, filing dates 2015-10-01 → 2026-09-30. Zero filing
dates failed to parse. Amendments (4/A) were excluded per the
registration (round-10 convention, no double counting); the
signal date is each filing's `FILING_DATE`, never its
transaction date — no look-ahead. **Coverage cutoff:**
`LASTDATE` = 2026-09-30, which is also the panel's last signal
month-end, so the registered move-to-cash rule never bound;
every traded month had complete coverage. 48 universe tickers
never appear in the purchase data — no qualifying P filing was
ever made under their current as-filed symbol (ticker changes
are absorbed by the disclosed survivorship caveat, never
back-filled), and one listed name (CWEN-A) has no bars at all.
The raw ZIPs (~450 MB) stay VM-local under
`data/insider_sc/raw/`; the derived `cluster_filings.csv` and
`coverage.json` are pushed with these results and the panel is
regenerable via `fetch_insider_clusters.py`.

**Scout record** (full reasoning in the pre-registration):
options-implied data has no free point-in-time 2016–2026
archive (Cboe history is paid; free tiers are current
snapshots); GDELT news tone has no point-in-time-valid
name→ticker mapping for Universe S; market breadth is a
transform of the already-tested price bars, adjacent to the
closed momentum family; 10-K text sentiment is annual and
sits on the exhausted EDGAR-fundamentals axis, and
earnings-call transcripts are not in EDGAR. The cluster axis
was the one candidate with structured, filing-date-stamped,
freely downloadable point-in-time data.

## What this closes

The insider axis is now tested in both universes and both
registered forms — net buying in large caps (H39, failed on
sparsity) and cluster breadth in small caps (H52, failed on
the t-stat with an uncorroborated control) — and is closed.
The standing programme result after fifteen rounds: **54
mechanical strategies tested, 0 pass**; the two live paper
forward tests (H1, H10) remain the other evidentiary track,
and any further round still needs a genuinely new data axis.
