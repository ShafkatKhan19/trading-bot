# ============================================================
#  andy.py — "Andy, the co-founder": the bot's desk supervisor.
#
#  Runs beside daily_runner.py (launched by start_bot.ps1) and does what a
#  desk head does around an automated book:
#    09:00 ET  pre-market brief: broker, data, runner health, today's plan
#    every 5m  health checks: runner/dashboard alive, books reconcile with
#              the broker, today's run happened, log errors, fill costs
#    16:10 ET  close report: fills, book equity, issues, Andy's take
#
#  Authority (deliberately limited, like a desk's risk function):
#    - MAY pause new orders (data/andy/HALT) on a critical fault, and
#      raise escalations for the owner on the dashboard.
#    - MAY NOT change strategy rules, sizing, capital or trading mode, or
#      close positions. Pre-registered rules only change through a new
#      pre-registration; anything like that is escalated, never applied.
#
#    python andy.py            # loop (what the watchdog runs)
#    python andy.py --once     # one pass, for testing
# ============================================================

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

import pandas as pd

import config

os.chdir(os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo("America/New_York")

BOOK_DIR   = os.path.join("data", "books")
ANDY_DIR   = os.path.join("data", "andy")
REPORT_DIR = os.path.join(ANDY_DIR, "reports")
STATUS     = os.path.join(ANDY_DIR, "status.json")
ESCALATIONS = os.path.join(ANDY_DIR, "escalations.json")
HALT       = os.path.join(ANDY_DIR, "HALT")
HEARTBEAT  = os.path.join(ANDY_DIR, "runner_heartbeat")
RUNNER_LOG = os.path.join("logs", "daily_runner.log")

CHECK_EVERY      = 300            # seconds
BRIEF_AT, CLOSE_AT = dtime(9, 0), dtime(16, 10)
RUN_DEADLINE     = dtime(9, 50)   # runner fires at 09:35; this late means it missed
HEARTBEAT_MAX    = 300            # seconds without a runner heartbeat
MAX_FILL_COST_BPS = 25.0          # SPY-type fills should cost ~1 bps
QTY_TOL          = 1e-3           # shares
INDEX_DD_ALERT   = 0.15           # index book drawdown that the owner should hear about
H5_EVAL_DATE     = date(2027, 3, 31)

os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] andy: %(message)s",
                    handlers=[logging.FileHandler(os.path.join("logs", "andy.log"), encoding="utf-8"),
                              logging.StreamHandler()])
log = logging.getLogger("andy")


# ── small io helpers ──────────────────────────────────────────
def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    os.replace(tmp, path)


def load_books() -> dict:
    out = {}
    for name in config.DAILY_BOOKS:
        b = _read_json(os.path.join(BOOK_DIR, f"{name}.json"), None)
        if b:
            out[name] = b
    return out


def read_csv(path) -> pd.DataFrame:
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


# ── escalations: things the owner decides ─────────────────────
def escalate(key: str, level: str, message: str, ask: str):
    """Open (or refresh) an escalation. key dedupes repeats of the same issue."""
    esc = _read_json(ESCALATIONS, [])
    now = datetime.now(ET).isoformat(timespec="seconds")
    cutoff = (datetime.now(ET) - timedelta(days=30)).isoformat(timespec="seconds")
    esc = [e for e in esc if e["status"] != "acknowledged" or e["last_seen"] >= cutoff]
    for e in esc:
        if e["key"] == key and e["status"] in ("open", "cleared"):
            e.update(last_seen=now, message=message, status="open", level=level)
            e["count"] += 1
            break
    else:
        esc.append({"id": f"{key}-{int(time.time())}", "key": key, "level": level,
                    "message": message, "ask": ask, "first_seen": now, "last_seen": now,
                    "count": 1, "status": "open"})
        log.warning(f"ESCALATION [{level}] {message}")
    _write_json(ESCALATIONS, esc)


def clear(key: str):
    """Condition gone: mark cleared (the owner still sees it until acknowledged)."""
    esc = _read_json(ESCALATIONS, [])
    changed = False
    for e in esc:
        if e["key"] == key and e["status"] == "open":
            e["status"], changed = "cleared", True
    if changed:
        _write_json(ESCALATIONS, esc)


def halt(reason: str):
    if not os.path.exists(HALT):
        _write_json(HALT, {"since": datetime.now(ET).isoformat(timespec="seconds"), "reason": reason})
        log.error(f"HALT — new orders paused: {reason}")


# ── checks ────────────────────────────────────────────────────
class Desk:
    def __init__(self):
        from alpaca_client import AlpacaClient
        self.client = AlpacaClient()
        self.mismatch_streak = 0

    # each check returns (name, level, detail); level ok | warn | critical
    def broker(self):
        try:
            a = self.client.trading.get_account()
        except Exception as e:
            escalate("broker_down", "critical", f"Can't reach the Alpaca account: {e}",
                     "Check the API keys in .env and Alpaca's status page.")
            return ("Broker", "critical", "unreachable"), None
        clear("broker_down")
        if a.trading_blocked or a.account_blocked:
            halt("broker reports the account or trading is blocked")
            escalate("account_blocked", "critical", "Alpaca reports the account/trading as BLOCKED.",
                     "Log in to Alpaca to see why; resume on the dashboard once fixed.")
            return ("Broker", "critical", "blocked"), a
        clear("account_blocked")
        if getattr(a, "pattern_day_trader", None):
            escalate("pdt", "warn", "Alpaca has flagged the account as a pattern day trader.",
                     "Under $25k equity a PDT-flagged margin account is restricted; decide whether to contact Alpaca.")
        dtc = getattr(a, "daytrade_count", None)
        detail = f"{a.status.value if hasattr(a.status, 'value') else a.status}"
        if dtc is not None:
            detail += f" · day trades (5d) {dtc}"
            if int(dtc) >= 3:
                escalate("daytrades", "warn", f"{dtc} day trades in the last 5 sessions.",
                         "A 4th would trigger PDT rules on a small margin account.")
        return ("Broker", "ok", detail), a

    def runner(self):
        try:
            age = time.time() - os.path.getmtime(HEARTBEAT)
        except OSError:
            age = None
        if age is None or age > HEARTBEAT_MAX:
            escalate("runner_dead", "critical",
                     f"daily_runner.py heartbeat is {'missing' if age is None else f'{age / 60:.0f} min old'}.",
                     "The watchdog should restart it; if this persists, check logs/daily_runner_console.log.")
            return ("Runner", "critical", "no heartbeat")
        clear("runner_dead")
        return ("Runner", "ok", f"heartbeat {age:.0f}s ago")

    def dashboard(self):
        try:
            urllib.request.urlopen("http://127.0.0.1:5000/", timeout=5)
            up = True
        except urllib.error.HTTPError:          # 401 = up and asking for a password
            up = True
        except Exception:
            up = False
        if not up:
            escalate("dashboard_down", "warn", "The dashboard isn't responding on port 5000.",
                     "The watchdog should restart it within a minute.")
            return ("Dashboard", "warn", "down")
        clear("dashboard_down")
        return ("Dashboard", "ok", "up")

    def reconcile(self, books):
        """Books' shares per symbol must equal the broker's positions."""
        want = {}
        for b in books.values():
            for s, p in b["positions"].items():
                want[s] = want.get(s, 0.0) + p["qty"]
        try:
            have = {p.symbol: float(p.qty) for p in self.client.trading.get_all_positions()}
        except Exception as e:
            return ("Reconciliation", "warn", f"positions unavailable: {e}")
        diffs = {s: (want.get(s, 0.0), have.get(s, 0.0)) for s in set(want) | set(have)
                 if abs(want.get(s, 0.0) - have.get(s, 0.0)) > QTY_TOL}
        if not diffs:
            self.mismatch_streak = 0
            clear("reconcile")
            return ("Reconciliation", "ok", f"{len(want)} symbol(s) match the broker")
        self.mismatch_streak += 1
        text = "; ".join(f"{s}: books {w:g} vs broker {h:g}" for s, (w, h) in sorted(diffs.items()))
        if self.mismatch_streak >= 2:            # one check can land mid-order; two can't
            halt(f"books and broker disagree: {text}")
            escalate("reconcile", "critical", f"Books and broker disagree — {text}.",
                     "Find the cause (manual trade? failed save?) and fix the ledger before resuming.")
            return ("Reconciliation", "critical", text)
        return ("Reconciliation", "warn", f"{text} (re-checking)")

    def todays_run(self, books, session_today: bool):
        now = datetime.now(ET)
        if not session_today or now.time() < RUN_DEADLINE or now.time() > dtime(16, 0):
            return ("Today's run", "ok", "not due" if now.time() < RUN_DEADLINE else "—")
        if os.path.exists(HALT):
            return ("Today's run", "warn", "paused by HALT")
        done = [n for n in config.DAILY_BOOKS if books.get(n, {}).get("last_run") == now.date().isoformat()]
        if len(done) < len(config.DAILY_BOOKS):
            missing = sorted(set(config.DAILY_BOOKS) - set(done))
            escalate("missed_run", "critical", f"It's past {RUN_DEADLINE:%H:%M} and book(s) {missing} haven't run today.",
                     "Check logs/daily_runner.log for the error.")
            return ("Today's run", "critical", f"missing {missing}")
        clear("missed_run")
        return ("Today's run", "ok", f"all {len(done)} books ran")

    def log_errors(self):
        today = datetime.now(ET).date().isoformat()
        try:
            with open(RUNNER_LOG, encoding="utf-8", errors="replace") as f:
                errs = [l.strip() for l in f if l.startswith(today) and "[ERROR]" in l]
        except OSError:
            errs = []
        if errs:
            escalate("log_errors", "warn", f"{len(errs)} error(s) in today's runner log. Last: {errs[-1][:200]}",
                     "Usually transient (the runner retries); look if it repeats.")
            return ("Runner errors", "warn", f"{len(errs)} today")
        return ("Runner errors", "ok", "none today")

    def fill_costs(self):
        f = read_csv(os.path.join(BOOK_DIR, "fills.csv"))
        if f.empty:
            return ("Fill costs", "ok", "no fills yet")
        today = f[f["time"].astype(str).str.startswith(datetime.now(ET).date().isoformat())]
        bad = today[today["cost_bps"] > MAX_FILL_COST_BPS]
        if len(bad):
            escalate("fill_cost", "warn",
                     "Expensive fill(s) today: " + "; ".join(f"{r.book} {r.side} {r.symbol} {r.cost_bps:.1f} bps"
                                                             for r in bad.itertuples()),
                     "Worth a look: the backtests assume 5 bps per side.")
            return ("Fill costs", "warn", f"{len(bad)} over {MAX_FILL_COST_BPS:g} bps")
        avg = f["cost_bps"].mean()
        return ("Fill costs", "ok", f"avg {avg:.1f} bps over {len(f)} fills")

    def index_drawdown(self):
        eq = read_csv(os.path.join(BOOK_DIR, "equity_log.csv"))
        if eq.empty or "index_equity" not in eq:
            return None
        s = eq["index_equity"].dropna()
        if s.empty:
            return None
        dd = 1 - s.iloc[-1] / s.cummax().iloc[-1]
        if dd >= INDEX_DD_ALERT:
            escalate("index_dd", "warn", f"The index book is {dd:.0%} below its peak.",
                     "The plan is to hold through drawdowns. Only you can decide to change that.")
        return dd

    # ── valuation ──
    def book_values(self, books):
        out = {}
        for n, b in books.items():
            eq = b["cash"]
            for s, p in b["positions"].items():
                px = self.client.get_latest_price(s) or p["entry_price"]
                eq += p["qty"] * px
            out[n] = {"equity": round(eq, 2), "return": round(eq / b["deposited"] - 1, 4),
                      "cash": round(b["cash"], 2), "positions": sorted(b["positions"])}
        return out

    def session_today(self) -> tuple[bool, str]:
        from alpaca.trading.requests import GetCalendarRequest
        today = datetime.now(ET).date()
        try:
            cal = self.client.trading.get_calendar(GetCalendarRequest(start=today, end=today))
        except Exception as e:           # broker() reports the outage; don't abort the pass
            log.warning(f"calendar unavailable: {e}")
            return False, "unknown (calendar API error)"
        if cal and cal[0].date == today:
            return True, f"{cal[0].open.strftime('%H:%M')}-{cal[0].close.strftime('%H:%M')}"
        return False, "market closed today"

    # ── passes ──
    def check(self) -> dict:
        books = load_books()
        broker, _ = self.broker()          # first: it escalates an API outage
        session, hours = self.session_today()
        checks = [broker, self.runner(), self.dashboard(), self.reconcile(books),
                  self.todays_run(books, session), self.log_errors(), self.fill_costs()]
        self.index_drawdown()
        status = {"time": datetime.now(ET).isoformat(timespec="seconds"), "session": hours,
                  "mode": config.TRADING_MODE, "halted": _read_json(HALT, None) if os.path.exists(HALT) else None,
                  "checks": [{"name": n, "level": l, "detail": d} for n, l, d in checks]}
        _write_json(STATUS, status)
        return status

    def brief(self, status) -> dict:
        """Pre-market: is everything ready, and what will the runner do at 09:35."""
        books = load_books()
        plan = []
        idx = books.get("index")
        if idx is None:
            plan.append(f"index: first run — invest ${config.ACCOUNT_CAPITAL:,.0f} in {config.INDEX_SYMBOL}.")
        elif idx["cash"] >= 1:
            plan.append(f"index: invest ${idx['cash']:,.2f} idle cash in {config.INDEX_SYMBOL}.")
        else:
            plan.append(f"index: fully invested, nothing to do — holding is the job.")
        h5 = books.get("h5")
        if h5:
            due = [s for s, p in h5["positions"].items()
                   if len(pd.bdate_range(p["entry_date"], datetime.now(ET).date())) - 1 >= 10]
            plan.append(f"h5 (paper): {len(h5['positions'])} open; ~{len(due)} due to exit; "
                        f"new upgrade headlines through 09:30 get bought.")
        else:
            plan.append("h5 (paper): first run — buys any upgrade headlines since the last session.")
        plan.append("h1 (paper): RSI(2) rules decide at 09:35 from yesterday's close.")
        bad = [c for c in status["checks"] if c["level"] != "ok"]
        headline = ("All systems go." if not bad else
                    f"{len(bad)} thing(s) need a look before the bell: " + ", ".join(c["name"] for c in bad) + ".")
        if status["halted"]:
            headline = "Trading is PAUSED (HALT) — nothing trades at 09:35 until you resume it on the dashboard."
        return {"time": status["time"], "headline": headline, "plan": plan, "checks": status["checks"]}

    def close(self, status) -> dict:
        """End of day: what happened, what it's worth, anything for the owner."""
        books = load_books()
        today = datetime.now(ET).date().isoformat()
        fills = read_csv(os.path.join(BOOK_DIR, "fills.csv"))
        fills = fills[fills["time"].astype(str).str.startswith(today)] if not fills.empty else fills
        vals = self.book_values(books)
        lines = [f"{r.book}: {r.side} {r.symbol} x{r.qty:g} @ ${r.fill:,.2f} ({r.cost_bps:+.1f} bps)"
                 for r in fills.itertuples()] if len(fills) else ["No fills today."]
        ev = read_csv(os.path.join(BOOK_DIR, "h5_events.csv"))
        n_ev = int((ev["entry_date"] == today).sum()) if not ev.empty else 0
        esc_open = [e for e in _read_json(ESCALATIONS, []) if e["status"] == "open"]
        take = []
        if "index" in vals:
            take.append(f"Index book {vals['index']['return']:+.2%} since start. That's the market, "
                        f"not skill — and it's the thing nine tested strategies failed to beat.")
        if "h5" in vals:
            take.append(f"H5 paper saw {n_ev} upgrade event(s) today. No verdict until "
                        f"{H5_EVAL_DATE:%Y-%m-%d} — I don't grade it early and neither should you.")
        take.append("Nothing needs you tonight." if not esc_open else
                    f"{len(esc_open)} item(s) waiting for your call on the dashboard.")
        return {"time": status["time"], "fills": lines, "books": vals, "take": take,
                "checks": status["checks"]}


def report_path(d: date) -> str:
    return os.path.join(REPORT_DIR, f"{d.isoformat()}.json")


def main(once: bool = False):
    log.info(f"Andy on the desk | mode={config.TRADING_MODE} | books={config.DAILY_BOOKS}")
    desk = Desk()
    while True:
        try:
            status = desk.check()
            now = datetime.now(ET)
            session = not status["session"].startswith("market closed")
            rep = _read_json(report_path(now.date()), {"date": now.date().isoformat()})
            if session and now.time() >= BRIEF_AT and "morning" not in rep:
                rep["morning"] = desk.brief(status)
                _write_json(report_path(now.date()), rep)
                log.info(f"Morning brief: {rep['morning']['headline']}")
            if session and now.time() >= CLOSE_AT and "close" not in rep:
                rep["close"] = desk.close(status)
                _write_json(report_path(now.date()), rep)
                log.info("Close report written")
        except Exception as e:
            log.error(f"Andy's pass failed: {e}", exc_info=True)
        if once:
            return
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main(once="--once" in sys.argv)
