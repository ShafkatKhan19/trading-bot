# ============================================================
#  main.py — Live trading entry point
#  Only runs after constitution.json is generated and verified
#  Run this: python main.py
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
from constitution_validator import load_constitution, print_constitution_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/live_trading.log")
    ]
)
logger = logging.getLogger(__name__)


def is_market_open() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9, minute=30, second=0)
    market_close = now.replace(hour=16, minute=0, second=0)
    return market_open <= now <= market_close


def run_cycle(client, strategy, kill_switch):
    if not is_market_open():
        return

    if kill_switch.check():
        logger.warning("Kill switch active — session paused")
        return

    summary = tl.get_summary()
    ks_status = kill_switch.status()
    logger.info(
        f"[LIVE] Portfolio: ${ks_status['current_value']:,.2f} | "
        f"Day loss: {ks_status['current_loss_pct']:.2%} | "
        f"All-time trades: {summary['total_trades']} | "
        f"Win rate: {summary['win_rate']:.1%}"
    )

    df_regime     = client.get_bars(config.REGIME_TICKER, timeframe="1Day", days=100)
    market_bullish = is_market_bullish(df_regime)

    strategy.evaluate_exits()

    if not market_bullish:
        logger.info("Regime bearish — no new entries")
        return

    for symbol in config.TICKERS:
        if symbol in strategy.positions:
            continue
        df_signal = client.get_bars(symbol, timeframe=config.SIGNAL_TIMEFRAME, days=30)
        df_trend  = client.get_bars(symbol, timeframe=config.TREND_TIMEFRAME, days=60)
        if df_signal is None or df_trend is None:
            continue
        strategy.evaluate_entry(symbol, df_signal, df_trend, df_regime)
        time.sleep(0.5)


def main():
    # ── Constitution check — REQUIRED before live trading ─────
    if config.TRADING_MODE == "live":
        constitution = load_constitution()
        if not constitution:
            logger.critical(
                "Cannot start live trading without a verified constitution.\n"
                "1. Run paper_runner.py until 500 trades complete\n"
                "2. Run constitution_builder.py to generate constitution.json\n"
                "3. Then restart main.py"
            )
            return
        print_constitution_summary()

    logger.info("=" * 60)
    logger.info(f"  BOT STARTED — MODE: {config.TRADING_MODE.upper()}")
    logger.info(f"  Kill switch: {config.KILL_SWITCH_PCT:.0%} daily loss")
    logger.info(f"  Tickers: {', '.join(config.TICKERS)}")
    logger.info("=" * 60)

    tl.init_db()

    client      = AlpacaClient()
    kill_switch = KillSwitch(client)
    strategy    = SwingStrategy(client, kill_switch)

    kill_switch.start_session()

    # Run every 30 minutes
    schedule.every(30).minutes.do(
        run_cycle, client=client, strategy=strategy, kill_switch=kill_switch
    )
    schedule.every().day.at("09:31").do(kill_switch.start_session)

    logger.info("Bot running — Ctrl+C to stop\n")
    run_cycle(client, strategy, kill_switch)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
