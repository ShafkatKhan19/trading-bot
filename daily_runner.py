# ============================================================
#  daily_runner.py — Once-a-day bot (replaces paper_runner.py, 2026-09-27)
#
#  Why: the intraday books (15-min swing, CRT) failed their out-of-sample
#  test, and three pre-registered low-frequency rules failed to beat simply
#  holding SPY (RESULTS_2026-09-27_daily.md). So the bot now runs:
#
#   "index" — buy SPY with the book's cash and hold; optional monthly deposit
#             is invested on the month's first session. Never sells. This is
#             the best-evidenced use of the $500 and what should go live.
#   "h1"    — PAPER-ONLY forward test of the pre-registered RSI(2) pullback
#             rules (daily_research.h1_decide — the exact code that was
#             backtested). Every session from 2026-09-28 is data those rules
#             have never seen. "index" is its benchmark in the same account.
#
#  Each book has its own virtual cash and share ledger in data/books/*.json
#  and only ever sells shares it bought, so both can hold SPY in one account.
#
#  Timing: once per session at DAILY_RUN_TIME ET (after the open). Signals
#  use COMPLETED daily bars (yesterday's close), so the free delayed SIP feed
#  is enough — no real-time data needed.
# ============================================================

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import config
import daily_research as research
import trade_logger as tl
from alpaca_client import AlpacaClient

ET = ZoneInfo("America/New_York")


def floor_qty(qty: float) -> float:
    """Round DOWN to 0.0001 share. Alpaca fractional orders accept finer steps than
    the 0.01 used elsewhere; at SPY ~$770, 0.01 share would strand up to $7.70."""
    return int(qty * 10_000) / 10_000
BOOK_DIR = os.path.join("data", "books")
EQUITY_LOG = os.path.join(BOOK_DIR, "equity_log.csv")

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("logs/daily_runner.log", encoding="utf-8"),
              logging.StreamHandler()],
)
logger = logging.getLogger("daily_runner")


# ── book ledger ───────────────────────────────────────────────
def load_book(name: str, capital: float) -> dict:
    path = os.path.join(BOOK_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"name": name, "cash": capital, "deposited": capital,
            "created": date.today().isoformat(), "last_run": None, "positions": {}}


def save_book(book: dict):
    os.makedirs(BOOK_DIR, exist_ok=True)
    tmp = os.path.join(BOOK_DIR, f"{book['name']}.json.tmp")
    with open(tmp, "w") as f:
        json.dump(book, f, indent=2)
    os.replace(tmp, os.path.join(BOOK_DIR, f"{book['name']}.json"))


def book_equity(book: dict, prices: dict) -> float:
    return book["cash"] + sum(p["qty"] * prices[s] for s, p in book["positions"].items())


# ── data ──────────────────────────────────────────────────────
def completed_daily_closes(client: AlpacaClient, symbols: list) -> pd.DataFrame:
    """Split+dividend-adjusted daily closes (as in the backtest), completed days only."""
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    now = datetime.now(timezone.utc)
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day,
                           start=now - timedelta(days=450),
                           end=now - timedelta(minutes=config.SIP_DELAY_MINUTES),
                           feed=DataFeed.SIP, adjustment=Adjustment.ALL)
    df = client.data.get_stock_bars(req).df.reset_index()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(ET).dt.date
    closes = df.pivot(index="date", columns="symbol", values="close").sort_index()
    closes = closes[closes.index < datetime.now(ET).date()]      # drop today's partial bar
    closes.index = pd.DatetimeIndex(closes.index)
    return closes[symbols]


# ── orders ────────────────────────────────────────────────────
def buy(client, book, sym, dollars, reason) -> bool:
    price = client.get_latest_price(sym)
    if not price:
        return False
    qty = floor_qty(min(dollars, book["cash"]) / price)
    if qty * price < 1.0:                       # Alpaca minimum order value
        return False
    order = client.submit_market_buy(sym, qty)
    if not order:
        logger.error(f"[{book['name']}] BUY {sym} x{qty} failed")
        return False
    fill, fqty = float(order.filled_avg_price or price), float(order.filled_qty or qty)
    trade_id = tl.log_trade_entry(symbol=sym, entry_price=fill, qty=fqty, rsi=None,
                                  signal_score=0, news_sentiment="n/a",
                                  market_regime=f"daily_{book['name']}", mode=config.TRADING_MODE)
    book["cash"] -= fill * fqty
    pos = book["positions"].get(sym)
    if pos:      # index book adds to one lot
        tot = pos["qty"] + fqty
        pos["entry_price"] = (pos["entry_price"] * pos["qty"] + fill * fqty) / tot
        pos["qty"] = tot
    else:
        book["positions"][sym] = {"qty": fqty, "entry_price": fill,
                                  "entry_date": date.today().isoformat(), "trade_id": trade_id}
    # Persist immediately: a crash between this fill and the end-of-run save
    # would otherwise leave the broker holding shares the ledger doesn't know
    # about, and the retry one minute later would buy them again.
    save_book(book)
    logger.info(f"[{book['name']}] BUY {sym} x{fqty} @ ${fill:.2f} (${fill * fqty:.2f}) — {reason}")
    return True


def sell(client, book, sym, reason) -> bool:
    pos = book["positions"][sym]
    order = client.submit_market_sell(sym, pos["qty"])
    if not order:
        logger.error(f"[{book['name']}] SELL {sym} x{pos['qty']} failed — kept in ledger, retry next run")
        return False
    fill = float(order.filled_avg_price or client.get_latest_price(sym))
    tl.log_trade_exit(pos["trade_id"], fill, reason)
    book["cash"] += fill * pos["qty"]
    logger.info(f"[{book['name']}] SELL {sym} x{pos['qty']} @ ${fill:.2f} "
                f"({fill / pos['entry_price'] - 1:+.2%}) — {reason}")
    del book["positions"][sym]
    save_book(book)          # same reason as in buy(): never re-sell after a crash
    return True


# ── the two books ─────────────────────────────────────────────
def run_index(client, closes, today: date):
    book = load_book("index", config.ACCOUNT_CAPITAL)
    first_session_of_month = (book["last_run"] is not None
                              and date.fromisoformat(book["last_run"]).month != today.month)
    if first_session_of_month and config.INDEX_MONTHLY_DEPOSIT > 0:
        book["cash"] += config.INDEX_MONTHLY_DEPOSIT
        book["deposited"] += config.INDEX_MONTHLY_DEPOSIT
        logger.info(f"[index] monthly deposit ${config.INDEX_MONTHLY_DEPOSIT:.2f}")
    if book["cash"] >= 1.0:
        buy(client, book, config.INDEX_SYMBOL, book["cash"], "invest available cash")
    book["last_run"] = today.isoformat()
    save_book(book)
    return book


def run_h1(client, closes, today: date):
    if config.TRADING_MODE == "live":
        logger.info("[h1] paper-only forward test — skipped in live mode")
        return None
    book = load_book("h1", config.H1_PAPER_CAPITAL)
    sma200, sma5, rsi2 = research.h1_indicators(closes)
    held_days = {s: int((closes.index >= pd.Timestamp(p["entry_date"])).sum())
                 for s, p in book["positions"].items()}
    last = closes.index[-1]
    sells, buys = research.h1_decide(closes.loc[last], sma200.loc[last], sma5.loc[last],
                                     rsi2.loc[last], held_days)
    # On a same-day retry, a position bought this morning shows 0 days held and
    # would be judged against the close that triggered its entry. In the
    # backtest a new position is first judged at its own entry-day close.
    sells = [s for s in sells if book["positions"][s]["entry_date"] != today.isoformat()]
    logger.info(f"[h1] decision close {last.date()}: sell {sells or '-'} | buy {buys or '-'} | "
                f"held {held_days or '-'}")
    # Size buys from book equity at the decision close BEFORE any fill, as the
    # backtest does (prev_eq = value at close i-1, then sells, then buys).
    equity = book_equity(book, closes.loc[last].to_dict())
    for s in sells:
        why = ("close > SMA(5)" if closes.loc[last, s] > sma5.loc[last, s]
               else f"{research.H1_MAX_HOLD_DAYS}-day max hold")
        sell(client, book, s, f"h1 exit: {why}")
    for s in buys:
        buy(client, book, s, research.H1_POSITION_PCT * equity,
            f"h1 entry: RSI(2)={rsi2.loc[last, s]:.1f} < 10, above SMA(200)")
    book["last_run"] = today.isoformat()
    save_book(book)
    return book


def log_equity(client, books: list):
    row = {"date": date.today().isoformat()}
    for b in books:
        if b is None:
            continue
        prices = {s: client.get_latest_price(s) or p["entry_price"] for s, p in b["positions"].items()}
        eq = book_equity(b, prices)
        row[f"{b['name']}_equity"] = round(eq, 2)
        row[f"{b['name']}_return"] = round(eq / b["deposited"] - 1, 4)
    new = not os.path.exists(EQUITY_LOG)
    pd.DataFrame([row]).to_csv(EQUITY_LOG, mode="a", header=new, index=False)
    logger.info("Equity: " + " | ".join(f"{k}={v}" for k, v in row.items() if k != "date"))


def run_session(client):
    today = datetime.now(ET).date()
    symbols = sorted(set(research.UNIVERSE) | {config.INDEX_SYMBOL})
    closes = completed_daily_closes(client, symbols)
    if closes.empty or len(closes) < 205:
        logger.error(f"Only {len(closes)} daily bars — need 205; skipping today")
        return
    books = [run_index(client, closes, today) if "index" in config.DAILY_BOOKS else None,
             run_h1(client, closes, today) if "h1" in config.DAILY_BOOKS else None]
    log_equity(client, books)


def already_ran(today: date) -> bool:
    names = [n for n in config.DAILY_BOOKS]
    books = [load_book(n, 0) for n in names]
    return all(b["last_run"] == today.isoformat() for b in books)


def main():
    logger.info("=" * 60)
    logger.info(f"  DAILY RUNNER STARTED | mode={config.TRADING_MODE} | books={config.DAILY_BOOKS} "
                f"| run at {config.DAILY_RUN_TIME} ET")
    logger.info("=" * 60)
    tl.init_db()
    client = AlpacaClient()
    run_at = datetime.strptime(config.DAILY_RUN_TIME, "%H:%M").time()
    while True:
        try:
            now = datetime.now(ET)
            if (now.time() >= run_at and now.time() < datetime.strptime("15:30", "%H:%M").time()
                    and not already_ran(now.date()) and client.trading.get_clock().is_open):
                logger.info(f"Running session {now.date()}")
                run_session(client)
        except Exception as e:
            logger.error(f"Session failed: {e}", exc_info=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
