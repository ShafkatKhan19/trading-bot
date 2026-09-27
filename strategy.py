# ============================================================
#  strategy.py — Swing trade entry and exit logic
#
#  Atomic Habits principles embedded throughout:
#
#  Ch.1  — Trajectory over results: rolling win rate logged each cycle
#  Ch.2  — Identity-based: tier-1 signals (RSI+MACD) define what this
#           bot IS — a momentum trader, not a noise trader
#  Ch.7  — Make bad habits invisible: cooldown blocks re-entry after
#           a stop-loss so the bot can't repeat a broken setup
#  Ch.12 — Law of Least Effort: environment (market regime + uptrend
#           filter) does the filtering work automatically
#  Ch.14 — Commitment device: per-segment rules locked in constitution
#  Ch.16 — Never miss twice: post-loss ticker cooldown + losing streak
#           auto-pause prevent compounding the same mistake
#  Ch.19 — Goldilocks Rule: position size scales with signal conviction
#  Ch.20 — Habits + Deliberate Practice = Mastery: every cycle logs
#           trajectory so the next constitution rebuild has richer data
# ============================================================

import json
import logging
import os
from datetime import datetime, date
from zoneinfo import ZoneInfo
import config
import signals as sig
import sizing
import macro_calendar as macro
import news_agent
import trade_logger as tl
from constitution_validator import constitution_allows

logger = logging.getLogger(__name__)

POSITIONS_STATE_PATH = os.path.join("logs", "open_positions.json")
ET = ZoneInfo("America/New_York")


class Position:
    """Tracks an open swing trade position, including its segment rules."""

    def __init__(self, symbol, entry_price, qty, trade_id,
                 stop_loss, entry_date, signal_score, rules):
        self.symbol          = symbol
        self.entry_price     = entry_price
        self.qty             = qty
        self.trade_id        = trade_id
        self.stop_loss       = stop_loss          # hard initial stop — never moves down
        self.trailing_stop   = stop_loss          # rises as position gains
        self.highest_price   = entry_price        # high-water mark for trailing
        self.trail_active    = False              # True once TRAIL_ACTIVATION_PCT reached
        # entry_date accepts either a date (legacy swing positions) or a
        # full datetime (day-trading) — entry_timestamp always normalizes
        # to a datetime so minute-level holds can be tracked intraday.
        self.entry_timestamp = (
            datetime.combine(entry_date, datetime.min.time())
            if isinstance(entry_date, date) and not isinstance(entry_date, datetime)
            else entry_date
        )
        self.signal_score    = signal_score
        self.rules            = rules

    @property
    def entry_date(self):
        return self.entry_timestamp.date()

    def hold_days(self) -> int:
        return (date.today() - self.entry_date).days

    def hold_minutes(self) -> float:
        return (datetime.now() - self.entry_timestamp).total_seconds() / 60

    def to_dict(self) -> dict:
        return {
            "symbol":        self.symbol,
            "entry_price":   self.entry_price,
            "qty":           self.qty,
            "trade_id":      self.trade_id,
            "stop_loss":     self.stop_loss,
            "trailing_stop": self.trailing_stop,
            "highest_price": self.highest_price,
            "trail_active":  self.trail_active,
            "entry_date":    self.entry_timestamp.isoformat(),
            "signal_score":  self.signal_score,
            "rules":         self.rules,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        pos = cls(
            symbol=d["symbol"],
            entry_price=d["entry_price"],
            qty=d["qty"],
            trade_id=d["trade_id"],
            stop_loss=d["stop_loss"],
            entry_date=datetime.fromisoformat(d["entry_date"]),
            signal_score=d["signal_score"],
            rules=d["rules"],
        )
        pos.trailing_stop = d["trailing_stop"]
        pos.highest_price = d["highest_price"]
        pos.trail_active  = d["trail_active"]
        return pos

    def pnl_pct(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price

    def update_trailing_stop(self, current_price: float):
        """
        Ratchet trailing stop upward as price rises.
        Activates once position gains TRAIL_ACTIVATION_PCT.
        Stop only ever moves up — never widens. (Best Loser Wins, Ch.6)
        """
        if current_price > self.highest_price:
            self.highest_price = current_price

        activation = self.entry_price * (1 + config.TRAIL_ACTIVATION_PCT)
        if current_price >= activation:
            self.trail_active = True

        if self.trail_active:
            new_trail = round(self.highest_price * (1 - config.TRAIL_STOP_PCT), 2)
            if new_trail > self.trailing_stop:
                self.trailing_stop = new_trail


class SwingStrategy:
    """
    Core swing trading strategy with per-segment rules and
    Atomic Habits behavioral guardrails.
    """

    def __init__(self, alpaca_client, kill_switch):
        self.client      = alpaca_client
        self.kill_switch = kill_switch
        self.positions   = {}
        self.mode        = config.TRADING_MODE
        self._load_positions()

    # ── Position-state persistence ────────────────────────────
    # Positions live in memory during normal operation, but a crash or
    # reboot while holding a real position would otherwise leave it
    # unmanaged on the live account — no stop-loss, no exit logic, no
    # kill-switch coverage. Persist to disk on every mutation and reload
    # on startup so an open position survives a restart.

    def _load_positions(self):
        if not os.path.exists(POSITIONS_STATE_PATH):
            return
        try:
            with open(POSITIONS_STATE_PATH, "r") as f:
                raw = json.load(f)
            for symbol, d in raw.items():
                self.positions[symbol] = Position.from_dict(d)
            if self.positions:
                logger.warning(
                    f"Restored {len(self.positions)} open position(s) from disk: "
                    f"{', '.join(self.positions.keys())}"
                )
        except Exception as e:
            logger.error(f"Failed to load saved positions — starting empty: {e}", exc_info=True)
            return
        self._reconcile_with_broker()

    def _reconcile_with_broker(self):
        """
        Drop any locally-tracked position that no longer exists on the broker.
        Without this, a kill-switch fire (or crash between a fill and
        _save_positions) leaves a ghost position on disk — the strategy then
        tries to manage/exit a position Alpaca no longer holds.
        """
        if not self.positions:
            return
        try:
            broker_symbols = {p.symbol for p in self.client.get_all_positions()}
        except Exception as e:
            logger.error(f"Could not reconcile positions with broker — keeping local state as-is: {e}", exc_info=True)
            return
        ghosts = [s for s in self.positions if s not in broker_symbols]
        for symbol in ghosts:
            logger.critical(
                f"GHOST POSITION: {symbol} tracked locally but not held at broker — "
                f"dropping from local state (was likely closed by the kill switch)"
            )
            del self.positions[symbol]
        if ghosts:
            self._save_positions()

    def _save_positions(self):
        try:
            os.makedirs(os.path.dirname(POSITIONS_STATE_PATH), exist_ok=True)
            raw = {symbol: pos.to_dict() for symbol, pos in self.positions.items()}
            with open(POSITIONS_STATE_PATH, "w") as f:
                json.dump(raw, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist positions to disk: {e}", exc_info=True)

    # ── Safety gate ───────────────────────────────────────────

    def _is_safe_to_trade(self) -> bool:
        if self.kill_switch.check():
            logger.warning("Strategy blocked — kill switch is ACTIVE")
            return False
        return True

    # ── Atomic Habits: Never Miss Twice (Ch.16) ───────────────

    def _ticker_in_cooldown(self, symbol: str) -> bool:
        """
        After a stop-loss, block re-entry for TICKER_COOLDOWN_DAYS.
        Prevents the bot from immediately re-entering a setup that just
        failed — the broken pattern may still be in play.
        "It's easier to avoid temptation than resist it." (Ch.7)
        """
        last = tl.get_last_exit(symbol)
        if not last:
            return False
        reason, exit_date = last
        if "stop_loss" not in (reason or ""):
            return False
        days_since = (date.today() - exit_date).days
        in_cooldown = days_since < config.TICKER_COOLDOWN_DAYS
        if in_cooldown:
            logger.debug(f"{symbol}: in stop-loss cooldown ({days_since}d of {config.TICKER_COOLDOWN_DAYS}d)")
        return in_cooldown

    def _ticker_on_losing_streak(self, symbol: str) -> bool:
        """
        Pause a ticker that has hit MAX_CONSECUTIVE_LOSSES in a row.
        That ticker's pattern is broken right now — don't keep feeding it capital.
        "Never miss twice" applied at the ticker level. (Ch.16)
        """
        if not config.ENABLE_CONSECUTIVE_LOSS_PAUSE:
            return False
        streak = tl.get_consecutive_losses(symbol)
        if streak >= config.MAX_CONSECUTIVE_LOSSES:
            logger.warning(f"{symbol}: {streak} consecutive losses — paused until streak resets")
            return True
        return False

    # ── Goldilocks position sizing (Ch.19) ───────────────────

    def _calc_qty(self, symbol: str, price: float, score: int) -> float:
        """
        Scale position size by signal conviction.
        Score 4 (all signals) → full allocation.
        Score 3 → 75%. Score 2 → 50%.
        "Peak motivation when working on tasks at the edge of ability" —
        high-conviction trades get more capital; borderline trades get less.
        Sized off sizing_capital() (equity capped at ACCOUNT_CAPITAL), then
        trimmed to whatever settled cash is left today.
        """
        capital     = sizing.sizing_capital(self.client)
        multiplier  = config.SCORE_POSITION_MULTIPLIERS.get(score, 0.5)
        max_dollars = capital * sizing.position_fraction("swing") * multiplier
        qty         = sizing.floor_qty(max_dollars / price)
        return sizing.cap_to_settled_cash(self.client, symbol, qty, price)

    # ── Entry decision ────────────────────────────────────────

    def evaluate_entry(self, symbol: str, df_signal, df_trend, df_regime,
                       df_vix=None) -> bool:
        """
        Full entry evaluation pipeline.
        Gates run cheapest-first. Every rejection is logged with its reason
        so the constitution can learn from the pattern. (Ch.4: awareness)
        """
        if not self._is_safe_to_trade():
            return False

        if symbol in self.positions:
            return False

        if len(self.positions) >= config.MAX_OPEN_POSITIONS:
            return False

        # The PDT day-trade cap that used to gate entries here was removed:
        # FINRA retired the rule on 2026-06-04 and Alpaca no longer tracks
        # day-trade counts, so the guard could never fire again. See config.py.

        # ── Clock gates ─────────────────────────────────────────
        # Nothing new at/after the EOD flatten: an entry at the 16:00 cycle
        # would be opened after flatten_for_close ran and held overnight.
        now_et = datetime.now(ET)
        if config.DAY_TRADING_MODE and now_et.strftime("%H:%M") >= config.EOD_FLATTEN_TIME:
            return False
        blackout = macro.entry_blocked(now_et)
        if blackout:
            tl.log_rejection(symbol, blackout)
            return False

        # ── Environment gates (Ch.6: environment shapes behavior) ─
        if not sig.is_market_bullish(df_regime):
            tl.log_rejection(symbol, "Market regime bearish (QQQ < 50MA)")
            return False

        # ── VIX macro filter — tariff / black swan protection ──
        if not sig.is_volatility_safe(df_vix):
            tl.log_rejection(symbol, f"VIX elevated — macro fear environment, no new entries")
            return False

        if not sig.is_stock_in_uptrend(df_trend, df_regime):
            tl.log_rejection(symbol, f"{symbol} below own 50MA — no entry in downtrend")
            return False

        # ── Commitment device: segment rules (Ch.14) ──────────
        rules = config.get_segment_rules(symbol)

        # ── Never miss twice: cooldown check (Ch.16) ──────────
        if self._ticker_in_cooldown(symbol):
            tl.log_rejection(symbol, f"Post-loss cooldown ({config.TICKER_COOLDOWN_DAYS}d)")
            return False

        # ── Losing streak auto-pause (Ch.16) ──────────────────
        if self._ticker_on_losing_streak(symbol):
            tl.log_rejection(symbol, f"{config.MAX_CONSECUTIVE_LOSSES}+ consecutive losses — paused")
            return False

        # ── Technical signals ──────────────────────────────────
        signal_result = sig.analyse(symbol, df_signal, rules)
        tl.log_signal(
            symbol, signal_result.rsi, signal_result.rsi_signal,
            signal_result.ma_signal, signal_result.macd_signal,
            signal_result.volume_signal, signal_result.score,
            "EVALUATE", " | ".join(signal_result.reason)
        )

        # Signal score gate (segment minimum)
        if not signal_result.is_entry_valid(rules["min_signal_score"]):
            tl.log_rejection(
                symbol,
                f"Signal score {signal_result.score} < {rules['min_signal_score']} "
                f"for {config.WATCHLIST.get(symbol, {}).get('theme', '?')}",
                signal_score=signal_result.score,
            )
            return False

        # ── Candlestick reversal gate ──────────────────────────
        # A bearish-reversal candle (hanging man, evening star, gravestone
        # doji, bearish engulfing) overrides a passing score — these patterns
        # mean the move is exhausting right as we'd be entering.
        if signal_result.candlestick_warning:
            tl.log_rejection(
                symbol,
                f"Candlestick warning: {signal_result.candlestick_pattern} — "
                f"bearish reversal signal overrides passing score",
                signal_score=signal_result.score,
            )
            return False

        # ── Attention gate (Ernie Chan, "Poor Person's Transformer") ─
        # When the entry is borderline (score == minimum exactly), require
        # the attention context to confirm bullish momentum. This eliminates
        # marginal setups that score just enough to pass but lack follow-through.
        if (config.REQUIRE_ATTENTION_ON_BORDERLINE
                and signal_result.score == rules["min_signal_score"]
                and not signal_result.attention_confirms):
            tl.log_rejection(
                symbol,
                f"Attention gate: borderline score {signal_result.score} but "
                f"attention context not bullish "
                f"(RSI={signal_result.attention_rsi_boost:+.2f}, "
                f"MACD={signal_result.attention_macd_boost:+.2f})",
                signal_score=signal_result.score,
            )
            return False

        # ── Tier-1 identity check (Ch.2: identity-based system) ─
        # RSI recovery AND MACD crossover must both fire.
        # These two signals confirm momentum from independent sources.
        # Without both, the score might be high but the setup isn't a
        # momentum trade — it's noise. This bot doesn't take noise trades.
        if config.REQUIRE_TIER1_SIGNALS and not sig.has_tier1_signals(signal_result):
            tl.log_rejection(
                symbol,
                f"Tier-1 gate: RSI ({signal_result.rsi_signal}) and "
                f"MACD ({signal_result.macd_signal}) must both confirm momentum",
                signal_score=signal_result.score,
            )
            return False

        # RSI momentum floor
        rsi_min = rules["rsi_min_entry"]
        if signal_result.rsi is not None and signal_result.rsi < rsi_min:
            tl.log_rejection(
                symbol,
                f"RSI {signal_result.rsi:.1f} below momentum floor {rsi_min}",
                signal_score=signal_result.score,
            )
            return False

        # ── News sentiment gate ────────────────────────────────
        sentiment = news_agent.analyse(symbol)
        safe, reason = news_agent.is_safe_to_enter(sentiment)
        if not safe:
            logger.warning(f"NEWS ALERT [{symbol}]: entry blocked — {reason}")
            tl.log_rejection(symbol, reason, signal_score=signal_result.score,
                             news_label=sentiment.label)
            return False

        # ── Constitution gate (live only) ──────────────────────
        if self.mode == "live":
            allowed, const_reason = constitution_allows(symbol, signal_result, sentiment)
            if not allowed:
                tl.log_rejection(symbol, f"Constitution: {const_reason}",
                                 signal_score=signal_result.score)
                return False

        return self._enter_trade(symbol, signal_result, sentiment, rules)

    def _enter_trade(self, symbol: str, signal_result, sentiment, rules: dict) -> bool:
        """Place the buy order with conviction-scaled position sizing."""
        price = self.client.get_latest_price(symbol)
        if not price:
            return False

        qty = self._calc_qty(symbol, price, signal_result.score)
        if qty < 0.01:
            logger.warning(f"{symbol}: qty too small ({qty:.4f}) — insufficient capital")
            return False

        # Submit order first — only log to DB on success to avoid phantom records.
        # submit_market_buy blocks until the order is confirmed filled and
        # returns the order with its actual fill price/qty — a quoted price
        # is not a fill, and partial fills change the real qty held.
        order = self.client.submit_market_buy(symbol, qty)
        if not order:
            return False

        fill_price = float(order.filled_avg_price or price)
        fill_qty   = float(order.filled_qty or qty)

        stop_loss        = round(fill_price * (1 - rules["stop_loss_pct"]), 2)
        trail_activation = round(fill_price * (1 + config.TRAIL_ACTIVATION_PCT), 2)

        trade_id = tl.log_trade_entry(
            symbol=symbol,
            entry_price=fill_price,
            qty=fill_qty,
            rsi=signal_result.rsi,
            signal_score=signal_result.score,
            news_sentiment=sentiment.label,
            market_regime="bullish",
            mode=self.mode,
        )

        self.positions[symbol] = Position(
            symbol=symbol,
            entry_price=fill_price,
            qty=fill_qty,
            trade_id=trade_id,
            stop_loss=stop_loss,
            entry_date=datetime.now(),
            signal_score=signal_result.score,
            rules=rules,
        )
        self._save_positions()

        theme      = config.WATCHLIST.get(symbol, {}).get("theme", "?")
        multiplier = config.SCORE_POSITION_MULTIPLIERS.get(signal_result.score, 0.5)
        logger.info(
            f"ENTERED: {symbol} [{theme}] | price=${fill_price:.2f} | qty={fill_qty} "
            f"({multiplier:.0%} size — score {signal_result.score}/4) | "
            f"stop=${stop_loss:.2f} | trail activates @${trail_activation:.2f} | "
            f"news={sentiment.label}"
        )
        return True

    # ── Exit evaluation ───────────────────────────────────────

    def evaluate_exits(self):
        if not self._is_safe_to_trade():
            # Kill switch just closed everything via Alpaca — clear local state too
            if self.positions:
                logger.warning(f"Kill switch active — clearing {len(self.positions)} ghost positions from memory")
                self.positions.clear()
                self._save_positions()
            return

        for symbol, pos in list(self.positions.items()):
            current_price = self.client.get_latest_price(symbol)
            if not current_price:
                continue
            exit_reason = self._should_exit(pos, current_price)
            if exit_reason:
                self._exit_trade(pos, current_price, exit_reason)
        self._save_positions()

    def _is_deteriorating(self, symbol: str, current_price: float) -> bool:
        """True if price has broken below its short-term average.

        Used only to qualify the no-progress exit. If bars are unavailable the
        answer is True, so an unreachable data feed falls back to the original
        stricter behaviour rather than silently holding a losing position.
        """
        try:
            df = self.client.get_bars(
                symbol, config.SIGNAL_TIMEFRAME, days=config.NO_PROGRESS_MA_DAYS
            )
            if df is None or len(df) < config.NO_PROGRESS_MA_PERIOD:
                return True
            ma = df["close"].rolling(config.NO_PROGRESS_MA_PERIOD).mean().iloc[-1]
            if ma != ma:  # NaN
                return True
            return current_price < float(ma)
        except Exception as e:
            logger.warning(f"{symbol}: deterioration check failed ({e}) — applying no-progress exit")
            return True

    def _should_exit(self, pos: Position, current_price: float) -> str | None:
        """
        Returns exit reason or None.
        Priority: hard stop → trailing stop → no-progress → time exit → news reversal

        Best Loser Wins principles (Tom Hougaard):
        - Hard stop is sacred — never moved down, never bypassed
        - Trailing stop replaces fixed take_profit — winners run until momentum dies
        - No-progress exit: "assume you're wrong until proven right" (Ch.4)
          If the trade hasn't worked in NO_PROGRESS_DAYS, it's not working — exit
        """
        # 1. Hard stop — always first, always sacred (Ch.5: best loser wins)
        if current_price <= pos.stop_loss:
            return f"stop_loss (${current_price:.2f} <= ${pos.stop_loss:.2f})"

        # 2. Update and check trailing stop
        pos.update_trailing_stop(current_price)
        if pos.trail_active and current_price <= pos.trailing_stop:
            return (
                f"trailing_stop (${current_price:.2f} <= ${pos.trailing_stop:.2f} | "
                f"high=${pos.highest_price:.2f})"
            )

        # 3. No-progress exit — "assume you're wrong" (Ch.4)
        # Day-trading mode: minute-based, not day-based — a trade that isn't
        # moving within NO_PROGRESS_MINUTES hasn't been proven right yet.
        if (config.DAY_TRADING_MODE
                and pos.hold_minutes() >= config.NO_PROGRESS_MINUTES
                and pos.pnl_pct(current_price) < config.NO_PROGRESS_MIN_GAIN_INTRADAY):
            # Flat is not the same as failing. A position chopping sideways above
            # its short-term average is still intact; one rolling over is not.
            # MSFT 2026-09-21 was cut here at -0.29% while holding above its MA,
            # then closed +1.46%. Only cut when price is actually deteriorating.
            if self._is_deteriorating(pos.symbol, current_price):
                return (
                    f"no_progress ({pos.hold_minutes():.0f}min held, "
                    f"only {pos.pnl_pct(current_price):.1%}, below "
                    f"{config.NO_PROGRESS_MA_PERIOD}-bar MA — assumed wrong)"
                )
        if (not config.DAY_TRADING_MODE
                and pos.hold_days() >= config.NO_PROGRESS_DAYS
                and pos.pnl_pct(current_price) < config.NO_PROGRESS_MIN_GAIN):
            return (
                f"no_progress ({pos.hold_days()}d held, "
                f"only {pos.pnl_pct(current_price):.1%} — assumed wrong)"
            )

        # 4. Time ceiling — absolute maximum hold
        if config.DAY_TRADING_MODE:
            if pos.hold_minutes() >= config.MAX_HOLD_MINUTES:
                return f"time_exit ({pos.hold_minutes():.0f}min — {config.MAX_HOLD_MINUTES}min max)"
            if pos.hold_minutes() < config.MIN_HOLD_MINUTES:
                return None
        else:
            max_hold = pos.rules.get("max_hold_days", config.MAX_HOLD_DAYS)
            if pos.hold_days() >= max_hold:
                return f"time_exit ({pos.hold_days()}d — {max_hold}d max)"
            if pos.hold_days() < config.MIN_HOLD_DAYS:
                return None

        # 5. News reversal — only exit into profit
        sentiment = news_agent.analyse(pos.symbol)
        if sentiment.label == "bearish" and pos.pnl_pct(current_price) > 0:
            logger.warning(
                f"NEWS ALERT [{pos.symbol}]: bearish sentiment (score={sentiment.score}) "
                f"— exiting to lock in {pos.pnl_pct(current_price):.1%} profit"
            )
            return "news_reversal (bearish sentiment, locking in profit)"

        return None

    def flatten_for_close(self):
        """
        Day-trading EOD safeguard: force-close every open position before
        market close. Without this, a position carries overnight — which
        defeats the point of day trading (reintroduces gap risk this mode
        is meant to avoid) and would count toward PDT differently than
        intended if closed the next session instead.
        """
        if not self.positions:
            return
        logger.warning(f"EOD FLATTEN: closing {len(self.positions)} open position(s) before market close")
        for symbol, pos in list(self.positions.items()):
            current_price = self.client.get_latest_price(symbol)
            if not current_price:
                current_price = pos.entry_price
            self._exit_trade(pos, current_price, "eod_flatten (day-trading mode — no overnight holds)")

    def _day_trade_count_5d(self) -> int:
        """
        Count same-day round-trips (entry and exit on the same calendar
        date) over the trailing 5 calendar days — the FINRA PDT definition.
        This is a simulated guard so paper testing reflects what the real
        $500 account would actually be allowed to do (see config.py note).
        """
        return tl.count_day_trades(days=5)

    def _exit_trade(self, pos: Position, exit_price: float, reason: str):
        order = self.client.submit_market_sell(pos.symbol, pos.qty)
        if order:
            actual_exit_price = float(order.filled_avg_price or exit_price)
            # Apply modeled slippage on stop-loss exits — Alpaca paper fills
            # at exactly the stop price with zero gap, but real stops on a
            # fast-moving stock fill worse. This makes paper metrics more honest.
            if reason.startswith("stop_loss"):
                actual_exit_price = round(actual_exit_price * (1 - config.STOP_SLIPPAGE_PCT), 4)
            tl.log_trade_exit(pos.trade_id, actual_exit_price, reason)
            pnl = pos.pnl_pct(actual_exit_price)
            outcome = "WIN" if pnl > 0 else "LOSS"
            logger.info(
                f"EXITED [{outcome}]: {pos.symbol} | price=${actual_exit_price:.2f} | "
                f"PnL={pnl:.2%} | reason={reason} | held={pos.hold_minutes():.0f}min"
            )
            del self.positions[pos.symbol]
            self._save_positions()
        else:
            logger.error(
                f"SELL order for {pos.symbol} did not confirm filled — "
                f"position kept open in memory, will retry next cycle"
            )

    # ── Trajectory logging (Ch.1: trajectory > current results) ─

    def log_trajectory(self):
        """
        Log rolling win rate vs all-time win rate each cycle.
        If trajectory is declining, the constitution needs a rebuild.
        "You should be far more concerned with your current trajectory
        than with your current results." (Ch.1)
        """
        summary  = tl.get_summary()
        rolling  = tl.get_rolling_win_rate(config.ROLLING_WIN_RATE_WINDOW)
        alltime  = summary.get("win_rate", 0)
        total    = summary.get("total_trades", 0)

        if total < 10:
            return

        trend = "IMPROVING" if rolling > alltime else ("STABLE" if abs(rolling - alltime) < 0.05 else "DECLINING")
        logger.info(
            f"[TRAJECTORY] Last-{config.ROLLING_WIN_RATE_WINDOW}: {rolling:.1%} | "
            f"All-time: {alltime:.1%} | Trend: {trend} | "
            f"Total trades: {total}"
        )

        if trend == "DECLINING" and rolling < 0.40:
            logger.warning(
                "Trajectory DECLINING below 40% — consider running constitution_builder.py "
                "to re-derive rules from recent performance."
            )

    # ── Summary ───────────────────────────────────────────────

    def open_positions_summary(self) -> list:
        summary = []
        for symbol, pos in self.positions.items():
            price = self.client.get_latest_price(symbol) or pos.entry_price
            summary.append({
                "symbol":         symbol,
                "theme":          config.WATCHLIST.get(symbol, {}).get("theme", "?"),
                "entry":          pos.entry_price,
                "current":        price,
                "pnl_pct":        round(pos.pnl_pct(price) * 100, 2),
                "hold_days":      pos.hold_days(),
                "hold_minutes":   round(pos.hold_minutes(), 1),
                "stop_loss":      pos.stop_loss,
                "trailing_stop":  pos.trailing_stop,
                "trail_active":   pos.trail_active,
                "highest_price":  pos.highest_price,
                "score":          pos.signal_score,
            })
        return summary
