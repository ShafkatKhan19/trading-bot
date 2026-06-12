# ============================================================
#  strategy.py — Swing trade entry and exit logic
#  Per-segment rules: each market theme has its own stop loss,
#  take profit, hold days, and signal requirements.
# ============================================================

import logging
from datetime import datetime, date
import config
import signals as sig
import news_agent
import trade_logger as tl
from constitution_validator import constitution_allows

logger = logging.getLogger(__name__)


class Position:
    """Tracks an open swing trade position, including its segment rules."""

    def __init__(self, symbol, entry_price, qty, trade_id,
                 stop_loss, take_profit, entry_date, signal_score, rules):
        self.symbol       = symbol
        self.entry_price  = entry_price
        self.qty          = qty
        self.trade_id     = trade_id
        self.stop_loss    = stop_loss
        self.take_profit  = take_profit
        self.entry_date   = entry_date
        self.signal_score = signal_score
        self.rules        = rules   # segment-specific rules locked at entry time

    def hold_days(self) -> int:
        return (date.today() - self.entry_date).days

    def pnl_pct(self, current_price: float) -> float:
        return (current_price - self.entry_price) / self.entry_price


class SwingStrategy:
    """
    Core swing trading strategy with per-segment rules.

    Entry gates (all must pass):
      1. Kill switch clear
      2. Max open positions not reached
      3. QQQ above 50MA (market regime)
      4. Stock above its own 50MA (stock-level uptrend filter)
      5. RSI >= segment rsi_min_entry (momentum floor)
      6. Signal score >= segment min_signal_score
      7. News sentiment not bearish / no earnings blackout
      8. Constitution (live mode only)

    Exit priority: stop-loss → take-profit → time exit → news reversal
    """

    def __init__(self, alpaca_client, kill_switch):
        self.client      = alpaca_client
        self.kill_switch = kill_switch
        self.positions   = {}
        self.mode        = config.TRADING_MODE

    # ── Safety gate ───────────────────────────────────────────

    def _is_safe_to_trade(self) -> bool:
        if self.kill_switch.check():
            logger.warning("Strategy blocked — kill switch is ACTIVE")
            return False
        return True

    # ── Position sizing ───────────────────────────────────────

    def _calc_qty(self, symbol: str, price: float) -> float:
        portfolio   = self.client.get_portfolio_value()
        max_dollars = portfolio * config.MAX_POSITION_PCT
        qty         = max_dollars / price
        return round(qty, 2)

    # ── Entry decision ────────────────────────────────────────

    def evaluate_entry(self, symbol: str, df_signal, df_trend, df_regime) -> bool:
        """
        Full entry evaluation using segment-specific rules.
        Returns True if a trade was entered.
        """
        if not self._is_safe_to_trade():
            return False

        if symbol in self.positions:
            return False

        if len(self.positions) >= config.MAX_OPEN_POSITIONS:
            logger.debug(f"{symbol}: max positions reached")
            return False

        # Macro regime gate: QQQ must be in uptrend
        if not sig.is_market_bullish(df_regime):
            tl.log_rejection(symbol, "Market regime bearish (QQQ < 50MA)")
            return False

        # Stock-level uptrend gate: stock must be above its own 50MA
        if not sig.is_stock_in_uptrend(df_trend):
            tl.log_rejection(symbol, f"{symbol} below own 50MA — no entry in downtrend")
            return False

        # Get this ticker's segment rules
        rules = config.get_segment_rules(symbol)

        # Technical signals (volume threshold from segment rules)
        signal_result = sig.analyse(symbol, df_signal, rules)
        tl.log_signal(
            symbol, signal_result.rsi,
            signal_result.ma_signal, signal_result.macd_signal,
            signal_result.volume_signal, signal_result.score,
            "EVALUATE", " | ".join(signal_result.reason)
        )

        # Signal score gate — use segment threshold
        if not signal_result.is_entry_valid(rules["min_signal_score"]):
            tl.log_rejection(
                symbol,
                f"Signal score {signal_result.score} < {rules['min_signal_score']} required for {config.WATCHLIST[symbol]['theme']}",
                signal_score=signal_result.score,
            )
            return False

        # RSI momentum floor — don't buy into a dead stock even if it's technically oversold
        rsi_min = rules["rsi_min_entry"]
        if signal_result.rsi is not None and signal_result.rsi < rsi_min:
            tl.log_rejection(
                symbol,
                f"RSI {signal_result.rsi:.1f} below minimum entry floor {rsi_min} — no momentum",
                signal_score=signal_result.score,
            )
            return False

        # News sentiment gate
        sentiment = news_agent.analyse(symbol)
        safe, reason = news_agent.is_safe_to_enter(sentiment)
        if not safe:
            tl.log_rejection(symbol, reason, signal_score=signal_result.score,
                             news_label=sentiment.label)
            return False

        # Constitution gate (live mode only)
        if self.mode == "live":
            allowed, const_reason = constitution_allows(symbol, signal_result, sentiment)
            if not allowed:
                tl.log_rejection(symbol, f"Constitution: {const_reason}",
                                 signal_score=signal_result.score)
                return False

        return self._enter_trade(symbol, signal_result, sentiment, rules)

    def _enter_trade(self, symbol: str, signal_result, sentiment, rules: dict) -> bool:
        """Place the buy order using segment-specific stop/target levels."""
        price = self.client.get_latest_price(symbol)
        if not price:
            return False

        qty = self._calc_qty(symbol, price)
        if qty < 1:
            logger.warning(f"{symbol}: qty too small ({qty}) — insufficient capital")
            return False

        stop_loss   = round(price * (1 - rules["stop_loss_pct"]),   2)
        take_profit = round(price * (1 + rules["take_profit_pct"]), 2)

        trade_id = tl.log_trade_entry(
            symbol=symbol,
            entry_price=price,
            qty=qty,
            rsi=signal_result.rsi,
            signal_score=signal_result.score,
            news_sentiment=sentiment.label,
            market_regime="bullish",
            mode=self.mode,
        )

        order = self.client.submit_market_buy(symbol, qty)
        if not order:
            return False

        self.positions[symbol] = Position(
            symbol=symbol,
            entry_price=price,
            qty=qty,
            trade_id=trade_id,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_date=date.today(),
            signal_score=signal_result.score,
            rules=rules,
        )

        theme = config.WATCHLIST.get(symbol, {}).get("theme", "?")
        logger.info(
            f"ENTERED: {symbol} [{theme}] | price=${price:.2f} | qty={qty} | "
            f"stop=${stop_loss:.2f} ({rules['stop_loss_pct']:.0%}) | "
            f"target=${take_profit:.2f} ({rules['take_profit_pct']:.0%}) | "
            f"signal={signal_result.score}/{rules['min_signal_score']} | "
            f"news={sentiment.label}"
        )
        return True

    # ── Exit evaluation ───────────────────────────────────────

    def evaluate_exits(self):
        if not self._is_safe_to_trade():
            return

        for symbol, pos in list(self.positions.items()):
            current_price = self.client.get_latest_price(symbol)
            if not current_price:
                continue

            exit_reason = self._should_exit(pos, current_price)
            if exit_reason:
                self._exit_trade(pos, current_price, exit_reason)

    def _should_exit(self, pos: Position, current_price: float) -> str | None:
        """
        Returns exit reason or None.
        Uses the position's locked segment rules for max_hold_days.
        Priority: stop-loss → take-profit → time exit → news reversal
        """
        if current_price <= pos.stop_loss:
            return f"stop_loss (${current_price:.2f} <= ${pos.stop_loss:.2f})"

        if current_price >= pos.take_profit:
            return f"take_profit (${current_price:.2f} >= ${pos.take_profit:.2f})"

        max_hold = pos.rules.get("max_hold_days", config.MAX_HOLD_DAYS)
        if pos.hold_days() >= max_hold:
            return f"time_exit ({pos.hold_days()}d reached — {max_hold}d max)"

        if pos.hold_days() < config.MIN_HOLD_DAYS:
            return None

        sentiment = news_agent.analyse(pos.symbol)
        if sentiment.label == "bearish" and pos.pnl_pct(current_price) > 0:
            return "news_reversal (bearish sentiment, locking in profit)"

        return None

    def _exit_trade(self, pos: Position, exit_price: float, reason: str):
        order = self.client.submit_market_sell(pos.symbol, pos.qty)
        if order:
            tl.log_trade_exit(pos.trade_id, exit_price, reason)
            logger.info(
                f"EXITED: {pos.symbol} | price=${exit_price:.2f} | "
                f"PnL={pos.pnl_pct(exit_price):.2%} | reason={reason} | "
                f"held={pos.hold_days()}d"
            )
            del self.positions[pos.symbol]

    # ── Summary ───────────────────────────────────────────────

    def open_positions_summary(self) -> list:
        summary = []
        for symbol, pos in self.positions.items():
            price = self.client.get_latest_price(symbol) or pos.entry_price
            summary.append({
                "symbol":      symbol,
                "theme":       config.WATCHLIST.get(symbol, {}).get("theme", "?"),
                "entry":       pos.entry_price,
                "current":     price,
                "pnl_pct":     round(pos.pnl_pct(price) * 100, 2),
                "hold_days":   pos.hold_days(),
                "stop_loss":   pos.stop_loss,
                "take_profit": pos.take_profit,
            })
        return summary
