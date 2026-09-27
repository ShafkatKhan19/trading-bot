# Honest Backtest Baseline — 2026-09-10

Measurement fixes A–E applied to `backtest_runner.py` and `constitution_builder.py`.
**No strategy parameter was retuned.** Every number here moved because the measurement
got more honest, not because the strategy changed.

---

## 1. Read this first: the headline number is not the finding

Total P&L barely moved (+$25.68 → +$28.89). **That is a coincidence, and it is
misleading.** Two large, opposite-signed errors were cancelling each other out. The
decomposition below is the real result.

| Run | Defects present | Trades | Total P&L | Win rate | Expectancy/trade | Avg P&L % | Max DD |
|---|---|---|---|---|---|---|---|
| **BEFORE** | A + B + C | 154 | **+$25.68** | **51.9%** | +$0.167 | +0.400% | 2.75% |
| A-only | B + C (ordering fixed) | 146 | +$57.67 | 49.3% | +$0.395 | +0.938% | 3.35% |
| B-only | A (costs fixed) | 154 | **−$39.12** | **36.4%** | −$0.254 | −0.730% | 8.09% |
| **AFTER** | none | 146 | **+$28.89** | **47.3%** | +$0.198 | +0.458% | 3.60% |

Symmetric transaction costs alone (B-only vs BEFORE) swing the result by **−$64.80**
and drop the win rate **15.5 points, from 51.9% to 36.4%** — below the 42%
`MIN_WIN_RATE` gate. That is the honest measure of how much of the edge was
transaction-cost illusion.

The audit's static estimate for B was −$29.13. The realised cost is roughly double
that, because the static estimate ignored compounding: position size is a fraction of
portfolio value, so early cost drag shrinks every later position.

Fixing the intrabar bias (A) happened to *add* P&L in this sample: not exiting on a
falsely-ratcheted trail leaves winners alive in a 4-year sample that trended up. That
is a property of this sample, not a source of edge, and it is the leg that will not
survive a sideways or down regime. **Do not read A-only's +$57.67 as good news.**

### Win rate is now below the configured gate on a cost-only basis

`config.MIN_WIN_RATE = 0.42`. The combined AFTER run passes at 47.3%, but only because
A's sample-specific tailwind offsets B. Strip that tailwind and the strategy fails its
own gate. Treat 47.3% as the optimistic end of the range, not the baseline.

---

## 2. Exit-reason distribution — bias A confirmed

| Exit reason | BEFORE | AFTER |
|---|---|---|
| trailing_stop | 75 | **67** |
| stop_loss | 65 | **66** |
| no_progress | 12 | 11 |
| time_exit | 2 | 2 |
| **trailing : stop_loss ratio** | **1.15 : 1** | **1.02 : 1** |

The audit predicted the ranking could flip. It did not flip, but the margin collapsed
to near-parity — 8 trailing-stop exits (10.7% of them) were fabricated by assuming the
bar's high always preceded its low.

### The clearest single piece of evidence

Distribution of `pnl_pct` on `trailing_stop` exits:

| | BEFORE | AFTER |
|---|---|---|
| min | **+1.85%** | **−0.65%** |
| avg | +4.26% | +5.17% |
| max | +17.42% | +20.51% |

**Before the fix, every single trailing-stop exit in 154 trades was profitable.** A
trailing stop that never once loses money is not a trading result, it is an artifact of
letting the stop ratchet up on a high that may have happened after the low that
triggered it. After the fix, trailing exits can lose, as they do in reality.

### Stop fills are no longer free

| | BEFORE | AFTER |
|---|---|---|
| stop_loss exits filling *exactly* at the stop price | **40 of 65** | **0 of 66** |
| worst stop_loss fill | −5.00% (= the 5% stop, capped) | **−5.87%** (gapped through) |
| median stop_loss fill | −5.00% | −5.19% |

BEFORE, the worst possible stop outcome was exactly the stop level — no gap, no
slippage, ever. AFTER, stops fill at `min(stop_price, bar_open)` minus slippage, so
overnight gaps punch through as they do live.

---

## 3. Changes applied

**A — intrabar ordering** (`backtest_runner.py`). The hard stop and the trailing stop
are now tested against `bar.low` using levels carried in from *prior* bars. Only if the
position survives the bar does `bar.high` update `highest_price`, activate the trail,
and ratchet it — taking effect from the next bar. Worst-case ordering assumed.

**B — symmetric costs + gap-through** (`backtest_runner.py`). New `exit_fill()` charges
slippage on every exit (`stop_loss`, `trailing_stop`, `no_progress`, `time_exit`, and
the end-of-run force-close). New `stop_fill()` fills stop exits at
`min(stop_price, bar_open)` before slippage, modelling overnight gaps.

**C — one cost model** (`backtest_runner.py`). The hard-coded `SLIPPAGE = 1.002` is
gone; `SLIPPAGE_PCT = config.STOP_SLIPPAGE_PCT` is now the single source of truth,
shared with the live path at `strategy.py:580`. The numeric value is unchanged (0.002),
so this is purely de-duplication — but the backtest and live bot can no longer drift
apart silently.

**D — dead per-segment score derivation** (`constitution_builder.py`). `score_wins` and
`best_score_wr` were initialised, never written, never read; `min_signal_score` was
always the config default. Implemented the intended derivation: `analyse_by_segment`
now records `score_outcomes` as `(score, won)` pairs, and `derive_segment_rules`
evaluates each candidate threshold `T` by the win rate of trades it would still admit
(`score >= T`). Guards, matching the existing `>= 20` convention used by `rsi_floor`
and `best_hold`:
- a threshold needs **≥ 20 admitted trades** before its win rate is trusted;
- candidates are floored at the config default, so backtest noise can only ever
  **tighten** entry quality, never loosen it (mirrors `max(default, derived)` in
  `rsi_floor`);
- two new output fields, `min_signal_score_source` (`derived` | `config_default`) and
  `min_signal_score_win_rate`, make the fallback explicit and auditable in
  `constitution.json`.

On the honest 146-trade dataset both segments now derive genuinely (`growth`: score 3,
51.1% win rate at threshold; `transport`: score 3, 41.1%). Unit-checked that it tightens
3 → 4 when the data supports it and falls back to `config_default` on thin samples.

**E — unordered chronological query** (`constitution_builder.py:24`). Added
`ORDER BY entry_date, id` to `fetch_trades()`. `analyse_trajectory` (first-half vs
second-half win rate) and `analyse_streaks` (trailing consecutive losses) both depend on
row order and were relying on undocumented SQLite rowid behaviour.

> On the interleaving concern: `analyse_streaks` already groups per symbol
> (`ticker_trades[sym].append(...)`) before walking `reversed(pnls)`, so with the new
> `ORDER BY` each symbol's list is genuinely chronological. No semantic change was
> needed and none was made.

---

## 4. Method

The pre-existing `trades.db` (379 backtest trades, +$11.61) was **not** used as the
before-baseline. It was generated by older code — `config.py`, `signals.py` and
`strategy.py` all have uncommitted modifications — so comparing against it would have
attributed unrelated changes to these fixes. Instead the pre-fix engine was
reconstructed from the current file by targeted text substitution and re-run against
identical data and config, so BEFORE and AFTER differ **only** by defects A/B/C.

Trade counts differ between runs (154 vs 146) because changing exit timing changes when
position slots free up, which changes which entries are taken. With ~150 trades this
path divergence is a real source of noise; treat single-run P&L differences as
indicative, not precise.

**Data safety.** `trades.db` was never written to — verified byte-identical (SHA-256) to
`trades.db.backup-20260910` after all runs, 380 rows intact including the single
`mode='paper'` row (id 7514). All four runs wrote to separate isolated databases:
`trades_before.db`, `trades_aonly.db`, `trades_bonly.db`, `trades_honest.db`.
`constitution.json` was **not** regenerated (see below).

---

## 5. Two findings outside the requested scope

**The one real paper trade shows a live position-sizing failure.** Row id 7514:

```
SOFI  qty=543.77 @ $18.39  =  $10,000 notional      pnl = -$522.02
```

That is a **$10,000 position on a $500 account** — roughly 20x leverage — and the single
trade lost more than the entire account balance. This looks like `MAX_POSITION_PCT`
being applied to Alpaca's default $100k paper balance rather than real capital. The
backtest correctly sizes off `STARTING_PORTFOLIO = 500.0`, so **this bug exists only in
the live path and the backtest cannot see it.** No amount of backtest honesty will catch
it. This is more dangerous than anything in A–E and should be fixed before any real
money is deployed. I did not touch it — `strategy.py` sizing sits next to your active
workstream.

Related: that row is inside `fetch_trades()`'s `mode IN ('paper','backtest')` filter, so
its −$522 flows into the constitution learning set alongside backtest trades whose P&L
is on a ~$5–30 scale. `pnl_pct` (−5.22%) is used for most analytics so the damage is
limited today, but any dollar-weighted aggregate added later will be dominated by this
one row.

**`constitution.json` is stale and I deliberately did not rebuild it.**
`constitution_builder.fetch_trades()` hard-codes `sqlite3.connect("trades.db")` — it
cannot be pointed at another database. Rebuilding it would have read the stale 379-trade
DB and rewritten the rules the *live* bot loads via `config.get_segment_rules()`. Since
fix D changes what that file contains for the first time, regenerating it is a live
behaviour change and is yours to make deliberately, from a fresh DB.

---

## 6. Bottom line

The strategy's measured edge was roughly half accounting. Symmetric transaction costs
alone take it from +$25.68 / 51.9% to −$39.12 / 36.4%, below its own win-rate gate. The
combined AFTER figure of +$28.89 / 47.3% survives only on a sample-specific tailwind
from correcting the intrabar bias in a market that trended up for four years.

On $500 of real capital, +$28.89 over four years is **+5.8% total** — before commissions,
before taxes, and before the fact that the live sizing bug above would have blown the
account on trade one. This is not yet a deployable edge.
