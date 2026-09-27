# ============================================================
#  backtest_runner.py — Walk-forward backtesting engine
#  Applies per-segment rules (stop, target, hold, signal score,
#  RSI floor, stock uptrend filter) to generate realistic trade data.
#  Run: python backtest_runner.py [--clear]
# ============================================================

import sqlite3
import sys
import logging
from datetime import datetime

import config
import signals
import trade_logger
from alpaca_client import AlpacaClient

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

TARGET_TRADES        = 750             # enough samples for constitution_builder
STARTING_PORTFOLIO   = 500.0          # real starting capital ($500)
# Slippage is charged on BOTH legs and is the SAME constant the live path uses
# (strategy.py::_exit_trade), so the backtest validates the strategy under the
# rules it actually trades under. Entry pays up, exit gets paid down.
SLIPPAGE_PCT         = config.STOP_SLIPPAGE_PCT
# Keep score loose so constitution_builder gets samples at every level
# and can derive the optimal threshold. Live strategy enforces segment minimums.
BACKTEST_MIN_SCORE   = 2


def exit_fill(price: float) -> float:
    """Exit leg pays slippage in the adverse (downward) direction for a long."""
    return price * (1 - SLIPPAGE_PCT)


def stop_fill(stop_price: float, bar_open: float) -> float:
    """
    Realistic stop fill for a long. A stop does not guarantee the stop price:
    if the bar gapped through it overnight, the order becomes a market order
    at the open. Fill at the worse of the two, then charge slippage on top.
    """
    return exit_fill(min(stop_price, bar_open))


# ── DB helpers ────────────────────────────────────────────────

def clear_db():
    conn = sqlite3.connect(trade_logger.DB_PATH)
    c    = conn.cursor()
    for tbl in ("trades", "signal_log", "rejections", "kill_switch_events"):
        c.execute(f"DELETE FROM {tbl}")
    conn.commit()
    conn.close()
    print("trades.db cleared.\n")


def log_entry(symbol, entry_date_str, entry_price, qty, rsi, score, regime):
    conn = sqlite3.connect(trade_logger.DB_PATH)
    c    = conn.cursor()
    c.execute("""
        INSERT INTO trades
        (symbol, entry_date, entry_price, qty, side, rsi_at_entry,
         signal_score, news_sentiment, market_regime, mode, run_id)
        VALUES (?, ?, ?, ?, 'BUY', ?, ?, 'neutral', ?, 'backtest', 0)
    """, (symbol, entry_date_str, round(entry_price, 4), round(qty, 4),
          round(rsi or 50.0, 2), score, regime))
    tid = c.lastrowid
    conn.commit()
    conn.close()
    return tid


def log_exit(trade_id, exit_date_str, exit_price, reason):
    conn = sqlite3.connect(trade_logger.DB_PATH)
    c    = conn.cursor()
    c.execute("SELECT entry_price, qty, entry_date FROM trades WHERE id=?", (trade_id,))
    row  = c.fetchone()
    if not row:
        conn.close()
        return 0.0
    entry_price, qty, entry_date_str_db = row
    pnl     = (exit_price - entry_price) * qty
    pnl_pct = (exit_price - entry_price) / entry_price
    try:
        hold_days = (datetime.fromisoformat(exit_date_str) -
                     datetime.fromisoformat(entry_date_str_db)).days
    except Exception:
        hold_days = 0
    c.execute("""
        UPDATE trades SET exit_date=?, exit_price=?, pnl=?, pnl_pct=?,
                          hold_days=?, exit_reason=?
        WHERE id=?
    """, (exit_date_str, round(exit_price, 4), round(pnl, 2),
          round(pnl_pct, 4), hold_days, reason, trade_id))
    conn.commit()
    conn.close()
    return pnl


# ── Progress ──────────────────────────────────────────────────

def print_progress(n, portfolio):
    conn = sqlite3.connect(trade_logger.DB_PATH)
    c    = conn.cursor()
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL")
    wins = c.fetchone()[0]
    c.execute("SELECT SUM(pnl) FROM trades WHERE exit_date IS NOT NULL")
    total_pnl = c.fetchone()[0] or 0.0
    conn.close()
    wr   = wins / n * 100 if n else 0
    sign = "+" if total_pnl >= 0 else ""
    print(f"  [Trades: {n:>4} | Win rate: {wr:.1f}% | "
          f"PnL: {sign}${total_pnl:,.0f} | Portfolio: ${portfolio:,.0f}]")


def print_final(portfolio):
    s = trade_logger.get_summary()
    print("\n" + "=" * 60)
    print("  BACKTEST COMPLETE")
    print("=" * 60)
    print(f"  Total trades   : {s['total_trades']}")
    print(f"  Wins           : {s['wins']}")
    print(f"  Losses         : {s['losses']}")
    print(f"  Win rate       : {s['win_rate']:.1%}")
    print(f"  Total PnL      : ${s['total_pnl']:,.2f}")
    print(f"  Avg PnL/trade  : {s['avg_pnl_pct']:+.2f}%")
    print(f"  Final portfolio: ${portfolio:,.2f}")
    growth = (portfolio - STARTING_PORTFOLIO) / STARTING_PORTFOLIO * 100
    print(f"  Return         : {growth:+.1f}% on ${STARTING_PORTFOLIO:,.0f}")
    print("=" * 60)
    if s["win_rate"] >= config.MIN_WIN_RATE:
        print("\n  [PASS] Win rate target reached!")
    else:
        print(f"\n  [FAIL] Win rate {s['win_rate']:.1%} below {config.MIN_WIN_RATE:.0%} target.")
        print("    Tune parameters and re-run before going live.")
    print(f"\n>> Run: python constitution_builder.py\n")


# ── Main ──────────────────────────────────────────────────────

def run_backtest(auto_clear: bool = False):
    if auto_clear:
        clear_db()
    else:
        resp = input("Clear existing trades.db and start fresh? [y/N]: ").strip().lower()
        if resp == "y":
            clear_db()

    trade_logger.init_db()
    client = AlpacaClient()

    # ── Fetch historical data ──────────────────────────────────
    # 4 years, not 5+ — RIVN/HOOD/PLTR/SOFI all IPO'd 2020-2021, so a
    # longer window would silently drop them from the sample.
    print("Fetching historical data (4 years)...")
    all_syms = config.TICKERS + [config.REGIME_TICKER]
    daily    = {}
    bars4h   = {}

    for sym in all_syms:
        df_d = client.get_bars(sym, "1Day",  days=1460)   # 4 years
        df_4 = client.get_bars(sym, "4Hour", days=1460)
        if df_d is not None and len(df_d) >= 60:
            df_d       = df_d.copy()
            df_d.index = df_d.index.normalize()
            daily[sym] = df_d
        if df_4 is not None and len(df_4) >= 60:
            bars4h[sym] = df_4

    valid = [t for t in config.TICKERS if t in daily]
    print(f"  Tickers ready : {', '.join(valid)}")
    print(f"  QQQ daily bars: {len(daily.get(config.REGIME_TICKER, []))}")

    if config.REGIME_TICKER not in daily:
        print("ERROR: No QQQ data. Exiting.")
        sys.exit(1)

    df_qqq = daily[config.REGIME_TICKER]

    # ── Build simulation clock from 4H bars ───────────────────
    if config.REGIME_TICKER in bars4h:
        sim_timestamps = sorted(bars4h[config.REGIME_TICKER].index.unique())
    else:
        sim_timestamps = sorted(df_qqq.index.unique())

    total_bars = len(sim_timestamps)
    print(f"  Simulation bars: {total_bars}")
    print(f"\nTarget: {TARGET_TRADES} trades. Walking forward over {total_bars} bars...\n")

    # ── Pre-build regime cache ────────────────────────────────
    regime_cache = {}

    def regime_on(dt):
        d = dt.normalize() if hasattr(dt, "normalize") else dt
        if d not in regime_cache:
            slice_ = df_qqq[df_qqq.index <= d]
            regime_cache[d] = signals.is_market_bullish(slice_)
        return regime_cache[d]

    # ── Walk-forward loop ─────────────────────────────────────
    portfolio    = STARTING_PORTFOLIO
    positions    = {}   # trade_id -> position dict (includes segment rules)
    completed    = 0
    milestone    = 0
    last_entries_date = None   # gates entry scanning to once per calendar day
    qqq_daily_dates = sorted(df_qqq.index.unique())

    for ts in sim_timestamps:
        cal_date = ts.normalize() if hasattr(ts, "normalize") else ts

        # ── Exits ─────────────────────────────────────────────
        closed = []
        for tid, pos in positions.items():
            sym  = pos["symbol"]
            df_d = daily.get(sym)
            if df_d is None:
                continue
            # A position can't be evaluated before its own entry day has
            # arrived, and each calendar day's bar must only be applied once
            # — without these guards a position opened "for next_day" gets
            # checked against today's (pre-entry) bar on every remaining
            # intraday tick of today, producing exit-before-entry dates and
            # hold_days inflated by the number of intraday ticks per day.
            if cal_date < pos["entry_cal_date"]:
                continue
            if pos.get("last_eval_date") == cal_date:
                continue
            pos["last_eval_date"] = cal_date

            day_bars = df_d[df_d.index == cal_date]
            if len(day_bars) == 0:
                continue
            bar = day_bars.iloc[0]
            op, lo, hi, cl = bar["open"], bar["low"], bar["high"], bar["close"]

            max_hold = pos["rules"]["max_hold_days"]
            reason = exit_price = None

            # Worst-case intrabar ordering. A daily bar does not say whether the
            # high or the low came first, so stops are tested against the levels
            # carried in from PRIOR bars — before this bar's high is allowed to
            # ratchet the trail up. Doing it the other way round assumes the high
            # always preceded the low, which over-counts trailing-stop exits at
            # favourable prices and understates hard-stop hits.
            if lo <= pos["stop_loss"]:
                exit_price, reason = stop_fill(pos["stop_loss"], op), "stop_loss"
            elif pos["trail_active"] and lo <= pos["trailing_stop"]:
                exit_price, reason = stop_fill(pos["trailing_stop"], op), "trailing_stop"
            elif (pos["hold_days"] >= config.NO_PROGRESS_DAYS
                  and (cl - pos["entry_price"]) / pos["entry_price"]
                      < config.NO_PROGRESS_MIN_GAIN):
                exit_price, reason = exit_fill(cl), "no_progress"
            elif pos["hold_days"] >= max_hold:
                exit_price, reason = exit_fill(cl), "time_exit"

            # Survived the bar — only now may this bar's high move the high-water
            # mark and ratchet the trail, which takes effect from the NEXT bar.
            if not reason:
                if hi > pos["highest_price"]:
                    pos["highest_price"] = hi
                activation = pos["entry_price"] * (1 + config.TRAIL_ACTIVATION_PCT)
                if pos["highest_price"] >= activation:
                    pos["trail_active"] = True
                if pos["trail_active"]:
                    new_trail = round(pos["highest_price"] * (1 - config.TRAIL_STOP_PCT), 4)
                    if new_trail > pos["trailing_stop"]:
                        pos["trailing_stop"] = new_trail

            if reason:
                pnl = log_exit(tid, ts.isoformat(), exit_price, reason)
                portfolio += pnl
                closed.append(tid)
                completed += 1
                if completed // 50 > milestone:
                    milestone = completed // 50
                    print_progress(completed, portfolio)
                if completed >= TARGET_TRADES:
                    break
            else:
                pos["hold_days"] += 1

        for tid in closed:
            del positions[tid]

        if completed >= TARGET_TRADES:
            break

        # ── Entries ───────────────────────────────────────────
        # Entries are decided once per calendar day (next_day's open) —
        # re-scanning on every intraday tick of the same day re-opened the
        # same symbol repeatedly whenever a same-day exit freed a slot.
        if cal_date == last_entries_date:
            continue
        last_entries_date = cal_date

        if len(positions) >= config.MAX_OPEN_POSITIONS:
            continue
        if not regime_on(cal_date):
            continue

        future_dates = [d for d in qqq_daily_dates if d > cal_date]
        if not future_dates:
            continue
        next_day     = future_dates[0]
        already_held = {p["symbol"] for p in positions.values()}

        for sym in valid:
            if len(positions) >= config.MAX_OPEN_POSITIONS:
                break
            if sym in already_held:
                continue

            rules = config.get_segment_rules(sym)

            # Stock uptrend filter: must be above own 50MA (with tolerance
            # when QQQ itself is strongly bullish — see signals.is_stock_in_uptrend)
            df_trend_slice  = daily[sym][daily[sym].index <= cal_date]
            df_regime_slice = df_qqq[df_qqq.index <= cal_date]
            if not signals.is_stock_in_uptrend(df_trend_slice, df_regime_slice):
                continue

            # Signal slice: 4H up to current bar
            if sym in bars4h:
                df_sig_slice = bars4h[sym][bars4h[sym].index <= ts]
            else:
                df_sig_slice = daily[sym][daily[sym].index <= cal_date]

            if len(df_sig_slice) < config.MA_SLOW + 10:
                continue

            result = signals.analyse(sym, df_sig_slice, rules)

            # Gate identically to strategy.py's live entry logic, so the
            # backtest is a true preview of what the live bot would take —
            # segment minimum score AND the tier-1 RSI+MACD confirmation.
            if not result.is_entry_valid(rules["min_signal_score"]):
                continue
            if config.REQUIRE_TIER1_SIGNALS and not signals.has_tier1_signals(result):
                continue

            # Entry at next day open
            df_d = daily[sym]
            nb   = df_d[df_d.index == next_day]
            if len(nb) == 0:
                continue

            entry_price = nb.iloc[0]["open"] * (1 + SLIPPAGE_PCT)
            # Match strategy.py's conviction-scaled sizing — score 4 = full size,
            # score 3 = 75%, score 2 = 50% — otherwise the backtest overstates
            # position size (and therefore PnL) on every borderline-score entry.
            multiplier  = config.SCORE_POSITION_MULTIPLIERS.get(result.score, 0.5)
            qty         = (portfolio * config.MAX_POSITION_PCT * multiplier) / entry_price
            if qty <= 0:
                continue

            stop_loss = entry_price * (1 - rules["stop_loss_pct"])

            tid = log_entry(sym, next_day.isoformat(), entry_price, qty,
                            result.rsi, result.score, "bullish")

            positions[tid] = {
                "symbol":         sym,
                "entry_price":    entry_price,
                "qty":            qty,
                "stop_loss":      stop_loss,
                "trailing_stop":  stop_loss,   # starts equal to hard stop
                "highest_price":  entry_price,
                "trail_active":   False,
                "hold_days":      0,
                "entry_cal_date": next_day,
                "last_eval_date": None,
                "rules":          rules,
            }
            already_held.add(sym)

    # ── Force-close remaining open positions ──────────────────
    if positions:
        last_ts  = sim_timestamps[-1]
        last_day = last_ts.normalize() if hasattr(last_ts, "normalize") else last_ts
        for tid, pos in list(positions.items()):
            df_d = daily.get(pos["symbol"])
            if df_d is None:
                continue
            lb = df_d[df_d.index <= last_day]
            if len(lb) == 0:
                continue
            ep  = exit_fill(lb.iloc[-1]["close"])
            pnl = log_exit(tid, last_ts.isoformat(), ep, "time_exit")
            portfolio += pnl
            completed += 1

    print_final(portfolio)


if __name__ == "__main__":
    auto = "--clear" in sys.argv
    run_backtest(auto_clear=auto)
