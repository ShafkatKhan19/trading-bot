# ============================================================
#  config.py — Central configuration for the trading bot
#  Edit your watchlist and risk settings here
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ── Alpaca credentials ────────────────────────────────────────
ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
TRADING_MODE      = os.getenv("TRADING_MODE", "paper")

# ── News API ──────────────────────────────────────────────────
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# ── Kill switch ───────────────────────────────────────────────
KILL_SWITCH_PCT = float(os.getenv("KILL_SWITCH_PCT", 25)) / 100  # 0.25

# ── Watchlist ─────────────────────────────────────────────────
# VRT (17.5% win rate) and AVGO (26.3% win rate) removed — paper data showed
# consistent losses across all signal score levels, not recoverable by tuning.
WATCHLIST = {
    # AI core — high volatility, need all 4 signals
    "AMD":  {"theme": "ai_core",    "avg_swing_days": 4},
    "MSFT": {"theme": "ai_core",    "avg_swing_days": 5},
    "GOOGL":{"theme": "ai_core",    "avg_swing_days": 5},
    "NVDA": {"theme": "ai_core",    "avg_swing_days": 4},
    # Cooling / power
    # SMCI removed: 26% win rate, avg RSI 69 at entry (near overbought — bad setups)
    # GEV removed: 33% win rate, insufficient edge
    "ETN":  {"theme": "cooling",    "avg_swing_days": 6},
    # Data centers
    "EQIX": {"theme": "datacenter", "avg_swing_days": 6},
    # Transport / logistics
    "UNP":  {"theme": "transport",  "avg_swing_days": 7},
    "FDX":  {"theme": "transport",  "avg_swing_days": 6},
}

TICKERS = list(WATCHLIST.keys())

# ── Market regime proxy ───────────────────────────────────────
REGIME_TICKER    = "QQQ"
REGIME_MA_PERIOD = 50

# ── Per-segment trading rules ─────────────────────────────────
# Each market segment is tuned to its volatility and correlation profile.
# constitution_builder.py refines these values from actual trade data.
#
# Design rationale:
#   ai_core/ai_infra — highly correlated to NASDAQ, 3-5% daily swings normal.
#     Wide stops prevent shaking out on normal noise. Require all 4 signals.
#   cooling/power/datacenter — mid-volatility infrastructure plays.
#     3 signals sufficient; moderate stops.
#   transport — lowest beta to tech sector, more mean-reverting.
#     Tighter stops, longer hold window acceptable.
SEGMENT_RULES = {
    "ai_core": {
        "stop_loss_pct":     0.05,   # 5% — absorbs normal intraday noise
        "take_profit_pct":   0.12,   # 12% — 2.4:1 R:R minimum
        "max_hold_days":     15,
        "min_signal_score":  4,      # all 4 signals required — high bar
        "rsi_min_entry":     38,     # momentum must exist before entry
        "volume_surge_mult": 1.5,    # strong institutional participation required
    },
    "ai_infra": {
        "stop_loss_pct":     0.05,
        "take_profit_pct":   0.12,
        "max_hold_days":     15,
        "min_signal_score":  4,
        "rsi_min_entry":     38,
        "volume_surge_mult": 1.5,
    },
    "cooling": {
        "stop_loss_pct":     0.04,
        "take_profit_pct":   0.10,   # 2.5:1 R:R vs 4% stop
        "max_hold_days":     20,
        "min_signal_score":  3,
        "rsi_min_entry":     35,
        "volume_surge_mult": 1.3,
    },
    "power": {
        "stop_loss_pct":     0.04,
        "take_profit_pct":   0.10,
        "max_hold_days":     20,
        "min_signal_score":  3,
        "rsi_min_entry":     35,
        "volume_surge_mult": 1.3,
    },
    "datacenter": {
        "stop_loss_pct":     0.04,
        "take_profit_pct":   0.10,
        "max_hold_days":     20,
        "min_signal_score":  3,
        "rsi_min_entry":     35,
        "volume_surge_mult": 1.3,
    },
    "transport": {
        "stop_loss_pct":     0.03,
        "take_profit_pct":   0.08,   # smaller moves — 2.7:1 R:R vs 3% stop
        "max_hold_days":     25,
        "min_signal_score":  3,
        "rsi_min_entry":     35,
        "volume_surge_mult": 1.2,
    },
}


def get_segment_rules(symbol: str) -> dict:
    """Return the trading rules for a symbol's market segment."""
    info  = WATCHLIST.get(symbol, {})
    theme = info.get("theme", "ai_core")
    return SEGMENT_RULES.get(theme, SEGMENT_RULES["ai_core"]).copy()


# ── Global signal thresholds (fallback; segment rules take priority) ──
RSI_OVERSOLD      = 35
RSI_OVERBOUGHT    = 68
RSI_MIN_ENTRY     = 38    # RSI must exceed this floor before any entry
RSI_PERIOD        = 14
MA_FAST           = 20
MA_SLOW           = 50
MACD_FAST         = 12
MACD_SLOW         = 26
MACD_SIGNAL       = 9
VOLUME_SURGE_MULT = 1.5   # Raised from 1.3 — weaker volume = weaker conviction

# ── Global risk management fallbacks ─────────────────────────
STOP_LOSS_PCT     = 0.05  # Widened from 3% — was stopping out on normal noise
TAKE_PROFIT_PCT   = 0.12
MAX_POSITION_PCT  = 0.10
MAX_OPEN_POSITIONS= 5
MIN_SIGNAL_SCORE  = 4     # Raised from 3

# ── Swing trade timing ────────────────────────────────────────
MIN_HOLD_DAYS     = 2
MAX_HOLD_DAYS     = 20    # Hard ceiling — was 326d in old constitution (too long)
EARNINGS_BLACKOUT = 2

# ── Paper test settings ───────────────────────────────────────
PAPER_TEST_RUNS   = 1000
MIN_WIN_RATE      = 0.55

# ── Candle timeframe ──────────────────────────────────────────
SIGNAL_TIMEFRAME  = "4Hour"
TREND_TIMEFRAME   = "1Day"
