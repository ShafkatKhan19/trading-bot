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

# ── Market data feed ──────────────────────────────────────────
# Measured on this account 2026-09-27 (free "Basic" data plan):
#   - real-time SIP (all exchanges) is refused: "subscription does not
#     permit querying recent SIP data"
#   - real-time IEX works but is ~2.8% of volume (NVDA 2026-09-25), and the
#     08:00-09:00 pre-market had 2 IEX bars / 325 shares vs 12 SIP bars /
#     1.66M shares. The CRT box built from IEX was not the real pre-market.
#   - SIP delayed 15 minutes is free.
# "sip_delayed": complete consolidated bars, SIP_DELAY_MINUTES behind. Signals
#                act ~16 min late, and intraday_backtest.py models exactly that.
# "iex":         real-time but thin (the pre-2026-09-27 behaviour).
# "sip":         real-time consolidated — requires the paid data plan.
BAR_FEED          = os.getenv("BAR_FEED", "sip_delayed")
SIP_DELAY_MINUTES = 16      # 15-min embargo + 1 min margin

# ── News API ──────────────────────────────────────────────────
NEWS_API_KEY = os.getenv("NEWS_API_KEY")   # unused since news_agent moved off NewsAPI

# News sentiment (news_agent.py)
NEWS_LOOKBACK_HOURS   = 24     # older headlines are ignored
NEWS_CACHE_MINUTES    = 30     # per-symbol result cache (exits poll every cycle)
# "keyword" (default, free) or "claude" (needs ANTHROPIC_API_KEY; falls back
# to keywords on any error). Only reached after every technical gate passes,
# so it is a few calls a day plus open-position rechecks every 30 min.
NEWS_SENTIMENT_ENGINE = os.getenv("NEWS_SENTIMENT_ENGINE", "keyword")
NEWS_LLM_MODEL        = os.getenv("NEWS_LLM_MODEL", "claude-opus-5")

# ── Kill switch ───────────────────────────────────────────────
# Default is the conservative value: if .env is missing or fails to load,
# fail safe to a tight stop rather than a loose one.
KILL_SWITCH_PCT = float(os.getenv("KILL_SWITCH_PCT", 5)) / 100  # 0.05 — resets daily

# Cumulative kill switch: tracks drawdown from the all-time equity peak,
# never resets on a new session. The daily switch alone allows losing
# KILL_SWITCH_PCT every single day with nothing stopping it from repeating —
# on a $500 account that's $25/day, indefinitely. This is a second,
# permanent ceiling that requires manual intervention to clear.
CUMULATIVE_KILL_SWITCH_PCT = float(os.getenv("CUMULATIVE_KILL_SWITCH_PCT", 40)) / 100  # 0.40

# ── Account capital ───────────────────────────────────────────
# The real money this bot is being tested for. Position sizing and the kill
# switch are measured against min(broker equity, ACCOUNT_CAPITAL), NOT raw
# broker equity. Alpaca paper accounts start at $100k, so sizing off equity
# made every paper trade ~$10,000 (SOFI 2026-06-24 lost -$522 — more than the
# whole $500 account) and made the 5% daily kill switch a $5,000 threshold
# that $50 positions could never reach. With the cap, paper trades exactly
# as the real account would. In live mode with a real $500 account, equity is
# already below the cap, so behaviour is unchanged.
# Raised $500 -> $2,000 on 2026-09-27 at the user's request.
ACCOUNT_CAPITAL = float(os.getenv("ACCOUNT_CAPITAL", 2000))

# Alpaca: margin (and therefore short selling) requires $2,000 of equity.
# Below that the account is a cash account — long-only, and sale proceeds
# only become usable after T+1 settlement.
# At exactly $2,000 the account sits ON the threshold — one losing trade
# drops it below — so it is treated as a cash account unless ACCOUNT_TYPE is
# explicitly set to "margin" (and the broker account is actually margin).
MARGIN_MIN_EQUITY = 2_000
ACCOUNT_TYPE      = os.getenv("ACCOUNT_TYPE", "cash")
CASH_ACCOUNT      = ACCOUNT_TYPE != "margin" or ACCOUNT_CAPITAL < MARGIN_MIN_EQUITY

# Model T+1 settlement in paper: in a cash account, each session's total
# entry notional is capped at the settled cash available at the open, and
# proceeds from same-day exits cannot be reused until the next session.
# Alpaca paper does not enforce this, so without the model paper can recycle
# the same dollars all day and overstate how many trades the real account takes.
ENFORCE_T1_SETTLEMENT = CASH_ACCOUNT

# ── Daily runner (daily_runner.py — the bot since 2026-09-27) ─
# "index": buy-and-hold INDEX_SYMBOL with ACCOUNT_CAPITAL (+ optional
#          monthly deposit). The best-evidenced use of the money.
# "h1":    paper-only forward test of the pre-registered RSI(2) rules with
#          H1_PAPER_CAPITAL; skipped automatically in live mode.
DAILY_BOOKS           = ["index", "h1"]
DAILY_RUN_TIME        = "09:35"    # ET, once per session, after the open
INDEX_SYMBOL          = "SPY"
INDEX_MONTHLY_DEPOSIT = float(os.getenv("INDEX_MONTHLY_DEPOSIT", 0))
H1_PAPER_CAPITAL      = ACCOUNT_CAPITAL   # same scale as the index book it is compared to

# ── Watchlist ─────────────────────────────────────────────────
# VRT (17.5% win rate) and AVGO (26.3% win rate) removed earlier — consistent
# losses across all signal score levels. MARA (-$13.52/33 trades, 39.4% win)
# and HOOD (-$7.30/48 trades, 50% win but avg loss > avg win) removed now —
# same pattern, confirmed on the 4yr/235-trade backtest after the RSI fix.
# Expanded 8 -> 20 on 2026-09-25. This is the ONLY lever that raises trade count
# without weakening the test: more independent samples of the same strategy at
# the same quality bar, rather than a lower bar. Measured over 21 real sessions,
# CRT gated setups went 0.52/day (8 symbols) -> 1.48/day (20). Loosening a filter
# instead would change what is being tested — ungated CRT lost 14.29% over 65
# setups, so the gates are what make the strategy viable at all.
# Every addition is a liquid large-cap that trades pre-market, which the
# 08:00-09:00 CRT box requires.
WATCHLIST = {
    # AI core — high volatility, need all 4 signals
    "MSFT": {"theme": "ai_core",    "avg_swing_days": 5},
    "GOOGL":{"theme": "ai_core",    "avg_swing_days": 5},
    "NVDA": {"theme": "ai_core",    "avg_swing_days": 4},
    "AAPL": {"theme": "ai_core",    "avg_swing_days": 5},
    "AMZN": {"theme": "ai_core",    "avg_swing_days": 5},
    "META": {"theme": "ai_core",    "avg_swing_days": 5},
    "AVGO": {"theme": "ai_core",    "avg_swing_days": 4},
    "AMD":  {"theme": "ai_core",    "avg_swing_days": 4},
    "MU":   {"theme": "ai_core",    "avg_swing_days": 4},
    "INTC": {"theme": "ai_core",    "avg_swing_days": 5},
    # High-momentum growth — lower price, fractional-friendly
    "PLTR": {"theme": "growth",     "avg_swing_days": 4},
    "SOFI": {"theme": "growth",     "avg_swing_days": 4},
    "RIVN": {"theme": "growth",     "avg_swing_days": 4},
    "TSLA": {"theme": "growth",     "avg_swing_days": 4},
    "COIN": {"theme": "growth",     "avg_swing_days": 4},
    "SHOP": {"theme": "growth",     "avg_swing_days": 4},
    "NFLX": {"theme": "growth",     "avg_swing_days": 5},
    "UBER": {"theme": "growth",     "avg_swing_days": 5},
    # Transport / logistics
    "UNP":  {"theme": "transport",  "avg_swing_days": 7},
    "FDX":  {"theme": "transport",  "avg_swing_days": 6},
}

TICKERS = list(WATCHLIST.keys())

# ── Market regime proxy ───────────────────────────────────────
REGIME_TICKER    = "QQQ"
REGIME_MA_PERIOD = 50

# Per-stock 50MA filter tolerance — adapts to market strength instead of
# being a flat on/off switch. When QQQ is trading at least
# STRONG_BULL_MARKET_PCT above its own 50MA (a strong market tailwind),
# allow individual stocks that are slightly below their own 50MA, up to
# UPTREND_TOLERANCE_PCT, rather than rejecting every below-MA stock outright.
STRONG_BULL_MARKET_PCT  = 0.03   # QQQ needs to be 3%+ above its 50MA
UPTREND_TOLERANCE_PCT   = 0.02   # stock can be up to 2% below its own 50MA

# ── VIX macro filter (Ernie Chan RL article — state includes VIX) ─────
# High VIX = market fear. Tariffs, crashes, black swans all spike VIX.
#
# The VIX index itself is not available from Alpaca, so VIXY (a VIX-futures
# ETF) is the proxy. The previous rule compared VIXY's *price* to 25 — a VIX
# *index* level. VIXY's price has no fixed relation to VIX: it decays
# continuously and is periodically reverse-split. Split-adjusted, VIXY was
# below 25 on only 4.4% of days 2019-2026, so the old gate's answer depended
# on where the ETF happened to have drifted, not on market fear.
#
# Replacement: a relative spike detector. Block new entries when VIXY's
# latest close is VIX_SPIKE_PCT or more above the mean of its prior
# VIX_BASELINE_BARS closes. Measured on split-adjusted VIXY 2019-01 to
# 2026-09 (1944 days), N=20 / 15% blocks 5.4% of days, and its episodes line
# up with known stress events: Aug-2019, Feb-2020 (COVID), Mar-2023 (SVB),
# 2024-08-02 (yen unwind), 2025-04-03 (tariffs). Chosen to match those events
# and a ~5% block rate — NOT tuned on trade P&L.
VIX_TICKER        = "VIXY"    # ETF that tracks VIX futures (tradeable via Alpaca)
VIX_BASELINE_BARS = 20        # prior daily closes forming the "normal" level
VIX_SPIKE_PCT     = 0.15      # block when latest close >= baseline * 1.15
# Calendar days of daily bars to request — must cover VIX_BASELINE_BARS + 1
# trading days with holiday headroom.
VIX_LOOKBACK_DAYS = 45
USE_VIX_FILTER    = True

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
        "take_profit_pct":   0.08,
        "max_hold_days":     25,
        "min_signal_score":  3,
        "rsi_min_entry":     35,
        "volume_surge_mult": 1.2,
    },
    "growth": {
        "stop_loss_pct":     0.05,   # volatile — wider stop needed
        "take_profit_pct":   0.15,   # high beta = bigger moves
        "max_hold_days":     10,     # shorter hold — momentum fades fast
        "min_signal_score":  3,      # 3 of 4 signals (lower price = noisier)
        "rsi_min_entry":     35,
        "volume_surge_mult": 1.4,
    },
}


def get_segment_rules(symbol: str) -> dict:
    """Return the trading rules for a symbol's market segment."""
    info  = WATCHLIST.get(symbol, {})
    theme = info.get("theme", "ai_core")
    return SEGMENT_RULES.get(theme, SEGMENT_RULES["ai_core"]).copy()


# ── Atomic Habits: Commitment Devices & System Rules ─────────────────
# These are "one-time choices that lock in better future behavior" (Ch.14)

# Never miss twice (Ch.16): after a stop-loss, cool down before re-entering same ticker.
# Prevents doubling down on a broken setup — the losing streak can't compound.
TICKER_COOLDOWN_DAYS   = 5

# Losing streak auto-pause (Ch.16 / "don't break the chain" inverted):
# If a ticker loses N times in a row, pause it. It has a broken pattern right now.
MAX_CONSECUTIVE_LOSSES = 3
# Disabled 2026-09-22. The streak threshold came from constitution.json, which
# was fitted in-sample with no holdout, so the number isn't trustworthy. It was
# benching PLTR — the strongest name on the watchlist — on every cycle for days.
ENABLE_CONSECUTIVE_LOSS_PAUSE = False

# Goldilocks Rule (Ch.19): scale position size to conviction level.
# Score 4 = full size. Score 3 = 75%. Score 2 = 50%.
# "Peak performance when working on tasks at the edge of current ability" —
# high-confidence entries deserve more capital, borderline entries get less.
SCORE_POSITION_MULTIPLIERS = {2: 0.50, 3: 0.75, 4: 1.00}

# Tier-1 signal requirement: RSI recovery AND MACD crossover must BOTH fire.
# These are the "identity signals" of the strategy — momentum confirmed by two
# independent methods. Volume and MA are supporting signals, not core.
# (Ch.2: identity-based habits — the bot IS a momentum trader, not a noise trader)
REQUIRE_TIER1_SIGNALS  = True

# Rolling window for trajectory tracking (Ch.1: trajectory matters more than results).
# The bot tracks last-N win rate separately from all-time to detect drift.
ROLLING_WIN_RATE_WINDOW = 30

# ── Global signal thresholds (fallback; segment rules take priority) ──
RSI_OVERSOLD      = 45   # was 35 — too close to RSI_MIN_ENTRY/uptrend filter to ever coincide
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
# Live-only Kelly sizing (sizing.position_fraction): quarter-Kelly from the
# strategy's out-of-sample validation report, capped at MAX_POSITION_PCT,
# and ZERO when validation.py has not returned PASS. Paper ignores this.
USE_KELLY_SIZING  = True
KELLY_MULTIPLIER  = 0.25
MAX_OPEN_POSITIONS= 5
MIN_SIGNAL_SCORE  = 4     # Raised from 3

# ── Best Loser Wins: Trailing stop (Tom Hougaard) ─────────────
# Replace fixed take_profit with a trailing stop so winners can run.
# Once a position gains TRAIL_ACTIVATION_PCT, the stop trails
# TRAIL_STOP_PCT below the highest price reached.
# "You can't be a big winner if you keep taking small profits." — Ch.6
TRAIL_ACTIVATION_PCT = 0.05   # Start trailing after +5% gain
TRAIL_STOP_PCT       = 0.03   # Trail 3% below high-water mark

# Best Loser Wins: "Assume you are wrong until the market proves you right."
# If after NO_PROGRESS_DAYS the position hasn't gained at least
# NO_PROGRESS_MIN_GAIN, the trade isn't working — cut it and move on.
# Raised from 4 → 7 days: analysis of MSFT trades showed the 4-day timer
# was cutting legitimate swing setups before trends had room to develop.
# The +134% SOFI trade survived because it gapped past the timer early —
# the fix is giving all trades that same runway.
NO_PROGRESS_DAYS     = 7      # was 4 — give swing trades time to develop
NO_PROGRESS_MIN_GAIN = 0.005  # was 0.8% — lower bar, focus is on time not threshold

# Ernie Chan attention gate: require bullish attention context on entry
# when score is borderline (score == min_signal_score exactly).
# Reduces marginal entries that produce flat no_progress exits.
REQUIRE_ATTENTION_ON_BORDERLINE = True

# ── Swing trade timing ────────────────────────────────────────
MIN_HOLD_DAYS     = 3         # was 2 — ensures no_progress can't fire before min hold
MAX_HOLD_DAYS     = 20    # Hard ceiling — was 326d in old constitution (too long)
EARNINGS_BLACKOUT = 2

# Modeled slippage applied on top of Alpaca paper fills for stop-loss exits.
# Alpaca paper fills stops at exactly the stop price with zero gap — real
# fills on a fast move fill worse. This haircut makes paper stats more honest.
STOP_SLIPPAGE_PCT = 0.002     # subtract 0.2% from stop exit fill price

# ── Paper test settings ───────────────────────────────────────
PAPER_TEST_RUNS   = 1000
# Trailing-stop system: win rate alone is not the right gate.
# Viability is measured by expectancy per trade (see constitution_builder.py).
# 40% win rate with 3:1 win/loss size ratio is more profitable than
# 55% win rate with 1:1 size ratio. Keep MIN_WIN_RATE as a soft reference only.
MIN_WIN_RATE      = 0.42

# ── Candle timeframe ──────────────────────────────────────────
SIGNAL_TIMEFRAME  = "15Min"   # was 4Hour — day-trading needs intraday entry signals
TREND_TIMEFRAME   = "1Day"    # still daily — the broader trend filter doesn't need to change

# ── Day trading conversion (live paper_runner.py only — backtest_runner.py
# stays on the swing-trade daily/4H rules above for its own historical sim) ──
#
# The Pattern Day Trader rule no longer exists. FINRA retired it on 2026-06-04
# and Alpaca implemented the replacement Intraday Margin Rule the same day:
# "The definition of a 'pattern day trader' has been eliminated... The specific
# $25,000 equity minimum required to day trade has been removed."
# Verified on this account — pattern_day_trader, daytrade_count and
# daytrading_buying_power all return None; Alpaca no longer tracks them.
# Day trades are now unlimited; a margin account needs $2,000 for 4x intraday
# buying power, and below that a cash account trades on settled funds (T+1).
# Day trading at $500 is therefore viable, which it was not before June.
DAY_TRADING_MODE      = True
MIN_HOLD_MINUTES       = 0        # no forced minimum hold — day trades can close same cycle
MAX_HOLD_MINUTES       = 240      # 4h hard ceiling — well inside a single session
NO_PROGRESS_MINUTES    = 90       # was 45 — give intraday trades more room before cutting
NO_PROGRESS_MIN_GAIN_INTRADAY = 0.003  # was 0.4% — lower bar, pair with longer timer
# The no-progress timer alone cuts flat trades that are still intact. It must
# also confirm the position is breaking down: price below this many bars of
# SIGNAL_TIMEFRAME. 5 x 15Min = 75 minutes, roughly the holding period itself.
NO_PROGRESS_MA_PERIOD  = 5
NO_PROGRESS_MA_DAYS    = 3        # lookback passed to get_bars; needs > MA period of bars
EOD_FLATTEN_TIME       = "15:55"  # ET — force-close everything before the close, zero overnight risk

# ── 8AM Candle / 9AM CRT model (crt_strategy.py) ──────────────
# Per symbol per day: the 08:00–09:00 ET hour candle defines a "narrative box".
# A sweep of one side arms the opposite bias; entry only after a close back
# inside the box (displacement) plus a break of structure on 5Min bars.
#
# Ships DORMANT. paper_runner.py only constructs CRTStrategy when this is True,
# so the existing RSI/MACD swing logic is completely unaffected by default.
ENABLE_CRT_STRATEGY = True

CRT_RANGE_START = "08:00"   # ET, inclusive — first 15Min bar of the range
CRT_RANGE_END   = "09:00"   # ET, exclusive — bars are stamped at bar-open, so
                            # 08:00/08:15/08:30/08:45 are the four range bars

# Degenerate-input guard. The 08:00–09:00 pre-market hour is thin: measured on
# 2026-09-21 real bars, MSFT printed a $0.84 range on 46,609 shares (~1.5% of
# the first 30 minutes of RTH volume), SOFI $0.07, RIVN $0.04. The model places
# its stop just beyond the sweep wick, so a 0.05% box produces a stop narrower
# than the bid/ask spread and guarantees an immediate chop-out regardless of
# whether the directional read was right.
#
# 0.40% is chosen because it is roughly 4-8x a typical liquid large-cap spread
# at this price range, so the CRT_STOP_BUFFER_PCT'd stop still sits outside
# noise, and because it is small enough that a genuinely active pre-market hour
# (news, earnings reaction, gap) still passes. Symbols whose box is narrower
# are skipped for the whole day and the reason is logged via log_rejection.
CRT_MIN_RANGE_PCT = 0.004   # 0.4% of the range midpoint

# Stop sits just beyond the sweep extreme (the wick that grabbed liquidity),
# not exactly on it — resting exactly on the wick gets tagged by a single tick.
CRT_STOP_BUFFER_PCT = 0.001   # 0.1% beyond the sweep high/low

# Minimum reward:risk required at entry, measured as
#   distance(entry -> opposite side of box) / distance(entry -> stop).
# Set to 1.0 on principle — never risk more than the trade can return — NOT by
# maximising a backtest: at every candidate threshold the surviving sample was
# 2-10 trades, far too few to optimise on. Across 33 replayed setups the median
# was 0.28 (equities) / 0.47 (crypto), i.e. most entries confirmed so late that
# the box was already spent while the stop still sat back at the sweep wick.
CRT_MIN_RR = 1.0

# Equities, switched back from crypto on 2026-09-24 for two structural reasons.
#
# 1. FEES. Alpaca takes ~0.246% per side on crypto, in-kind, so ~0.49% round
#    trip — against a median 08:00-09:00 box of 0.41%. Seven of twelve observed
#    crypto boxes could not pay their own fee even on a perfect traverse to
#    target. Equities are commission-free, so the box is kept in full.
# 2. PDT. The rule that previously capped this at 3 day-trades per 5 days was
#    retired on 2026-06-04, so intraday equity trading is no longer blocked.
#
# Backtest, 8 symbols x 20 sessions, fixed-target exit, R:R gate applied:
#   ungated   n=65  -14.29%  45% win   <- the gate is doing the work
#   RR>=1.0   n=10   +1.56%  50% win   (t=0.78, NOT significant - 10 trades)
# Positive but unproven; frequency is ~0.5 gated setups/day across 8 names.
CRT_SYMBOLS = TICKERS   # same 20-name universe as the swing book

# Crypto rejects plain STOP orders ("invalid order type for crypto order"), so a
# protective stop there must be STOP_LIMIT. A limit exactly at the trigger can be
# jumped clean through and never fill, so it is placed this far beyond it: wide
# enough to fill in a fast move, tight enough to bound the loss. ETH fell 2.2% in
# ten minutes on 2026-09-23, so 0.5% is deliberately generous.
CRYPTO_STOP_LIMIT_SLACK_PCT = 0.005

# Alpaca's crypto fee, per side, measured from a real fill on 2026-09-23:
# bought 3.68 ETH, received 3.6708 — 0.246% taken in the asset itself.
# ~0.49% round trip, against a median 8AM box of 0.41%. Equities are free.
CRYPTO_FEE_PCT = 0.00246

# Short (sweep-high) setups need a margin account: Alpaca does not allow
# short selling in a cash account, and a $500 account is a cash account. Paper
# accounts CAN short, so without this gate paper would record trades the real
# account could never place. Follows ACCOUNT_CAPITAL automatically.
CRT_ALLOW_SHORTS = not CASH_ACCOUNT

CRT_MAX_OPEN_POSITIONS = 3   # concurrent CRT positions, independent of the swing book
CRT_TIMEFRAME_RANGE    = "15Min"  # 4 bars build the 08:00–09:00 hour candle
CRT_TIMEFRAME_ENTRY    = "5Min"   # lower-timeframe CRT: displacement + BOS
