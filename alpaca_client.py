# ============================================================
#  alpaca_client.py — Alpaca API connection wrapper
#  Handles all communication with Alpaca paper/live API
# ============================================================

import logging
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import Adjustment, DataFeed
from datetime import datetime, timedelta, timezone
import config

logger = logging.getLogger(__name__)

_TF_MINUTES = {"5Min": 5, "15Min": 15, "1Hour": 60, "4Hour": 240}


class AlpacaClient:
    """
    Wraps Alpaca trading and data APIs.
    Switching from paper to live = change ALPACA_BASE_URL in .env
    """

    def __init__(self):
        self.trading = TradingClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
            paper=(config.TRADING_MODE == "paper")
        )
        self.data = StockHistoricalDataClient(
            api_key=config.ALPACA_API_KEY,
            secret_key=config.ALPACA_SECRET_KEY,
        )
        logger.info(f"Alpaca client initialised — mode: {config.TRADING_MODE.upper()}")

    # ── Account ───────────────────────────────────────────────

    def get_account(self):
        """Return account object with equity, cash, buying_power."""
        return self.trading.get_account()

    def get_portfolio_value(self) -> float:
        """Return current total portfolio equity as float."""
        account = self.get_account()
        return float(account.equity)

    def get_cash(self) -> float:
        return float(self.get_account().cash)

    # ── Positions ─────────────────────────────────────────────

    def get_positions(self) -> list:
        """Return list of all open positions."""
        return self.trading.get_all_positions()

    def get_position(self, symbol: str):
        """Return position for a single symbol, or None."""
        try:
            return self.trading.get_open_position(symbol)
        except Exception:
            return None

    def close_position(self, symbol: str):
        """Close a single position at market."""
        try:
            self.trading.close_position(symbol)
            logger.info(f"Closed position: {symbol}")
        except Exception as e:
            logger.error(f"Failed to close {symbol}: {e}")

    def close_all_positions(self) -> bool:
        """Kill switch: close everything immediately. Returns True on success."""
        try:
            self.trading.close_all_positions(cancel_orders=True)
            logger.warning("ALL POSITIONS CLOSED — kill switch executed")
            return True
        except Exception as e:
            # The kill switch calls this expecting positions to be flat afterward —
            # swallowing this silently would let it believe a stop succeeded when
            # the account still holds risk. Caller must check the return value.
            logger.critical(f"FAILED to close all positions during kill switch: {e}", exc_info=True)
            return False

    # ── Orders ────────────────────────────────────────────────

    def cancel_all_orders(self) -> bool:
        """Cancel every open order. Returns True on success."""
        try:
            self.trading.cancel_orders()
            logger.info("All open orders cancelled")
            return True
        except Exception as e:
            logger.critical(f"FAILED to cancel all orders during kill switch: {e}", exc_info=True)
            return False

    def _wait_for_fill(self, order, timeout_s: int = 30, poll_s: float = 1.0):
        """
        Poll order status until it reaches a terminal state.
        A submitted market order is NOT a fill — without this, the strategy
        would assume the quoted price filled exactly, hiding rejections,
        partial fills, and slippage from the trade logic entirely.
        Returns the final order object, or None if it never filled.
        """
        import time as _time
        elapsed = 0.0
        while elapsed < timeout_s:
            try:
                current = self.trading.get_order_by_id(order.id)
            except Exception as e:
                logger.error(f"Failed to poll order {order.id}: {e}")
                return None

            status = current.status.value if hasattr(current.status, "value") else str(current.status)
            if status == "filled":
                filled_qty   = float(current.filled_qty or 0)
                filled_price = float(current.filled_avg_price or 0)
                logger.info(f"Order {order.id} FILLED: {filled_qty} @ ${filled_price:.2f}")
                return current
            if status in ("canceled", "expired", "rejected"):
                logger.error(f"Order {order.id} ended in status={status} — not filled")
                return None
            if status == "partially_filled" and elapsed + poll_s >= timeout_s:
                # Out of time but something filled — treat as the result we got.
                logger.warning(f"Order {order.id} only partially filled before timeout")
                return current

            _time.sleep(poll_s)
            elapsed += poll_s

        logger.error(f"Order {order.id} did not reach a terminal state within {timeout_s}s — cancelling")
        try:
            self.trading.cancel_order_by_id(order.id)
        except Exception as e:
            logger.critical(
                f"FAILED to cancel order {order.id} after timeout — it may still fill "
                f"unmanaged on the broker with no stop-loss tracking: {e}", exc_info=True
            )
        return None

    @staticmethod
    def _tif(symbol: str):
        """Crypto trades 24/7 and rejects DAY — it requires GTC. Equities keep
        DAY so an unfilled order cannot leak into the next session."""
        return TimeInForce.GTC if "/" in symbol else TimeInForce.DAY

    def submit_market_buy(self, symbol: str, qty: float):
        """Submit a market buy order and block until it's confirmed filled."""
        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=self._tif(symbol)
            )
            order = self.trading.submit_order(req)
            logger.info(f"BUY order submitted: {symbol} x{qty} (id={order.id})")
            return self._wait_for_fill(order)
        except Exception as e:
            logger.error(f"BUY order failed {symbol}: {e}")
            return None

    def is_shortable(self, symbol: str) -> bool:
        """Crypto cannot be sold short on Alpaca, and some equities are
        hard-to-borrow. Checked before a sell-to-open so the strategy skips
        the setup rather than firing an order the broker will reject."""
        try:
            return bool(self.trading.get_asset(symbol).shortable)
        except Exception as e:
            logger.warning(f"Could not check shortability for {symbol}: {e}")
            return False

    def submit_protective_stop(self, symbol: str, qty: float, stop_price: float,
                               side: str = "SELL"):
        """Rest a stop at the broker so the exchange enforces it.

        Without this the stop is only as fast as the polling loop: on
        2026-09-23 ETH fell $59 in ten minutes and the 5-minute cycle exited
        $27.84 below the intended stop — 3.5x the risk the trade was sized for.

        Order type differs by asset class, verified against the live API:
          equities — STOP (becomes a market order on trigger)
          crypto   — STOP_LIMIT; plain STOP and TRAILING_STOP are rejected as
                     "invalid order type for crypto order".
        A stop-limit can miss a fill if price jumps clean through the limit, so
        the limit is placed CRYPTO_STOP_LIMIT_SLACK_PCT beyond the trigger —
        wide enough to fill in a fast move, bounded enough to cap the damage.
        """
        from alpaca.trading.requests import StopOrderRequest, StopLimitOrderRequest
        order_side = OrderSide.BUY if str(side).upper() == "BUY" else OrderSide.SELL
        try:
            if "/" in symbol:
                slack = getattr(config, "CRYPTO_STOP_LIMIT_SLACK_PCT", 0.005)
                limit = (stop_price * (1 - slack) if order_side == OrderSide.SELL
                         else stop_price * (1 + slack))
                req = StopLimitOrderRequest(
                    symbol=symbol, qty=qty, side=order_side,
                    time_in_force=TimeInForce.GTC,
                    stop_price=round(stop_price, 2), limit_price=round(limit, 2),
                )
            else:
                req = StopOrderRequest(
                    symbol=symbol, qty=qty, side=order_side,
                    time_in_force=TimeInForce.DAY, stop_price=round(stop_price, 2),
                )
            order = self.trading.submit_order(req)
            logger.info(f"Protective stop resting at broker: {symbol} x{qty} @ ${stop_price:.2f} (id={order.id})")
            return order
        except Exception as e:
            logger.error(f"Protective stop FAILED for {symbol} @ ${stop_price:.2f}: {e}")
            return None

    def cancel_order(self, order_id) -> bool:
        """Cancel a resting order. Already-filled or already-cancelled is fine."""
        try:
            self.trading.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            logger.info(f"Could not cancel order {order_id} (likely already done): {e}")
            return False

    def get_order(self, order_id):
        try:
            return self.trading.get_order_by_id(order_id)
        except Exception:
            return None

    def held_qty(self, symbol: str) -> float:
        """Quantity actually held at the broker, or 0.

        A crypto buy can fill slightly under the requested size (fees are taken
        in the asset), so selling the recorded fill quantity is rejected for
        insufficient balance and the position never closes. Always close against
        what the broker says is held.
        """
        # Market data uses "BTC/USD"; positions come back as "BTCUSD".
        pos = self.get_position(symbol) or (
            self.get_position(symbol.replace("/", "")) if "/" in symbol else None
        )
        if not pos:
            return 0.0
        try:
            return abs(float(pos.qty_available or pos.qty))
        except Exception:
            return abs(float(pos.qty))

    def submit_market_sell(self, symbol: str, qty: float):
        """Submit a market sell order and block until it's confirmed filled."""
        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=self._tif(symbol)
            )
            order = self.trading.submit_order(req)
            logger.info(f"SELL order submitted: {symbol} x{qty} (id={order.id})")
            return self._wait_for_fill(order)
        except Exception as e:
            logger.error(f"SELL order failed {symbol}: {e}")
            return None

    # ── Market data ───────────────────────────────────────────

    def get_bars(self, symbol: str, timeframe: str = "1Day", days: int = 60,
                 split_adjusted: bool = True):
        """
        Fetch historical OHLCV bars for a symbol.
        timeframe options: '1Day', '4Hour', '1Hour', '15Min', '5Min'
        split_adjusted (default True): Alpaca's own default is raw prices, where
        a split looks like a -90% crash (NVDA 10:1, 2024-06-10) or a reverse
        split like a +300% spike (VIXY). Every indicator here compares a price
        to its own history, so all bars are split-adjusted — which is also what
        intraday_backtest.py was tested on.
        Returns a pandas DataFrame.
        """
        tf_map = {
            "1Day":  TimeFrame.Day,
            "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
            "1Hour": TimeFrame.Hour,
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "5Min":  TimeFrame(5, TimeFrameUnit.Minute),
        }
        tf = tf_map.get(timeframe, TimeFrame.Day)
        start = datetime.now(timezone.utc) - timedelta(days=days)

        # Crypto pairs ("BTC/USD") are served by a different endpoint than
        # equities; the stock endpoint rejects them as invalid symbols.
        if "/" in symbol:
            return self._get_crypto_bars(symbol, tf, start)

        # Feed selection — see config.BAR_FEED. Without an explicit feed a
        # free-plan account silently gets IEX (~3% of volume, near-empty
        # pre-market), which is what the bot ran on before.
        end, feed = None, None
        if config.BAR_FEED == "sip_delayed":
            feed = DataFeed.SIP
            end  = datetime.now(timezone.utc) - timedelta(minutes=config.SIP_DELAY_MINUTES)
        elif config.BAR_FEED == "sip":
            feed = DataFeed.SIP
        elif config.BAR_FEED == "iex":
            feed = DataFeed.IEX

        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start,
                end=end,
                feed=feed,
                adjustment=Adjustment.SPLIT if split_adjusted else Adjustment.RAW,
            )
            bars = self.data.get_stock_bars(req)
            df = bars.df
            if isinstance(df.index, pd.MultiIndex) and 'symbol' in df.index.names:
                df = df.xs(symbol, level='symbol')
            # With a delayed end the last intraday bar can be only partly
            # built. Keep bars that were complete by `end`, which is exactly
            # what intraday_backtest.py assumes. Daily bars keep today's
            # partial bar on purpose (the regime/VIX gates want today's move).
            minutes = _TF_MINUTES.get(timeframe)
            if end is not None and minutes and len(df):
                df = df[df.index + pd.Timedelta(minutes=minutes) <= pd.Timestamp(end)]
            return df
        except Exception as e:
            logger.error(f"Failed to get bars for {symbol}: {e}")
            return None

    def _get_crypto_bars(self, symbol: str, tf, start):
        """Crypto OHLCV, shaped identically to the equity path so callers
        need no special-casing. Crypto data needs no API keys."""
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoBarsRequest
            if not hasattr(self, "_crypto_data"):
                self._crypto_data = CryptoHistoricalDataClient()
            req = CryptoBarsRequest(
                symbol_or_symbols=symbol, timeframe=tf, start=start
            )
            df = self._crypto_data.get_crypto_bars(req).df
            if isinstance(df.index, pd.MultiIndex) and 'symbol' in df.index.names:
                df = df.xs(symbol, level='symbol')
            return df
        except Exception as e:
            logger.error(f"Failed to get crypto bars for {symbol}: {e}")
            return None

    def get_latest_price(self, symbol: str) -> float:
        """
        Return the latest quote midpoint for a symbol.
        Using ask-only overstates unrealized PnL on open positions (you'd sell
        at bid, not ask) and can misjudge stop/trail triggers near the spread.
        """
        try:
            if "/" in symbol:
                from alpaca.data.historical import CryptoHistoricalDataClient
                from alpaca.data.requests import CryptoLatestQuoteRequest
                if not hasattr(self, "_crypto_data"):
                    self._crypto_data = CryptoHistoricalDataClient()
                q = self._crypto_data.get_crypto_latest_quote(
                    CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
                )
                bid = float(q[symbol].bid_price)
                ask = float(q[symbol].ask_price)
                if bid <= 0 and ask <= 0:
                    return None
                return (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)

            req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.data.get_stock_latest_quote(req)
            bid = float(quote[symbol].bid_price)
            ask = float(quote[symbol].ask_price)
            if bid <= 0 and ask <= 0:
                logger.warning(f"{symbol}: no valid bid/ask — outside market hours or illiquid, skipping")
                return None
            price = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
            return price
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None
