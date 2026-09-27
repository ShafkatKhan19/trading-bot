import sqlite3
from datetime import date

conn = sqlite3.connect('trades.db')
c = conn.cursor()
today = date.today().isoformat()

print("=== TRADES TODAY ===")
c.execute(
    "SELECT symbol, entry_date, exit_date, entry_price, exit_price, pnl_pct, exit_reason, signal_score "
    "FROM trades WHERE entry_date LIKE ? ORDER BY entry_date",
    (today + '%',)
)
trades = c.fetchall()
if trades:
    for t in trades:
        symbol, entry, exit_d, ep, xp, pnl, reason, score = t
        status = "OPEN" if not exit_d else ("WIN" if (pnl or 0) > 0 else "LOSS")
        print(f"  [{status}] {symbol} | entry=${ep} | exit=${xp} | pnl={pnl:.2%} | score={score} | {reason or 'open'}")
else:
    print("  No trades entered today")

print()
print("=== REJECTIONS TODAY ===")
c.execute(
    "SELECT timestamp, symbol, reason, signal_score FROM rejections WHERE timestamp LIKE ? ORDER BY timestamp",
    (today + '%',)
)
rejs = c.fetchall()
if rejs:
    for ts, sym, reason, score in rejs:
        print(f"  {ts[11:19]} {sym:6} score={score} — {reason}")
else:
    print("  No rejections logged today")

print()
print("=== SIGNALS EVALUATED TODAY ===")
c.execute(
    "SELECT timestamp, symbol, rsi, score, action FROM signal_log WHERE timestamp LIKE ? ORDER BY timestamp",
    (today + '%',)
)
sigs = c.fetchall()
if sigs:
    for ts, sym, rsi, score, action in sigs:
        print(f"  {ts[11:19]} {sym:6} RSI={rsi:.1f} score={score} action={action}")
else:
    print("  No signals evaluated today")

conn.close()
