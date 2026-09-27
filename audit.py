import trade_logger, config, sqlite3

s = trade_logger.get_summary()
print("=== CURRENT BOT STATE ===")
print(f"  Trades    : {s['total_trades']}")
print(f"  Win rate  : {s['win_rate']:.1%}")
print(f"  Total PnL : ${s['total_pnl']:,.2f}")
print(f"  Avg/trade : {s['avg_pnl_pct']:+.2f}%")

conn = sqlite3.connect("trades.db")
c = conn.cursor()

print("\n=== EXIT BREAKDOWN ===")
c.execute("""
    SELECT exit_reason, COUNT(*),
           ROUND(AVG(pnl_pct)*100,2),
           ROUND(AVG(CASE WHEN pnl>0 THEN pnl_pct END)*100,2),
           ROUND(AVG(CASE WHEN pnl<=0 THEN ABS(pnl_pct) END)*100,2)
    FROM trades WHERE exit_date IS NOT NULL
    GROUP BY exit_reason ORDER BY COUNT(*) DESC
""")
print(f"  {'Exit Reason':<30} {'Count':>6} {'Avg%':>7} {'Win avg':>8} {'Loss avg':>9}")
for row in c.fetchall():
    reason, cnt, avg, win_avg, loss_avg = row
    print(f"  {str(reason):<30} {cnt:>6} {avg:>+7.2f}% {str(win_avg or '-'):>8} {str(loss_avg or '-'):>9}")

print("\n=== PER TICKER BREAKDOWN ===")
c.execute("""
    SELECT symbol,
           COUNT(*) as trades,
           SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
           ROUND(SUM(pnl),2) as total_pnl,
           ROUND(AVG(pnl_pct)*100,2) as avg_pct
    FROM trades WHERE exit_date IS NOT NULL
    GROUP BY symbol ORDER BY SUM(pnl) DESC
""")
print(f"  {'Symbol':<8} {'Trades':>6} {'Wins':>6} {'WinR':>6} {'PnL $':>10} {'Avg%':>7}")
for sym, trades, wins, pnl, avg in c.fetchall():
    wr = wins/trades*100 if trades else 0
    print(f"  {sym:<8} {trades:>6} {wins:>6} {wr:>5.1f}% {pnl:>10,.2f} {avg:>+7.2f}%")

print("\n=== WIN/LOSS SIZING (Hougaard test) ===")
c.execute("SELECT AVG(pnl_pct) FROM trades WHERE pnl>0 AND exit_date IS NOT NULL")
avg_win = (c.fetchone()[0] or 0) * 100
c.execute("SELECT AVG(ABS(pnl_pct)) FROM trades WHERE pnl<=0 AND exit_date IS NOT NULL")
avg_loss = (c.fetchone()[0] or 0) * 100
ratio = avg_win / avg_loss if avg_loss > 0 else 0
print(f"  Avg win  : +{avg_win:.2f}%")
print(f"  Avg loss : -{avg_loss:.2f}%")
print(f"  Ratio    : {ratio:.2f}x  ({'GOOD - wins > losses' if ratio > 1 else 'BAD - losses > wins'})")

conn.close()
