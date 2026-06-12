# ============================================================
#  web_dashboard.py — Flask browser dashboard for trading bot
#  Serves on http://localhost:5000
#  Auto-refreshes every 10 seconds via fetch() + DOM update
# ============================================================

import os
import sqlite3
from flask import Flask, jsonify

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "trades.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "paper_runner.log")
MAX_TRADES = 500


# ── DB helpers ────────────────────────────────────────────────

def db_ok() -> bool:
    return os.path.isfile(DB_PATH)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_summary() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(pnl), AVG(pnl_pct) FROM trades WHERE exit_date IS NOT NULL")
    row = c.fetchone()
    total, total_pnl, avg_pnl_pct = row[0] or 0, row[1] or 0.0, row[2] or 0.0
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0 AND exit_date IS NOT NULL")
    wins = c.fetchone()[0] or 0
    conn.close()
    return {
        "total_trades": total,
        "wins": wins,
        "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_pct": round(avg_pnl_pct * 100, 2),
    }


def fetch_open_positions() -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT symbol, entry_date, entry_price, qty, signal_score, news_sentiment
        FROM trades
        WHERE exit_date IS NULL
        ORDER BY entry_date DESC
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def fetch_recent_trades() -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT symbol, entry_price, exit_price, pnl, pnl_pct, hold_days, exit_reason
        FROM trades
        WHERE exit_date IS NOT NULL
        ORDER BY exit_date DESC
        LIMIT 10
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def fetch_per_ticker() -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT
            symbol,
            COUNT(*) AS trade_count,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
            ROUND(SUM(pnl), 2) AS total_pnl
        FROM trades
        WHERE exit_date IS NOT NULL
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
    "news_reversal": "News Reversal",
    "news reversal": "News Reversal",
    "newsreversal": "News Reversal",
}

_EXIT_REASON_LABELS = ["Take Profit", "Stop Loss", "Time Exit", "News Reversal"]


def fetch_exit_reasons() -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT exit_reason, COUNT(*) AS cnt
        FROM trades
        WHERE exit_date IS NOT NULL
        GROUP BY exit_reason
    """)
    counts = {label: 0 for label in _EXIT_REASON_LABELS}
    for r in c.fetchall():
        raw = (r["exit_reason"] or "").strip().lower()
        label = _EXIT_REASON_MAP.get(raw)
        if label:
            counts[label] += r["cnt"]
        else:
            # best-effort partial match
            for key, mapped in _EXIT_REASON_MAP.items():
                if key in raw:
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


# ── Routes ────────────────────────────────────────────────────

@app.route("/api/data")
def api_data():
    if not db_ok():
        return jsonify({"db_ready": False})

    return jsonify({
        "db_ready": True,
        "summary": fetch_summary(),
        "open_positions": fetch_open_positions(),
        "recent_trades": fetch_recent_trades(),
        "per_ticker": fetch_per_ticker(),
        "exit_reasons": fetch_exit_reasons(),
        "log_tail": fetch_log_tail(15),
        "max_trades": MAX_TRADES,
    })


# ── HTML page ─────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Bot Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #0d1117;
    --card:      #161b22;
    --border:    #30363d;
    --text:      #c9d1d9;
    --muted:     #8b949e;
    --green:     #3fb950;
    --red:       #f85149;
    --yellow:    #e3b341;
    --orange:    #f0883e;
    --blue:      #58a6ff;
    --purple:    #bc8cff;
    --header-bg: #010409;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, monospace;
    font-size: 14px;
    min-height: 100vh;
  }

  /* ── Top nav ── */
  header {
    background: var(--header-bg);
    border-bottom: 1px solid var(--border);
    padding: 0 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    height: 56px;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  header .logo {
    font-size: 16px;
    font-weight: 600;
    color: var(--text);
    letter-spacing: .5px;
  }
  header .logo span { color: var(--green); }
  #refresh-indicator {
    margin-left: auto;
    font-size: 12px;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: .3; }
  }

  /* ── Layout ── */
  main {
    max-width: 1400px;
    margin: 0 auto;
    padding: 24px 20px 48px;
  }

  /* ── Waiting state ── */
  #waiting {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 60vh;
    gap: 16px;
    color: var(--muted);
  }
  #waiting .icon { font-size: 48px; }
  #waiting h2 { font-size: 20px; color: var(--text); }

  /* ── Stat cards ── */
  #stats-bar {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
  }
  .stat-card .label {
    font-size: 12px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .6px;
    margin-bottom: 8px;
  }
  .stat-card .value {
    font-size: 28px;
    font-weight: 700;
    line-height: 1;
  }
  .stat-card .sub { font-size: 12px; color: var(--muted); margin-top: 6px; }

  /* Progress bar */
  .progress-wrap { margin-top: 10px; }
  .progress-track {
    background: var(--border);
    border-radius: 4px;
    height: 6px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    border-radius: 4px;
    background: var(--green);
    transition: width .4s ease;
  }
  .progress-label { font-size: 11px; color: var(--muted); margin-top: 4px; }

  /* ── Section cards ── */
  .section {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 20px;
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
    color: var(--text);
  }
  .badge {
    background: var(--border);
    border-radius: 20px;
    padding: 2px 10px;
    font-size: 12px;
    color: var(--muted);
  }
  .section-body { padding: 0; }

  /* ── Tables ── */
  table {
    width: 100%;
    border-collapse: collapse;
  }
  thead th {
    padding: 10px 16px;
    text-align: left;
    font-size: 12px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .5px;
    border-bottom: 1px solid var(--border);
    font-weight: 500;
    white-space: nowrap;
  }
  tbody tr {
    border-bottom: 1px solid var(--border);
    transition: background .15s;
  }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: rgba(255,255,255,.03); }
  tbody td {
    padding: 10px 16px;
    font-size: 13px;
    white-space: nowrap;
  }
  .empty-row td {
    text-align: center;
    color: var(--muted);
    padding: 32px;
    font-style: italic;
  }

  /* ── Color helpers ── */
  .pos  { color: var(--green); }
  .neg  { color: var(--red); }
  .neu  { color: var(--muted); }
  .sym  { color: var(--blue); font-weight: 600; font-family: monospace; }

  /* ── Two-column row ── */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }
  @media (max-width: 800px) { .two-col { grid-template-columns: 1fr; } }

  /* ── Exit reasons ── */
  .exit-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    padding: 20px;
  }
  .exit-tile {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }
  .exit-tile .cnt { font-size: 32px; font-weight: 700; }
  .exit-tile .lbl { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .exit-tile.tp  .cnt { color: var(--green); }
  .exit-tile.sl  .cnt { color: var(--red); }
  .exit-tile.te  .cnt { color: var(--yellow); }
  .exit-tile.nr  .cnt { color: var(--purple); }

  /* ── Log tail ── */
  .log-body {
    padding: 16px 20px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 12px;
    line-height: 1.7;
    background: var(--bg);
    border-radius: 0 0 8px 8px;
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

  /* ── Footer ── */
  footer {
    text-align: center;
    color: var(--muted);
    font-size: 12px;
    padding: 20px;
  }
</style>
</head>
<body>

<header>
  <div class="logo">&#9654; Trading<span>Bot</span></div>
  <div id="refresh-indicator">
    <div class="dot"></div>
    <span id="last-updated">connecting...</span>
  </div>
</header>

<main>
  <!-- Waiting state -->
  <div id="waiting" style="display:none;">
    <div class="icon">&#9202;</div>
    <h2>Waiting for bot...</h2>
    <p>trades.db not found — the bot hasn't started yet. Checking every 10 seconds.</p>
  </div>

  <!-- Dashboard -->
  <div id="dashboard" style="display:none;">

    <!-- Stats bar -->
    <div id="stats-bar">
      <div class="stat-card">
        <div class="label">Trades Completed</div>
        <div class="value" id="s-trades">—</div>
        <div class="progress-wrap">
          <div class="progress-track"><div class="progress-fill" id="s-progress" style="width:0%"></div></div>
          <div class="progress-label" id="s-progress-label"></div>
        </div>
      </div>
      <div class="stat-card">
        <div class="label">Win Rate</div>
        <div class="value" id="s-winrate">—</div>
        <div class="sub" id="s-winrate-sub"></div>
      </div>
      <div class="stat-card">
        <div class="label">Total PnL</div>
        <div class="value" id="s-pnl">—</div>
      </div>
      <div class="stat-card">
        <div class="label">Avg PnL %</div>
        <div class="value" id="s-avg-pnl">—</div>
      </div>
    </div>

    <!-- Open positions -->
    <div class="section">
      <div class="section-header">
        <div class="section-title">Open Positions</div>
        <div class="badge" id="open-badge">0</div>
      </div>
      <div class="section-body">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Entry Date</th>
              <th>Entry Price</th>
              <th>Qty</th>
              <th>Signal Score</th>
              <th>Sentiment</th>
            </tr>
          </thead>
          <tbody id="open-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Two-col: Recent trades + Per-ticker -->
    <div class="two-col">

      <!-- Recent closed trades -->
      <div class="section">
        <div class="section-header">
          <div class="section-title">Recent Closed Trades</div>
          <div class="badge">last 10</div>
        </div>
        <div class="section-body">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Entry $</th>
                <th>Exit $</th>
                <th>PnL $</th>
                <th>PnL %</th>
                <th>Days</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody id="recent-tbody"></tbody>
          </table>
        </div>
      </div>

      <!-- Per-ticker breakdown -->
      <div class="section">
        <div class="section-header">
          <div class="section-title">Per-Ticker Breakdown</div>
          <div class="badge" id="ticker-badge">0</div>
        </div>
        <div class="section-body">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Trades</th>
                <th>Wins</th>
                <th>Win %</th>
                <th>Total PnL</th>
              </tr>
            </thead>
            <tbody id="ticker-tbody"></tbody>
          </table>
        </div>
      </div>

    </div><!-- /two-col -->

    <!-- Exit reasons -->
    <div class="section">
      <div class="section-header">
        <div class="section-title">Exit Reasons</div>
      </div>
      <div class="exit-grid">
        <div class="exit-tile tp">
          <div class="cnt" id="er-tp">0</div>
          <div class="lbl">Take Profit</div>
        </div>
        <div class="exit-tile sl">
          <div class="cnt" id="er-sl">0</div>
          <div class="lbl">Stop Loss</div>
        </div>
        <div class="exit-tile te">
          <div class="cnt" id="er-te">0</div>
          <div class="lbl">Time Exit</div>
        </div>
        <div class="exit-tile nr">
          <div class="cnt" id="er-nr">0</div>
          <div class="lbl">News Reversal</div>
        </div>
      </div>
    </div>

    <!-- Live log tail -->
    <div class="section">
      <div class="section-header">
        <div class="section-title">Live Log</div>
        <div class="badge">last 15 lines</div>
      </div>
      <div class="log-body" id="log-body"></div>
    </div>

  </div><!-- /dashboard -->
</main>

<footer>Auto-refreshes every 10 s &middot; Trading Bot Dashboard</footer>

<script>
  const $ = id => document.getElementById(id);

  function pnlClass(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : 'neu'; }
  function fmt$(v)      { return (v >= 0 ? '+$' : '-$') + Math.abs(v).toFixed(2); }
  function fmtPct(v)    { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }

  function renderStats(s, maxTrades) {
    $('s-trades').textContent = s.total_trades + ' / ' + maxTrades;
    $('s-trades').className   = '';

    const pct = Math.min(s.total_trades / maxTrades * 100, 100);
    $('s-progress').style.width = pct + '%';
    $('s-progress-label').textContent = pct.toFixed(1) + '% of target';

    const wr = $('s-winrate');
    wr.textContent  = s.win_rate + '%';
    wr.className    = 'value ' + (s.win_rate >= 50 ? 'pos' : 'neg');
    $('s-winrate-sub').textContent = s.wins + ' wins / ' + (s.total_trades - s.wins) + ' losses';

    const pnlEl = $('s-pnl');
    pnlEl.textContent = fmt$(s.total_pnl);
    pnlEl.className   = 'value ' + pnlClass(s.total_pnl);

    const avgEl = $('s-avg-pnl');
    avgEl.textContent = fmtPct(s.avg_pnl_pct);
    avgEl.className   = 'value ' + pnlClass(s.avg_pnl_pct);
  }

  function renderOpenPositions(rows) {
    $('open-badge').textContent = rows.length;
    const tb = $('open-tbody');
    if (rows.length === 0) {
      tb.innerHTML = '<tr class="empty-row"><td colspan="6">No open positions</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(r => `
      <tr>
        <td class="sym">${esc(r.symbol)}</td>
        <td>${esc(r.entry_date ? r.entry_date.slice(0,16).replace('T',' ') : '—')}</td>
        <td>$${(r.entry_price||0).toFixed(2)}</td>
        <td>${(r.qty||0).toFixed(4)}</td>
        <td>${r.signal_score ?? '—'}</td>
        <td>${esc(r.news_sentiment||'—')}</td>
      </tr>`).join('');
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
      <tr>
        <td class="sym">${esc(r.symbol)}</td>
        <td>$${(r.entry_price||0).toFixed(2)}</td>
        <td>$${(r.exit_price||0).toFixed(2)}</td>
        <td class="${pc}">${fmt$(r.pnl||0)}</td>
        <td class="${pc}">${fmtPct((r.pnl_pct||0)*100)}</td>
        <td>${r.hold_days ?? '—'}</td>
        <td>${esc(r.exit_reason||'—')}</td>
      </tr>`;
    }).join('');
  }

  function renderPerTicker(rows) {
    $('ticker-badge').textContent = rows.length;
    const tb = $('ticker-tbody');
    if (rows.length === 0) {
      tb.innerHTML = '<tr class="empty-row"><td colspan="5">No data</td></tr>';
      return;
    }
    tb.innerHTML = rows.map(r => `
      <tr>
        <td class="sym">${esc(r.symbol)}</td>
        <td>${r.trade_count}</td>
        <td>${r.wins}</td>
        <td class="${r.win_pct >= 50 ? 'pos' : 'neg'}">${r.win_pct}%</td>
        <td class="${pnlClass(r.total_pnl)}">${fmt$(r.total_pnl)}</td>
      </tr>`).join('');
  }

  function renderExitReasons(er) {
    $('er-tp').textContent = er['Take Profit']  || 0;
    $('er-sl').textContent = er['Stop Loss']    || 0;
    $('er-te').textContent = er['Time Exit']    || 0;
    $('er-nr').textContent = er['News Reversal']|| 0;
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

  function esc(s) {
    return String(s)
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;');
  }

  function setLastUpdated() {
    const now = new Date();
    $('last-updated').textContent = 'Updated ' + now.toLocaleTimeString();
  }

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

      renderStats(data.summary, data.max_trades);
      renderOpenPositions(data.open_positions);
      renderRecentTrades(data.recent_trades);
      renderPerTicker(data.per_ticker);
      renderExitReasons(data.exit_reasons);
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
def index():
    return HTML


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
