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
    return sqlite3.connect(DB_PATH)


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
            run_id          INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS signal_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT,
            symbol      TEXT,
            rsi         REAL,
            ma_signal   INTEGER,
            macd_signal INTEGER,
            vol_signal  INTEGER,
            score       INTEGER,
            action      TEXT,
            reason      TEXT
        )
    """)

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
                    news_sentiment, market_regime, mode="paper", run_id=0):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades
        (symbol, entry_date, entry_price, qty, side, rsi_at_entry,
         signal_score, news_sentiment, market_regime, mode, run_id)
        VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?)
    """, (symbol, datetime.now().isoformat(), entry_price, qty,
          rsi, signal_score, news_sentiment, market_regime, mode, run_id))
    trade_id = c.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"Trade entry logged: {symbol} @ ${entry_price:.2f} [id={trade_id}]")
    return trade_id


def log_trade_exit(trade_id, exit_price, exit_reason):
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT entry_price, qty, entry_date FROM trades WHERE id=?", (trade_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return

    entry_price, qty, entry_date = row
    pnl     = (exit_price - entry_price) * qty
    pnl_pct = (exit_price - entry_price) / entry_price

    # Calculate hold days
    try:
        entry_dt  = datetime.fromisoformat(entry_date)
        hold_days = (datetime.now() - entry_dt).days
    except Exception:
        hold_days = 0

    c.execute("""
        UPDATE trades SET
            exit_date   = ?,
            exit_price  = ?,
            pnl         = ?,
            pnl_pct     = ?,
            hold_days   = ?,
            exit_reason = ?
        WHERE id = ?
    """, (datetime.now().isoformat(), exit_price,
          round(pnl, 2), round(pnl_pct, 4),
          hold_days, exit_reason, trade_id))
    conn.commit()
    conn.close()
    logger.info(f"Trade exit logged: id={trade_id} @ ${exit_price:.2f} | PnL={pnl_pct:.2%}")


def log_signal(symbol, rsi, ma_signal, macd_signal, vol_signal, score, action, reason):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO signal_log
        (timestamp, symbol, rsi, ma_signal, macd_signal, vol_signal, score, action, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), symbol, rsi,
          int(ma_signal), int(macd_signal), int(vol_signal), score, action, reason))
    conn.commit()
    conn.close()


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
