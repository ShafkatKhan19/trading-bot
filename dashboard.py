# ============================================================
#  dashboard.py — Real-time trading bot monitor
#  Run: python dashboard.py
#  Refreshes every 10 seconds. Press Ctrl+C to exit.
# ============================================================

import sqlite3
import time
import os
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.live import Live
from rich.layout import Layout
from rich import box

DB_PATH = "trades.db"
LOG_PATH = "logs/paper_runner.log"
REFRESH_SECONDS = 10


def db_ok() -> bool:
    return os.path.exists(DB_PATH)


def query(sql, params=()):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def get_summary() -> dict:
    rows = query("SELECT COUNT(*), SUM(pnl), AVG(pnl_pct) FROM trades WHERE exit_date IS NOT NULL")
    total, total_pnl, avg_pnl = rows[0] if rows else (0, 0, 0)
    wins = query("SELECT COUNT(*) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL")
    wins = wins[0][0] if wins else 0
    total = total or 0
    return {
        "total_trades": total,
        "wins":         wins,
        "losses":       total - wins,
        "win_rate":     round(wins / total, 4) if total > 0 else 0,
        "total_pnl":    round(total_pnl or 0, 2),
        "avg_pnl_pct":  round((avg_pnl or 0) * 100, 2),
    }


def get_open_positions():
    return query("""
        SELECT symbol, entry_date, entry_price, qty, signal_score, news_sentiment
        FROM trades
        WHERE exit_date IS NULL
        ORDER BY entry_date DESC
    """)


def get_recent_trades(n=10):
    return query("""
        SELECT symbol, entry_price, exit_price, pnl, pnl_pct, hold_days, exit_reason
        FROM trades
        WHERE exit_date IS NOT NULL
        ORDER BY exit_date DESC
        LIMIT ?
    """, (n,))


def get_ticker_breakdown():
    return query("""
        SELECT symbol,
               COUNT(*) AS trades,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
               ROUND(SUM(pnl), 2) AS total_pnl
        FROM trades
        WHERE exit_date IS NOT NULL
        GROUP BY symbol
        ORDER BY total_pnl DESC
    """)


def get_exit_reasons():
    return query("""
        SELECT
            CASE
                WHEN exit_reason LIKE 'take_profit%' THEN 'Take Profit'
                WHEN exit_reason LIKE 'stop_loss%'   THEN 'Stop Loss'
                WHEN exit_reason LIKE 'time_exit%'   THEN 'Time Exit'
                WHEN exit_reason LIKE 'news_reversal%' THEN 'News Reversal'
                ELSE exit_reason
            END AS reason,
            COUNT(*) as count
        FROM trades
        WHERE exit_date IS NOT NULL
        GROUP BY reason
        ORDER BY count DESC
    """)


def tail_log(n=8):
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception:
        return ["Log file not found"]


def build_header(s: dict) -> Panel:
    progress_bar_len = 40
    filled = int((s["total_trades"] / 500) * progress_bar_len)
    bar = "[green]" + "█" * filled + "[/green][dim]" + "░" * (progress_bar_len - filled) + "[/dim]"

    win_color  = "green" if s["win_rate"] >= 0.55 else "yellow" if s["win_rate"] >= 0.45 else "red"
    pnl_color  = "green" if s["total_pnl"] >= 0 else "red"
    pnl_sign   = "+" if s["total_pnl"] >= 0 else ""

    content = (
        f"  Trades: [bold white]{s['total_trades']}[/] / 500   "
        f"Wins: [green]{s['wins']}[/]  Losses: [red]{s['losses']}[/]  "
        f"Win Rate: [{win_color}]{s['win_rate']:.1%}[/]  "
        f"Total PnL: [{pnl_color}]{pnl_sign}${s['total_pnl']:,.2f}[/]  "
        f"Avg PnL: [{pnl_color}]{s['avg_pnl_pct']:+.2f}%[/]\n\n"
        f"  {bar}  [dim]{s['total_trades']}/500[/]"
    )
    return Panel(content, title="[bold cyan] TRADING BOT — PAPER RUNNER[/]", border_style="cyan")


def build_open_positions(positions) -> Panel:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold yellow")
    table.add_column("Symbol", style="bold white", width=7)
    table.add_column("Entry Date", width=12)
    table.add_column("Entry $", justify="right", width=9)
    table.add_column("Qty", justify="right", width=7)
    table.add_column("Score", justify="center", width=6)
    table.add_column("News", width=10)

    if not positions:
        table.add_row("[dim]no open positions[/]", "", "", "", "", "")
    else:
        for sym, edate, eprice, qty, score, news in positions:
            news_color = "green" if news == "bullish" else "red" if news == "bearish" else "yellow"
            edate_short = edate[:10] if edate else "—"
            table.add_row(
                sym,
                edate_short,
                f"${eprice:.2f}",
                str(round(qty, 1)),
                f"{score}/4",
                f"[{news_color}]{news or '—'}[/]"
            )

    return Panel(table, title=f"[yellow]Open Positions ({len(positions)})[/]", border_style="yellow")


def build_recent_trades(trades) -> Panel:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold blue")
    table.add_column("Symbol", style="bold white", width=7)
    table.add_column("Entry $", justify="right", width=9)
    table.add_column("Exit $", justify="right", width=9)
    table.add_column("PnL $", justify="right", width=10)
    table.add_column("PnL %", justify="right", width=8)
    table.add_column("Days", justify="center", width=5)
    table.add_column("Reason", width=20)

    if not trades:
        table.add_row("[dim]no completed trades yet[/]", "", "", "", "", "", "")
    else:
        for sym, ep, xp, pnl, pnl_pct, days, reason in trades:
            color = "green" if (pnl or 0) >= 0 else "red"
            sign  = "+" if (pnl or 0) >= 0 else ""
            reason_short = (reason or "")[:20]
            table.add_row(
                sym,
                f"${ep:.2f}" if ep else "—",
                f"${xp:.2f}" if xp else "—",
                f"[{color}]{sign}${pnl:,.2f}[/]" if pnl is not None else "—",
                f"[{color}]{(pnl_pct or 0)*100:+.2f}%[/]",
                str(days or 0),
                f"[dim]{reason_short}[/]"
            )

    return Panel(table, title="[blue]Recent Closed Trades[/]", border_style="blue")


def build_ticker_breakdown(rows) -> Panel:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold magenta")
    table.add_column("Ticker", style="bold white", width=7)
    table.add_column("Trades", justify="center", width=7)
    table.add_column("Wins", justify="center", width=6)
    table.add_column("Win%", justify="right", width=7)
    table.add_column("PnL $", justify="right", width=11)

    if not rows:
        table.add_row("[dim]no data yet[/]", "", "", "", "")
    else:
        for sym, trades, wins, pnl in rows:
            wr = wins / trades if trades else 0
            wr_color = "green" if wr >= 0.55 else "yellow" if wr >= 0.45 else "red"
            pnl_color = "green" if (pnl or 0) >= 0 else "red"
            table.add_row(
                sym,
                str(trades),
                str(wins),
                f"[{wr_color}]{wr:.0%}[/]",
                f"[{pnl_color}]{'+' if (pnl or 0) >= 0 else ''}${pnl:,.2f}[/]" if pnl is not None else "—"
            )

    return Panel(table, title="[magenta]Per-Ticker Breakdown[/]", border_style="magenta")


def build_exit_reasons(rows) -> Panel:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Exit Reason", width=16)
    table.add_column("Count", justify="right", width=6)

    colors = {
        "Take Profit":  "green",
        "Stop Loss":    "red",
        "Time Exit":    "yellow",
        "News Reversal":"cyan",
    }
    if not rows:
        table.add_row("[dim]no exits yet[/]", "")
    else:
        for reason, count in rows:
            color = colors.get(reason, "white")
            table.add_row(f"[{color}]{reason}[/]", str(count))

    return Panel(table, title="[white]Exit Reasons[/]", border_style="white")


def build_log_tail(lines) -> Panel:
    text = Text()
    for line in lines:
        if "[ERROR]" in line or "[CRITICAL]" in line:
            text.append(line + "\n", style="red")
        elif "[WARNING]" in line:
            text.append(line + "\n", style="yellow")
        elif "ENTERED" in line or "EXITED" in line:
            text.append(line + "\n", style="bold green")
        elif "Kill switch" in line.lower():
            text.append(line + "\n", style="bold red")
        else:
            text.append(line + "\n", style="dim")
    return Panel(text, title="[white]Live Log[/]", border_style="dim white")


def render():
    if not db_ok():
        return Panel(
            "[yellow]Waiting for trades.db — start the bot first:[/]\n\n"
            "  [cyan]python paper_runner.py[/]",
            title="Dashboard", border_style="dim"
        )

    s        = get_summary()
    open_pos = get_open_positions()
    recent   = get_recent_trades(10)
    tickers  = get_ticker_breakdown()
    exits    = get_exit_reasons()
    log_lines= tail_log(8)

    now = datetime.now().strftime("%H:%M:%S")

    layout = Layout()
    layout.split_column(
        Layout(build_header(s), size=5),
        Layout(name="middle"),
        Layout(build_log_tail(log_lines), size=12),
        Layout(
            Panel(f"[dim]Refreshing every {REFRESH_SECONDS}s — last update {now} — Ctrl+C to exit[/]",
                  border_style="dim"),
            size=3
        )
    )
    layout["middle"].split_row(
        Layout(build_open_positions(open_pos), ratio=2),
        Layout(build_recent_trades(recent), ratio=3),
    )

    bottom = Layout()
    bottom.split_row(
        Layout(build_ticker_breakdown(tickers)),
        Layout(build_exit_reasons(exits)),
    )

    layout.split_column(
        Layout(build_header(s), size=5),
        Layout(name="mid"),
        Layout(bottom, size=14),
        Layout(build_log_tail(log_lines), size=11),
        Layout(
            Panel(f"[dim]Refreshing every {REFRESH_SECONDS}s — last update: {now} — Ctrl+C to exit[/]",
                  border_style="dim"),
            size=3
        )
    )
    layout["mid"].split_row(
        Layout(build_open_positions(open_pos), ratio=2),
        Layout(build_recent_trades(recent), ratio=3),
    )

    return layout


def main():
    console = Console()
    console.print(Panel(
        "[cyan]Starting dashboard...[/]\n[dim]Make sure paper_runner.py is running in another terminal.[/]",
        border_style="cyan"
    ))
    time.sleep(1)

    with Live(render(), console=console, refresh_per_second=1, screen=True) as live:
        while True:
            time.sleep(REFRESH_SECONDS)
            live.update(render())


if __name__ == "__main__":
    main()
