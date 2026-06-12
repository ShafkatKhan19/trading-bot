# ============================================================
#  paper_runner.py — 500-run paper trading engine
#  Runs the full strategy across all tickers and market conditions
#  Logs every trade to trades.db for constitution_builder.py
#  Run this: python paper_runner.py
# ============================================================

import logging
import time
import schedule
from datetime import datetime
import config
import trade_logger as tl
from alpaca_client import AlpacaClient
from kill_switch import KillSwitch
from strategy import SwingStrategy
from signals import is_market_bullish

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/paper_runner.log")
    ]
)
logger = logging.getLogger(__name__)

TRADE_COUNT_TARGET = config.PAPER_TEST_RUNS


def is_market_open() -> bool:
    """Simple market hours check (ET). Alpaca handles holidays."""
    now = datetime.now()
    # Mon–Fri, 9:30AM–4:00PM ET (approximate, adjust for your timezone)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close


def run_cycle(client: AlpacaClient, strategy: SwingStrategy, kill_switch: KillSwitch):
    """One evaluation cycle — check all tickers for entries and exits."""

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

    # Fetch regime data once per cycle
    df_regime = client.get_bars(config.REGIME_TICKER, timeframe="1Day", days=100)
    market_bullish = is_market_bullish(df_regime)

    # Evaluate exits first
    strategy.evaluate_exits()

    if not market_bullish:
        logger.info("Market regime bearish — no new entries this cycle")
        return

    # Evaluate entries for each ticker
    for symbol in config.TICKERS:
        if symbol in strategy.positions:
            continue

        df_signal = client.get_bars(symbol, timeframe=config.SIGNAL_TIMEFRAME, days=30)
        df_trend  = client.get_bars(symbol, timeframe=config.TREND_TIMEFRAME, days=60)

        if df_signal is None or df_trend is None:
            logger.warning(f"{symbol}: no data available")
            continue

        strategy.evaluate_entry(symbol, df_signal, df_trend, df_regime)
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

    kill_switch.start_session()

    # Run every 30 minutes during market hours
    schedule.every(30).minutes.do(
        run_cycle, client=client, strategy=strategy, kill_switch=kill_switch
    )

    # Reset kill switch at market open each day
    schedule.every().day.at("09:31").do(kill_switch.start_session)

    logger.info("Scheduler running — evaluating every 30 minutes")
    logger.info("Press Ctrl+C to stop\n")

    # Run once immediately
    run_cycle(client, strategy, kill_switch)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
