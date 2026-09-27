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


def fetch_trades(db_path: str = "trades.db", until: str | None = None):
    """
    until: fit only on trades entered BEFORE this date (YYYY-MM-DD) — the
    in-sample cut from validation.py. Everything on/after it is out-of-sample
    and must never feed the rules it is later used to judge.
    """
    conn = sqlite3.connect(db_path)
    c    = conn.cursor()
    c.execute("""
        SELECT symbol, pnl_pct, rsi_at_entry, signal_score,
               news_sentiment, market_regime, hold_days, exit_reason,
               entry_price, exit_price
        FROM trades
        WHERE exit_date IS NOT NULL AND mode IN ('paper', 'backtest')
          AND (? IS NULL OR entry_date < ?)
        ORDER BY entry_date, id
    """, (until, until))
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
        "score_outcomes": [],
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
            # Keep score paired with its own outcome — derive_segment_rules
            # needs per-score win rates, which a flat list of scores can't give.
            s["score_outcomes"].append((score, (pnl_pct or 0) > 0))
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
        # Rebuild wins/totals per score from this segment's own trades, then
        # score each candidate threshold T by the win rate of the trades it
        # would still have admitted (score >= T).
        score_wins  = defaultdict(int)
        score_total = defaultdict(int)
        for sc, won in s["score_outcomes"]:
            score_total[sc] += 1
            if won:
                score_wins[sc] += 1

        # A threshold must clear 20 admitted trades before its win rate is
        # trusted — same small-sample guard used for rsi_floor and best_hold
        # below. Candidates are also floored at the config default so a noisy
        # backtest can only ever TIGHTEN entry quality, never loosen it
        # (mirrors how rsi_floor uses max(default, derived)).
        best_score    = default["min_signal_score"]
        best_score_wr = None
        for threshold in sorted(score_total):
            if threshold < default["min_signal_score"]:
                continue
            admitted = [sc for sc in score_total if sc >= threshold]
            n_at = sum(score_total[sc] for sc in admitted)
            if n_at < 20:
                continue
            wr_at = sum(score_wins[sc] for sc in admitted) / n_at
            if best_score_wr is None or wr_at > best_score_wr:
                best_score_wr, best_score = wr_at, threshold

        # best_score_wr is None => every candidate bucket was too thin to
        # trust, so the config default stands. Recorded explicitly so
        # constitution.json shows whether the threshold was derived or defaulted.
        score_derived = best_score_wr is not None

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
            "min_signal_score_source": "derived" if score_derived else "config_default",
            "min_signal_score_win_rate": round(best_score_wr, 3) if score_derived else None,
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


# ── Goodhart's Law warning (Ch.20) ───────────────────────────
# "When a measure becomes a target, it ceases to be a good measure."
# If the bot is mainly winning by holding until time-exit, it may be
# optimizing for patience rather than signal quality.

def check_goodharts_law(exit_stats: dict, win_rate: float) -> dict:
    """
    If >60% of winning trades exit via time_exit, warn that the bot is
    winning by waiting, not by reading momentum correctly.
    This is Goodhart's Law in action: max_hold_days became a target.
    """
    time_wins  = exit_stats.get("time_exit", {}).get("wins",  0)
    total_wins = sum(s["wins"] for s in exit_stats.values())

    if total_wins == 0:
        return {"goodharts_warning": False}

    time_win_pct = time_wins / total_wins
    warning      = time_win_pct > 0.60

    result = {
        "goodharts_warning":        warning,
        "pct_wins_via_time_exit":   round(time_win_pct, 3),
    }

    if warning:
        result["message"] = (
            f"{time_win_pct:.0%} of wins came from time_exit — "
            "the bot is winning by outlasting, not by momentum quality. "
            "Consider reducing max_hold_days or raising min_signal_score "
            "to force sharper entries that reach target faster."
        )
    return result


# ── Trajectory analysis (Ch.1) ────────────────────────────────
# "You should be far more concerned with your current trajectory
#  than your current results."

def analyse_trajectory(rows) -> dict:
    """
    Split trades in half chronologically. If the second half win rate is
    meaningfully lower than the first half, the strategy is drifting.
    """
    completed = [r for r in rows if r[1] is not None]
    if len(completed) < 40:
        return {"insufficient_data": True}

    mid        = len(completed) // 2
    first_half = completed[:mid]
    second_half= completed[mid:]

    def win_rate(rs):
        wins = sum(1 for r in rs if (r[1] or 0) > 0)
        return round(wins / len(rs), 4) if rs else 0

    first_wr  = win_rate(first_half)
    second_wr = win_rate(second_half)
    delta     = second_wr - first_wr

    trend = "IMPROVING" if delta > 0.05 else ("STABLE" if abs(delta) <= 0.05 else "DECLINING")

    result = {
        "first_half_win_rate":  first_wr,
        "second_half_win_rate": second_wr,
        "delta":                round(delta, 4),
        "trend":                trend,
    }

    if trend == "DECLINING":
        result["message"] = (
            f"Win rate dropped from {first_wr:.1%} (first half) to "
            f"{second_wr:.1%} (second half) — strategy is deteriorating. "
            "Rebuild constitution with fresher data or tighten entry rules."
        )

    return result


# ── Consecutive loss analysis (Ch.16) ─────────────────────────
# Which tickers have a losing streak that should trigger a pause?

def analyse_streaks(rows) -> dict:
    """
    For each ticker, count trailing consecutive losses.
    Tickers above MAX_CONSECUTIVE_LOSSES should be flagged.
    """
    from collections import defaultdict

    # Group by symbol, in order of (entry_date, id — position in rows)
    ticker_trades = defaultdict(list)
    for sym, pnl_pct, *_ in rows:
        ticker_trades[sym].append(pnl_pct or 0)

    streaks = {}
    paused  = []
    for sym, pnls in ticker_trades.items():
        streak = 0
        for pnl in reversed(pnls):
            if pnl <= 0:
                streak += 1
            else:
                break
        streaks[sym] = streak
        if streak >= config.MAX_CONSECUTIVE_LOSSES:
            paused.append(sym)

    return {
        "consecutive_losses_by_ticker": streaks,
        "tickers_currently_paused":     paused,
        "pause_threshold":              config.MAX_CONSECUTIVE_LOSSES,
    }


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


# ── Best Loser Wins: Win/Loss Asymmetry Check (Tom Hougaard) ──
# The 43-million-trade study: 61% win rate but traders still lost money.
# Why? Average loss (-83 pips) was nearly twice the average win (+43 pips).
# A bot with a 60% win rate still loses money if avg_loss > avg_win.
# This check flags that scenario immediately.

def check_win_loss_asymmetry(rows) -> dict:
    """
    Flag if average loss magnitude exceeds average win.
    Hougaard's core finding: win rate means nothing if your losses
    dwarf your wins. The bot must let winners run beyond avg_loss size.
    """
    wins   = [(pnl_pct or 0) for _, pnl_pct, *_ in rows if (pnl_pct or 0) > 0]
    losses = [abs(pnl_pct or 0) for _, pnl_pct, *_ in rows if (pnl_pct or 0) <= 0]

    if not wins or not losses:
        return {"asymmetry_warning": False}

    avg_win  = sum(wins)  / len(wins)
    avg_loss = sum(losses) / len(losses)
    ratio    = avg_loss / avg_win if avg_win > 0 else float("inf")
    warning  = ratio > 1.0  # bad: avg loss > avg win

    result = {
        "asymmetry_warning":  warning,
        "avg_win_pct":        round(avg_win * 100,  2),
        "avg_loss_pct":       round(avg_loss * 100, 2),
        "loss_to_win_ratio":  round(ratio, 3),
    }
    if warning:
        result["message"] = (
            f"CRITICAL: avg loss ({avg_loss:.1%}) > avg win ({avg_win:.1%}). "
            f"Ratio = {ratio:.2f}x. Even with a 60%% win rate, this is a losing system. "
            "Trailing stops must run winners further than losses are cut. "
            "Ref: Hougaard Ch.3 — 43M trade study."
        )
    else:
        result["message"] = (
            f"Win/loss size healthy: avg win {avg_win:.1%} > avg loss {avg_loss:.1%} "
            f"(ratio {ratio:.2f}x — losses are smaller than wins)"
        )
    return result


# ── Main builder ──────────────────────────────────────────────

def build_constitution(db_path: str = "trades.db", until: str | None = None):
    rows  = fetch_trades(db_path, until)
    print(f"Fitting on {db_path}" + (f", trades before {until} only" if until else
          " — ALL trades (no out-of-sample holdout; prefer --until)"))
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
    goodharts    = check_goodharts_law(exit_stats, 0)  # win_rate computed below
    trajectory   = analyse_trajectory(rows)
    streaks      = analyse_streaks(rows)
    asymmetry    = check_win_loss_asymmetry(rows)

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

    # ── Goodhart's Law warning (Ch.20) ────────────────────────
    if goodharts.get("goodharts_warning"):
        print(f"\n[GOODHART WARNING] {goodharts['message']}")

    # ── Trajectory check (Ch.1) ───────────────────────────────
    if not trajectory.get("insufficient_data"):
        first  = trajectory["first_half_win_rate"]
        second = trajectory["second_half_win_rate"]
        trend  = trajectory["trend"]
        print(f"\nTrajectory: {first:.1%} (first half) -> {second:.1%} (second half) [{trend}]")
        if trajectory.get("message"):
            print(f"  WARNING: {trajectory['message']}")

    # ── Streak summary (Ch.16) ────────────────────────────────
    if streaks["tickers_currently_paused"]:
        print(f"\nPaused tickers (>={config.MAX_CONSECUTIVE_LOSSES} consecutive losses): "
              f"{', '.join(streaks['tickers_currently_paused'])}")

    # ── Best Loser Wins: Win/Loss Asymmetry (Tom Hougaard, Ch.3) ─
    print(f"\nWin/Loss Asymmetry: {asymmetry['message']}")
    if asymmetry.get("asymmetry_warning"):
        print("  [CRITICAL] Trailing stops are not running winners far enough.")

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

    # Trailing-stop viability: use EXPECTANCY not raw win rate.
    # Win rate alone is misleading when winners are much larger than losers.
    # Expectancy = (win_rate × avg_win) - (loss_rate × avg_loss)
    # Minimum viable: +0.5% per trade expectancy AND positive total PnL.
    wins_data   = [r[1] for r in rows if (r[1] or 0) > 0]
    losses_data = [abs(r[1] or 0) for r in rows if (r[1] or 0) <= 0]
    avg_win_e   = sum(wins_data)  / len(wins_data)  if wins_data  else 0
    avg_loss_e  = sum(losses_data)/ len(losses_data) if losses_data else 0
    expectancy  = (win_rate * avg_win_e) - ((1 - win_rate) * avg_loss_e)
    MIN_EXPECTANCY = 0.005  # 0.5% per trade

    print(f"\nExpectancy per trade: {expectancy:.3%}  "
          f"(win {win_rate:.1%} x {avg_win_e:.2%}) - "
          f"(loss {1-win_rate:.1%} x {avg_loss_e:.2%})")

    strategy_viable = expectancy >= MIN_EXPECTANCY and avg_pnl > 0

    if not strategy_viable:
        print(f"\nWARNING: Expectancy {expectancy:.3%} below {MIN_EXPECTANCY:.1%} minimum "
              f"or total PnL is negative.")
        print("Strategy not ready for live. Re-run paper_runner.py after tuning parameters.")
        return False

    if win_rate < config.MIN_WIN_RATE:
        print(f"\nNOTE: Overall win rate {win_rate:.1%} below {config.MIN_WIN_RATE:.0%}, "
              f"but expectancy is {expectancy:.3%} — viable for trailing-stop strategy.")

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
            "trail_activation_pct":   config.TRAIL_ACTIVATION_PCT,
            "trail_stop_pct":         config.TRAIL_STOP_PCT,
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
        # Goodhart's Law: are wins coming from outlasting rather than momentum?
        "goodharts_analysis": goodharts,
        # Trajectory: first-half vs second-half win rate — is strategy improving or drifting?
        "trajectory": trajectory,
        # Atomic Habits Ch.16: which tickers are on a losing streak right now?
        "streak_summary": streaks,
        # Best Loser Wins (Hougaard Ch.3): avg win vs avg loss size check
        "win_loss_asymmetry": asymmetry,
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
    print("Go live only when validation.py returns PASS out-of-sample AND golive_gate")
    print("passes on the paper record — a win rate on its own says nothing about edge.")
    return True


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="trades.db")
    ap.add_argument("--until", help="fit only on trades entered before YYYY-MM-DD")
    a = ap.parse_args()
    ok = build_constitution(a.db, a.until)
    sys.exit(0 if ok else 1)
