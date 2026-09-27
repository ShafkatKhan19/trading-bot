# Markov Regime Engine — Walk-Forward Study

**Date:** 2026-09-10 &middot; **Code:** `regime.py` &middot; **Data:** SPY daily bars,
2684 rows, 2016-01-06 to 2026-09-09 (QQQ used only for the
incumbent baseline).

> ## Verdict: FAIL
> Section 9 has the detail. Read it before wiring anything into the live bot.

---

## 1. State definition

> **A bar is BULL if its trailing 20-day log return exceeds +0.5 "noise units" — that
> return divided by the trailing 20-day realized daily volatility scaled to a 20-day
> horizon — BEAR if it is below -0.5 noise units, and CHOP otherwise.**

In code (`classify_states`):

```
trend_t = log(close_t / close_t-20)
vol_t   = std(daily log returns over the last 20 bars) * sqrt(20)
z_t     = trend_t / vol_t
state_t = BULL if z_t > 0.5 ; BEAR if z_t < -0.5 ; else CHOP
```

Dividing by realized vol is what makes CHOP meaningful: +2% over a month in a quiet
tape is a trend, the same +2% in a violent tape is noise. A fixed percentage band
would call 2022 "trending" and 2017 "chop" purely because of volatility levels.

`LOOKBACK=20` and `Z_THRESHOLD=0.5` were fixed before any out-of-sample number was
computed. Section 7 reports a grid over both, in full, as a robustness check — no
configuration was selected on the strength of its out-of-sample result.

### Lookahead control

Every feature is a trailing window ending at t: `close.shift(k)` with k>0 and
`rolling(20, min_periods=20)`. There is no `shift(-k)`, no centered window, and no
full-sample mean/std normalisation anywhere in the feature path. The walk-forward loop
additionally fits each transition matrix only on states dated strictly before the first
bar of the test month.

This is verified empirically, not just asserted. `verify_no_lookahead()` picks random
bars t, recomputes the state using only `df.iloc[:t+1]`, and compares it to the state
computed on the full history — any leakage would change the answer.
**Result: 40/40 bars matched.** The check runs on every `python regime.py` and
aborts the analysis on mismatch.

The only forward-looking quantity in the study is the evaluation target itself
(`fwd_ret` = close_t to close_t+1), which is never an input to any model.

---

## 2. Transition matrix (full sample — DESCRIPTIVE ONLY)

These numbers describe the history. They are in-sample and are **not** evidence of
predictive value. Section 4 onward is the out-of-sample part.

State occupancy:

| state | share_pct | stationary_pct |
|---|---|---|
| BEAR | 16.8 | 16.7 |
| CHOP | 31.2 | 31.2 |
| BULL | 52.0 | 52.1 |

Observed transition counts:

| from \ to | BEAR | CHOP | BULL |
|---|---|---|---|
| BEAR | 363 | 85 | 0 |
| CHOP | 84 | 610 | 135 |
| BULL | 0 | 135 | 1251 |

P(state at t+1 | state at t), Laplace-smoothed (+1 per cell):

| from \ to | BEAR | CHOP | BULL |
|---|---|---|---|
| BEAR | 0.8071 | 0.1907 | 0.0022 |
| CHOP | 0.1022 | 0.7344 | 0.1635 |
| BULL | 0.0007 | 0.0979 | 0.9014 |

---

## 3. Stickiness

Self-transition probability and implied expected dwell time `1/(1-P(s|s))`, in trading
days:

| state | self_prob | expected_dwell_days |
|---|---|---|
| BEAR | 0.8071 | 5.1839 |
| CHOP | 0.7344 | 3.7647 |
| BULL | 0.9014 | 10.1387 |

All three states are extremely sticky. This is largely mechanical: consecutive 20-day
trailing returns share 19 of their 20 bars, so `state_t+1` is nearly determined by
`state_t` by construction. **A high stickiness score is therefore not a discovery about
markets — it is an artifact of the overlapping window.** This is the single most
important thing to understand about the course's "stickiness" metric, and the reason
section 5's accuracy numbers must be read against the persistence baseline rather than
against 33%.

---

## 4. Walk-forward design

Expanding window, refit monthly:

1. For test month M, fit P on all states dated strictly before M's first bar.
2. For each bar t in M, predict `state_t+1 = argmax_j P(j | state_t)`.
3. Record the realised `state_t+1` and SPY's realised close_t to close_t+1 return.
4. Roll forward. Warm-up: 756 bars (~3 years) before the first prediction.

**91 refits &middot; 1891 out-of-sample days &middot;
2019-03-01 to 2026-09-08.** Everything below is out-of-sample.

---

## 5. Out-of-sample next-state accuracy

| predictor | oos_accuracy_pct |
|---|---|
| Markov (argmax P) | 84.19 |
| Persistence (t+1 = t) | 84.19 |
| Always BULL | 51.14 |

The Markov argmax and the naive persistence rule issue the **same prediction on
100.0% of out-of-sample days**. Because every row of P is dominated by its
diagonal, `argmax_j P(j | s)` is almost always `s` itself — the transition matrix
reduces to "tomorrow looks like today" and adds essentially nothing on top of it.

---

## 6. Out-of-sample economics

Each rule is an entry gate on SPY: hold the next bar when the gate is on, else flat. No
transaction costs are applied to any rule — they are scored identically, and costs are
discussed in section 8.

| entry gate | days_in_market_pct | mean_ret_when_in_bps | sharpe | cagr_pct | max_dd_pct | t_vs_flat |
|---|---|---|---|---|---|---|
| Markov: predict BULL | 51.190 | 5.648 | 0.778 | 7.085 | -8.371 | -0.135 |
| Persistence: state=BULL | 51.190 | 5.648 | 0.778 | 7.085 | -8.371 | -0.135 |
| QQQ > 50MA (current bot rule) | 70.280 | 5.778 | 0.897 | 10.052 | -15.281 | -0.103 |
| Buy & hold SPY | 100.000 | 6.019 | 0.793 | 14.258 | -34.181 | n/a |

Next-day SPY return conditioned on the current state — the question that actually
matters, i.e. does knowing the state tell you anything about tomorrow:

| state at t | n_days | mean_bps | median_bps | ann_vol_pct | hit_rate_pct | t_vs_rest |
|---|---|---|---|---|---|---|
| BEAR | 337.000 | 6.108 | 14.945 | 32.645 | 53.116 | 0.010 |
| CHOP | 586.000 | 6.580 | 7.178 | 16.949 | 54.266 | 0.145 |
| BULL | 968.000 | 5.648 | 9.007 | 13.081 | 55.992 | -0.135 |

---

## 7. Robustness grid (reported in full, nothing selected)

Every cell below is out-of-sample under the same walk-forward protocol. This grid is
published to show the spread, **not** to pick a winner; the pre-registered
configuration is `lb=20, z=0.5`.

| config | markov_acc_pct | persist_acc_pct | markov_sharpe | qqq50ma_sharpe | bh_sharpe | chop_pct |
|---|---|---|---|---|---|---|
| lb=10,z=0.25 | 77.801 | 77.801 | 0.839 | 0.934 | 0.814 | 18.443 |
| lb=10,z=0.5 | 75.183 | 75.183 | 0.589 | 0.934 | 0.814 | 35.060 |
| lb=10,z=1.0 | 81.885 | 81.885 | 0.370 | 0.934 | 0.814 | 64.456 |
| lb=20,z=0.25 | 85.405 | 85.405 | 0.665 | 0.897 | 0.793 | 15.462 |
| lb=20,z=0.5 | 84.188 | 84.188 | 0.778 | 0.897 | 0.793 | 30.924 |
| lb=20,z=1.0 | 87.150 | 87.150 | 0.122 | 0.897 | 0.793 | 63.487 |
| lb=40,z=0.25 | 89.358 | 89.358 | 0.507 | 0.884 | 0.785 | 16.915 |
| lb=40,z=0.5 | 89.358 | 89.358 | 0.547 | 0.884 | 0.785 | 33.122 |
| lb=40,z=1.0 | 89.358 | 89.358 | 0.178 | 0.884 | 0.785 | 61.252 |
| lb=60,z=0.25 | 91.239 | 91.239 | 0.682 | 0.865 | 0.775 | 12.034 |
| lb=60,z=0.5 | 90.211 | 90.211 | 0.372 | 0.865 | 0.775 | 30.551 |
| lb=60,z=1.0 | 92.158 | 92.158 | 0.149 | 0.865 | 0.775 | 60.842 |

---

## 8. Does CHOP explain the `no_progress` exits?

This is the specific hypothesis that motivated the work: that the cluster of
`no_progress` exits in the trade database is the signature of trading in a sideways
tape. Every backtest trade is tagged with the SPY state in force on its entry date
(matched backward in time, so no post-entry information is used):

| state at entry | n_trades | no_progress_pct | win_rate_pct | mean_pnl_usd | total_pnl_usd |
|---|---|---|---|---|---|
| BEAR | 8.00 | 0.00 | 0.00 | -1.50 | -11.99 |
| CHOP | 89.00 | 13.48 | 49.44 | -0.00 | -0.19 |
| BULL | 282.00 | 15.25 | 52.13 | 0.08 | 23.79 |

**The chop hypothesis is not supported.** Trades entered in CHOP exited on `no_progress` 13.5% of the time versus 15.2% for trades entered in BULL — the rate is *higher* in the supposedly-good state. Filtering out CHOP entries would not have removed the `no_progress` cluster; it would have removed a representative slice of trades. Caveat: only 89 backtest trades were entered in CHOP, so this test is weak — it rules out a large effect, not a small one.

---

## 9. Verdict

### FAIL — the Markov regime model shows no out-of-sample predictive value, and is worse than the rule it would replace.

**1. The transition matrix adds nothing over "tomorrow = today."** Markov argmax and
naive persistence scored *identically* (84.19% vs 84.19%) because
they emit the same prediction on 100.0% of out-of-sample days. Every row of P is
diagonal-dominant, so `argmax_j P(j|s)` collapses to `s`. The matrix is a more expensive
way to write `state_t+1 = state_t`.

**2. The 84.2% accuracy figure is not a result.** It sounds impressive
against a 33% three-class coin flip, but the correct benchmark is the persistence
baseline, which ties it exactly. The accuracy comes from the overlapping 20-day window
— consecutive states share 19 of 20 bars — not from the market being predictable.
Section 7 makes this mechanical: accuracy rises monotonically with lookback
(~75% at lb=10 to
~92% at lb=60) purely because longer windows
overlap more. Longer window, higher "accuracy", *lower* Sharpe.

**3. Knowing the state tells you nothing about tomorrow's return.** All three states'
next-day means sit within about 1 bp of each other, and the largest t-statistic against
the rest of the sample is 0.14 — indistinguishable from zero. BULL, the state
the gate trades in, had the *lowest* mean forward return (5.65 bps) of the
three; the highest was CHOP (6.58 bps). The sign is backwards from the
thesis.

**4. It loses to both required baselines.** Markov-BULL gating gave Sharpe 0.778
against 0.897 for the existing QQQ-above-50MA rule and 0.793 for buy-and-hold.
It lost to the incumbent 50MA rule in **12 of 12 robustness
configurations** — this is not a knife-edge parameter choice, it is a consistent loss.

**5. The chop hypothesis specifically failed.** See section 8. The `no_progress` exits
are not concentrated in CHOP.

### The one honest point in its favour

Max drawdown fell to -8.4% versus -34.2% for buy-and-hold, on
51% market exposure. That is real risk reduction — but the incumbent 50MA rule
already achieves -15.3% *with a higher Sharpe*, so the regime model is not the way
to buy that reduction.

### Recommendation

**Do not integrate this as an entry gate.** `is_market_bullish()` in `regime.py` is
written and drop-in compatible, but on this evidence swapping it for the 50MA rule would
make the bot worse, not better. The three-state vocabulary may still be useful as
*telemetry* — logging the regime alongside each trade costs nothing and builds the
record needed to test this properly later — but it should not be allowed to veto trades.

### Caveats and things I am not certain about

- **This tests index-level direction, not the bot's actual edge.** The bot trades single
  names with stops and targets; a regime filter could in principle help trade-level P&L
  even with no index-level forward-return signal. Section 8 is the closest available test
  of that and it came back negative, but on only 379
  trades.
- **Costs are excluded from section 6.** All four rules are scored gross. The
  Markov gate trades in and out more often than buy-and-hold, so charging realistic
  costs would widen its loss, not narrow it. This does not change the conclusion's sign.
- **One market cycle.** 2016-01-06 to 2026-09-09 contains one
  major bear (2022) and two crashes. A three-state model estimated over one cycle has
  wide error bars on the BEAR row regardless of walk-forward discipline.
- **The threshold was not tuned, and I did not tune it after seeing results.** Section 7
  is published in full precisely so that a later reader can see nothing was cherry-picked.
  If a future version of this reports a better number, check whether the parameters moved.

### The bigger picture

This model was evaluated against SPY's own forward returns, which is a fair test of the
regime idea in isolation. It should not be read as evidence about the bot's overall
viability — the separate audit found the strategy's backtest edge (+$11.61 over 379
trades) turns negative once exit slippage is charged symmetrically. A regime filter that
does not work cannot fix a strategy that does not have an edge, and adding one would
mostly add the appearance of sophistication.
