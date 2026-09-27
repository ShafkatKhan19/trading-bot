# ============================================================
#  trade_logger.py — SQLite trade database
#  Logs every trade, signal, and rejection
#  Used by constitution_builder.py to extract winning rules
# ============================================================

import sqlite3
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
DB_PATH = "trades.db"


def get_connection():
    return sqlite3.connect(DB_PATH, timeout=10)


def init_db():
    """Create tables if they don't exist."""
    os.makedirs("logs", exist_ok=True)
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT NOT NULL,
            entry_date      TEXT,
            exit_date       TEXT,
            entry_price     REAL,
            exit_price      REAL,
            qty             REAL,
            side            TEXT,
            pnl             REAL,
            pnl_pct         REAL,
            hold_days       INTEGER,
            exit_reason     TEXT,
            rsi_at_entry    REAL,
            signal_score    INTEGER,
            news_sentiment  TEXT,
            market_regime   TEXT,
            mode            TEXT,
            run_id          INTEGER,
            account         TEXT
        )
    """)

    # Existing databases predate the account column; add it in place.
    if "account" not in [r[1] for r in c.execute("PRAGMA table_info(trades)")]:
        c.execute("ALTER TABLE trades ADD COLUMN account TEXT")

    c.execute("""
        CREATE TABLE IF NOT EXISTS signal_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT,
            symbol      TEXT,
            rsi         REAL,
            rsi_signal  INTEGER,
            ma_signal   INTEGER,
            macd_signal INTEGER,
            vol_signal  INTEGER,
            score       INTEGER,
            action      TEXT,
            reason      TEXT
        )
    """)
    # Migration: older DBs may predate the rsi_signal column.
    c.execute("PRAGMA table_info(signal_log)")
    if "rsi_signal" not in {row[1] for row in c.fetchall()}:
        c.execute("ALTER TABLE signal_log ADD COLUMN rsi_signal INTEGER")

    c.execute("""
        CREATE TABLE IF NOT EXISTS rejections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT,
            symbol      TEXT,
            reason      TEXT,
            signal_score INTEGER,
            news_label  TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS news_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT,
            symbol      TEXT,
            title       TEXT,
            link        TEXT,
            published   TEXT,
            sentiment_score REAL,
            sentiment_label TEXT
        )
    """)

    # Post-exit telemetry. Answers the question a trade log cannot: was the exit
    # right? MSFT on 2026-09-21 was cut flat at -0.29% and closed +1.46% — the
    # trade log records a small loss and says nothing about the $175 left on the
    # table. Recorded for every exit so that when the sample is large enough to
    # act on, the evidence already exists. Nothing reads this to change
    # behaviour; learning from four trades is how the constitution got overfitted.
    c.execute("""
        CREATE TABLE IF NOT EXISTS exit_followup (
            trade_id        INTEGER PRIMARY KEY,
            symbol          TEXT,
            side            TEXT,
            exit_date       TEXT,
            exit_price      REAL,
            exit_reason     TEXT,
            checked_at      TEXT,
            best_after      REAL,   -- best price in OUR direction after exiting
            worst_after     REAL,   -- worst price against us after exiting
            price_at_eod    REAL,
            mfe_pct         REAL,   -- max favourable excursion we gave up
            mae_pct         REAL,   -- max adverse excursion we avoided
            verdict         TEXT    -- premature | justified | inconclusive
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS kill_switch_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT,
            session_start   REAL,
            value_at_trigger REAL,
            loss_pct        REAL
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Trade database initialised")


# ── Trade logging ─────────────────────────────────────────────

def log_trade_entry(symbol, entry_price, qty, rsi, signal_score,
                    news_sentiment, market_regime, mode="paper", run_id=0,
                    side="BUY"):
    """Open a trade row. side is "BUY" (long) or "SELL" (short, sell-to-open);
    log_trade_exit reads it back to sign P&L correctly."""
    conn = get_connection()
    c = conn.cursor()
    # Stamp the broker account so a later key rotation to a different account
    # cannot leave orphaned rows inflating live statistics.
    account = None
    if mode != "backtest":
        try:
            import os
            from alpaca.trading.client import TradingClient
            account = TradingClient(
                os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True
            ).get_account().account_number
        except Exception as e:
            logger.warning(f"Could not resolve broker account for trade log: {e}")

    side = "SELL" if str(side).upper() in ("SELL", "SHORT") else "BUY"
    c.execute("""
        INSERT INTO trades
        (symbol, entry_date, entry_price, qty, side, rsi_at_entry,
         signal_score, news_sentiment, market_regime, mode, run_id, account)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (symbol, datetime.now().isoformat(), entry_price, qty, side,
          rsi, signal_score, news_sentiment, market_regime, mode, run_id, account))
    trade_id = c.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Trade entry logged: {symbol} @ ${entry_price:.2f} [id={trade_id}]")
    return trade_id


def log_trade_exit(trade_id, exit_price, exit_reason):
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT entry_price, qty, entry_date, exit_date, side FROM trades WHERE id=?", (trade_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return

    entry_price, qty, entry_date, existing_exit, side = row

    # Idempotency guard — if already closed, don't overwrite with a retry's timestamp.
    # Prevents crash/retry cycles from corrupting exit dates or creating impossible rows.
    if existing_exit:
        logger.warning(f"log_trade_exit called on already-closed trade id={trade_id} — skipping")
        conn.close()
        return

    # A short is sold to open and bought to close, so its P&L is the mirror
    # of a long's. Without this sign flip every profitable short would be
    # recorded as a loss and corrupt win rate, expectancy and the constitution.
    direction = -1 if str(side).upper() == "SELL" else 1
    pnl     = (exit_price - entry_price) * qty * direction
    pnl_pct = ((exit_price - entry_price) / entry_price) * direction

    # Crypto charges a per-side fee, taken in-kind: a 3.68 ETH buy delivered
    # 3.6708, so the cost never appears as a line item and price*qty silently
    # overstates the result. Measured at 0.246%/side on a real fill. Equities
    # are commission-free, which is why this only matters now.
    symbol = None
    try:
        c.execute("SELECT symbol FROM trades WHERE id=?", (trade_id,))
        symbol = (c.fetchone() or [None])[0]
    except Exception:
        pass
    if symbol and "/" in str(symbol):
        import config as _cfg
        rate = getattr(_cfg, "CRYPTO_FEE_PCT", 0.00246)
        fees = (abs(entry_price * qty) + abs(exit_price * qty)) * rate
        pnl     -= fees
        pnl_pct -= (fees / (entry_price * qty)) if entry_price and qty else 0.0
        logger.info(f"Crypto fees applied to trade {trade_id}: -${fees:.2f} ({rate*2:.2%} round trip)")

    try:
        entry_dt  = datetime.fromisoformat(entry_date)
        hold_days = (datetime.now() - entry_dt).days
    except Exception:
        entry_dt  = datetime.now()
        hold_days = 0

    # Exit timestamp must never precede entry — clock skew or a replay bug
    # produces impossible rows that corrupt aggregate stats.
    exit_dt = datetime.now()
    if exit_dt < entry_dt:
        exit_dt = entry_dt

    c.execute("""
        UPDATE trades SET
            exit_date   = ?,
            exit_price  = ?,
            pnl         = ?,
            pnl_pct     = ?,
            hold_days   = ?,
            exit_reason = ?
        WHERE id = ?
    """, (exit_dt.isoformat(), exit_price,
          round(pnl, 2), round(pnl_pct, 4),
          hold_days, exit_reason, trade_id))
    conn.commit()
    conn.close()
    logger.info(f"Trade exit logged: id={trade_id} @ ${exit_price:.2f} | PnL={pnl_pct:.2%}")


def log_signal(symbol, rsi, rsi_signal, ma_signal, macd_signal, vol_signal, score, action, reason):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO signal_log
        (timestamp, symbol, rsi, rsi_signal, ma_signal, macd_signal, vol_signal, score, action, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), symbol, rsi, int(rsi_signal),
          int(ma_signal), int(macd_signal), int(vol_signal), score, action, reason))
    conn.commit()
    conn.close()


def log_news(symbol, headlines, sentiment_score, sentiment_label):
    """
    Persist scraped headlines so the dashboard can show what the bot saw,
    deduplicated by (symbol, link) so re-fetching the same RSS feed across
    cycles doesn't pile up duplicate rows.
    """
    if not headlines:
        return
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat()
    for h in headlines:
        link = h.get("link", "")
        c.execute("SELECT 1 FROM news_log WHERE symbol=? AND link=?", (symbol, link))
        if c.fetchone():
            continue
        c.execute("""
            INSERT INTO news_log (timestamp, symbol, title, link, published, sentiment_score, sentiment_label)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (now, symbol, h.get("title", ""), link, h.get("published", ""),
              sentiment_score, sentiment_label))
    conn.commit()
    conn.close()


def get_recent_news(limit: int = 50) -> list:
    """Return the most recently scraped headlines across all tickers, for the dashboard news feed."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT timestamp, symbol, title, link, published, sentiment_score, sentiment_label
        FROM news_log ORDER BY timestamp DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    cols = ["timestamp", "symbol", "title", "link", "published", "sentiment_score", "sentiment_label"]
    return [dict(zip(cols, row)) for row in rows]


def log_rejection(symbol, reason, signal_score=0, news_label="unknown"):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO rejections (timestamp, symbol, reason, signal_score, news_label)
        VALUES (?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), symbol, reason, signal_score, news_label))
    conn.commit()
    conn.close()
    logger.info(f"Trade rejected: {symbol} — {reason}")


def count_day_trades(days: int = 5) -> int:
    """
    Count round-trips opened and closed on the same calendar date within
    the trailing N calendar days — the FINRA Pattern Day Trader definition.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT entry_date, exit_date FROM trades
        WHERE exit_date IS NOT NULL
          AND exit_date >= datetime('now', ?)
    """, (f'-{days} days',))
    rows = c.fetchall()
    conn.close()
    count = 0
    for entry_date, exit_date in rows:
        try:
            if datetime.fromisoformat(entry_date).date() == datetime.fromisoformat(exit_date).date():
                count += 1
        except Exception:
            continue
    return count


def entry_notional_on(day: str) -> float:
    """
    Total dollars deployed into new positions (paper/live, not backtest) on
    calendar date `day` (YYYY-MM-DD, host-local like entry_date). Counts
    positions already closed too: in a cash account their sale proceeds are
    unsettled until T+1, so the dollars stay spent for the rest of the day.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COALESCE(SUM(entry_price * qty), 0) FROM trades
        WHERE mode != 'backtest'
          AND substr(entry_date, 1, 10) = ?
    """, (day,))
    total = c.fetchone()[0]
    conn.close()
    return float(total or 0.0)


def log_kill_switch(session_start, value_at_trigger, loss_pct):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO kill_switch_events
        (timestamp, session_start, value_at_trigger, loss_pct)
        VALUES (?, ?, ?, ?)
    """, (datetime.now().isoformat(), session_start, value_at_trigger, round(loss_pct, 4)))
    conn.commit()
    conn.close()


# ── Query helpers ─────────────────────────────────────────────

# ── Atomic Habits analytics ───────────────────────────────────
# "Reflection and review allows you to remain conscious of your performance." (Ch.20)
# "Trajectory matters more than current results." (Ch.1)

def get_last_exit(symbol: str):
    """
    Return (exit_reason, exit_date) of the most recent closed trade for this ticker.
    Used by strategy.py to enforce post-loss cooldowns (Never Miss Twice, Ch.16).
    """
    conn = get_connection()
    c    = conn.cursor()
    c.execute("""
        SELECT exit_reason, exit_date FROM trades
        WHERE symbol=? AND exit_date IS NOT NULL
        ORDER BY exit_date DESC LIMIT 1
    """, (symbol,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    reason, exit_date_str = row
    try:
        from datetime import date
        exit_date = date.fromisoformat(exit_date_str[:10])
    except Exception:
        return None
    return reason or "", exit_date


def get_consecutive_losses(symbol: str) -> int:
    """
    Count how many consecutive losses this ticker has at the tail of its history.
    Resets to 0 on any win. Used to auto-pause broken tickers (Ch.16).
    """
    conn = get_connection()
    c    = conn.cursor()
    c.execute("""
        SELECT pnl FROM trades
        WHERE symbol=? AND exit_date IS NOT NULL
        ORDER BY exit_date DESC LIMIT 10
    """, (symbol,))
    rows = c.fetchall()
    conn.close()
    streak = 0
    for (pnl,) in rows:
        if (pnl or 0) < 0:
            streak += 1
        else:
            break
    return streak


def get_rolling_win_rate(n: int = 30) -> float:
    """
    Win rate over the last N closed trades across all tickers.
    Trajectory check: if rolling rate < all-time rate, the bot is drifting. (Ch.1)
    """
    conn = get_connection()
    c    = conn.cursor()
    c.execute("""
        SELECT pnl FROM trades
        WHERE exit_date IS NOT NULL
        ORDER BY exit_date DESC LIMIT ?
    """, (n,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        return 0.0
    wins = sum(1 for (pnl,) in rows if (pnl or 0) > 0)
    return round(wins / len(rows), 4)


def get_ticker_streak_summary() -> dict:
    """
    Return {symbol: consecutive_losses} for all tickers with recent trades.
    Used by the constitution_builder and daily logging.
    """
    conn = get_connection()
    c    = conn.cursor()
    c.execute("SELECT DISTINCT symbol FROM trades WHERE exit_date IS NOT NULL")
    symbols = [r[0] for r in c.fetchall()]
    conn.close()
    return {sym: get_consecutive_losses(sym) for sym in symbols}


def get_all_trades():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM trades WHERE exit_date IS NOT NULL")
    rows = c.fetchall()
    conn.close()
    return rows


def get_win_rate() -> float:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL")
    wins = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE exit_date IS NOT NULL")
    total = c.fetchone()[0]
    conn.close()
    if total == 0:
        return 0.0
    return wins / total


def get_summary() -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(pnl), AVG(pnl_pct) FROM trades WHERE exit_date IS NOT NULL")
    total, total_pnl, avg_pnl = c.fetchone()
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL")
    wins = c.fetchone()[0]
    conn.close()
    total = total or 0
    return {
        "total_trades": total,
        "wins":         wins,
        "losses":       total - wins,
        "win_rate":     round(wins / total, 4) if total > 0 else 0,
        "total_pnl":    round(total_pnl or 0, 2),
        "avg_pnl_pct":  round((avg_pnl or 0) * 100, 2),
    }


# ── Post-exit telemetry ───────────────────────────────────────

def pending_followups(min_age_minutes: int = 120) -> list:
    """Closed trades that have no follow-up row yet and are old enough to judge."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(minutes=min_age_minutes)).isoformat()
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT t.id, t.symbol, t.side, t.exit_date, t.exit_price, t.exit_reason
        FROM trades t
        LEFT JOIN exit_followup f ON f.trade_id = t.id
        WHERE t.exit_date IS NOT NULL
          AND t.mode IN ('paper','live')
          AND t.exit_date <= ?
          AND f.trade_id IS NULL
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_followup(trade_id, symbol, side, exit_date, exit_price, exit_reason,
                    best_after, worst_after, price_at_eod):
    """Store what price did after we left. verdict is descriptive, not a trigger."""
    is_short = str(side).upper() == "SELL"
    # "Favourable" after exiting means the direction the trade was betting on.
    mfe = ((exit_price - best_after) / exit_price) if is_short else ((best_after - exit_price) / exit_price)
    mae = ((worst_after - exit_price) / exit_price) if is_short else ((exit_price - worst_after) / exit_price)

    if mfe >= 0.005 and mfe > abs(mae) * 2:
        verdict = "premature"      # left real money on the table
    elif mae >= 0.005:
        verdict = "justified"      # exiting avoided a worse move
    else:
        verdict = "inconclusive"

    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO exit_followup
        (trade_id,symbol,side,exit_date,exit_price,exit_reason,checked_at,
         best_after,worst_after,price_at_eod,mfe_pct,mae_pct,verdict)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (trade_id, symbol, side, exit_date, exit_price, exit_reason,
          datetime.now().isoformat(), best_after, worst_after, price_at_eod,
          round(mfe, 5), round(mae, 5), verdict))
    conn.commit()
    conn.close()
    logger.info(f"Exit follow-up {symbol} id={trade_id}: {verdict} "
                f"(gave up {mfe:+.2%}, avoided {mae:+.2%})")
    return verdict


def followup_summary() -> dict:
    conn = get_connection()
    rows = conn.execute("SELECT verdict, COUNT(*) FROM exit_followup GROUP BY verdict").fetchall()
    conn.close()
    return {v: n for v, n in rows}
