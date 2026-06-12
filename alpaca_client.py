# ============================================================
#  alpaca_client.py — Alpaca API connection wrapper
#  Handles all communication with Alpaca paper/live API
# ============================================================

import logging
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from datetime import datetime, timedelta
import config

logger = logging.getLogger(__name__)


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

    def close_all_positions(self):
        """Kill switch: close everything immediately."""
        try:
            self.trading.close_all_positions(cancel_orders=True)
            logger.warning("ALL POSITIONS CLOSED — kill switch executed")
        except Exception as e:
            logger.error(f"Error closing all positions: {e}")

    # ── Orders ────────────────────────────────────────────────

    def cancel_all_orders(self):
        """Cancel every open order."""
        try:
            self.trading.cancel_orders()
            logger.info("All open orders cancelled")
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")

    def submit_market_buy(self, symbol: str, qty: float):
        """Submit a market buy order."""
        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
            order = self.trading.submit_order(req)
            logger.info(f"BUY order submitted: {symbol} x{qty}")
            return order
        except Exception as e:
            logger.error(f"BUY order failed {symbol}: {e}")
            return None

    def submit_market_sell(self, symbol: str, qty: float):
        """Submit a market sell order."""
        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
            order = self.trading.submit_order(req)
            logger.info(f"SELL order submitted: {symbol} x{qty}")
            return order
        except Exception as e:
            logger.error(f"SELL order failed {symbol}: {e}")
            return None

    # ── Market data ───────────────────────────────────────────

    def get_bars(self, symbol: str, timeframe: str = "1Day", days: int = 60):
        """
        Fetch historical OHLCV bars for a symbol.
        timeframe options: '1Day', '4Hour', '1Hour'
        Returns a pandas DataFrame.
        """
        tf_map = {
            "1Day":  TimeFrame.Day,
            "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
            "1Hour": TimeFrame.Hour,
        }
        tf = tf_map.get(timeframe, TimeFrame.Day)
        start = datetime.now() - timedelta(days=days)

        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                start=start
            )
            bars = self.data.get_stock_bars(req)
            df = bars.df
            if isinstance(df.index, object) and hasattr(df.index, 'get_level_values'):
                df = df.xs(symbol, level='symbol') if symbol in df.index.get_level_values(0) else df
            return df
        except Exception as e:
            logger.error(f"Failed to get bars for {symbol}: {e}")
            return None

    def get_latest_price(self, symbol: str) -> float:
        """Return the latest ask price for a symbol."""
        try:
            req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.data.get_stock_latest_quote(req)
            return float(quote[symbol].ask_price)
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None
