# ============================================================
#  constitution_validator.py
#  Verifies constitution.json has not been tampered with.
#  Called before EVERY live trade — no bypass possible.
# ============================================================

import json
import hashlib
import logging
import os

logger = logging.getLogger(__name__)
CONSTITUTION_FILE = "constitution.json"

_cached_constitution = None


def load_constitution() -> dict | None:
    """Load and verify constitution.json. Returns None if invalid."""
    global _cached_constitution

    if not os.path.exists(CONSTITUTION_FILE):
        logger.warning("No constitution.json found. Run constitution_builder.py first.")
        return None

    with open(CONSTITUTION_FILE, "r") as f:
        data = json.load(f)

    stored_hash = data.pop("sha256", None)
    if not stored_hash:
        logger.error("Constitution missing SHA-256 hash — file may be corrupted.")
        return None

    constitution_str = json.dumps(data, indent=2, sort_keys=True)
    computed_hash    = hashlib.sha256(constitution_str.encode()).hexdigest()

    if computed_hash != stored_hash:
        logger.critical(
            "CONSTITUTION HASH MISMATCH — file was modified after paper testing!\n"
            f"Expected: {stored_hash}\n"
            f"Got:      {computed_hash}\n"
            "Live trading is BLOCKED. Re-run paper testing to generate a new constitution."
        )
        return None

    data["sha256"]    = stored_hash
    _cached_constitution = data
    logger.info(f"Constitution verified OK (built from {data.get('paper_trades_used')} paper trades)")
    return data


def get_rules() -> dict:
    """Return the global fallback rules dict."""
    c = _cached_constitution or load_constitution()
    return c.get("rules", {}) if c else {}


def get_segment_rules(theme: str) -> dict:
    """Return per-segment rules from constitution, or empty dict."""
    c = _cached_constitution or load_constitution()
    if not c:
        return {}
    return c.get("segment_rules", {}).get(theme, {})


def constitution_allows(symbol: str, signal_result, sentiment) -> tuple[bool, str]:
    """
    Secondary safety gate — runs after strategy.py has already applied
    segment rules. Checks global constitution minimums and news/earnings.
    Returns (allowed, reason).
    """
    rules = get_rules()
    if not rules:
        return False, "No valid constitution loaded — cannot trade live"

    # Global minimum score floor (constitution's global best, not segment-specific)
    min_score = rules.get("min_signal_score", 2)
    if signal_result.score < min_score:
        return False, f"Signal score {signal_result.score} < constitution floor {min_score}"

    if rules.get("require_bullish_news") and sentiment.label != "bullish":
        return False, f"Constitution requires bullish news, got: {sentiment.label}"

    if sentiment.near_earnings:
        return False, "Earnings blackout — constitution blocks entry"

    return True, "All constitution rules passed"


def print_constitution_summary():
    """Print a readable summary of the locked constitution."""
    c = load_constitution()
    if not c:
        print("No constitution found.")
        return

    rules = c.get("rules", {})
    seg   = c.get("segment_rules", {})
    les   = c.get("lessons", {})

    print(f"\n{'='*56}")
    print(f"  TRADING CONSTITUTION  (v{c.get('version', 1)})")
    print(f"  Built   : {c.get('built_at', 'unknown')[:19]}")
    print(f"  Trades  : {c.get('paper_trades_used')}")
    print(f"  Win rate: {c.get('overall_win_rate', 0):.1%}  "
          f"(time-exit: {c.get('time_exit_win_rate', 0):.1%})")
    print(f"{'='*56}")
    print("  GLOBAL RULES (fallback):")
    for key, val in rules.items():
        print(f"    {key:<32} {val}")

    if seg:
        print(f"\n  PER-SEGMENT RULES:")
        for theme, sr in sorted(seg.items()):
            wr = sr.get("win_rate", 0)
            print(f"    [{theme:<12}]  "
                  f"score>={sr.get('min_signal_score','?')}  "
                  f"stop={sr.get('stop_loss_pct',0):.0%}  "
                  f"target={sr.get('take_profit_pct',0):.0%}  "
                  f"hold<={sr.get('max_hold_days','?')}d  "
                  f"win={wr:.0%}")

    if les and les.get("lessons"):
        print(f"\n  LESSONS FROM {les.get('total_losses', 0)} LOSSES:")
        for lesson in les["lessons"]:
            # wrap at 70 chars for readability
            words, line = lesson.split(), ""
            for w in words:
                if len(line) + len(w) > 68:
                    print(f"    * {line}")
                    line = w + " "
                else:
                    line += w + " "
            if line:
                print(f"    * {line}")

    print(f"{'='*56}\n")
