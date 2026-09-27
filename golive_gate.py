"""
golive_gate.py - iTrade go-live readiness gate.

Decides GO / NO-GO for moving a strategy from paper to a real (small) account,
based on the *cost-adjusted* paper record rather than raw P&L.

Feed it a list of closed-trade dicts (see TRADE_SCHEMA). It computes the metrics
that actually matter before risking real money and returns a structured verdict.
Core logic is stdlib-only. The reconciliation helper just needs two {symbol: qty}
dicts (your bot's view and the broker's view).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from statistics import mean, pstdev
from math import sqrt

# ---------------------------------------------------------------------------
# Canonical trade schema - log THIS for every closed round-trip, paper or live.
# Map your existing SQLite columns onto these keys.
# ---------------------------------------------------------------------------
TRADE_SCHEMA = {
    "trade_id":     "unique id",
    "symbol":       "e.g. NVDA",
    "entry_time":   "ISO 8601 string",
    "exit_time":    "ISO 8601 string",
    "qty":          "shares (float)",
    "entry_price":  "ACTUAL fill price in",
    "exit_price":   "ACTUAL fill price out",
    "fees":         "actual fees paid (live); ~0 on Alpaca paper",
    "modeled_cost": "your slippage+spread haircut estimate for THIS trade",
    "signal_reason":"why you entered",
    "exit_reason":  "why you exited",
    "is_paper":     "True if paper, False if live",
}

# ---------------------------------------------------------------------------
# Thresholds - tune these, but tune them BEFORE you look at results.
# ---------------------------------------------------------------------------
@dataclass
class GoLiveConfig:
    # 100, matching validation.Criteria.min_oos_trades. At a ~45-50% win rate,
    # 30 trades cannot tell a real edge from a coin flip. This gate reads the
    # PAPER record; validation.py's out-of-sample backtest verdict is the other
    # half — both must pass before real money.
    min_trades: int = 100
    require_positive_expectancy: bool = True
    max_allowed_drawdown_pct: float = 0.20  # 20% peak-to-trough on paper equity
    starting_equity: float = 500.0          # the real account you're gating toward
    trades_per_year: int = 150              # for a rough annualized Sharpe


def _net_pnl(t: dict) -> float:
    """Realized P&L for one closed trade, net of ACTUAL fees only."""
    gross = (t["exit_price"] - t["entry_price"]) * t["qty"]
    return gross - t.get("fees", 0.0)


def _cost_adjusted_pnl(t: dict) -> float:
    """
    The honest number. Alpaca paper fills are optimistic and fees ~0, so we
    subtract YOUR modeled slippage/spread haircut to approximate reality.
    The go-live decision is built on THIS, not raw paper P&L.
    """
    return _net_pnl(t) - t.get("modeled_cost", 0.0)


def _max_drawdown(equity_curve: list[float]) -> float:
    """Largest peak-to-trough drop as a fraction of the running peak."""
    peak, max_dd = equity_curve[0], 0.0
    for v in equity_curve:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return max_dd


@dataclass
class Readiness:
    n_trades: int
    win_rate: float
    expectancy: float           # mean cost-adjusted $ per trade
    total_cost_adj_pnl: float
    max_drawdown_pct: float
    sharpe: float
    reconciliation_ok: bool | None
    verdict: str = "NO-GO"
    reasons: list = field(default_factory=list)


def evaluate(trades: list[dict],
             cfg: GoLiveConfig = GoLiveConfig(),
             reconciliation_ok: bool | None = None) -> Readiness:
    paper = [t for t in trades if t.get("is_paper", True)]
    n = len(paper)
    if n == 0:
        return Readiness(0, 0, 0, 0, 0, 0, reconciliation_ok,
                         "NO-GO", ["No closed paper trades logged yet."])

    ca = [_cost_adjusted_pnl(t) for t in paper]
    expectancy = mean(ca)
    total = sum(ca)
    win_rate = sum(1 for x in ca if x > 0) / n

    eq = [cfg.starting_equity]
    for x in ca:
        eq.append(eq[-1] + x)
    max_dd = _max_drawdown(eq)

    sd = pstdev(ca) if n > 1 else 0.0
    sharpe = (expectancy / sd * sqrt(cfg.trades_per_year)) if sd > 0 else 0.0

    reasons, ok = [], True
    if n < cfg.min_trades:
        ok = False
        reasons.append(f"Sample too small: {n} trades < {cfg.min_trades} required.")
    if cfg.require_positive_expectancy and expectancy <= 0:
        ok = False
        reasons.append(f"Cost-adjusted expectancy not positive: ${expectancy:.2f}/trade.")
    if max_dd > cfg.max_allowed_drawdown_pct:
        ok = False
        reasons.append(f"Max drawdown {max_dd:.1%} exceeds limit {cfg.max_allowed_drawdown_pct:.0%}.")
    if reconciliation_ok is False:
        ok = False
        reasons.append("Position reconciliation FAILED - bot and broker disagree.")
    if reconciliation_ok is None:
        reasons.append("Reconciliation not checked - run check_reconciliation() before funding.")
    if ok and reconciliation_ok is not False:
        reasons.insert(0, "All gating criteria met on the cost-adjusted paper record.")

    return Readiness(n, win_rate, expectancy, total, max_dd, sharpe,
                     reconciliation_ok,
                     "GO" if ok else "NO-GO", reasons)


def check_reconciliation(bot_positions: dict[str, float],
                         broker_positions: dict[str, float],
                         tol: float = 1e-6) -> bool:
    """
    True only if the bot's holdings match the broker's exactly. This is the
    check that catches duplicate logging and phantom positions BEFORE real
    money is involved. {symbol: qty} on both sides.
    """
    for s in set(bot_positions) | set(broker_positions):
        if abs(bot_positions.get(s, 0.0) - broker_positions.get(s, 0.0)) > tol:
            return False
    return True


def report(r: Readiness) -> str:
    lines = [
        "=" * 54,
        f"  iTrade GO-LIVE GATE:  {r.verdict}",
        "=" * 54,
        f"  Closed paper trades....... {r.n_trades}",
        f"  Win rate.................. {r.win_rate:.1%}",
        f"  Expectancy (cost-adj)..... ${r.expectancy:.2f} / trade",
        f"  Total cost-adj P&L........ ${r.total_cost_adj_pnl:.2f}",
        f"  Max drawdown.............. {r.max_drawdown_pct:.1%}",
        f"  Rough annualized Sharpe... {r.sharpe:.2f}",
        f"  Reconciliation............ {r.reconciliation_ok}",
        "-" * 54,
    ]
    lines += [f"  - {reason}" for reason in r.reasons]
    lines.append("=" * 54)
    return "\n".join(lines)


def load_trades_from_sqlite(db_path: str, modeled_cost_per_trade: float = 0.15) -> list[dict]:
    """
    Maps trade_logger.py's actual `trades` table (entry_date/exit_date/
    entry_price/exit_price/qty/pnl, no fees or cost columns) onto
    TRADE_SCHEMA. Alpaca paper fills carry no commission and no modeled
    slippage, so modeled_cost_per_trade is a flat per-trade haircut applied
    here rather than a column read from the DB.
    """
    import sqlite3
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM trades WHERE exit_date IS NOT NULL").fetchall()
    con.close()
    return [
        {
            "trade_id":      r["id"],
            "symbol":        r["symbol"],
            "entry_time":    r["entry_date"],
            "exit_time":     r["exit_date"],
            "qty":           r["qty"],
            "entry_price":   r["entry_price"],
            "exit_price":    r["exit_price"],
            "fees":          0.0,
            "modeled_cost":  modeled_cost_per_trade,
            "signal_reason": f"signal_score={r['signal_score']}",
            "exit_reason":   r["exit_reason"],
            "is_paper":      (r["mode"] != "live"),
        }
        for r in rows
    ]


if __name__ == "__main__":
    # Demo with synthetic trades so you can run it immediately, then swap in
    # load_trades_from_sqlite(<your N: drive db>).
    pnls = [2, -1, 3, -2, 1.5, 4, -1, -0.5, 2, 1, -1.5, 3, 2, -1, 1, -2,
            2.5, 1, -0.5, 2, 1, -1, 3, -2, 1, 2, -1, 1.5, 2, -1, 1, 2]
    demo = [{"trade_id": i, "symbol": "NVDA", "entry_price": 100,
             "exit_price": 100 + p, "qty": 1, "fees": 0.0,
             "modeled_cost": 0.15, "is_paper": True,
             "signal_reason": "rel-strength breakout", "exit_reason": "target"}
            for i, p in enumerate(pnls)]
    recon = check_reconciliation({"NVDA": 1.0, "AMD": 2.0},
                                 {"NVDA": 1.0, "AMD": 2.0})
    print(report(evaluate(demo, reconciliation_ok=recon)))
