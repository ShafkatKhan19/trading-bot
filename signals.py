# ============================================================
#  signals.py — Technical indicator calculations
#  RSI, Moving Average crossover, MACD, Volume surge,
#  plus stock-level uptrend filter (own 50MA)
# ============================================================

import pandas as pd
import numpy as np
import logging
import config

logger = logging.getLogger(__name__)


class SignalResult:
    """Holds the outcome of signal analysis for one ticker."""

    def __init__(self, symbol: str):
        self.symbol        = symbol
        self.rsi           = None
        self.rsi_signal    = False
        self.ma_signal     = False
        self.macd_signal   = False
        self.volume_signal = False
        self.score         = 0
        self.reason        = []

    def compute_score(self):
        self.score = sum([
            self.rsi_signal,
            self.ma_signal,
            self.macd_signal,
            self.volume_signal,
        ])

    def is_entry_valid(self, min_score: int = None) -> bool:
        threshold = min_score if min_score is not None else config.MIN_SIGNAL_SCORE
        return self.score >= threshold

    def summary(self) -> str:
        return (f"{self.symbol} | score={self.score}/4 | "
                f"RSI={self.rsi:.1f} | "
                f"{'ENTER' if self.is_entry_valid() else 'SKIP'}")


# ── Individual indicator functions ────────────────────────────

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(series: pd.Series,
              fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast    = series.ewm(span=fast, adjust=False).mean()
    ema_slow    = series.ewm(span=slow, adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_volume_surge(volume: pd.Series, period: int = 20) -> pd.Series:
    avg = volume.rolling(window=period).mean()
    return volume / avg


# ── Stock-level uptrend filter ────────────────────────────────

def is_stock_in_uptrend(df_trend: pd.DataFrame) -> bool:
    """
    Returns True if the stock itself is trading above its own 50-day MA.
    Prevents buying into a downtrending stock even when a short-term
    signal fires — a common cause of false entries.
    Falls back to True when insufficient data (don't block on data gaps).
    """
    if df_trend is None or len(df_trend) < config.MA_SLOW:
        return True
    close = df_trend["close"]
    ma50  = close.rolling(window=config.MA_SLOW).mean()
    in_uptrend = close.iloc[-1] > ma50.iloc[-1]
    if not in_uptrend:
        logger.debug(f"Stock below own 50MA — uptrend filter blocked entry")
    return in_uptrend


# ── Main signal analyser ──────────────────────────────────────

def analyse(symbol: str, df: pd.DataFrame, rules: dict = None) -> SignalResult:
    """
    Run all four indicators on OHLCV dataframe.
    rules: optional per-segment overrides (from config.SEGMENT_RULES).
           If supplied, volume_surge_mult is taken from rules.
    """
    result = SignalResult(symbol)
    r      = rules or {}

    volume_surge_mult = r.get("volume_surge_mult", config.VOLUME_SURGE_MULT)

    if df is None or len(df) < config.MA_SLOW + 10:
        logger.warning(f"{symbol}: not enough data for signal analysis")
        result.reason.append("Insufficient data")
        return result

    close  = df["close"]
    volume = df["volume"]

    # ── RSI ───────────────────────────────────────────────────
    rsi      = calc_rsi(close, config.RSI_PERIOD)
    result.rsi = rsi.iloc[-1]
    prev_rsi   = rsi.iloc[-2]

    if prev_rsi < config.RSI_OVERSOLD and result.rsi > prev_rsi:
        result.rsi_signal = True
        result.reason.append(f"RSI recovering from oversold ({result.rsi:.1f})")
    elif result.rsi > config.RSI_OVERBOUGHT:
        result.reason.append(f"RSI overbought ({result.rsi:.1f}) — no entry")
    else:
        result.reason.append(f"RSI neutral ({result.rsi:.1f})")

    # ── Moving average crossover ──────────────────────────────
    ma_fast    = close.rolling(window=config.MA_FAST).mean()
    ma_slow    = close.rolling(window=config.MA_SLOW).mean()
    price_now  = close.iloc[-1]
    fast_now   = ma_fast.iloc[-1]
    fast_prev  = ma_fast.iloc[-2]
    slow_now   = ma_slow.iloc[-1]

    if price_now > fast_now and fast_now > slow_now and fast_prev <= slow_now:
        result.ma_signal = True
        result.reason.append("MA crossover: fast crossed above slow")
    elif price_now > fast_now and fast_now > slow_now:
        result.ma_signal = True
        result.reason.append("Price above both MAs (uptrend)")
    else:
        result.reason.append("MA: no bullish crossover")

    # ── MACD ──────────────────────────────────────────────────
    macd_line, signal_line, _ = calc_macd(
        close, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    )
    macd_now  = macd_line.iloc[-1]
    macd_prev = macd_line.iloc[-2]
    sig_now   = signal_line.iloc[-1]
    sig_prev  = signal_line.iloc[-2]

    if macd_prev < sig_prev and macd_now > sig_now:
        result.macd_signal = True
        result.reason.append("MACD crossed above signal line")
    elif macd_now > sig_now:
        result.macd_signal = True
        result.reason.append("MACD above signal line (momentum)")
    else:
        result.reason.append("MACD: no bullish cross")

    # ── Volume surge ──────────────────────────────────────────
    vol_ratio = calc_volume_surge(volume).iloc[-1]
    if vol_ratio >= volume_surge_mult:
        result.volume_signal = True
        result.reason.append(f"Volume surge: {vol_ratio:.2f}x (need {volume_surge_mult}x)")
    else:
        result.reason.append(f"Volume weak: {vol_ratio:.2f}x (need {volume_surge_mult}x)")

    result.compute_score()
    logger.debug(result.summary())
    return result


# ── Market regime check ───────────────────────────────────────

def is_market_bullish(df_regime: pd.DataFrame) -> bool:
    """QQQ must be above its 50-day MA — macro tailwind gate."""
    if df_regime is None or len(df_regime) < config.REGIME_MA_PERIOD:
        return False
    close   = df_regime["close"]
    ma50    = close.rolling(window=config.REGIME_MA_PERIOD).mean()
    bullish = close.iloc[-1] > ma50.iloc[-1]
    if not bullish:
        logger.warning("Market regime: QQQ below 50MA — entries paused")
    return bullish
