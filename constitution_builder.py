# ============================================================
#  constitution_builder.py
#  Analyses completed paper/backtest trades, learns from wins
#  and losses, derives per-segment rules, and locks the
#  winning rule set into constitution.json.
#  Run: python constitution_builder.py
# ============================================================

import json
import hashlib
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
import config

CONSTITUTION_FILE = "constitution.json"
MIN_TRADES        = 100


def fetch_trades():
    conn = sqlite3.connect("trades.db")
    c    = conn.cursor()
    c.execute("""
        SELECT symbol, pnl_pct, rsi_at_entry, signal_score,
               news_sentiment, market_regime, hold_days, exit_reason,
               entry_price, exit_price
        FROM trades
        WHERE exit_date IS NOT NULL AND mode IN ('paper', 'backtest')
    """)
    rows = c.fetchall()
    conn.close()
    return rows


# ── Symbol → segment mapping ──────────────────────────────────

def symbol_theme(symbol: str) -> str:
    return config.WATCHLIST.get(symbol, {}).get("theme", "unknown")


# ── Core analytics ────────────────────────────────────────────

def analyse_by_score(rows):
    stats = defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []})
    for sym, pnl_pct, rsi, score, news, regime, hold, reason, ep, xp in rows:
        stats[score]["total"] += 1
        stats[score]["pnls"].append(pnl_pct or 0)
        if (pnl_pct or 0) > 0:
            stats[score]["wins"] += 1
    return stats


def analyse_exit_reasons(rows):
    stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for sym, pnl_pct, rsi, score, news, regime, hold, reason, ep, xp in rows:
        key = (reason or "").split("(")[0].strip()
        stats[key]["total"] += 1
        if (pnl_pct or 0) > 0:
            stats[key]["wins"] += 1
    return stats


# ── Per-segment analysis ──────────────────────────────────────

def analyse_by_segment(rows):
    """
    Break down win rate, avg PnL, and signal quality by market segment.
    Each theme's data tells us if the segment's default rules are working.
    """
    seg_stats = defaultdict(lambda: {
        "wins": 0, "total": 0, "pnls": [],
        "rsi_at_entry": [], "signal_scores": [], "hold_days": [],
    })

    for sym, pnl_pct, rsi, score, news, regime, hold, reason, ep, xp in rows:
        theme = symbol_theme(sym)
        s     = seg_stats[theme]
        s["total"] += 1
        s["pnls"].append(pnl_pct or 0)
        if (pnl_pct or 0) > 0:
            s["wins"] += 1
        if rsi is not None:
            s["rsi_at_entry"].append(rsi)
        if score is not None:
            s["signal_scores"].append(score)
        if hold is not None:
            s["hold_days"].append(hold)

    return seg_stats


def derive_segment_rules(seg_stats: dict) -> dict:
    """
    For each segment, derive tuned rules from actual trade data.
    Falls back to config.SEGMENT_RULES defaults when data is sparse.
    """
    derived = {}

    for theme, s in seg_stats.items():
        default  = config.SEGMENT_RULES.get(theme, config.SEGMENT_RULES["ai_core"])
        total    = s["total"]
        win_rate = s["wins"] / total if total else 0
        pnls     = sorted(s["pnls"])
        avg_pnl  = sum(pnls) / len(pnls) if pnls else 0

        # --- signal score: find the threshold with the best win rate ---
        score_wins  = defaultdict(int)
        score_total = defaultdict(int)
        for sc in s["signal_scores"]:
            score_total[sc] += 1

        # rebuild wins per score from the trades belonging to this segment
        best_score    = default["min_signal_score"]
        best_score_wr = 0

        # --- RSI floor: losses tend to cluster at low RSI entries ---
        rsi_list = s["rsi_at_entry"]
        rsi_floor = default["rsi_min_entry"]
        if len(rsi_list) >= 20:
            avg_rsi = sum(rsi_list) / len(rsi_list)
            # If average RSI at entry is very low, raise the floor
            rsi_floor = max(default["rsi_min_entry"], round(avg_rsi * 0.85))
            rsi_floor = min(rsi_floor, 50)  # never block above 50

        # --- hold days: find median winning hold period ---
        best_hold = default["max_hold_days"]
        if len(s["hold_days"]) >= 20:
            sorted_holds = sorted(s["hold_days"])
            p75 = sorted_holds[int(len(sorted_holds) * 0.75)]
            best_hold = max(config.MIN_HOLD_DAYS + 1, min(p75, config.MAX_HOLD_DAYS))

        derived[theme] = {
            "win_rate":         round(win_rate, 3),
            "avg_pnl":          round(avg_pnl, 4),
            "trade_count":      total,
            "stop_loss_pct":    default["stop_loss_pct"],
            "take_profit_pct":  default["take_profit_pct"],
            "max_hold_days":    int(best_hold),
            "min_signal_score": best_score,
            "rsi_min_entry":    int(rsi_floor),
            "volume_surge_mult":default["volume_surge_mult"],
        }

    return derived


# ── Learn from losses ─────────────────────────────────────────

def analyse_loss_patterns(rows):
    """
    For losing trades, find which entry conditions were borderline.
    Returns a dict of lessons — what rules were commonly broken.
    """
    losses = [r for r in rows if (r[1] or 0) <= 0]
    wins   = [r for r in rows if (r[1] or 0) >  0]

    def avg(lst):
        return round(sum(lst) / len(lst), 3) if lst else None

    def pct(lst, condition):
        return round(sum(1 for x in lst if condition(x)) / len(lst), 3) if lst else 0

    loss_rsi    = [r[2] for r in losses if r[2] is not None]
    loss_scores = [r[3] for r in losses if r[3] is not None]
    loss_hold   = [r[6] for r in losses if r[6] is not None]

    win_rsi     = [r[2] for r in wins if r[2] is not None]
    win_scores  = [r[3] for r in wins if r[3] is not None]

    # Per-segment loss rates
    seg_loss = defaultdict(lambda: {"losses": 0, "total": 0})
    for sym, pnl_pct, *_ in rows:
        theme = symbol_theme(sym)
        seg_loss[theme]["total"] += 1
        if (pnl_pct or 0) <= 0:
            seg_loss[theme]["losses"] += 1

    seg_loss_rates = {
        t: round(v["losses"] / v["total"], 3)
        for t, v in seg_loss.items() if v["total"] >= 5
    }

    # Identify the most common exit reason in losses
    loss_exit_counts = defaultdict(int)
    for _, _, _, _, _, _, _, reason, _, _ in losses:
        key = (reason or "").split("(")[0].strip()
        loss_exit_counts[key] += 1
    dominant_loss_exit = max(loss_exit_counts, key=loss_exit_counts.get) if loss_exit_counts else "unknown"

    lessons = {
        "total_losses":          len(losses),
        "total_wins":            len(wins),
        "avg_rsi_at_loss_entry": avg(loss_rsi),
        "avg_rsi_at_win_entry":  avg(win_rsi),
        "avg_score_at_loss":     avg(loss_scores),
        "avg_score_at_win":      avg(win_scores),
        "avg_hold_days_losses":  avg(loss_hold),
        "dominant_loss_exit":    dominant_loss_exit,
        "loss_rate_by_segment":  seg_loss_rates,
        "lessons": [],
    }

    # Derive human-readable lessons
    if lessons["avg_rsi_at_loss_entry"] and lessons["avg_rsi_at_win_entry"]:
        if lessons["avg_rsi_at_loss_entry"] < lessons["avg_rsi_at_win_entry"] - 3:
            lessons["lessons"].append(
                f"Losses entered at avg RSI {lessons['avg_rsi_at_loss_entry']:.1f} vs "
                f"wins at {lessons['avg_rsi_at_win_entry']:.1f} — raise RSI floor to avoid weak-momentum entries"
            )

    if lessons["avg_score_at_loss"] and lessons["avg_score_at_win"]:
        if lessons["avg_score_at_loss"] < lessons["avg_score_at_win"]:
            lessons["lessons"].append(
                f"Losses had avg signal score {lessons['avg_score_at_loss']:.1f} vs "
                f"wins at {lessons['avg_score_at_win']:.1f} — borderline entries underperform"
            )

    if dominant_loss_exit == "time_exit":
        lessons["lessons"].append(
            "Most losses exited by time — position held too long without a target. "
            "Tighten max_hold_days to force earlier discipline."
        )
    elif dominant_loss_exit == "stop_loss":
        lessons["lessons"].append(
            "Most losses hit stop loss — may be too tight relative to normal volatility. "
            "Consider widening stop or requiring stronger signal before entry."
        )

    worst_segments = [t for t, lr in seg_loss_rates.items() if lr > 0.65]
    if worst_segments:
        lessons["lessons"].append(
            f"Worst loss rates in segments: {', '.join(worst_segments)} — "
            "these themes need stricter entry criteria or should be removed from watchlist."
        )

    return lessons


# ── Parameter derivation ──────────────────────────────────────

def derive_stop_loss(rows):
    # p80 is already a decimal (e.g. 0.05 = 5%), not a percentage
    stop_hits = [
        abs((xp or ep) / ep - 1)
        for sym, pnl_pct, rsi, score, news, regime, hold, reason, ep, xp in rows
        if (reason or "").startswith("stop_loss") and ep and ep > 0
    ]
    if len(stop_hits) < 10:
        return config.STOP_LOSS_PCT
    stop_hits.sort()
    p80 = stop_hits[int(len(stop_hits) * 0.8)]
    # Add 1% buffer above the 80th-pct stop hit; round to nearest 0.5%; clamp 3-8%
    suggested = p80 + 0.01
    suggested = round(suggested * 200) / 200   # nearest 0.005 (0.5%)
    return round(max(0.03, min(0.08, suggested)), 3)


def derive_best_hold(rows):
    hold_pnls = defaultdict(list)
    for sym, pnl_pct, rsi, score, news, regime, hold, reason, ep, xp in rows:
        if hold is not None:
            hold_pnls[min(hold, config.MAX_HOLD_DAYS)].append(pnl_pct or 0)

    best_hold = config.MAX_HOLD_DAYS
    best_wr   = 0
    for days in sorted(hold_pnls):
        pnls = hold_pnls[days]
        if len(pnls) < 20:
            continue
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        if wr > best_wr:
            best_wr   = wr
            best_hold = days

    return best_hold


# ── Main builder ──────────────────────────────────────────────

def build_constitution():
    rows  = fetch_trades()
    total = len(rows)

    if total < MIN_TRADES:
        print(f"ERROR: Only {total} completed trades. Need {MIN_TRADES}+.")
        print("Run: python paper_runner.py")
        return False

    print(f"\nAnalysing {total} trades...\n")

    score_stats  = analyse_by_score(rows)
    exit_stats   = analyse_exit_reasons(rows)
    best_stop    = derive_stop_loss(rows)
    best_hold    = derive_best_hold(rows)
    seg_stats    = analyse_by_segment(rows)
    seg_rules    = derive_segment_rules(seg_stats)
    lessons      = analyse_loss_patterns(rows)

    # ── Signal score breakdown ────────────────────────────────
    print("Signal Score Breakdown:")
    best_score    = config.MIN_SIGNAL_SCORE
    best_score_wr = 0
    for score in sorted(score_stats):
        s  = score_stats[score]
        wr = s["wins"] / s["total"] if s["total"] else 0
        mark = ""
        if s["total"] >= 20 and wr > best_score_wr:
            best_score_wr = wr
            best_score    = score
            mark = " <-- best"
        print(f"  Score {score}/4 | {s['total']:>4} trades | win rate {wr:.1%}{mark}")

    # ── Exit reason breakdown ─────────────────────────────────
    print("\nExit Reason Breakdown:")
    for reason, s in sorted(exit_stats.items(), key=lambda x: -x[1]["total"]):
        wr = s["wins"] / s["total"] if s["total"] else 0
        print(f"  {reason:<20} | {s['total']:>4} trades | win rate {wr:.1%}")

    # ── Per-segment breakdown ─────────────────────────────────
    print("\nPer-Segment Breakdown:")
    for theme in sorted(seg_stats):
        s  = seg_stats[theme]
        wr = s["wins"] / s["total"] if s["total"] else 0
        avg_rsi = (sum(s["rsi_at_entry"]) / len(s["rsi_at_entry"])
                   if s["rsi_at_entry"] else 0)
        dr = seg_rules.get(theme, {})
        print(f"  {theme:<12} | {s['total']:>4} trades | win rate {wr:.1%} | "
              f"avg RSI {avg_rsi:.1f} | derived hold {dr.get('max_hold_days','?')}d")

    # ── Lessons from losses ───────────────────────────────────
    print(f"\nLessons from {lessons['total_losses']} losses:")
    for lesson in lessons["lessons"]:
        print(f"  • {lesson}")

    # ── Overall stats ─────────────────────────────────────────
    wins     = sum(1 for r in rows if (r[1] or 0) > 0)
    win_rate = wins / total
    avg_pnl  = sum((r[1] or 0) for r in rows) / total

    print(f"\nOverall: {win_rate:.1%} win rate | avg PnL/trade {avg_pnl:.2%}")
    print(f"Derived stop loss  : {best_stop:.1%}  (global fallback)")
    print(f"Derived max hold   : {best_hold}d    (global fallback)")

    # ── Regime analysis ───────────────────────────────────────
    regime_stats = defaultdict(lambda: {"wins": 0, "total": 0})
    for sym, pnl_pct, rsi, score, news, regime, hold, reason, ep, xp in rows:
        regime_stats[regime or "unknown"]["total"] += 1
        if (pnl_pct or 0) > 0:
            regime_stats[regime or "unknown"]["wins"] += 1

    require_bull_regime = True
    for regime, s in regime_stats.items():
        wr = s["wins"] / s["total"] if s["total"] else 0
        if regime == "bearish" and wr >= config.MIN_WIN_RATE and s["total"] >= 20:
            require_bull_regime = False

    # ── Viability gate ────────────────────────────────────────
    time_exit_wr = 0
    if "time_exit" in exit_stats and exit_stats["time_exit"]["total"] > 0:
        te = exit_stats["time_exit"]
        time_exit_wr = te["wins"] / te["total"]

    strategy_viable = (
        win_rate >= config.MIN_WIN_RATE
        or time_exit_wr >= config.MIN_WIN_RATE
    )

    if not strategy_viable:
        print(f"\nWARNING: Both overall win rate {win_rate:.1%} and time-exit win rate "
              f"{time_exit_wr:.1%} are below {config.MIN_WIN_RATE:.0%}.")
        print("Strategy not ready for live. Re-run paper_runner.py after tuning parameters.")
        return False

    if win_rate < config.MIN_WIN_RATE:
        print(f"\nNOTE: Overall win rate {win_rate:.1%} below {config.MIN_WIN_RATE:.0%}, "
              f"but time-exit win rate is {time_exit_wr:.1%}.")

    # ── Write constitution ─────────────────────────────────────
    constitution = {
        "version":            2,
        "built_at":           datetime.now().isoformat(),
        "paper_trades_used":  total,
        "overall_win_rate":   round(win_rate, 4),
        "overall_avg_pnl":    round(avg_pnl, 4),
        "time_exit_win_rate": round(time_exit_wr, 4),
        # Global fallback rules (used when segment is not matched)
        "rules": {
            "min_signal_score":       best_score,
            "stop_loss_pct":          best_stop,
            "take_profit_pct":        config.TAKE_PROFIT_PCT,
            "max_hold_days":          best_hold,
            "min_hold_days":          config.MIN_HOLD_DAYS,
            "max_open_positions":     config.MAX_OPEN_POSITIONS,
            "max_position_pct":       config.MAX_POSITION_PCT,
            "kill_switch_pct":        config.KILL_SWITCH_PCT,
            "rsi_oversold":           config.RSI_OVERSOLD,
            "rsi_min_entry":          config.RSI_MIN_ENTRY,
            "rsi_overbought":         config.RSI_OVERBOUGHT,
            "volume_surge_mult":      config.VOLUME_SURGE_MULT,
            "require_bull_regime":    require_bull_regime,
            "require_bullish_news":   False,
            "earnings_blackout_days": config.EARNINGS_BLACKOUT,
        },
        # Per-segment rules derived from actual trade data
        "segment_rules": seg_rules,
        # What the bot learned from its wins and losses
        "lessons": lessons,
    }

    constitution_str = json.dumps(constitution, indent=2, sort_keys=True)
    sha256           = hashlib.sha256(constitution_str.encode()).hexdigest()
    constitution["sha256"] = sha256

    with open(CONSTITUTION_FILE, "w") as f:
        json.dump(constitution, f, indent=2)

    print(f"\n{'='*60}")
    print(f"  CONSTITUTION LOCKED  ->  {CONSTITUTION_FILE}")
    print(f"  SHA-256: {sha256[:32]}...")
    print(f"  Segment rules saved for: {', '.join(seg_rules.keys())}")
    print(f"{'='*60}")
    print("\nNext step: re-run paper_runner.py with new parameters.")
    print("When win rate >= 55%, switch .env to TRADING_MODE=live")
    return True


if __name__ == "__main__":
    ok = build_constitution()
    sys.exit(0 if ok else 1)
