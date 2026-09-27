# ============================================================
#  paper_runner.py — 500-run paper trading engine
#  Runs the full strategy across all tickers and market conditions
#  Logs every trade to trades.db for constitution_builder.py
#  Run this: python paper_runner.py
# ============================================================

import logging
import os
import time
import schedule
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
import config
import trade_logger as tl
from alpaca_client import AlpacaClient
from kill_switch import KillSwitch
from strategy import SwingStrategy
from crt_strategy import CRTStrategy
from signals import is_market_bullish, is_volatility_safe

# Ensure logs/ exists before FileHandler tries to open it
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/paper_runner.log", encoding="utf-8")
    ]
)

ET = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)

TRADE_COUNT_TARGET = config.PAPER_TEST_RUNS


def is_market_open() -> bool:
    """Market hours check in US Eastern Time. Alpaca handles holidays."""
    now = datetime.now(ET)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now <= market_close


def collect_exit_followups(client):
    """Record what price did after each exit. Pure telemetry — nothing reads
    this to alter behaviour. Acting on four trades is how the constitution got
    overfitted; the point is to have the evidence when the sample is big enough.
    """
    try:
        pending = tl.pending_followups(min_age_minutes=120)
    except Exception as e:
        logger.error(f"Follow-up query failed: {e}")
        return
    for t in pending:
        try:
            df = client.get_bars(t["symbol"], "5Min", days=3)
            if df is None or len(df) == 0:
                continue
            exit_dt = datetime.fromisoformat(t["exit_date"])
            idx = df.index
            if getattr(idx, "tz", None) is not None:
                exit_cmp = exit_dt if exit_dt.tzinfo else exit_dt.replace(tzinfo=idx.tz)
            else:
                exit_cmp = exit_dt.replace(tzinfo=None)
            after = df[idx > exit_cmp]
            if len(after) == 0:
                continue
            is_short = str(t["side"]).upper() == "SELL"
            best  = float(after["low"].min()) if is_short else float(after["high"].max())
            worst = float(after["high"].max()) if is_short else float(after["low"].min())
            tl.record_followup(t["id"], t["symbol"], t["side"], t["exit_date"],
                               float(t["exit_price"]), t["exit_reason"],
                               best, worst, float(after["close"].iloc[-1]))
        except Exception as e:
            logger.warning(f"Follow-up failed for {t['symbol']} id={t['id']}: {e}")


def run_cycle(client: AlpacaClient, strategy: SwingStrategy, kill_switch: KillSwitch,
              crt=None):
    """One evaluation cycle — check all tickers for entries and exits."""
    try:
        _run_cycle_inner(client, strategy, kill_switch)
    except Exception as e:
        logger.error(f"Cycle failed with unhandled error: {e}", exc_info=True)
    # CRT runs in its own try block and after the swing pass: it keeps a
    # separate position book, so a fault on either side must not stop the other.
    if crt is not None and is_market_open():
        try:
            crt.run_cycle()
        except Exception as e:
            logger.error(f"CRT cycle failed with unhandled error: {e}", exc_info=True)


def _run_cycle_inner(client: AlpacaClient, strategy: SwingStrategy, kill_switch: KillSwitch):
    """Inner cycle body — wrapped by run_cycle for crash recovery."""
    if not is_market_open():
        logger.debug("Market closed — skipping cycle")
        return

    # Kill switch check
    if kill_switch.check():
        logger.warning("Kill switch active — skipping cycle")
        return

    # Log current stats
    summary = tl.get_summary()
    logger.info(
        f"Run cycle | trades={summary['total_trades']} "
        f"win_rate={summary['win_rate']:.1%} "
        f"total_pnl=${summary['total_pnl']:.2f}"
    )

    if summary["total_trades"] >= TRADE_COUNT_TARGET:
        logger.info(f"TARGET REACHED: {TRADE_COUNT_TARGET} paper trades completed!")
        logger.info("Run constitution_builder.py to generate your constitution.")
        return

    # Fetch regime + macro data once per cycle
    # days=120 → ~85 trading bars, enough for 50-period MA with headroom
    df_regime = client.get_bars(config.REGIME_TICKER, timeframe="1Day", days=120)
    df_vix    = client.get_bars(config.VIX_TICKER,    timeframe="1Day",
                                days=config.VIX_LOOKBACK_DAYS, split_adjusted=True)
    market_bullish = is_market_bullish(df_regime)

    # Evaluate exits first (always, even in bearish regime)
    strategy.evaluate_exits()

    if not market_bullish:
        logger.info("Market regime bearish — no new entries this cycle")
        return

    # Check VIX before any entries
    if not is_volatility_safe(df_vix):
        logger.info(f"VIX elevated — skipping all new entries this cycle")
        return

    # Evaluate entries for each ticker
    for symbol in config.TICKERS:
        if symbol in strategy.positions:
            continue

        # days=10 of 15Min bars → ~260 bars, plenty for the 50-period MA;
        # days=120 of daily bars for the broader trend filter (unchanged).
        signal_days = 10 if config.DAY_TRADING_MODE else 60
        df_signal = client.get_bars(symbol, timeframe=config.SIGNAL_TIMEFRAME, days=signal_days)
        df_trend  = client.get_bars(symbol, timeframe=config.TREND_TIMEFRAME,  days=120)

        if df_signal is None or df_trend is None:
            logger.warning(f"{symbol}: no data available")
            continue

        strategy.evaluate_entry(symbol, df_signal, df_trend, df_regime, df_vix)
        time.sleep(0.5)  # Rate limit — be kind to the API

    # Log open positions
    open_pos = strategy.open_positions_summary()
    if open_pos:
        logger.info(f"Open positions ({len(open_pos)}):")
        for p in open_pos:
            logger.info(f"  {p['symbol']}: {p['pnl_pct']:+.2f}% | {p['hold_days']}d | stop=${p['stop_loss']}")


def main():
    logger.info("=" * 60)
    logger.info("  PAPER TRADING ENGINE STARTED")
    logger.info(f"  Target: {TRADE_COUNT_TARGET} trades")
    logger.info(f"  Tickers: {', '.join(config.TICKERS)}")
    logger.info("=" * 60)

    tl.init_db()

    client      = AlpacaClient()
    kill_switch = KillSwitch(client)
    strategy    = SwingStrategy(client, kill_switch)
    # Ships dormant — ENABLE_CRT_STRATEGY defaults to False, so nothing about
    # the existing RSI/MACD path changes until the user opts in.
    # swing_strategy is passed so CRT can see the other book's open symbols and
    # refuse to double up on one ticker.
    crt = CRTStrategy(client, kill_switch, swing_strategy=strategy) if config.ENABLE_CRT_STRATEGY else None
    if crt:
        logger.info(f"  CRT model ENABLED | box {config.CRT_RANGE_START}-{config.CRT_RANGE_END} ET"
                    f" | min range {config.CRT_MIN_RANGE_PCT:.2%}")

    kill_switch.start_session()

    # Day trading needs much tighter cycles than swing's 30-minute check —
    # a 15Min signal timeframe is meaningless if we only look at it twice an hour.
    cycle_minutes = 5 if config.DAY_TRADING_MODE else 30
    schedule.every(cycle_minutes).minutes.do(
        run_cycle, client=client, strategy=strategy, kill_switch=kill_switch, crt=crt
    )

    # Reset kill switch at market open each day
    schedule.every().day.at("09:31").do(kill_switch.start_session)

    # Post-exit telemetry — records what price did AFTER each exit so the
    # question "was that exit right?" can be answered from evidence later.
    # Read-only with respect to trading; it never changes a rule.
    schedule.every(20).minutes.do(collect_exit_followups, client=client)

    # EOD flatten — day trading must never carry positions overnight
    if config.DAY_TRADING_MODE:
        schedule.every().day.at(config.EOD_FLATTEN_TIME).do(strategy.flatten_for_close)
    if crt:
        schedule.every().day.at(config.EOD_FLATTEN_TIME).do(crt.flatten_for_close)

    logger.info(f"Scheduler running — evaluating every {cycle_minutes} minutes"
                + (f" | EOD flatten at {config.EOD_FLATTEN_TIME} ET" if config.DAY_TRADING_MODE else ""))
    logger.info("Press Ctrl+C to stop\n")

    # Run once immediately
    run_cycle(client, strategy, kill_switch, crt=crt)

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
