# ============================================================
#  sizing.py — Capital base and cash-account limits
#  Shared by strategy.py (swing) and crt_strategy.py so both
#  books size off the same capital and draw on one settled-cash pool.
# ============================================================

import logging
import math
from datetime import date

import config
import trade_logger as tl

logger = logging.getLogger(__name__)


def floor_qty(qty: float) -> float:
    """Round DOWN to Alpaca's 0.01-share fractional step. round() can round
    up and push a position past its MAX_POSITION_PCT cap (by up to ~$2 at
    META's price on a $50 position)."""
    return math.floor(qty * 100 + 1e-9) / 100


def kelly_fraction(strategy: str) -> float | None:
    """
    Fractional Kelly allocation from the strategy's OUT-OF-SAMPLE validation
    report (validation.py), or None when there is no validated edge.
    Continuous-return Kelly: f* = mean / variance of per-trade net return,
    scaled by KELLY_MULTIPLIER (quarter-Kelly — full Kelly on an estimated
    edge overbets, because the estimate is noisy).
    """
    import validation
    rep = validation.load(strategy)
    if not rep or rep.get("verdict") != "PASS":
        return None
    oos = rep["out_of_sample"]
    mu, sd = oos.get("mean_net_pct", 0.0), oos.get("std_net_pct", 0.0)
    if mu <= 0 or sd <= 0:
        return None
    return config.KELLY_MULTIPLIER * mu / sd ** 2


def position_fraction(strategy: str) -> float:
    """
    Share of sizing_capital() for one position.
    Paper: fixed MAX_POSITION_PCT — the point of paper is to keep collecting
    evidence. Live with USE_KELLY_SIZING: quarter-Kelly capped at
    MAX_POSITION_PCT, and 0.0 without a PASS verdict — live money is never
    sized on an edge that has not been shown out-of-sample.
    """
    if config.TRADING_MODE != "live" or not config.USE_KELLY_SIZING:
        return config.MAX_POSITION_PCT
    k = kelly_fraction(strategy)
    if k is None:
        logger.warning(f"{strategy}: no PASS out-of-sample verdict — live position size is 0")
        return 0.0
    return min(k, config.MAX_POSITION_PCT)


def sizing_capital(client) -> float:
    """
    Capital that position sizes are a fraction of: broker equity, capped at
    config.ACCOUNT_CAPITAL. On a $100k paper account this is $500; on a real
    $500 account that has drawn down to $450 it is $450.
    """
    return min(client.get_portfolio_value(), config.ACCOUNT_CAPITAL)


def settled_cash_remaining(client) -> float | None:
    """
    Cash still spendable on new entries today under T+1 settlement, or None
    when the account is not a modelled cash account (no limit applies).

    Every position is flattened by EOD, so at the open all prior-session
    proceeds have settled and the day's budget is sizing_capital(). Each
    entry consumes its notional for the rest of the session — selling it
    does not hand the cash back until the next day.
    """
    if not config.ENFORCE_T1_SETTLEMENT:
        return None
    spent = tl.entry_notional_on(date.today().isoformat())
    return max(0.0, sizing_capital(client) - spent)


def cap_to_settled_cash(client, symbol: str, qty: float, price: float) -> float:
    """
    Shrink qty so the entry fits inside today's settled cash. Returns 0.0
    when nothing is left — callers already skip entries below 0.01 shares.
    """
    if "/" in symbol:   # crypto settles instantly — T+1 does not apply
        return qty
    remaining = settled_cash_remaining(client)
    if remaining is None or qty * price <= remaining:
        return qty
    capped = floor_qty(remaining / price)
    if capped < 0.01:
        tl.log_rejection(symbol, f"t1_settlement (wanted ${qty * price:.2f}, "
                                 f"only ${remaining:.2f} settled cash left today)")
        return 0.0
    logger.info(f"{symbol}: resized ${qty * price:.2f} -> ${capped * price:.2f} "
                f"to fit settled cash (T+1)")
    return capped
