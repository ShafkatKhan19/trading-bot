# ============================================================
#  web_dashboard.py — Flask browser dashboard for trading bot
#  Serves on http://localhost:5000
#  Auto-refreshes every 10 seconds via fetch() + DOM update
# ============================================================

import os
import re
import hmac
import sqlite3
import logging
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, jsonify, request, Response
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "daily_runner.log")
BOOK_DIR = os.path.join(os.path.dirname(__file__), "data", "books")

# ── Security ──────────────────────────────────────────────────
# Set DASHBOARD_PASSWORD in .env before exposing this dashboard publicly
# (e.g. via start_with_tunnel.py / ngrok). Without it, the dashboard is
# unauthenticated — fine for localhost-only use, NOT fine over a public
# tunnel. A warning is logged on every request when it's unset.
DASHBOARD_USER     = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")

_SYMBOL_RE = re.compile(r"^[A-Z]{1,6}$")


def _auth_ok(auth) -> bool:
    if not auth:
        return False
    user_ok = hmac.compare_digest(auth.username or "", DASHBOARD_USER)
    pass_ok = hmac.compare_digest(auth.password or "", DASHBOARD_PASSWORD)
    return user_ok and pass_ok


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not DASHBOARD_PASSWORD:
            logger.warning(
                "DASHBOARD_PASSWORD is not set — dashboard is unauthenticated. "
                "Set it in .env before exposing this over a public tunnel."
            )
            return view(*args, **kwargs)
        if not _auth_ok(request.authorization):
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="iTrade Dashboard"'},
            )
        return view(*args, **kwargs)
    return wrapped


@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'"
    )
    return resp


# ── DB helpers ────────────────────────────────────────────────

def db_ok() -> bool:
    return os.path.isfile(DB_PATH)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# A backtest row is a simulation that never reached a broker; a paper/live row is
# a real order with a real fill. Blending them makes 379 simulated trades drown
# out the 1 that actually happened, so every stat below is scoped explicitly.
LIVE_MODES = ("paper", "live")


def _active_account() -> str | None:
    """Broker account the bot currently trades. Rows tagged to a retired
    account (e.g. after a key rotation) must not count toward live stats,
    or the dashboard can never reconcile against Alpaca."""
    try:
        from alpaca.trading.client import TradingClient
        return TradingClient(
            os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True
        ).get_account().account_number
    except Exception:
        return None


ACTIVE_ACCOUNT = _active_account()


def _mode_clause(scope: str) -> str:
    if scope != "live":
        return "mode = 'backtest'"
    base = "mode IN ('paper','live')"
    if ACTIVE_ACCOUNT:
        # account IS NULL kept so rows predating the column still surface.
        return f"{base} AND (account = '{ACTIVE_ACCOUNT}' OR account IS NULL)"
    return base


def fetch_summary(scope: str = "live") -> dict:
    m = _mode_clause(scope)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"SELECT COUNT(*), SUM(pnl), AVG(pnl_pct) FROM trades WHERE exit_date IS NOT NULL AND {m}")
    row = c.fetchone()
    total, total_pnl, avg_pnl_pct = row[0] or 0, row[1] or 0.0, row[2] or 0.0
    c.execute(f"SELECT COUNT(*) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL AND {m}")
    wins = c.fetchone()[0] or 0
    # Expectancy = (win_rate × avg_win) − (loss_rate × avg_loss)
    c.execute(f"SELECT AVG(pnl_pct) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL AND {m}")
    avg_win = (c.fetchone()[0] or 0.0) * 100
    c.execute(f"SELECT AVG(ABS(pnl_pct)) FROM trades WHERE pnl <= 0 AND exit_date IS NOT NULL AND {m}")
    avg_loss = (c.fetchone()[0] or 0.0) * 100
    conn.close()
    win_rate = wins / total if total > 0 else 0.0
    expectancy = round((win_rate * avg_win) - ((1 - win_rate) * avg_loss), 3)
    return {
        "scope":        scope,
        "total_trades": total,
        "wins":         wins,
        "win_rate":     round(win_rate * 100, 1),
        "total_pnl":    round(total_pnl, 2),
        "avg_pnl_pct":  round(avg_pnl_pct * 100, 2),
        "avg_win_pct":  round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "expectancy":   expectancy,
    }


def fetch_open_positions() -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT symbol, entry_date, entry_price, qty, signal_score, news_sentiment
        FROM trades
        WHERE exit_date IS NULL AND {_mode_clause('live')}
        ORDER BY entry_date DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def fetch_recent_trades(scope: str = "live", limit: int = 10) -> list:
    m = _mode_clause(scope)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT symbol, entry_price, exit_price, pnl, pnl_pct, hold_days, exit_reason,
               mode, exit_date
        FROM trades
        WHERE exit_date IS NOT NULL AND {m}
        ORDER BY exit_date DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def fetch_per_ticker(scope: str = "live") -> list:
    m = _mode_clause(scope)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT
            symbol,
            COUNT(*) AS trade_count,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(SUM(pnl), 2) AS total_pnl
        FROM trades
        WHERE exit_date IS NOT NULL AND {m}
        GROUP BY symbol
        ORDER BY SUM(pnl) DESC
    """)
    results = []
    for r in c.fetchall():
        d = dict(r)
        d["win_pct"] = round(d["wins"] / d["trade_count"] * 100, 1) if d["trade_count"] > 0 else 0.0
        results.append(d)
    conn.close()
    return results


_EXIT_REASON_MAP = {
    "take_profit": "Take Profit",
    "take profit": "Take Profit",
    "takeprofit": "Take Profit",
    "stop_loss": "Stop Loss",
    "stop loss": "Stop Loss",
    "stoploss": "Stop Loss",
    "time_exit": "Time Exit",
    "time exit": "Time Exit",
    "timeexit": "Time Exit",
    "trailing_stop": "Trailing Stop",
    "trailing stop": "Trailing Stop",
    "no_progress":   "No Progress (cut)",
    "no progress":   "No Progress (cut)",
    "news_reversal": "News Reversal",
    "news reversal": "News Reversal",
    "newsreversal": "News Reversal",
}

_EXIT_REASON_LABELS = [
    "Take Profit", "Stop Loss", "Time Exit",
    "Trailing Stop", "No Progress (cut)", "News Reversal",
]


def fetch_exit_reasons(scope: str = "live") -> dict:
    m = _mode_clause(scope)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT exit_reason, COUNT(*) AS cnt
        FROM trades
        WHERE exit_date IS NOT NULL AND {m}
        GROUP BY exit_reason
    """)
    counts = {label: 0 for label in _EXIT_REASON_LABELS}
    for r in c.fetchall():
        raw = (r["exit_reason"] or "").strip().lower()
        label = _EXIT_REASON_MAP.get(raw)
        if label and label in counts:
            counts[label] += r["cnt"]
        else:
            # best-effort partial match
            for key, mapped in _EXIT_REASON_MAP.items():
                if key in raw and mapped in counts:
                    counts[mapped] += r["cnt"]
                    break
    conn.close()
    return counts


def fetch_log_tail(n: int = 15) -> list:
    if not os.path.isfile(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except OSError:
        return []


def fetch_equity_curve(scope: str = "live") -> list:
    """Cumulative realized PnL over time, one point per closed trade."""
    m = _mode_clause(scope)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT exit_date, pnl FROM trades
        WHERE exit_date IS NOT NULL AND {m}
        ORDER BY exit_date ASC
    """)
    rows = c.fetchall()
    conn.close()
    curve = []
    running = 0.0
    for r in rows:
        running += (r["pnl"] or 0.0)
        curve.append({"date": r["exit_date"], "cum_pnl": round(running, 2)})
    return curve


def fetch_profit_factor(scope: str = "live") -> float:
    m = _mode_clause(scope)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"SELECT SUM(pnl) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL AND {m}")
    gross_win = c.fetchone()[0] or 0.0
    c.execute(f"SELECT SUM(ABS(pnl)) FROM trades WHERE pnl <= 0 AND exit_date IS NOT NULL AND {m}")
    gross_loss = c.fetchone()[0] or 0.0
    conn.close()
    if gross_loss == 0:
        return round(gross_win, 2) if gross_win > 0 else 0.0
    return round(gross_win / gross_loss, 2)


def fetch_cycle_feed(limit: int = 20) -> list:
    """
    Build the live 'this cycle' feed from the most recent batch of
    signal_log evaluations, enriched with the matching rejection reason
    (if any) and whether the symbol is currently an open position.
    All real data — no synthetic scores or fabricated reasons.
    """
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT MAX(timestamp) FROM signal_log")
    latest_ts = c.fetchone()[0]
    if not latest_ts:
        conn.close()
        return []

    # "This cycle" = signal_log rows within 5 minutes of the latest timestamp
    # (a single run_cycle() evaluates every ticker in quick succession).
    #
    # The bound is computed in Python, not with SQLite's datetime(): stored
    # timestamps are datetime.now().isoformat() ("...T17:30:00.123456") while
    # datetime() returns a space-separated string ("... 17:25:00"). Comparing
    # those as TEXT put 'T' (0x54) against ' ' (0x20), so every row on the
    # same date passed the filter and the 5-minute window did nothing.
    try:
        cutoff = (datetime.fromisoformat(latest_ts) - timedelta(minutes=5)).isoformat()
    except ValueError:
        cutoff = latest_ts
    c.execute("""
        SELECT timestamp, symbol, rsi, rsi_signal, ma_signal, macd_signal, vol_signal, score, reason
        FROM signal_log
        WHERE timestamp >= ?
        ORDER BY timestamp DESC
        LIMIT ?
    """, (cutoff, limit))
    sig_rows = [dict(r) for r in c.fetchall()]

    c.execute("SELECT symbol FROM trades WHERE exit_date IS NULL")
    open_symbols = {r["symbol"] for r in c.fetchall()}

    feed = []
    for s in sig_rows:
        sym = s["symbol"]
        c.execute("""
            SELECT reason FROM rejections
            WHERE symbol = ? AND timestamp >= ?
            ORDER BY timestamp ASC LIMIT 1
        """, (sym, s["timestamp"]))
        rej = c.fetchone()
        if sym in open_symbols:
            status = "ACCEPTED"
            reason = "Position opened"
        elif rej:
            status = "REJECTED"
            reason = rej["reason"]
        else:
            status = "HELD"
            reason = s["reason"]
        feed.append({
            "timestamp":    s["timestamp"],
            "symbol":       sym,
            "rsi":          round(s["rsi"], 1) if s["rsi"] is not None else None,
            "rsi_signal":   bool(s["rsi_signal"]),
            "ma_signal":    bool(s["ma_signal"]),
            "macd_signal":  bool(s["macd_signal"]),
            "vol_signal":   bool(s["vol_signal"]),
            "score":        s["score"],
            "status":       status,
            "reason":       reason,
        })
    conn.close()
    return feed


def fetch_position_cushions() -> list:
    """
    For each open position, compute trailing-stop cushion progress using
    the real entry price and the segment's configured trail thresholds.
    No live quote available here, so cushion is expressed relative to
    entry — the dashboard shows the configured stop/trail bands, not a
    simulated live price.
    """
    import config as cfg
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT symbol, entry_date, entry_price, qty, signal_score, news_sentiment
        FROM trades WHERE exit_date IS NULL ORDER BY entry_date DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    out = []
    for r in rows:
        rules = cfg.get_segment_rules(r["symbol"])
        r["stop_loss_pct"]   = rules["stop_loss_pct"]
        r["take_profit_pct"] = rules["take_profit_pct"]
        r["trail_activation_pct"] = cfg.TRAIL_ACTIVATION_PCT
        r["trail_stop_pct"]       = cfg.TRAIL_STOP_PCT
        out.append(r)
    return out


def cycle_minutes() -> int:
    """
    Mirror paper_runner.py's schedule interval (5 min in day-trading mode,
    30 otherwise). Previously hardcoded to 30 here, which made the countdown
    wrong for the entire session whenever DAY_TRADING_MODE was on.
    """
    import config as cfg
    return 5 if getattr(cfg, "DAY_TRADING_MODE", False) else 30


def fetch_next_eval():
    """Last signal_log timestamp + the runner's actual cycle interval."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT MAX(timestamp) FROM signal_log")
        latest_ts = c.fetchone()[0]
    finally:
        # This ran every 10s from /api/data and used to open a second
        # connection it never closed — ~2,300 leaked handles per session.
        conn.close()
    if not latest_ts:
        return None
    try:
        dt = datetime.fromisoformat(latest_ts)
    except ValueError:
        return None
    return (dt + timedelta(minutes=cycle_minutes())).isoformat(timespec="seconds")


def fetch_news_feed(limit: int = 40) -> list:
    """All headlines the bot has scraped recently, regardless of whether
    any single one was decisive for a trade — purely informational, per
    the user's request to see 'what the bot sees', not just what it acted on."""
    import trade_logger as tl
    return tl.get_recent_news(limit)


def _narrate_signal(label, ok):
    return f"{label} {'confirmed' if ok else 'did not confirm'}"


def build_decision_narratives(cycle_feed: list) -> list:
    """
    Translate each cycle_feed row into a plain-English sentence explaining
    the actual decision logic — not code, the reasoning a human would give:
    which of the 4 signals fired, what score that produced, and why the
    bot accepted, held, or rejected the trade.
    """
    narratives = []
    for r in cycle_feed:
        parts = [
            _narrate_signal("RSI momentum", r["rsi_signal"]),
            _narrate_signal("Moving-average trend", r["ma_signal"]),
            _narrate_signal("MACD crossover", r["macd_signal"]),
            _narrate_signal("Volume surge", r["vol_signal"]),
        ]
        signal_sentence = "; ".join(parts)
        score = r["score"] if r["score"] is not None else 0

        if r["status"] == "ACCEPTED":
            verdict = (
                f"That was strong enough ({score}/4 signals) to open a position — "
                f"the bot bought {r['symbol']} on this evaluation."
            )
        elif r["status"] == "REJECTED":
            verdict = (
                f"Despite scoring {score}/4, the bot rejected the trade: {r['reason']}."
            )
        else:
            verdict = (
                f"Score was {score}/4 — not enough conviction to act, so the bot took "
                f"no action and kept watching {r['symbol']}."
            )

        sentence = (
            f"At {r['timestamp'][11:19]}, {r['symbol']} had RSI={r['rsi']}. "
            f"{signal_sentence}. {verdict}"
        )
        narratives.append({
            "timestamp": r["timestamp"],
            "symbol":    r["symbol"],
            "status":    r["status"],
            "text":      sentence,
        })
    return narratives


# ── Daily runner books (daily_runner.py, since 2026-09-28) ─────
_price_cache: dict = {}      # symbol -> (fetched_at, price); the page polls every 10s


def _latest_price(symbol: str) -> float | None:
    hit = _price_cache.get(symbol)
    if hit and (datetime.now() - hit[0]).total_seconds() < 60:
        return hit[1]
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest
        from alpaca.data.enums import DataFeed
        client = StockHistoricalDataClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"))
        trade = client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX))[symbol]
        price = float(trade.price)
    except Exception as e:
        logger.warning(f"latest price for {symbol} failed: {e}")
        return hit[1] if hit else None
    _price_cache[symbol] = (datetime.now(), price)
    return price


def _read_csv_rows(path: str) -> list:
    import csv
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_daily_books() -> dict:
    """Each book's ledger valued at the latest price, plus the runner's fills.
    Read-only: the ledgers are written by daily_runner.py alone."""
    import json
    import config as cfg
    books = []
    for name in cfg.DAILY_BOOKS:
        path = os.path.join(BOOK_DIR, f"{name}.json")
        if not os.path.isfile(path):
            books.append({"name": name, "started": False})
            continue
        with open(path) as f:
            b = json.load(f)
        positions, equity = [], b["cash"]
        for sym, p in b["positions"].items():
            price = _latest_price(sym) or p["entry_price"]
            value = p["qty"] * price
            equity += value
            positions.append({"symbol": sym, "qty": p["qty"], "entry_price": p["entry_price"],
                              "entry_date": p["entry_date"], "price": price, "value": round(value, 2),
                              "pnl_pct": round((price / p["entry_price"] - 1) * 100, 2)})
        books.append({"name": name, "started": True, "cash": round(b["cash"], 2),
                      "deposited": b["deposited"], "equity": round(equity, 2),
                      "return_pct": round((equity / b["deposited"] - 1) * 100, 2),
                      "last_run": b["last_run"], "positions": positions})
    fills = _read_csv_rows(os.path.join(BOOK_DIR, "fills.csv"))
    return {
        "books":        books,
        "fills":        list(reversed(fills))[:20],
        "equity_log":   _read_csv_rows(os.path.join(BOOK_DIR, "equity_log.csv")),
        "run_time_et":  cfg.DAILY_RUN_TIME,
    }


def next_daily_run(books: list) -> str | None:
    """Next DAILY_RUN_TIME on a weekday that hasn't run yet (holidays aside —
    the runner itself checks the broker clock). Returned as an offset-aware
    ISO string so the browser counts down correctly in any timezone."""
    from zoneinfo import ZoneInfo
    import config as cfg
    now = datetime.now(ZoneInfo("America/New_York"))
    hh, mm = map(int, cfg.DAILY_RUN_TIME.split(":"))
    ran_today = bool(books) and all(b.get("last_run") == now.date().isoformat() for b in books)
    day = now
    for _ in range(8):
        slot = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        is_today = slot.date() == now.date()
        if slot.weekday() < 5 and (slot > now or (is_today and not ran_today and now.hour < 15)):
            return slot.isoformat(timespec="seconds")
        day = (day + timedelta(days=1)).replace(hour=0, minute=0)
    return None


def fetch_symbol_history(symbol: str) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT symbol, entry_date, exit_date, entry_price, exit_price,
               qty, pnl, pnl_pct, hold_days, exit_reason, signal_score
        FROM trades WHERE symbol = ? ORDER BY entry_date DESC
    """, (symbol,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Routes ────────────────────────────────────────────────────

@app.route("/api/data")
@require_auth
def api_data():
    if not db_ok():
        return jsonify({"db_ready": False})

    import config as cfg

    # Headline stats = real broker orders only. Simulation is reported alongside,
    # never folded in.
    summary = fetch_summary("live")
    summary["profit_factor"] = fetch_profit_factor()
    backtest_summary = fetch_summary("backtest")
    per_ticker = fetch_per_ticker()
    cycle_feed = fetch_cycle_feed(20)
    by_symbol = {r["symbol"]: r for r in per_ticker}
    watchlist = [
        {
            "symbol": sym,
            "total_pnl": by_symbol.get(sym, {}).get("total_pnl", 0.0),
            "trade_count": by_symbol.get(sym, {}).get("trade_count", 0),
            "win_pct": by_symbol.get(sym, {}).get("win_pct", 0.0),
        }
        for sym in cfg.TICKERS
    ]
    daily = fetch_daily_books()
    return jsonify({
        "db_ready":       True,
        "daily":          daily,
        "summary":          summary,
        "backtest_summary": backtest_summary,
        "backtest_trades":  fetch_recent_trades("backtest"),
        "open_positions": fetch_open_positions(),
        "position_cushions": fetch_position_cushions(),
        "recent_trades":  fetch_recent_trades("live"),
        "per_ticker":     per_ticker,
        "watchlist":      watchlist,
        "exit_reasons":   fetch_exit_reasons(),
        "log_tail":       fetch_log_tail(15),
        "equity_curve":   fetch_equity_curve(),
        "cycle_feed":     cycle_feed,
        "decision_narratives": build_decision_narratives(cycle_feed),
        "news_feed":      fetch_news_feed(40),
        # The intraday runner's signal_log cadence is retired; count down to
        # the daily runner's once-a-session slot instead.
        "next_eval":      next_daily_run([b for b in daily["books"] if b.get("started")]),
        "cycle_minutes":  24 * 60,
    })


@app.route("/api/symbol/<symbol>")
@require_auth
def api_symbol(symbol):
    symbol = symbol.upper()
    if not _SYMBOL_RE.match(symbol):
        return jsonify({"error": "invalid symbol"}), 400
    if not db_ok():
        return jsonify({"history": []})
    return jsonify({"history": fetch_symbol_history(symbol)})


# ── HTML page ─────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>iTrade — Live Algorithmic Trading Terminal</title>
<link rel="icon" type="image/png" href="/static/logo.png">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #07090d;
    --bg-soft:   #0c0f15;
    --card:      #11151c;
    --card-hi:   #161b24;
    --border:    #232a36;
    --text:      #e6e9ef;
    --muted:     #7d8694;
    --green:     #3ddc84;
    --red:       #ff5c5c;
    --yellow:    #f5c451;
    --orange:    #f0883e;
    --blue:      #58a6ff;
    --purple:    #b083f0;
    --accent:    #3ddc84;
    --mono: "JetBrains Mono", Consolas, monospace;
    --sans: "Space Grotesk", -apple-system, "Segoe UI", sans-serif;
  }

  html { scroll-behavior: smooth; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    min-height: 100vh;
    background-image:
      linear-gradient(rgba(61,220,132,.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(61,220,132,.035) 1px, transparent 1px);
    background-size: 44px 44px;
  }

  /* ── Top nav ── */
  header {
    background: rgba(7,9,13,.85);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
    padding: 0 28px;
    display: flex;
    align-items: center;
    gap: 16px;
    height: 60px;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  header .logo {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: .5px;
    font-family: var(--mono);
  }
  /* Hidden until the file loads; the text mark below is the fallback. */
  header .logo #logo-img {
    display: none;
    height: 34px;
    width: auto;
    border-radius: 6px;
  }
  header .logo span { color: var(--green); }
  /* Simulation is visually separated from live so the two can never be read
     as one number again. */
  #sim-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 7px;
    margin-bottom: 14px;
    padding: 9px 14px;
    border: 1px dashed var(--border);
    border-left: 3px solid var(--yellow);
    border-radius: 6px;
    background: rgba(245,196,81,.05);
    color: var(--muted);
    font-family: var(--mono);
    font-size: 12px;
  }
  #sim-strip b {
    color: var(--yellow);
    letter-spacing: 1px;
    font-size: 11px;
  }
  #sim-strip span[id] { color: var(--text); font-weight: 700; }
  #sim-strip em { color: var(--muted); font-style: normal; opacity: .75; }
  header nav { display: flex; gap: 22px; margin-left: 32px; }
  header nav a {
    color: var(--muted);
    text-decoration: none;
    font-size: 13px;
    font-family: var(--mono);
    transition: color .15s;
  }
  header nav a:hover { color: var(--text); }
  #refresh-indicator {
    margin-left: auto;
    font-size: 12px;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: var(--mono);
  }
  .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
    box-shadow: 0 0 8px var(--green);
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: .3; }
  }

  /* ── Hero ── */
  .hero {
    max-width: 1400px;
    margin: 0 auto;
    padding: 64px 28px 40px;
  }
  .hero .eyebrow {
    font-family: var(--mono);
    color: var(--green);
    font-size: 12px;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 18px;
  }
  .hero h1 {
    font-size: clamp(40px, 7vw, 96px);
    font-weight: 700;
    line-height: .95;
    letter-spacing: -2px;
    -webkit-text-stroke: 1px var(--border);
  }
  .hero h1 .fill { color: var(--text); -webkit-text-stroke: 0; }
  .hero-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 32px;
    margin-top: 36px;
    align-items: flex-end;
  }
  .hero-stat .label {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }
  .hero-stat .value {
    font-family: var(--mono);
    font-size: 32px;
    font-weight: 700;
  }
  .market-pill {
    font-family: var(--mono);
    font-size: 12px;
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 6px 14px;
    color: var(--muted);
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .countdown { color: var(--green); font-weight: 700; }

  /* ── Custom cursor ── */
  #cursor-dot, #cursor-ring {
    position: fixed;
    top: 0; left: 0;
    pointer-events: none;
    z-index: 9999;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    transition: opacity .2s;
  }
  #cursor-dot {
    width: 6px; height: 6px;
    background: var(--green);
    mix-blend-mode: difference;
  }
  #cursor-ring {
    width: 32px; height: 32px;
    border: 1px solid var(--green);
    mix-blend-mode: difference;
    transition: width .15s, height .15s, transform .08s linear, opacity .2s;
  }
  body.using-mouse { cursor: none; }
  body.using-mouse a, body.using-mouse button, body.using-mouse tr[data-symbol], body.using-mouse .position-card {
    cursor: none;
  }
  @media (hover: none) { #cursor-dot, #cursor-ring { display: none; } }

  /* ── Scroll reveal ── */
  .reveal {
    opacity: 0;
    transform: translateY(28px);
    transition: opacity .6s ease, transform .6s ease;
  }
  .reveal.visible {
    opacity: 1;
    transform: translateY(0);
  }

  /* ── Layout ── */
  main {
    max-width: 1400px;
    margin: 0 auto;
    padding: 0 20px 64px;
  }
  section.block { margin-bottom: 28px; }
  .block-head {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 16px;
    padding: 0 4px;
  }
  .block-num {
    font-family: var(--mono);
    color: var(--green);
    font-size: 13px;
  }
  .block-title {
    font-size: 20px;
    font-weight: 600;
    letter-spacing: -.3px;
  }
  .block-sub {
    margin-left: auto;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
  }

  /* ── Waiting state ── */
  #waiting {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 50vh;
    gap: 16px;
    color: var(--muted);
  }
  #waiting .icon { font-size: 48px; }
  #waiting h2 { font-size: 20px; color: var(--text); font-family: var(--sans); }

  /* ── Stat cards ── */
  #stats-bar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 14px;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 20px;
    position: relative;
    overflow: hidden;
  }
  .stat-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: var(--accent); opacity: .6;
  }
  .stat-card .label {
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .8px;
    margin-bottom: 8px;
    font-family: var(--mono);
  }
  .stat-card .value {
    font-size: 28px;
    font-weight: 700;
    line-height: 1;
    font-family: var(--mono);
  }
  .stat-card .sub { font-size: 12px; color: var(--muted); margin-top: 6px; font-family: var(--mono); }

  /* ── Section cards ── */
  .section {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
  }
  .section-header {
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .section-title {
    font-size: 14px;
    font-weight: 600;
  }
  .badge {
    background: var(--bg-soft);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 12px;
    color: var(--muted);
    font-family: var(--mono);
  }

  /* ── Charts grid ── */
  .chart-grid {
    display: grid;
    grid-template-columns: 1.6fr 1fr;
    gap: 16px;
  }
  @media (max-width: 900px) { .chart-grid { grid-template-columns: 1fr; } }
  .chart-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 20px;
  }
  .chart-card .chart-title {
    font-size: 13px;
    color: var(--muted);
    font-family: var(--mono);
    margin-bottom: 10px;
    text-transform: uppercase;
    letter-spacing: .6px;
  }
  .chart-wrap { position: relative; height: 240px; }
  .donut-wrap { position: relative; height: 200px; }
  .donut-center {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
  }
  .donut-center .pct { font-size: 26px; font-weight: 700; font-family: var(--mono); }
  .donut-center .lbl { font-size: 11px; color: var(--muted); font-family: var(--mono); }

  /* ── Tables ── */
  table {
    width: 100%;
    border-collapse: collapse;
  }
  thead th {
    padding: 10px 16px;
    text-align: left;
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .5px;
    border-bottom: 1px solid var(--border);
    font-weight: 500;
    white-space: nowrap;
    font-family: var(--mono);
  }
  tbody tr {
    border-bottom: 1px solid var(--border);
    transition: background .15s;
    cursor: pointer;
  }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: rgba(255,255,255,.03); }
  tbody td {
    padding: 10px 16px;
    font-size: 13px;
    white-space: nowrap;
    font-family: var(--mono);
  }
  .empty-row td {
    text-align: center;
    color: var(--muted);
    padding: 32px;
    font-style: italic;
    cursor: default;
  }

  /* ── Color helpers ── */
  .pos  { color: var(--green); }
  .neg  { color: var(--red); }
  .neu  { color: var(--muted); }
  .sym  { color: var(--blue); font-weight: 600; font-family: var(--mono); }

  /* ── Two-column row ── */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  @media (max-width: 800px) { .two-col { grid-template-columns: 1fr; } }

  /* ── Cycle feed ── */
  .feed-list { max-height: 420px; overflow-y: auto; }
  .feed-row {
    display: grid;
    grid-template-columns: 90px 70px 50px 130px 1fr 100px;
    gap: 12px;
    align-items: center;
    padding: 11px 20px;
    border-bottom: 1px solid var(--border);
    font-family: var(--mono);
    font-size: 12px;
  }
  .feed-row:last-child { border-bottom: none; }
  .feed-time { color: var(--muted); }
  .feed-reason { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tag {
    border-radius: 6px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 600;
    text-align: center;
    letter-spacing: .3px;
  }
  .tag.ACCEPTED { background: rgba(61,220,132,.15); color: var(--green); }
  .tag.REJECTED { background: rgba(255,92,92,.15); color: var(--red); }
  .tag.HELD     { background: rgba(125,134,148,.15); color: var(--muted); }
  .score-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px; height: 22px;
    border-radius: 50%;
    font-size: 11px;
    font-weight: 700;
  }
  .score-badge.s4 { background: rgba(245,196,81,.2); color: var(--yellow); }
  .score-badge.s3 { background: rgba(176,131,240,.2); color: var(--purple); }
  .score-badge.s2, .score-badge.s1, .score-badge.s0 { background: rgba(125,134,148,.15); color: var(--muted); }

  /* ── Decision narrative ── */
  .narrative-list { max-height: 360px; overflow-y: auto; }
  .narrative-row {
    padding: 13px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    line-height: 1.5;
  }
  .narrative-row:last-child { border-bottom: none; }
  .narrative-row .n-sym { font-family: var(--mono); font-weight: 700; color: var(--blue); margin-right: 8px; }
  .narrative-row .n-time { font-family: var(--mono); color: var(--muted); font-size: 11px; margin-right: 8px; }
  .narrative-row.ACCEPTED { border-left: 3px solid var(--green); }
  .narrative-row.REJECTED { border-left: 3px solid var(--red); }
  .narrative-row.HELD     { border-left: 3px solid var(--muted); }

  /* ── News feed ── */
  .news-list { max-height: 420px; overflow-y: auto; }
  .news-row {
    display: grid;
    grid-template-columns: 80px 70px 1fr 90px;
    gap: 12px;
    align-items: center;
    padding: 11px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 12.5px;
  }
  .news-row:last-child { border-bottom: none; }
  .news-row .news-time { font-family: var(--mono); color: var(--muted); font-size: 11px; }
  .news-row a { color: var(--text); text-decoration: none; }
  .news-row a:hover { color: var(--blue); text-decoration: underline; }
  .news-sent { font-family: var(--mono); font-size: 11px; padding: 2px 8px; border-radius: 10px; text-align: center; }
  .news-sent.bullish { background: rgba(61,220,132,.15); color: var(--green); }
  .news-sent.bearish { background: rgba(255,92,92,.15); color: var(--red); }
  .news-sent.neutral { background: rgba(125,134,148,.15); color: var(--muted); }

  /* ── Position cards (cushion) ── */
  .position-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
    padding: 18px;
  }
  .position-card {
    background: var(--bg-soft);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    cursor: pointer;
    transition: border-color .15s;
  }
  .position-card:hover { border-color: var(--green); }
  .position-card .pc-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 10px;
  }
  .position-card .pc-sym { font-family: var(--mono); font-weight: 700; color: var(--blue); font-size: 15px; }
  .position-card .pc-score { font-family: var(--mono); font-size: 11px; color: var(--muted); }
  .position-card .pc-row { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); font-family: var(--mono); margin-bottom: 4px; }
  .cushion-track {
    background: var(--border);
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
    margin: 10px 0 6px;
    position: relative;
  }
  /* Risk/reward band. No live quote is available server-side, so this shows
     the configured stop and target distances to scale rather than a fake
     live cushion. Widths are set inline by renderPositions(). */
  .cushion-risk   { position: absolute; top:0; bottom:0; left: 0; background: var(--red);   opacity: .55; }
  .cushion-reward { position: absolute; top:0; bottom:0; right: 0; background: var(--green); opacity: .55; }
  .cushion-trail  { position: absolute; top:-2px; bottom:-2px; width: 2px; background: var(--yellow); }
  .cushion-zero   { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--text); }
  .cushion-labels { display: flex; justify-content: space-between; font-size: 10px; color: var(--muted); font-family: var(--mono); }

  /* ── Exit reasons ── */
  .exit-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    padding: 20px;
  }
  .exit-tile {
    background: var(--bg-soft);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
    text-align: center;
  }
  .exit-tile .cnt { font-size: 32px; font-weight: 700; font-family: var(--mono); }
  .exit-tile .lbl { font-size: 11px; color: var(--muted); margin-top: 4px; font-family: var(--mono); }
  .exit-tile.tp  .cnt { color: var(--green); }
  .exit-tile.sl  .cnt { color: var(--red); }
  .exit-tile.te  .cnt { color: var(--yellow); }
  .exit-tile.ts  .cnt { color: var(--blue); }
  .exit-tile.np  .cnt { color: var(--orange); }
  .exit-tile.nr  .cnt { color: var(--purple); }

  /* ── Bar chart (per ticker) labels ── */
  .ticker-bars { padding: 18px 20px; }
  .tbar-row { display: grid; grid-template-columns: 60px 1fr 90px; gap: 10px; align-items: center; margin-bottom: 10px; font-family: var(--mono); font-size: 12px; }
  .tbar-track { background: var(--border); border-radius: 4px; height: 10px; position: relative; overflow: hidden; }
  .tbar-fill { position: absolute; top:0; bottom:0; border-radius: 4px; }
  .tbar-fill.pos { background: var(--green); left: 50%; }
  .tbar-fill.neg { background: var(--red); right: 50%; }

  /* ── Log tail ── */
  .log-body {
    padding: 16px 20px;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.7;
    background: var(--bg-soft);
    max-height: 320px;
    overflow-y: auto;
  }
  .log-line { display: block; }
  .log-line.entered { color: var(--green); }
  .log-line.exited   { color: var(--yellow); }
  .log-line.error    { color: var(--red); }
  .log-line.warning  { color: var(--orange); }
  .log-line.default  { color: var(--muted); }
  .log-empty { color: var(--muted); font-style: italic; }

  /* ── Modal ── */
  .modal-overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,.7);
    backdrop-filter: blur(3px);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 20px;
  }
  .modal-overlay.open { display: flex; }
  .modal-box {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    max-width: 640px;
    width: 100%;
    max-height: 80vh;
    overflow-y: auto;
  }
  .modal-head {
    display: flex; justify-content: space-between; align-items: center;
    padding: 18px 22px; border-bottom: 1px solid var(--border);
  }
  .modal-head h3 { font-family: var(--mono); font-size: 18px; color: var(--blue); }
  .modal-close { cursor: pointer; color: var(--muted); font-size: 20px; background:none; border:none; }
  .modal-body { padding: 8px 0; }

  /* ── Ticker tape ── */
  .tape {
    background: var(--bg-soft);
    border-bottom: 1px solid var(--border);
    overflow: hidden;
    white-space: nowrap;
    position: sticky;
    top: 60px;
    z-index: 99;
  }
  .tape-track {
    display: inline-flex;
    gap: 36px;
    padding: 8px 0;
    animation: tape-scroll 36s linear infinite;
  }
  .tape:hover .tape-track { animation-play-state: paused; }
  @keyframes tape-scroll {
    from { transform: translateX(0); }
    to   { transform: translateX(-50%); }
  }
  .tape-item {
    font-family: var(--mono);
    font-size: 12px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--muted);
  }
  .tape-item .tsym { color: var(--text); font-weight: 700; }

  /* ── SVG gauges ── */
  .gauge-wrap { display: flex; align-items: center; justify-content: center; }
  .gauge-wrap svg { transform: rotate(-90deg); }
  .gauge-track { fill: none; stroke: var(--border); stroke-width: 10; }
  .gauge-fill  { fill: none; stroke: var(--green); stroke-width: 10; stroke-linecap: round; transition: stroke-dashoffset .6s ease; }
  .gauge-center { position: absolute; text-align: center; }
  .gauge-center .pct { font-size: 24px; font-weight: 700; font-family: var(--mono); }
  .gauge-center .lbl { font-size: 10px; color: var(--muted); font-family: var(--mono); }
  #ring-countdown { transform: rotate(-90deg); }
  .ring-track { fill:none; stroke: var(--border); stroke-width: 3; }
  .ring-fill  { fill:none; stroke: var(--green); stroke-width: 3; stroke-linecap: round; transition: stroke-dashoffset 1s linear; }

  /* ── Markets heatmap ── */
  .heat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 10px;
    padding: 18px;
  }
  .heat-cell {
    border-radius: 8px;
    padding: 12px 10px;
    border: 1px solid var(--border);
    cursor: pointer;
    transition: transform .15s;
  }
  .heat-cell:hover { transform: translateY(-2px); }
  .heat-cell .h-sym { font-family: var(--mono); font-weight: 700; font-size: 13px; }
  .heat-cell .h-pnl { font-family: var(--mono); font-size: 12px; margin-top: 4px; }
  .heat-cell .h-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; margin-right: 5px; }

  /* ── Radar ── */
  .radar-wrap { display: flex; align-items: center; justify-content: center; padding: 18px; }
  #radar-legend { display: flex; gap: 16px; justify-content: center; font-family: var(--mono); font-size: 11px; color: var(--muted); padding: 0 18px 16px; }
  #radar-legend span { display: inline-flex; align-items: center; gap: 5px; }
  #radar-legend .dot { width: 7px; height: 7px; border-radius: 50%; }

  /* ── Footer ── */
  footer {
    text-align: center;
    color: var(--muted);
    font-size: 12px;
    padding: 28px;
    font-family: var(--mono);
  }
</style>
</head>
<body>
<div id="cursor-ring"></div>
<div id="cursor-dot"></div>

<header>
  <div class="logo">
    <img id="logo-img" src="/static/logo.png" alt="iTrade"
         onload="document.getElementById('logo-text').style.display='none';this.style.display='inline-block'"
         onerror="this.remove()">
    <b id="logo-text">&#9654; i<span>Trade</span></b>
  </div>
  <nav>
    <a href="#performance">Performance</a>
    <a href="#cycle">This Cycle</a>
    <a href="#narrative">Why</a>
    <a href="#news">News</a>
    <a href="#positions">Positions</a>
    <a href="#log">Trade Log</a>
  </nav>
  <div id="refresh-indicator">
    <div class="dot"></div>
    <span id="last-updated">connecting...</span>
  </div>
</header>

<div class="tape">
  <div class="tape-track" id="tape-track">
    <span class="tape-item">Loading watchlist&hellip;</span>
  </div>
</div>

<div class="hero">
  <div class="eyebrow">Live Algorithmic Trading &middot; Paper Mode &middot; Real Data Only</div>
  <h1><span class="fill">i</span>TRADE</h1>
  <div class="hero-meta">
    <div class="hero-stat">
      <div class="label">Realized PnL</div>
      <div class="value" id="hero-pnl">—</div>
    </div>
    <div class="hero-stat">
      <div class="label">Win Rate</div>
      <div class="value" id="hero-winrate">—</div>
    </div>
    <div class="hero-stat">
      <div class="label">Profit Factor</div>
      <div class="value" id="hero-pf">—</div>
    </div>
    <div class="market-pill"><div class="dot" style="background:var(--green);box-shadow:0 0 6px var(--green)"></div><span id="hero-positions">0 open positions</span></div>
    <div class="market-pill" style="position:relative;">
      <svg id="ring-countdown" width="22" height="22" viewBox="0 0 22 22">
        <circle class="ring-track" cx="11" cy="11" r="9"></circle>
        <circle class="ring-fill" id="ring-fill" cx="11" cy="11" r="9" stroke-dasharray="56.5" stroke-dashoffset="0"></circle>
      </svg>
      <span>Next eval in</span>&nbsp;<span id="hero-countdown" class="countdown">—</span>
    </div>
  </div>
</div>

<main>
  <!-- Waiting state -->
  <div id="waiting" style="display:none;">
    <div class="icon">&#9202;</div>
    <h2>Waiting for bot...</h2>
    <p>trades.db not found — the bot hasn't started yet. Checking every 10 seconds.</p>
  </div>

  <div id="dashboard" style="display:none;">

    <!-- 00 Daily books -->
    <section class="block reveal" id="daily-books">
      <div class="block-head">
        <span class="block-num">00</span>
        <span class="block-title">Daily Books</span>
        <span class="block-sub" id="daily-sub">daily_runner.py &middot; once per session</span>
      </div>
      <div class="two-col" id="daily-book-cards"></div>
      <div class="section">
        <div class="section-header">
          <div class="section-title">Fills</div>
          <div class="badge">data/books/fills.csv &middot; newest first</div>
        </div>
        <table>
          <thead>
            <tr><th>Time (ET)</th><th>Book</th><th>Side</th><th>Symbol</th><th>Qty</th><th>Fill $</th><th>Notional $</th><th>Cost bps</th></tr>
          </thead>
          <tbody id="fills-tbody"></tbody>
        </table>
      </div>
    </section>

    <!-- 01 Performance -->
    <section class="block reveal" id="performance">
      <div class="block-head">
        <span class="block-num">01</span>
        <span class="block-title">Performance</span>
        <span class="block-sub">LIVE — real broker orders only</span>
      </div>

      <div id="sim-strip">
        <b>SIMULATED</b>
        <span>backtest, never sent to a broker —</span>
        <span id="sim-trades">—</span> trades ·
        win rate <span id="sim-winrate">—</span> ·
        P&amp;L <span id="sim-pnl">—</span>
        <em>excluded from the figures below</em>
      </div>

      <div id="stats-bar" style="margin-bottom:16px;">
        <div class="stat-card">
          <div class="label">Total Trades</div>
          <div class="value" id="s-trades">—</div>
          <div class="sub" id="s-winrate-sub"></div>
        </div>
        <div class="stat-card">
          <div class="label">Win Rate</div>
          <div class="value" id="s-winrate">—</div>
          <div class="sub">target &gt;42%</div>
        </div>
        <div class="stat-card">
          <div class="label">Total PnL</div>
          <div class="value" id="s-pnl">—</div>
          <div class="sub" id="s-pnl-sub"></div>
        </div>
        <div class="stat-card">
          <div class="label">Avg PnL / Trade</div>
          <div class="value" id="s-avg-pnl">—</div>
          <div class="sub">target &gt;+0.50%</div>
        </div>
        <div class="stat-card">
          <div class="label">Expectancy</div>
          <div class="value" id="s-expectancy">—</div>
          <div class="sub">win&times;size &minus; loss&times;size</div>
        </div>
        <div class="stat-card">
          <div class="label">Profit Factor</div>
          <div class="value" id="s-pf">—</div>
          <div class="sub">gross win &divide; gross loss</div>
        </div>
      </div>

      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title">Cumulative Realized PnL</div>
          <div class="chart-wrap"><canvas id="equity-chart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">Win / Loss Split</div>
          <div class="donut-wrap">
            <canvas id="donut-chart"></canvas>
            <div class="donut-center"><div class="pct" id="donut-pct">—</div><div class="lbl">WIN RATE</div></div>
          </div>
        </div>
      </div>
    </section>

    <!-- 02 Per-ticker -->
    <section class="block reveal">
      <div class="block-head">
        <span class="block-num">02</span>
        <span class="block-title">Per-Symbol Edge</span>
        <span class="block-sub" id="ticker-badge-sub">0 symbols traded</span>
      </div>
      <div class="section">
        <div class="ticker-bars" id="ticker-bars"></div>
      </div>
    </section>

    <!-- 02b Markets heatmap -->
    <section class="block reveal">
      <div class="block-head">
        <span class="block-num">02b</span>
        <span class="block-title">Markets</span>
        <span class="block-sub">full watchlist &middot; config.TICKERS</span>
      </div>
      <div class="section">
        <div class="heat-grid" id="heat-grid"></div>
      </div>
    </section>

    <!-- 03 This cycle -->
    <section class="block reveal" id="cycle">
      <div class="block-head">
        <span class="block-num">03</span>
        <span class="block-title">This Cycle</span>
        <span class="block-sub">live signal_log + rejections, most recent run_cycle()</span>
      </div>
      <div class="two-col">
        <div class="section">
          <div class="radar-wrap"><canvas id="radar" width="280" height="280"></canvas></div>
          <div id="radar-legend">
            <span><i class="dot" style="background:var(--green)"></i>Accepted</span>
            <span><i class="dot" style="background:var(--muted)"></i>Held</span>
            <span><i class="dot" style="background:var(--red)"></i>Rejected</span>
          </div>
        </div>
        <div class="section">
          <div class="feed-list" id="cycle-feed"></div>
        </div>
      </div>
    </section>

    <!-- 03b Decision narrative -->
    <section class="block reveal" id="narrative">
      <div class="block-head">
        <span class="block-num">03b</span>
        <span class="block-title">Why It Did That</span>
        <span class="block-sub">plain-English reasoning, derived from the same signals above &mdash; not code</span>
      </div>
      <div class="section">
        <div class="narrative-list" id="narrative-list"></div>
      </div>
    </section>

    <!-- 03c News feed -->
    <section class="block reveal" id="news">
      <div class="block-head">
        <span class="block-num">03c</span>
        <span class="block-title">News The Bot Sees</span>
        <span class="block-sub">scraped live from Yahoo Finance per ticker &middot; informational, not all of it is acted on</span>
      </div>
      <div class="section">
        <div class="news-list" id="news-list"></div>
      </div>
    </section>

    <!-- 04 Open positions -->
    <section class="block reveal" id="positions">
      <div class="block-head">
        <span class="block-num">04</span>
        <span class="block-title">Open Positions</span>
        <span class="block-sub" id="open-badge">0 open</span>
      </div>
      <div class="section">
        <div class="position-grid" id="position-grid"></div>
      </div>
    </section>

    <!-- 05 Recent trades + Exit reasons -->
    <section class="block reveal">
      <div class="two-col">
        <div class="section">
          <div class="section-header">
            <div class="section-title">Recent Closed Trades</div>
            <div class="badge">last 10 &middot; click for history</div>
          </div>
          <table>
            <thead>
              <tr><th>Symbol</th><th>Entry $</th><th>Exit $</th><th>PnL $</th><th>PnL %</th><th>Days</th><th>Reason</th></tr>
            </thead>
            <tbody id="recent-tbody"></tbody>
          </table>
        </div>

        <div class="section">
          <div class="section-header"><div class="section-title">Exit Reasons</div></div>
          <div class="exit-grid">
            <div class="exit-tile sl"><div class="cnt" id="er-sl">0</div><div class="lbl">Stop Loss</div></div>
            <div class="exit-tile np"><div class="cnt" id="er-np">0</div><div class="lbl">No Progress (cut)</div></div>
            <div class="exit-tile ts"><div class="cnt" id="er-ts">0</div><div class="lbl">Trailing Stop</div></div>
            <div class="exit-tile te"><div class="cnt" id="er-te">0</div><div class="lbl">Time Exit</div></div>
            <div class="exit-tile tp"><div class="cnt" id="er-tp">0</div><div class="lbl">Take Profit</div></div>
            <div class="exit-tile nr"><div class="cnt" id="er-nr">0</div><div class="lbl">News Reversal</div></div>
          </div>
        </div>
      </div>
    </section>

    <!-- 06 Live log -->
    <section class="block reveal" id="log">
      <div class="block-head">
        <span class="block-num">06</span>
        <span class="block-title">Trade Log</span>
        <span class="block-sub">last 15 lines &middot; logs/daily_runner.log</span>
      </div>
      <div class="section">
        <div class="log-body" id="log-body"></div>
      </div>
    </section>

  </div><!-- /dashboard -->
</main>

<footer>Auto-refreshes every 10s &middot; All figures sourced live from trades.db &middot; No simulated data</footer>

<!-- Symbol history modal -->
<div class="modal-overlay" id="modal-overlay">
  <div class="modal-box">
    <div class="modal-head">
      <h3 id="modal-symbol">—</h3>
      <button class="modal-close" id="modal-close">&times;</button>
    </div>
    <div class="modal-body">
      <table>
        <thead><tr><th>Entry</th><th>Exit</th><th>Entry $</th><th>Exit $</th><th>PnL %</th><th>Reason</th></tr></thead>
        <tbody id="modal-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
  const $ = id => document.getElementById(id);

  function pnlClass(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : 'neu'; }
  function fmt$(v)      { return (v >= 0 ? '+$' : '-$') + Math.abs(v).toFixed(2); }
  function fmtPct(v)    { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
  function esc(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  let equityChart = null, donutChart = null;

  // ── Custom cursor (mix-blend-mode, follows pointer) ──────────
  (function initCursor() {
    const dot = $('cursor-dot'), ring = $('cursor-ring');
    let mouseUsed = false;
    window.addEventListener('mousemove', e => {
      if (!mouseUsed) { mouseUsed = true; document.body.classList.add('using-mouse'); }
      dot.style.left = e.clientX + 'px';
      dot.style.top  = e.clientY + 'px';
      ring.style.left = e.clientX + 'px';
      ring.style.top  = e.clientY + 'px';
    });
    document.addEventListener('mousedown', () => ring.style.transform = 'translate(-50%,-50%) scale(0.7)');
    document.addEventListener('mouseup',   () => ring.style.transform = 'translate(-50%,-50%) scale(1)');
    document.querySelectorAll('a, button, tr, .position-card').forEach(el => {
      el.addEventListener('mouseenter', () => { ring.style.width = '48px'; ring.style.height = '48px'; });
      el.addEventListener('mouseleave', () => { ring.style.width = '32px'; ring.style.height = '32px'; });
    });
  })();

  // ── Scroll-reveal: sections animate in as they enter the viewport ──
  const revealObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -60px 0px' });
  document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

  // ── Next-eval countdown, ticks every second client-side ──────
  let nextEvalAt = null;
  // Set from the API each refresh so the ring matches the runner's real
  // cycle interval instead of a hardcoded 30 minutes.
  let EVAL_WINDOW_MS = 30 * 60 * 1000;
  function tickCountdown() {
    const el = $('hero-countdown');
    const ring = $('ring-fill');
    if (!nextEvalAt) { el.textContent = '—'; return; }
    const diffMs = nextEvalAt.getTime() - Date.now();
    if (diffMs <= 0) { el.textContent = 'due now'; ring.style.strokeDashoffset = 0; return; }
    const hrs  = Math.floor(diffMs / 3600000);
    const mins = Math.floor((diffMs % 3600000) / 60000);
    const secs = Math.floor((diffMs % 60000) / 1000);
    el.textContent = (hrs ? hrs + 'h ' : '') + String(mins).padStart(2,'0') + ':' + String(secs).padStart(2,'0');
    const frac = Math.max(0, Math.min(1, diffMs / EVAL_WINDOW_MS));
    ring.style.strokeDashoffset = (56.5 * (1 - frac)).toFixed(1);
  }
  setInterval(tickCountdown, 1000);

  function renderTape(rows) {
    const track = $('tape-track');
    if (!rows || rows.length === 0) {
      track.innerHTML = '<span class="tape-item">No watchlist data</span>';
      return;
    }
    const items = rows.map(r => {
      const cls = r.total_pnl > 0 ? 'pos' : r.total_pnl < 0 ? 'neg' : 'neu';
      return `<span class="tape-item"><span class="tsym">${esc(r.symbol)}</span><span class="${cls}">${fmt$(r.total_pnl||0)}</span></span>`;
    });
    // duplicate the list so the CSS scroll loop (translateX -50%) is seamless
    track.innerHTML = items.join('') + items.join('');
  }

  function renderHeatmap(rows) {
    const el = $('heat-grid');
    if (!rows || rows.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:24px;font-family:var(--mono)">No watchlist data</div>';
      return;
    }
    const maxAbs = Math.max(1, ...rows.map(r => Math.abs(r.total_pnl||0)));
    el.innerHTML = rows.map(r => {
      const pnl = r.total_pnl || 0;
      const intensity = Math.min(1, Math.abs(pnl) / maxAbs);
      const base = pnl >= 0 ? '61,220,132' : '255,92,92';
      const bg = `rgba(${base},${(0.06 + intensity * 0.22).toFixed(2)})`;
      const dotColor = pnl > 0 ? 'var(--green)' : pnl < 0 ? 'var(--red)' : 'var(--muted)';
      return `<div class="heat-cell" data-symbol="${esc(r.symbol)}" style="background:${bg}">
        <div class="h-sym"><span class="h-dot" style="background:${dotColor}"></span>${esc(r.symbol)}</div>
        <div class="h-pnl ${pnlClass(pnl)}">${fmt$(pnl)}</div>
        <div class="h-pnl neu" style="font-size:10px">${r.trade_count||0} trades</div>
      </div>`;
    }).join('');
    el.querySelectorAll('.heat-cell').forEach(cell => {
      cell.addEventListener('click', () => openModal(cell.dataset.symbol));
    });
  }

  let radarAngle = 0, radarFeed = [];
  function renderRadar(feed) {
    radarFeed = feed || [];
  }
  function drawRadar() {
    const canvas = $('radar');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height, cx = w/2, cy = h/2, r = Math.min(w,h)/2 - 10;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = 'rgba(125,134,148,.25)';
    for (let i = 1; i <= 3; i++) {
      ctx.beginPath(); ctx.arc(cx, cy, r * i / 3, 0, Math.PI*2); ctx.stroke();
    }
    ctx.beginPath(); ctx.moveTo(cx-r,cy); ctx.lineTo(cx+r,cy); ctx.moveTo(cx,cy-r); ctx.lineTo(cx,cy+r); ctx.stroke();

    const grad = ctx.createConicGradient ? ctx.createConicGradient(radarAngle, cx, cy) : null;
    if (grad) {
      grad.addColorStop(0, 'rgba(61,220,132,.35)');
      grad.addColorStop(0.08, 'rgba(61,220,132,0)');
      grad.addColorStop(1, 'rgba(61,220,132,0)');
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.moveTo(cx,cy); ctx.arc(cx,cy,r,0,Math.PI*2); ctx.fill();
    }

    const n = radarFeed.length;
    radarFeed.forEach((f, i) => {
      const angle = (i / Math.max(1,n)) * Math.PI * 2;
      const dist = r * (0.3 + 0.6 * ((f.score||0) / 4));
      const x = cx + Math.cos(angle) * dist;
      const y = cy + Math.sin(angle) * dist;
      const color = f.status === 'ACCEPTED' ? '#3ddc84' : f.status === 'REJECTED' ? '#ff5c5c' : '#7d8694';
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI*2); ctx.fillStyle = color; ctx.fill();
      ctx.font = '10px JetBrains Mono'; ctx.fillStyle = '#7d8694';
      ctx.fillText(f.symbol, x + 6, y + 3);
    });

    radarAngle += 0.02;
    requestAnimationFrame(drawRadar);
  }
  requestAnimationFrame(drawRadar);

  function renderSimStrip(b) {
    const strip = $('sim-strip');
    if (!b || !b.total_trades) { strip.style.display = 'none'; return; }
    strip.style.display = 'flex';
    $('sim-trades').textContent  = b.total_trades;
    $('sim-winrate').textContent = b.win_rate + '%';
    $('sim-pnl').textContent     = (b.total_pnl >= 0 ? '+$' : '-$') + Math.abs(b.total_pnl).toFixed(2);
  }

  function renderStats(s) {
    $('s-trades').textContent   = s.total_trades;
    $('s-winrate-sub').textContent = s.wins + ' wins / ' + (s.total_trades - s.wins) + ' losses';

    const wr = $('s-winrate');
    wr.textContent = s.win_rate + '%';
    wr.className   = 'value ' + (s.win_rate >= 42 ? 'pos' : 'neg');

    const pnlEl = $('s-pnl');
    pnlEl.textContent = fmt$(s.total_pnl);
    pnlEl.className   = 'value ' + pnlClass(s.total_pnl);
    $('s-pnl-sub').textContent = 'avg win ' + (s.avg_win_pct || 0).toFixed(2) + '% / avg loss -' + (s.avg_loss_pct || 0).toFixed(2) + '%';

    const avgEl = $('s-avg-pnl');
    avgEl.textContent = fmtPct(s.avg_pnl_pct);
    avgEl.className   = 'value ' + pnlClass(s.avg_pnl_pct);

    const expEl = $('s-expectancy');
    expEl.textContent = (s.expectancy >= 0 ? '+' : '') + s.expectancy + '%';
    expEl.className   = 'value ' + (s.expectancy >= 0.5 ? 'pos' : 'neg');

    const pfEl = $('s-pf');
    pfEl.textContent = s.profit_factor;
    pfEl.className   = 'value ' + (s.profit_factor >= 1 ? 'pos' : 'neg');

    $('hero-pnl').textContent = fmt$(s.total_pnl);
    $('hero-pnl').className = 'value ' + pnlClass(s.total_pnl);
    $('hero-winrate').textContent = s.win_rate + '%';
    $('hero-pf').textContent = s.profit_factor;
  }

  function renderEquityChart(curve) {
    const labels = curve.map(p => (p.date||'').slice(0,10));
    const data   = curve.map(p => p.cum_pnl);
    const ctx = $('equity-chart').getContext('2d');
    const cfg = {
      type: 'line',
      data: { labels, datasets: [{
        data,
        borderColor: '#3ddc84',
        backgroundColor: 'rgba(61,220,132,.12)',
        fill: true,
        tension: .25,
        pointRadius: 0,
        borderWidth: 2,
      }]},
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#7d8694', maxTicksLimit: 6 }, grid: { color: '#232a36' } },
          y: { ticks: { color: '#7d8694' }, grid: { color: '#232a36' } },
        }
      }
    };
    if (equityChart) { equityChart.data = cfg.data; equityChart.update(); }
    else if (labels.length) { equityChart = new Chart(ctx, cfg); }
  }

  function renderDonutChart(s) {
    const wins = s.wins, losses = s.total_trades - s.wins;
    $('donut-pct').textContent = s.win_rate + '%';
    const ctx = $('donut-chart').getContext('2d');
    const cfg = {
      type: 'doughnut',
      data: { labels: ['Wins','Losses'], datasets: [{
        data: [wins, losses],
        backgroundColor: ['#3ddc84', '#ff5c5c'],
        borderWidth: 0,
      }]},
      options: {
        responsive: true, maintainAspectRatio: false,
        cutout: '72%',
        plugins: { legend: { display: false } },
      }
    };
    if (donutChart) { donutChart.data = cfg.data; donutChart.update(); }
    else if (wins + losses > 0) { donutChart = new Chart(ctx, cfg); }
  }

  function renderTickerBars(rows) {
    $('ticker-badge-sub').textContent = rows.length + ' symbols traded';
    const el = $('ticker-bars');
    if (rows.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:24px;font-family:var(--mono)">No closed trades yet</div>';
      return;
    }
    const maxAbs = Math.max(1, ...rows.map(r => Math.abs(r.total_pnl)));
    el.innerHTML = rows.map(r => {
      const pct = Math.min(50, Math.abs(r.total_pnl) / maxAbs * 50);
      const cls = r.total_pnl >= 0 ? 'pos' : 'neg';
      const style = r.total_pnl >= 0 ? `width:${pct}%` : `width:${pct}%`;
      return `<div class="tbar-row">
        <span class="sym">${esc(r.symbol)}</span>
        <div class="tbar-track"><div class="tbar-fill ${cls}" style="${style}"></div></div>
        <span class="${pnlClass(r.total_pnl)}">${fmt$(r.total_pnl)}</span>
      </div>`;
    }).join('');
  }

  function scoreClass(score) { return 's' + Math.max(0, Math.min(4, score||0)); }

  function renderCycleFeed(rows) {
    const el = $('cycle-feed');
    if (!rows || rows.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:32px;font-family:var(--mono)">No signal evaluations logged yet</div>';
      return;
    }
    const sig = (ok, label) => `<span title="${label}: ${ok ? 'PASSED' : 'failed'}" style="color:${ok ? 'var(--green,#3c9)' : 'var(--muted)'};font-weight:${ok?'700':'400'}">${label}</span>`;
    el.innerHTML = rows.map(r => `
      <div class="feed-row">
        <span class="feed-time">${esc((r.timestamp||'').slice(11,19))}</span>
        <span class="sym">${esc(r.symbol)}</span>
        <span class="score-badge ${scoreClass(r.score)}">${r.score ?? '—'}</span>
        <span class="feed-rules" style="font-family:var(--mono);font-size:11px;letter-spacing:1px" title="RSI=${r.rsi ?? '—'}">
          ${sig(r.rsi_signal,'R')} ${sig(r.ma_signal,'MA')} ${sig(r.macd_signal,'MACD')} ${sig(r.vol_signal,'V')}
        </span>
        <span class="feed-reason" title="${esc(r.reason||'')}">${esc(r.reason||'—')}</span>
        <span class="tag ${esc(r.status)}">${esc(r.status)}</span>
      </div>`).join('');
  }

  function renderNarrative(rows) {
    const el = $('narrative-list');
    if (!rows || rows.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:32px;font-family:var(--mono)">No decisions evaluated yet this cycle</div>';
      return;
    }
    el.innerHTML = rows.map(r => `
      <div class="narrative-row ${esc(r.status)}">
        <span class="n-time">${esc((r.timestamp||'').slice(11,19))}</span>
        <span class="n-sym">${esc(r.symbol)}</span>${esc(r.text)}
      </div>`).join('');
  }

  function renderNews(rows) {
    const el = $('news-list');
    if (!rows || rows.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:32px;font-family:var(--mono)">No headlines scraped yet</div>';
      return;
    }
    el.innerHTML = rows.map(r => `
      <div class="news-row">
        <span class="news-time">${esc((r.timestamp||'').slice(0,10))}</span>
        <span class="sym">${esc(r.symbol)}</span>
        <a href="${esc(r.link||'#')}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a>
        <span class="news-sent ${esc(r.sentiment_label||'neutral')}">${esc(r.sentiment_label||'neutral')}</span>
      </div>`).join('');
  }

  function renderPositions(rows) {
    $('open-badge').textContent = rows.length + ' open';
    $('hero-positions').textContent = rows.length + ' open position' + (rows.length===1?'':'s');
    const el = $('position-grid');
    if (rows.length === 0) {
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:24px;font-family:var(--mono);grid-column:1/-1">No open positions</div>';
      return;
    }
    el.innerHTML = rows.map(r => {
      // Cushion bar: stop_loss_pct on the left, take_profit_pct on the right of entry (0).
      // Trail activation marks where trailing protection kicks in.
      const slPct = (r.stop_loss_pct||0) * 100;
      const tpPct = (r.take_profit_pct||0) * 100;
      const trailPct = (r.trail_activation_pct||0) * 100;
      // Lay the configured stop and target out to scale on one bar so the
      // risk:reward ratio is readable at a glance. Entry sits where the two
      // meet; the yellow tick is where the trailing stop activates.
      const span = slPct + tpPct;
      const entryAt = span > 0 ? (slPct / span) * 100 : 50;
      const trailAt = span > 0 ? ((slPct + trailPct) / span) * 100 : 50;
      const rr = slPct > 0 ? (tpPct / slPct) : 0;
      const entryPrice = r.entry_price || 0;
      const stopPrice  = entryPrice * (1 - (r.stop_loss_pct||0));
      const tgtPrice   = entryPrice * (1 + (r.take_profit_pct||0));
      return `<div class="position-card" data-symbol="${esc(r.symbol)}">
        <div class="pc-head">
          <span class="pc-sym">${esc(r.symbol)}</span>
          <span class="pc-score">score ${r.signal_score ?? '—'}/4</span>
        </div>
        <div class="pc-row"><span>Entry</span><span>$${entryPrice.toFixed(2)}</span></div>
        <div class="pc-row"><span>Qty</span><span>${(r.qty||0).toFixed(4)}</span></div>
        <div class="pc-row"><span>Opened</span><span>${esc(r.entry_date ? r.entry_date.slice(0,16).replace('T',' ') : '—')}</span></div>
        <div class="pc-row"><span>Risk : Reward</span><span>1 : ${rr.toFixed(1)}</span></div>
        <div class="cushion-track" title="Configured bands — no live quote">
          <div class="cushion-risk"   style="width:${entryAt.toFixed(1)}%"></div>
          <div class="cushion-reward" style="width:${(100-entryAt).toFixed(1)}%"></div>
          <div class="cushion-trail"  style="left:${trailAt.toFixed(1)}%"></div>
          <div class="cushion-zero"   style="left:${entryAt.toFixed(1)}%"></div>
        </div>
        <div class="cushion-labels">
          <span class="neg">$${stopPrice.toFixed(2)}</span>
          <span>trail +${trailPct.toFixed(0)}%</span>
          <span class="pos">$${tgtPrice.toFixed(2)}</span>
        </div>
      </div>`;
    }).join('');
    el.querySelectorAll('.position-card').forEach(card => {
      card.addEventListener('click', () => openModal(card.dataset.symbol));
    });
  }

  const BOOK_BLURB = {
    index: 'Buy &amp; hold SPY &middot; never sells',
    h1:    'Paper forward test &middot; RSI(2) pullback rules',
    h5:    'Paper forward test &middot; analyst-upgrade drift, 10-day hold',
  };

  function renderDailyBooks(d) {
    const cards = $('daily-book-cards');
    if (!d || !d.books) { cards.innerHTML = ''; return; }
    $('daily-sub').innerHTML = 'daily_runner.py &middot; runs ' + esc(d.run_time_et) + ' ET each session';
    cards.innerHTML = d.books.map(b => {
      if (!b.started) {
        return `<div class="section">
          <div class="section-header"><div class="section-title">${esc(b.name)}</div></div>
          <div style="color:var(--muted);font-family:var(--mono);font-size:12px">${BOOK_BLURB[b.name] || ''}<br><br>
          No ledger yet &mdash; first run at ${esc(d.run_time_et)} ET.</div></div>`;
      }
      const pos = b.positions.length
        ? b.positions.map(p => `<div class="pc-row">
            <span class="sym">${esc(p.symbol)} &times;${p.qty.toFixed(4)} @ $${p.entry_price.toFixed(2)}</span>
            <span>$${p.value.toFixed(2)} <span class="${pnlClass(p.pnl_pct)}">${fmtPct(p.pnl_pct)}</span></span>
          </div>`).join('')
        : '<div class="pc-row"><span>No positions</span><span></span></div>';
      return `<div class="section">
        <div class="section-header">
          <div class="section-title">${esc(b.name)}</div>
          <div class="badge">last run ${esc(b.last_run || 'never')}</div>
        </div>
        <div style="color:var(--muted);font-family:var(--mono);font-size:11px;margin-bottom:10px">${BOOK_BLURB[b.name] || ''}</div>
        <div class="pc-row"><span>Equity</span><span>$${b.equity.toFixed(2)} <span class="${pnlClass(b.return_pct)}">${fmtPct(b.return_pct)}</span></span></div>
        <div class="pc-row"><span>Cash</span><span>$${b.cash.toFixed(2)}</span></div>
        <div class="pc-row"><span>Deposited</span><span>$${b.deposited.toFixed(2)}</span></div>
        ${pos}
      </div>`;
    }).join('');

    const tb = $('fills-tbody');
    if (!d.fills.length) {
      tb.innerHTML = '<tr class="empty-row"><td colspan="8">No fills yet &mdash; first orders at ' + esc(d.run_time_et) + ' ET</td></tr>';
      return;
    }
    tb.innerHTML = d.fills.map(f => {
      const qty = parseFloat(f.qty), fill = parseFloat(f.fill), cost = parseFloat(f.cost_bps);
      return `<tr data-symbol="${esc(f.symbol)}">
        <td>${esc((f.time||'').slice(0,19).replace('T',' '))}</td>
        <td>${esc(f.book)}</td>
        <td class="${f.side === 'BUY' ? 'pos' : 'neg'}">${esc(f.side)}</td>
        <td class="sym">${esc(f.symbol)}</td>
        <td>${qty.toFixed(4)}</td>
        <td>$${fill.toFixed(2)}</td>
        <td>$${(qty * fill).toFixed(2)}</td>
        <td class="${cost > 0 ? 'neg' : 'neu'}">${isNaN(cost) ? '—' : cost.toFixed(1)}</td>
      </tr>`;
    }).join('');
  }

  function renderRecentTrades(rows) {
    const tb = $('recent-tbody');
    if (rows.length === 0) {
      tb.innerHTML = '<tr class="empty-row"><td colspan="7">No closed trades yet</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(r => {
      const pc = pnlClass(r.pnl);
      return `
      <tr data-symbol="${esc(r.symbol)}">
        <td class="sym">${esc(r.symbol)}</td>
        <td>$${(r.entry_price||0).toFixed(2)}</td>
        <td>$${(r.exit_price||0).toFixed(2)}</td>
        <td class="${pc}">${fmt$(r.pnl||0)}</td>
        <td class="${pc}">${fmtPct((r.pnl_pct||0)*100)}</td>
        <td>${r.hold_days ?? '—'}</td>
        <td>${esc(r.exit_reason||'—')}</td>
      </tr>`;
    }).join('');
    tb.querySelectorAll('tr[data-symbol]').forEach(row => {
      row.addEventListener('click', () => openModal(row.dataset.symbol));
    });
  }

  function renderExitReasons(er) {
    $('er-sl').textContent = er['Stop Loss']         || 0;
    $('er-np').textContent = er['No Progress (cut)'] || 0;
    $('er-ts').textContent = er['Trailing Stop']     || 0;
    $('er-te').textContent = er['Time Exit']         || 0;
    $('er-tp').textContent = er['Take Profit']       || 0;
    $('er-nr').textContent = er['News Reversal']     || 0;
  }

  function lineClass(line) {
    const u = line.toUpperCase();
    if (u.includes('ENTERED') || u.includes('ENTRY')) return 'entered';
    if (u.includes('EXITED')  || u.includes('EXIT'))  return 'exited';
    if (u.includes('ERROR'))   return 'error';
    if (u.includes('WARNING')) return 'warning';
    return 'default';
  }

  function renderLog(lines) {
    const el = $('log-body');
    if (!lines || lines.length === 0) {
      el.innerHTML = '<span class="log-empty">No log file found.</span>';
      return;
    }
    el.innerHTML = lines.map(l =>
      `<span class="log-line ${lineClass(l)}">${esc(l)}</span>`
    ).join('\n');
    el.scrollTop = el.scrollHeight;
  }

  function setLastUpdated() {
    const now = new Date();
    $('last-updated').textContent = 'Updated ' + now.toLocaleTimeString();
  }

  async function openModal(symbol) {
    $('modal-symbol').textContent = symbol;
    $('modal-overlay').classList.add('open');
    try {
      const res = await fetch('/api/symbol/' + encodeURIComponent(symbol));
      const data = await res.json();
      const tb = $('modal-tbody');
      if (!data.history || data.history.length === 0) {
        tb.innerHTML = '<tr class="empty-row"><td colspan="6">No history</td></tr>';
        return;
      }
      tb.innerHTML = data.history.map(h => `
        <tr>
          <td>${esc(h.entry_date ? h.entry_date.slice(0,10) : '—')}</td>
          <td>${esc(h.exit_date ? h.exit_date.slice(0,10) : 'OPEN')}</td>
          <td>$${(h.entry_price||0).toFixed(2)}</td>
          <td>${h.exit_price ? '$'+h.exit_price.toFixed(2) : '—'}</td>
          <td class="${pnlClass(h.pnl_pct||0)}">${h.pnl_pct!=null ? fmtPct(h.pnl_pct*100) : '—'}</td>
          <td>${esc(h.exit_reason||'—')}</td>
        </tr>`).join('');
    } catch (err) {
      console.error(err);
    }
  }

  $('modal-close').addEventListener('click', () => $('modal-overlay').classList.remove('open'));
  $('modal-overlay').addEventListener('click', e => {
    if (e.target.id === 'modal-overlay') $('modal-overlay').classList.remove('open');
  });

  async function refresh() {
    try {
      const res  = await fetch('/api/data');
      const data = await res.json();

      if (!data.db_ready) {
        $('waiting').style.display   = 'flex';
        $('dashboard').style.display = 'none';
        $('last-updated').textContent = 'Waiting for trades.db...';
        return;
      }

      $('waiting').style.display   = 'none';
      $('dashboard').style.display = 'block';

      renderDailyBooks(data.daily);
      renderSimStrip(data.backtest_summary);
      renderStats(data.summary);
      renderEquityChart(data.equity_curve);
      renderDonutChart(data.summary);
      renderTickerBars(data.per_ticker);
      renderTape(data.watchlist);
      renderHeatmap(data.watchlist);
      renderCycleFeed(data.cycle_feed);
      renderRadar(data.cycle_feed);
      renderNarrative(data.decision_narratives);
      renderNews(data.news_feed);
      renderPositions(data.position_cushions);
      renderRecentTrades(data.recent_trades);
      renderExitReasons(data.exit_reasons);
      if (data.cycle_minutes) EVAL_WINDOW_MS = data.cycle_minutes * 60 * 1000;
      nextEvalAt = data.next_eval ? new Date(data.next_eval.replace(' ', 'T')) : null;
      tickCountdown();
      renderLog(data.log_tail);
      setLastUpdated();

    } catch (err) {
      $('last-updated').textContent = 'Fetch error — retrying...';
      console.error(err);
    }
  }

  // Initial load + poll every 10 s
  refresh();
  setInterval(refresh, 10_000);
</script>
</body>
</html>"""


@app.route("/")
@require_auth
def index():
    return HTML


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
