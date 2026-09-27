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
        self.symbol                = symbol
        self.rsi                   = None
        self.rsi_signal            = False
        self.ma_signal             = False
        self.macd_signal           = False
        self.volume_signal         = False
        self.score                 = 0
        self.reason                = []
        self.attention_rsi_boost   = 0.0
        self.attention_macd_boost  = 0.0
        self.attention_confirms    = False
        self.candlestick_pattern   = None   # name of detected pattern, if any
        self.candlestick_bullish   = False  # pattern confirms a bullish entry
        self.candlestick_warning   = False  # bearish-reversal pattern — block/exit even on a good score

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
        rsi_str = f"{self.rsi:.1f}" if self.rsi is not None else "N/A"
        return (f"{self.symbol} | score={self.score}/4 | "
                f"RSI={rsi_str} | "
                f"{'ENTER' if self.is_entry_valid() else 'SKIP'}")


# ── Individual indicator functions ────────────────────────────

def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = avg_loss.replace(0, float('nan'))  # avoid 0/0 NaN and inf propagation
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50)  # flat price → neutral RSI, not NaN
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


# ── Tier-1 signal validation ──────────────────────────────────

def has_tier1_signals(result: "SignalResult") -> bool:
    """
    RSI recovery AND MACD crossover must both fire — these are the identity signals.
    (Ch.2: identity-based system — this bot IS a momentum trader.
     A momentum trade requires momentum confirmed from two independent sources.)

    Volume and MA are supporting signals. Without RSI + MACD, a high score could
    be MA + Volume + something else — a trend-following entry, not a momentum entry.
    We don't take those.
    """
    return result.rsi_signal and result.macd_signal


# ── Stock-level uptrend filter ────────────────────────────────

def is_stock_in_uptrend(df_trend: pd.DataFrame, df_regime: pd.DataFrame = None) -> bool:
    """
    Returns True if the stock itself is trading above its own 50-day MA.
    Prevents buying into a downtrending stock even when a short-term
    signal fires — a common cause of false entries.
    Falls back to True when insufficient data (don't block on data gaps).

    Adapts to the broader market: when QQQ is trading comfortably above
    its own 50MA (a strong market tailwind), individual stocks slightly
    below their own 50MA are still allowed, since a strong market often
    pulls names up before their MA crosses. The tolerance only opens up
    when the market itself is strong — in a weak/choppy market the filter
    stays a hard cutoff.
    """
    if df_trend is None or len(df_trend) < config.MA_SLOW:
        return True
    close = df_trend["close"]
    ma50  = close.rolling(window=config.MA_SLOW).mean()
    pct_above_ma = (close.iloc[-1] - ma50.iloc[-1]) / ma50.iloc[-1]
    in_uptrend = pct_above_ma > 0

    if not in_uptrend and df_regime is not None and len(df_regime) >= config.REGIME_MA_PERIOD:
        regime_close = df_regime["close"]
        regime_ma50  = regime_close.rolling(window=config.REGIME_MA_PERIOD).mean()
        regime_pct_above = (regime_close.iloc[-1] - regime_ma50.iloc[-1]) / regime_ma50.iloc[-1]
        if (regime_pct_above >= config.STRONG_BULL_MARKET_PCT
                and pct_above_ma >= -config.UPTREND_TOLERANCE_PCT):
            logger.debug(
                f"Stock below own 50MA ({pct_above_ma:.1%}) but QQQ strongly "
                f"bullish ({regime_pct_above:.1%} above its 50MA) — tolerance allows entry"
            )
            return True

    if not in_uptrend:
        logger.debug(f"Stock below own 50MA — uptrend filter blocked entry")
    return in_uptrend


# ── Candlestick pattern recognition ───────────────────────────
# Reference: tradingsim.com/blog/candlestick-patterns-explained
# Patterns are read off the last 1-3 completed bars of the signal dataframe.
# Bullish patterns ADD confirmation on borderline entries; bearish-reversal
# patterns at the top of an extended move WARN/BLOCK regardless of score —
# a perfect RSI+MACD+MA+Volume score doesn't matter if the candles are
# screaming exhaustion.

def _candle_parts(o, h, l, c):
    body       = abs(c - o)
    full_range = max(h - l, 1e-9)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return body, full_range, upper_wick, lower_wick


def detect_candlestick_pattern(df: pd.DataFrame, lookback: int = 20) -> tuple:
    """
    Inspects the last few completed bars for a known reversal/continuation
    pattern. Returns (pattern_name_or_None, is_bullish, is_bearish_warning).

    Trend context (uptrend/downtrend over `lookback` bars) is required for
    the directional patterns (hammer/hanging-man, morning/evening star) —
    the same candle shape means opposite things depending on what preceded it.
    """
    if df is None or len(df) < lookback + 3:
        return None, False, False

    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    closes = c.iloc[-(lookback + 1):-1]
    prior_trend_up = closes.iloc[-1] > closes.iloc[0]

    o1, h1, l1, c1 = o.iloc[-1], h.iloc[-1], l.iloc[-1], c.iloc[-1]
    o2, h2, l2, c2 = o.iloc[-2], h.iloc[-2], l.iloc[-2], c.iloc[-2]
    o3, h3, l3, c3 = o.iloc[-3], h.iloc[-3], l.iloc[-3], c.iloc[-3]

    body1, range1, upper1, lower1 = _candle_parts(o1, h1, l1, c1)
    body2, range2, upper2, lower2 = _candle_parts(o2, h2, l2, c2)
    body3, range3, upper3, lower3 = _candle_parts(o3, h3, l3, c3)

    # ── Bullish engulfing: green body fully covers prior red body ──
    if c2 < o2 and c1 > o1 and c1 >= o2 and o1 <= c2 and body1 > body2:
        return "bullish_engulfing", True, False

    # ── Bearish engulfing: red body fully covers prior green body ──
    if c2 > o2 and c1 < o1 and o1 >= c2 and c1 <= o2 and body1 > body2:
        return "bearish_engulfing", False, True

    # ── Hammer (downtrend) / Hanging man (uptrend) ──
    # Same shape: small body near the high, long lower wick (>= 2x body).
    small_body_near_high = body1 <= range1 * 0.35 and lower1 >= body1 * 2 and upper1 <= body1
    if small_body_near_high:
        if not prior_trend_up:
            return "hammer", True, False
        else:
            return "hanging_man", False, True

    # ── Gravestone doji: long upper wick, tiny body near the low ──
    if body1 <= range1 * 0.1 and upper1 >= range1 * 0.6 and lower1 <= range1 * 0.1:
        if prior_trend_up:
            return "gravestone_doji", False, True

    # ── Morning star (downtrend) / Evening star (uptrend) ──
    # bar3 = strong trend candle, bar2 = small-bodied indecision candle
    # not overlapping bar3's body, bar1 = strong reversal closing back
    # into bar3's body.
    star_gap_down = max(o2, c2) < min(o3, c3)
    star_gap_up   = min(o2, c2) > max(o3, c3)
    small_star    = body2 <= range2 * 0.3

    if (not prior_trend_up and c3 < o3 and small_star and star_gap_down
            and c1 > o1 and c1 > (o3 + c3) / 2):
        return "morning_star", True, False

    if (prior_trend_up and c3 > o3 and small_star and star_gap_up
            and c1 < o1 and c1 < (o3 + c3) / 2):
        return "evening_star", False, True

    # ── Three white soldiers: 3 consecutive bullish candles, each ──
    # opening within the prior body and closing near its own high.
    if (c3 > o3 and c2 > o2 and c1 > o1
            and o2 > o3 and o2 < c3 and o1 > o2 and o1 < c2
            and c1 > c2 > c3
            and (h1 - c1) <= body1 * 0.25 and (h2 - c2) <= body2 * 0.25):
        return "three_white_soldiers", True, False

    return None, False, False


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

    # Momentum continuation, not mean-reversion: RSI rising while inside the
    # healthy momentum band. The old "recovered from oversold" definition was
    # a mean-reversion pattern gated behind a trend-following uptrend filter —
    # those two rarely coincide, which is why trade volume stayed near zero.
    if config.RSI_MIN_ENTRY <= result.rsi <= config.RSI_OVERBOUGHT and result.rsi > prev_rsi:
        result.rsi_signal = True
        result.reason.append(f"RSI rising in momentum zone ({result.rsi:.1f})")
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

    # ── Candlestick pattern recognition ────────────────────────
    pattern, bullish, warning = detect_candlestick_pattern(df)
    result.candlestick_pattern = pattern
    result.candlestick_bullish = bullish
    result.candlestick_warning = warning
    if pattern:
        result.reason.append(
            f"Candlestick: {pattern} "
            f"({'bullish confirm' if bullish else 'bearish warning' if warning else 'neutral'})"
        )

    # ── Poor Person's Transformer: attention momentum boost ───
    # After computing the base score, compute attention-weighted
    # momentum context over the last 20 bars of RSI and MACD.
    # If both attention scores are bullish (+slope), add an
    # attention_boost flag and log it. This is an informational
    # enhancement — it doesn't replace the Tier-1 gate.
    rsi_boost  = attention_signal_boost(rsi,       window=20)
    macd_boost = attention_signal_boost(macd_line, window=20)
    result.attention_rsi_boost  = round(rsi_boost,  3)
    result.attention_macd_boost = round(macd_boost, 3)
    result.attention_confirms   = (rsi_boost > 0.1 and macd_boost > 0.1)
    if result.attention_confirms:
        result.reason.append(
            f"Attention context: bullish "
            f"(RSI slope={rsi_boost:+.2f}, MACD slope={macd_boost:+.2f})"
        )
    else:
        result.reason.append(
            f"Attention context: neutral/bearish "
            f"(RSI={rsi_boost:+.2f}, MACD={macd_boost:+.2f})"
        )

    logger.debug(result.summary())
    return result


# ── Poor Person's Transformer (Ernie Chan, May 2025) ─────────
# Zero-parameter self-attention over lookback windows.
# Each indicator's recent history attends to itself:
#   A = softmax(X·Xᵀ / √n)   Z = A·X
# Column sums of A give sample-specific feature importance —
# which past periods the current bar "attends to" most.
# Unlike fixed thresholds, this adapts to the current regime.
# Ref: epchan.blogspot.com/2025/05/a-poor-persons-transformer

def _attention_context(series: np.ndarray) -> np.ndarray:
    """
    Compute attention-weighted context vector for a 1-D indicator series.
    Input:  X  shape (n,) — normalized values over lookback window
    Output: Z  shape (n,) — attention-weighted context
    """
    n = len(series)
    if n < 2:
        return series
    X = series.reshape(-1, 1)                        # (n, 1)
    scores = (X @ X.T) / np.sqrt(n)                  # (n, n)
    scores -= scores.max(axis=1, keepdims=True)       # numerical stability
    A = np.exp(scores)
    A /= A.sum(axis=1, keepdims=True)                 # softmax row-wise
    Z = (A @ X).flatten()                             # (n,)
    return Z


def attention_signal_boost(series: pd.Series, window: int = 20) -> float:
    """
    Returns an attention-derived momentum score in [-1, +1].
    Positive → recent attention-weighted values rising (bullish context).
    Negative → attention-weighted values falling (bearish context).

    Usage: add this as a tiebreaker or soft boost to existing signal scores.
    It does NOT replace RSI/MACD — it makes each signal context-aware.
    """
    if len(series) < window:
        return 0.0
    raw = series.iloc[-window:].values.astype(float)
    if raw.std() < 1e-9:
        return 0.0
    # Normalize to zero-mean unit-variance before attention
    raw = (raw - raw.mean()) / raw.std()
    Z   = _attention_context(raw)
    # Score = correlation between attention output and forward momentum
    # (i.e., do recent high-attention periods align with a rising trend?)
    slope = np.polyfit(np.arange(window), Z, 1)[0]
    # Clamp to [-1, +1]
    return float(np.clip(slope * 10, -1.0, 1.0))


# ── VIX macro filter (tariff / black swan protection) ────────
# Ernie Chan's RL article includes VIX in the state vector because
# regime volatility changes the entire risk profile of any position.
# High VIX = tail-risk environment = do not enter new trades.

def is_volatility_safe(df_vix: pd.DataFrame, spike_pct: float = None) -> bool:
    """
    Returns False (block new entries) when VIXY's latest close is spike_pct
    or more above the mean of its prior VIX_BASELINE_BARS closes — a fear
    spike: tariff announcements, Fed surprises, crashes. See config.py for
    why this is relative: VIXY's absolute price is not a VIX level.

    df_vix must be SPLIT-ADJUSTED daily bars, or a reverse split reads as a
    spike. Fails CLOSED: missing or short data blocks entries, because an
    unknown fear level is not a safe one.
    """
    if not config.USE_VIX_FILTER:
        return True
    n = config.VIX_BASELINE_BARS
    if df_vix is None or len(df_vix) < n + 1:
        logger.warning(
            f"VIX filter: insufficient VIXY data "
            f"({0 if df_vix is None else len(df_vix)} bars, need {n + 1}) — "
            "blocking new entries"
        )
        return False
    threshold = spike_pct if spike_pct is not None else config.VIX_SPIKE_PCT
    close    = df_vix["close"]
    current  = close.iloc[-1]
    baseline = close.iloc[-(n + 1):-1].mean()
    spike    = current / baseline - 1
    safe = bool(spike < threshold)   # plain bool, not numpy.bool_
    if not safe:
        logger.warning(
            f"VIX filter: VIXY={current:.2f} is {spike:+.1%} vs {n}-day mean "
            f"{baseline:.2f} (limit {threshold:+.0%}) — elevated fear, blocking new entries"
        )
    return safe


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
