# ============================================================
#  crt_strategy.py — "8AM Candle / 9AM CRT" model
#
#  Per symbol, per day:
#    1. At 09:00 ET the 08:00-09:00 ET hour candle is closed. Its high/low
#       become the day's "narrative box" (built from four 15Min bars).
#    2. Wait for a sweep of one side of the box during the session:
#         price trades ABOVE range_high -> arm SHORT (expect reversal down)
#         price trades BELOW range_low  -> arm LONG  (expect reversal up)
#       The furthest excursion outside the box is the "sweep extreme".
#    3. Never enter on the sweep itself. Require, on 5Min bars:
#         displacement — a candle CLOSES back inside the box, and then
#         BOS — a candle CLOSES through the most recent opposing swing
#               point, in the reversal direction.
#    4. Enter on that BOS close, in the reversal direction.
#    5. Stop just beyond the sweep extreme (the wick that took liquidity).
#    6. Exit on a trailing stop (TRAIL_ACTIVATION_PCT / TRAIL_STOP_PCT),
#       not a fixed target.
#    7. One setup per symbol per day.
#    8. EOD flatten at EOD_FLATTEN_TIME — longs and shorts, no overnight holds.
#
#  This module is deliberately self-contained. It does NOT touch the RSI/MACD
#  scorer in strategy.py, and it keeps its own position book and state file,
#  because it is the first thing in this bot that can hold a SHORT and every
#  stop / trail / P&L rule inverts on that side.
#
#  It ships dormant: paper_runner.py only constructs CRTStrategy when
#  config.ENABLE_CRT_STRATEGY is True.
# ============================================================

import json
import logging
import os
from datetime import datetime, date, time as dtime, timedelta
from zoneinfo import ZoneInfo

import config
import macro_calendar as macro
import signals as sig
import sizing
import trade_logger as tl

logger = logging.getLogger(__name__)

# The host clock happens to be ET, but bars come back UTC-indexed and a VPS
# move would silently break every window check. Always convert explicitly.
ET = ZoneInfo("America/New_York")

CRT_STATE_PATH = os.path.join("logs", "crt_positions.json")

# Duration of one CRT_TIMEFRAME_ENTRY bar — bars are stamped at bar-OPEN,
# so a bar's entry (its close) lands _BAR_5M after its timestamp.
_BAR_5M = timedelta(minutes=5)

LONG  = "long"
SHORT = "short"


# ── Helpers ───────────────────────────────────────────────────

def _parse_hhmm(value: str) -> dtime:
    hh, mm = str(value).split(":")
    return dtime(int(hh), int(mm))


def _to_et(df):
    """Return a copy of an Alpaca bar frame with an ET-localized index."""
    out = df.copy()
    idx = out.index
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    out.index = idx.tz_convert(ET)
    return out


# ── Stage 1: the narrative box ────────────────────────────────

def compute_range(df_15m, session_date: date) -> dict | None:
    """
    Build the 08:00-09:00 ET hour candle for session_date from 15Min bars.

    Returns {"high", "low", "width", "width_pct", "bars"} or None when the
    window has no bars at all (holiday, halted symbol, missing pre-market).
    width_pct is measured against the box midpoint, not the last close, so
    the number does not drift with intraday price action.
    """
    if df_15m is None or len(df_15m) == 0:
        return None

    start = _parse_hhmm(config.CRT_RANGE_START)
    end   = _parse_hhmm(config.CRT_RANGE_END)

    df = _to_et(df_15m)
    # Bars are stamped at bar-OPEN, so [start, end) selects exactly the bars
    # whose bodies fall inside the window: 08:00, 08:15, 08:30, 08:45.
    mask = [(t.date() == session_date and start <= t.time() < end) for t in df.index]
    window = df[mask]
    if len(window) == 0:
        return None

    high = float(window["high"].max())
    low  = float(window["low"].min())
    mid  = (high + low) / 2
    if mid <= 0:
        return None

    return {
        "high":      round(high, 4),
        "low":       round(low, 4),
        "width":     round(high - low, 4),
        "width_pct": (high - low) / mid,
        "bars":      int(len(window)),
    }


def range_is_tradeable(symbol: str, rng: dict) -> bool:
    """
    Degenerate-input guard, not a strategy override.

    The 08:00-09:00 window is thin by construction. When the box is narrower
    than CRT_MIN_RANGE_PCT the stop — which sits just beyond the sweep wick —
    lands inside the bid/ask spread, so the trade is chopped out on noise no
    matter how good the directional read was. Skip the symbol for the day.
    """
    if rng["width_pct"] >= config.CRT_MIN_RANGE_PCT:
        return True
    logger.info(
        f"{symbol}: CRT range too narrow — ${rng['width']:.2f} "
        f"({rng['width_pct']:.3%} < {config.CRT_MIN_RANGE_PCT:.2%}) — skipping for the day"
    )
    return False


# ── Stage 2-3: sweep, displacement, break of structure ────────

def _swing_lows(lows) -> list:
    """Indices of 3-bar fractal swing lows (low[i] < low[i-1] and < low[i+1])."""
    return [i for i in range(1, len(lows) - 1)
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]]


def _swing_highs(highs) -> list:
    """Indices of 3-bar fractal swing highs."""
    return [i for i in range(1, len(highs) - 1)
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]]


def detect_setup(df_5m, rng: dict, session_date: date) -> dict:
    """
    Walk the session's 5Min bars and report how far the model got.

    Returns a dict that is always populated, so callers (live and replay) can
    report the exact stage reached:
        stage        — "no_bars" | "no_sweep" | "swept" | "displaced" | "confirmed"
        bias         — LONG / SHORT once armed
        sweep_*      — side, extreme price, bar time
        displaced_at — time of the candle that closed back inside the box
        bos_level    — the opposing swing point that had to break
        entry_price / entry_time / stop_price — only when stage == "confirmed"
    """
    result = {
        "stage": "no_bars", "bias": None, "sweep_side": None,
        "sweep_extreme": None, "sweep_time": None, "displaced_at": None,
        "bos_level": None, "entry_price": None, "entry_time": None,
        "stop_price": None, "notes": "",
    }
    if df_5m is None or len(df_5m) == 0:
        return result

    end = _parse_hhmm(config.CRT_RANGE_END)
    # A setup that confirms at or after the EOD flatten is not tradeable: the
    # entry would be closed by flatten_for_close in the same breath, paying two
    # spreads for zero exposure. Replayed RIVN 2026-09-17 did exactly that —
    # BOS on the 15:50 bar, whose close IS 15:55. So the last eligible bar is
    # one that CLOSES strictly before EOD_FLATTEN_TIME.
    flat = _parse_hhmm(config.EOD_FLATTEN_TIME)
    cutoff = (datetime.combine(session_date, flat) - _BAR_5M).time()

    df  = _to_et(df_5m)
    mask = [(t.date() == session_date and end <= t.time() < cutoff) for t in df.index]
    bars = df[mask]
    if len(bars) == 0:
        return result

    times  = list(bars.index)
    highs  = [float(x) for x in bars["high"]]
    lows   = [float(x) for x in bars["low"]]
    closes = [float(x) for x in bars["close"]]

    hi, lo = rng["high"], rng["low"]
    result["stage"] = "no_sweep"

    sweep_i = None
    displaced_i = None

    for i in range(len(bars)):
        if sweep_i is None:
            above = highs[i] > hi
            below = lows[i] < lo
            if above and below:
                # A single 5Min bar that pierced BOTH sides. OHLC cannot say
                # which side was hit first, so take the larger excursion as the
                # liquidity grab; a coin flip here would arm the wrong bias half
                # the time and the stop would sit on the wrong wick.
                if (highs[i] - hi) >= (lo - lows[i]):
                    below = False
                else:
                    above = False
                result["notes"] = "both sides swept in one bar; took the larger excursion"
            if above:
                sweep_i = i
                result.update(stage="swept", bias=SHORT, sweep_side="above",
                              sweep_extreme=highs[i], sweep_time=times[i])
            elif below:
                sweep_i = i
                result.update(stage="swept", bias=LONG, sweep_side="below",
                              sweep_extreme=lows[i], sweep_time=times[i])
            continue

        # Armed. One setup per symbol per day means we never re-arm the other
        # side — this sweep is the day's narrative, right or wrong.
        if displaced_i is None:
            # Track how far the grab ran before price came back.
            if result["bias"] == SHORT and highs[i] > result["sweep_extreme"]:
                result["sweep_extreme"] = highs[i]
                result["sweep_time"]    = times[i]
            elif result["bias"] == LONG and lows[i] < result["sweep_extreme"]:
                result["sweep_extreme"] = lows[i]
                result["sweep_time"]    = times[i]

            # Displacement: a CLOSE back inside the box. A wick back inside is
            # not acceptance, so the close is what counts.
            if lo <= closes[i] <= hi:
                displaced_i = i
                result.update(stage="displaced", displaced_at=times[i])
            continue

        # Displaced. Now wait for BOS through the most recent opposing swing
        # point formed between the sweep and the displacement.
        if result["bos_level"] is None:
            window_lo, window_hi = sweep_i, displaced_i
            seg = slice(window_lo, window_hi + 1)
            if result["bias"] == SHORT:
                pivots = _swing_lows(lows[seg])
                # Most RECENT opposing pivot, i.e. the last one formed.
                level = (lows[window_lo + pivots[-1]] if pivots else min(lows[seg]))
            else:
                pivots = _swing_highs(highs[seg])
                level = (highs[window_lo + pivots[-1]] if pivots else max(highs[seg]))
            result["bos_level"] = round(level, 4)
            if not pivots:
                # No confirmed 3-bar pivot formed in that window (common when
                # the reversal is fast). Fall back to the extreme of the
                # sweep->displacement leg, which is still a real structural
                # level rather than an invented one.
                result["notes"] = (result["notes"] + "; " if result["notes"] else "") + \
                    "no fractal pivot in sweep->displacement leg; used leg extreme as BOS level"

        bos = result["bos_level"]
        broke = closes[i] < bos if result["bias"] == SHORT else closes[i] > bos
        if broke:
            buf = config.CRT_STOP_BUFFER_PCT
            stop = (result["sweep_extreme"] * (1 + buf) if result["bias"] == SHORT
                    else result["sweep_extreme"] * (1 - buf))
            result.update(stage="confirmed", entry_price=round(closes[i], 4),
                          entry_time=times[i], stop_price=round(stop, 4))
            return result

    return result


# ── Position ──────────────────────────────────────────────────

class CRTPosition:
    """
    A CRT position. Unlike strategy.Position this is side-aware: for a short
    the stop sits ABOVE entry, the high-water mark is a LOW-water mark, and
    the trailing stop ratchets DOWN.
    """

    def __init__(self, symbol, side, entry_price, qty, trade_id,
                 stop_price, entry_time, range_high, range_low, sweep_extreme,
                 stop_order_id=None):
        # Id of the stop resting at the broker. The polling loop is the backup;
        # the exchange is what actually enforces the stop.
        self.stop_order_id = stop_order_id
        self.symbol        = symbol
        self.side          = side
        self.entry_price   = float(entry_price)
        self.qty           = float(qty)
        self.trade_id      = trade_id
        self.stop_price    = float(stop_price)   # hard stop — never widened
        self.trailing_stop = float(stop_price)
        self.extreme_price = float(entry_price)  # best price seen in our favour
        self.trail_active  = False
        self.entry_time    = entry_time
        self.range_high    = range_high
        self.range_low     = range_low
        self.sweep_extreme = sweep_extreme

    @property
    def is_short(self) -> bool:
        return self.side == SHORT

    def hold_minutes(self) -> float:
        return (datetime.now(ET) - self.entry_time).total_seconds() / 60

    def pnl_pct(self, price: float) -> float:
        d = -1 if self.is_short else 1
        return ((price - self.entry_price) / self.entry_price) * d

    def update_trailing_stop(self, price: float):
        """Ratchet the trail in the direction of profit only — never widen."""
        if self.is_short:
            if price < self.extreme_price:
                self.extreme_price = price
            if price <= self.entry_price * (1 - config.TRAIL_ACTIVATION_PCT):
                self.trail_active = True
            if self.trail_active:
                new_trail = round(self.extreme_price * (1 + config.TRAIL_STOP_PCT), 2)
                if new_trail < self.trailing_stop:
                    self.trailing_stop = new_trail
        else:
            if price > self.extreme_price:
                self.extreme_price = price
            if price >= self.entry_price * (1 + config.TRAIL_ACTIVATION_PCT):
                self.trail_active = True
            if self.trail_active:
                new_trail = round(self.extreme_price * (1 - config.TRAIL_STOP_PCT), 2)
                if new_trail > self.trailing_stop:
                    self.trailing_stop = new_trail

    def stop_hit(self, price: float) -> bool:
        return price >= self.stop_price if self.is_short else price <= self.stop_price

    def trail_hit(self, price: float) -> bool:
        if not self.trail_active:
            return False
        return price >= self.trailing_stop if self.is_short else price <= self.trailing_stop

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["entry_time"] = self.entry_time.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CRTPosition":
        pos = cls(d["symbol"], d["side"], d["entry_price"], d["qty"], d["trade_id"],
                  d["stop_price"], datetime.fromisoformat(d["entry_time"]),
                  d["range_high"], d["range_low"], d["sweep_extreme"],
                  d.get("stop_order_id"))
        pos.trailing_stop = d["trailing_stop"]
        pos.extreme_price = d["extreme_price"]
        pos.trail_active  = d["trail_active"]
        return pos


# ── Strategy ──────────────────────────────────────────────────

class CRTStrategy:
    """
    Live driver for the CRT model. Call run_cycle() on the paper_runner's
    schedule and flatten_for_close() at EOD_FLATTEN_TIME.

    Every entry is still gated by the kill switch, exactly like SwingStrategy.
    """

    def __init__(self, alpaca_client, kill_switch, swing_strategy=None):
        self.client      = alpaca_client
        self.kill_switch = kill_switch
        # CRT and the swing book now share the same 20-symbol universe. Without
        # a cross-check both could open the same name at MAX_POSITION_PCT each,
        # doubling concentration on one ticker while each book believes it is
        # within its own limit.
        self.swing       = swing_strategy
        self.mode        = config.TRADING_MODE
        self.positions   = {}
        self._ranges     = {}   # symbol -> range dict, rebuilt each session
        self._done_today = set()
        self._session    = None
        self._load_positions()

    # ── State persistence ─────────────────────────────────────

    def _load_positions(self):
        if not os.path.exists(CRT_STATE_PATH):
            return
        try:
            with open(CRT_STATE_PATH, "r") as f:
                raw = json.load(f)
            for symbol, d in raw.get("positions", {}).items():
                self.positions[symbol] = CRTPosition.from_dict(d)
            self._done_today = set(raw.get("done_today", []))
            self._session    = raw.get("session")
            if self.positions:
                logger.warning(f"CRT: restored {len(self.positions)} position(s) from disk: "
                               f"{', '.join(self.positions)}")
        except Exception as e:
            logger.error(f"CRT: failed to load saved state — starting empty: {e}", exc_info=True)

    def _save_positions(self):
        try:
            os.makedirs(os.path.dirname(CRT_STATE_PATH), exist_ok=True)
            with open(CRT_STATE_PATH, "w") as f:
                json.dump({
                    "session":     self._session,
                    "done_today":  sorted(self._done_today),
                    "positions":   {s: p.to_dict() for s, p in self.positions.items()},
                }, f, indent=2)
        except Exception as e:
            logger.error(f"CRT: failed to persist state: {e}", exc_info=True)

    def _roll_session(self):
        """Reset per-day state when the ET calendar date changes."""
        today = datetime.now(ET).date().isoformat()
        if self._session != today:
            self._session = today
            self._ranges.clear()
            self._done_today.clear()
            self._save_positions()

    # ── Gates ─────────────────────────────────────────────────

    def _is_safe_to_trade(self) -> bool:
        if self.kill_switch.check():
            logger.warning("CRT blocked — kill switch is ACTIVE")
            return False
        return True

    def _calc_qty(self, symbol: str, price: float, side: str) -> float:
        capital = sizing.sizing_capital(self.client)
        qty = (capital * sizing.position_fraction("crt")) / price
        if side == SHORT:
            # Alpaca rejects fractional short sales — whole shares only.
            return float(int(qty))
        return sizing.cap_to_settled_cash(self.client, symbol, sizing.floor_qty(qty), price)

    # ── Main cycle ────────────────────────────────────────────

    def run_cycle(self, symbols=None):
        """One CRT evaluation pass: manage open trades, then look for setups."""
        if not config.ENABLE_CRT_STRATEGY:
            return

        self._roll_session()
        self.evaluate_exits()

        if not self._is_safe_to_trade():
            return

        # Same fear-spike gate as the swing book. Exits above still run; only
        # new entries are blocked, and symbols are NOT marked done for the day
        # so setups can still fire if the spike clears.
        df_vix = self.client.get_bars(config.VIX_TICKER, timeframe="1Day",
                                      days=config.VIX_LOOKBACK_DAYS, split_adjusted=True)
        if not sig.is_volatility_safe(df_vix):
            logger.info("CRT: VIX elevated — no new entries this cycle")
            return

        now = datetime.now(ET)
        if now.time() < _parse_hhmm(config.CRT_RANGE_END):
            logger.debug("CRT: before range close — nothing to evaluate yet")
            return
        # An entry at/after the flatten would be opened after flatten_for_close
        # ran and carried overnight.
        if now.strftime("%H:%M") >= config.EOD_FLATTEN_TIME:
            return
        blackout = macro.crt_blocked_today(now.date()) or macro.entry_blocked(now)
        if blackout:
            logger.info(f"CRT: {blackout} — no new entries this cycle")
            return

        for symbol in (symbols or config.CRT_SYMBOLS):
            if symbol in self.positions or symbol in self._done_today:
                continue
            # Never stack on top of the swing book's exposure to the same name.
            if self.swing is not None and symbol in getattr(self.swing, "positions", {}):
                tl.log_rejection(symbol, "crt_already_held (swing book holds this symbol — "
                                         "avoiding doubled concentration in one ticker)")
                continue
            if len(self.positions) >= config.CRT_MAX_OPEN_POSITIONS:
                logger.info(f"CRT: {len(self.positions)} positions open — at cap, no new entries")
                break
            try:
                self._evaluate_symbol(symbol, now.date())
            except Exception as e:
                logger.error(f"CRT: {symbol} evaluation failed: {e}", exc_info=True)

    def _evaluate_symbol(self, symbol: str, session_date: date):
        rng = self._ranges.get(symbol)
        if rng is None:
            df15 = self.client.get_bars(symbol, config.CRT_TIMEFRAME_RANGE, days=3)
            rng  = compute_range(df15, session_date)
            if rng is None:
                tl.log_rejection(symbol, f"crt_no_range ({config.CRT_RANGE_START}-"
                                         f"{config.CRT_RANGE_END} ET window had no bars)")
                self._done_today.add(symbol)
                self._save_positions()
                return
            if not range_is_tradeable(symbol, rng):
                tl.log_rejection(
                    symbol,
                    f"crt_range_too_narrow (${rng['width']:.2f} = {rng['width_pct']:.3%} "
                    f"< CRT_MIN_RANGE_PCT {config.CRT_MIN_RANGE_PCT:.2%}) — "
                    f"stop would sit inside the spread"
                )
                self._done_today.add(symbol)
                self._save_positions()
                return
            self._ranges[symbol] = rng
            logger.info(f"CRT box {symbol}: {rng['low']:.2f}-{rng['high']:.2f} "
                        f"(${rng['width']:.2f}, {rng['width_pct']:.2%}, {rng['bars']} bars)")

        df5   = self.client.get_bars(symbol, config.CRT_TIMEFRAME_ENTRY, days=2)
        setup = detect_setup(df5, rng, session_date)
        if setup["stage"] != "confirmed":
            logger.debug(f"CRT {symbol}: stage={setup['stage']}")
            return

        self._enter_trade(symbol, setup, rng)

    # ── Entry ─────────────────────────────────────────────────

    def _enter_trade(self, symbol: str, setup: dict, rng: dict) -> bool:
        price = self.client.get_latest_price(symbol)
        if not price:
            return False

        side = setup["bias"]
        # Re-derive the stop from the live price's perspective only for the
        # sanity check; the stop itself is anchored to the sweep wick, which is
        # what the model says invalidates the idea.
        stop = setup["stop_price"]
        if (side == SHORT and stop <= price) or (side == LONG and stop >= price):
            tl.log_rejection(symbol, f"crt_stop_wrong_side (price ${price:.2f} already "
                                     f"past stop ${stop:.2f} — sweep level retaken)")
            self._done_today.add(symbol)
            self._save_positions()
            return False

        # A cash account (ACCOUNT_CAPITAL < $2,000) cannot short at all. The
        # paper account can, so without this paper would log trades the real
        # account could never place.
        if side == SHORT and not config.CRT_ALLOW_SHORTS:
            tl.log_rejection(symbol, f"crt_short_disabled (cash account — shorting needs "
                                     f"${config.MARGIN_MIN_EQUITY:,} margin equity)")
            self._done_today.add(symbol)
            self._save_positions()
            return False

        # A sweep-high setup is a sell-to-open. Crypto is not shortable on
        # Alpaca and some equities are hard-to-borrow, so confirm the broker
        # will accept it rather than firing an order that gets rejected.
        if side == SHORT and not self.client.is_shortable(symbol):
            tl.log_rejection(symbol, "crt_not_shortable (sweep-high setup needs a "
                                     "short; broker does not permit it for this asset)")
            self._done_today.add(symbol)
            self._save_positions()
            return False

        # Reward:risk gate. The model targets the opposite side of the box, so
        # reward is fixed by geometry the moment BOS confirms. A late entry
        # leaves little box left while the stop stays back at the sweep wick —
        # across 33 replayed setups the median R:R was 0.33, i.e. risking three
        # to make one. Those lose even at a high hit rate.
        target = rng["low"] if side == SHORT else rng["high"]
        risk   = abs(price - stop)
        reward = abs(target - price)
        rr     = (reward / risk) if risk > 0 else 0.0
        if rr < config.CRT_MIN_RR:
            tl.log_rejection(symbol, f"crt_low_rr ({rr:.2f} < {config.CRT_MIN_RR} — "
                                     f"target ${target:.2f} too close vs stop ${stop:.2f})")
            self._done_today.add(symbol)
            self._save_positions()
            return False

        qty = self._calc_qty(symbol, price, side)
        if qty < 0.01 or (side == SHORT and qty < 1):
            logger.warning(f"CRT {symbol}: qty too small ({qty:.4f}) — insufficient capital")
            return False

        # Short entries are SELL-to-open: alpaca_client.submit_market_sell opens
        # a short when no long position exists (account has shorting_enabled).
        order = (self.client.submit_market_sell(symbol, qty) if side == SHORT
                 else self.client.submit_market_buy(symbol, qty))
        if not order:
            return False

        fill_price = float(order.filled_avg_price or price)
        fill_qty   = float(order.filled_qty or qty)

        trade_id = tl.log_trade_entry(
            symbol=symbol,
            entry_price=fill_price,
            qty=fill_qty,
            rsi=None,
            signal_score=0,          # CRT is structural — there is no 0-4 score
            news_sentiment="n/a",
            market_regime=f"crt_{setup['sweep_side']}_sweep",
            mode=self.mode,
            side=("SELL" if side == SHORT else "BUY"),
        )

        # Rest the stop at the broker immediately. The polling loop cannot be
        # trusted to enforce it: a 5-minute gap is long enough for price to run
        # far past the level before the bot ever looks.
        protective = self.client.submit_protective_stop(
            symbol=symbol,
            qty=(self.client.held_qty(symbol) or fill_qty) if side != SHORT else fill_qty,
            stop_price=stop,
            side=("BUY" if side == SHORT else "SELL"),
        )
        if not protective:
            logger.warning(f"CRT {symbol}: broker stop REJECTED — position is protected only "
                           f"by the {config.CRT_POLL_SECONDS if hasattr(config,'CRT_POLL_SECONDS') else 300}s polling loop")

        self.positions[symbol] = CRTPosition(
            symbol=symbol, side=side, entry_price=fill_price, qty=fill_qty,
            trade_id=trade_id, stop_price=stop, entry_time=datetime.now(ET),
            range_high=rng["high"], range_low=rng["low"],
            sweep_extreme=setup["sweep_extreme"],
            stop_order_id=(protective.id if protective else None),
        )
        self._done_today.add(symbol)
        self._save_positions()

        logger.info(
            f"CRT ENTERED {side.upper()}: {symbol} @ ${fill_price:.2f} x{fill_qty} | "
            f"box {rng['low']:.2f}-{rng['high']:.2f} | swept {setup['sweep_side']} to "
            f"${setup['sweep_extreme']:.2f} | BOS ${setup['bos_level']:.2f} | stop ${stop:.2f}"
        )
        return True

    # ── Exits ─────────────────────────────────────────────────

    def evaluate_exits(self):
        if self.kill_switch.check():
            if self.positions:
                logger.warning(f"CRT: kill switch active — clearing "
                               f"{len(self.positions)} ghost position(s)")
                self.positions.clear()
                self._save_positions()
            return

        for symbol, pos in list(self.positions.items()):
            # The broker may have already closed this via the resting stop. If
            # so the trade is done and re-sending a market order would open a
            # fresh position in the opposite direction.
            if self._broker_stop_filled(pos):
                continue
            price = self.client.get_latest_price(symbol)
            if not price:
                continue
            reason = self._should_exit(pos, price)
            if reason:
                self._exit_trade(pos, price, reason)
        self._save_positions()

    def _broker_stop_filled(self, pos: CRTPosition) -> bool:
        """True if the resting stop executed; records the exit and drops the position."""
        if not pos.stop_order_id:
            return False
        order = self.client.get_order(pos.stop_order_id)
        if order is None or not getattr(order, "filled_at", None):
            return False

        fill = float(order.filled_avg_price or pos.stop_price)
        logger.warning(
            f"CRT: broker stop EXECUTED for {pos.symbol} @ ${fill:.2f} "
            f"(stop was ${pos.stop_price:.2f}) — exchange closed it, not the polling loop"
        )
        tl.log_trade_exit(pos.trade_id, fill,
                          f"crt_broker_stop (${fill:.2f} vs stop ${pos.stop_price:.2f})")
        self.positions.pop(pos.symbol, None)
        self._done_today.add(pos.symbol)
        self._save_positions()
        return True

    def _should_exit(self, pos: CRTPosition, price: float) -> str | None:
        if pos.stop_hit(price):
            return f"crt_stop_loss (${price:.2f} vs stop ${pos.stop_price:.2f})"

        # Primary exit is the opposite side of the box — "tap the lows, target
        # the highs". This is the take-profit the model is built around, and the
        # reward half of the R:R gate that admitted the trade. The trailing stop
        # below is only a fallback for when the target is never reached.
        target = pos.range_low if pos.is_short else pos.range_high
        if (pos.is_short and price <= target) or (not pos.is_short and price >= target):
            return f"crt_target (${price:.2f} reached box {'low' if pos.is_short else 'high'} ${target:.2f})"

        pos.update_trailing_stop(price)
        if pos.trail_hit(price):
            return (f"crt_trailing_stop (${price:.2f} vs trail ${pos.trailing_stop:.2f} | "
                    f"best=${pos.extreme_price:.2f})")
        return None

    def _exit_trade(self, pos: CRTPosition, exit_price: float, reason: str):
        """Close the position — BUY to cover a short, SELL to close a long."""
        # Release the resting stop first. Left alive it becomes a naked order
        # that could open a brand-new position the moment this one is closed.
        if pos.stop_order_id:
            self.client.cancel_order(pos.stop_order_id)
            pos.stop_order_id = None

        # Close against the broker's actual holding, not the recorded fill: a
        # crypto buy can land marginally short of the requested size and the
        # exit is then rejected for insufficient balance.
        close_qty = pos.qty
        if not pos.is_short:
            held = self.client.held_qty(pos.symbol)
            if held > 0:
                close_qty = min(pos.qty, held)

        order = (self.client.submit_market_buy(pos.symbol, close_qty) if pos.is_short
                 else self.client.submit_market_sell(pos.symbol, close_qty))
        if not order:
            logger.error(
                f"CRT: {'BUY-to-cover' if pos.is_short else 'SELL'} for {pos.symbol} "
                f"did not confirm filled — position kept in memory, will retry next cycle"
            )
            return

        fill = float(order.filled_avg_price or exit_price)
        if reason.startswith("crt_stop_loss"):
            # Modeled slippage, same haircut strategy.py applies — but a short's
            # stop fills HIGHER (worse) while a long's fills lower.
            slip = config.STOP_SLIPPAGE_PCT
            fill = round(fill * (1 + slip) if pos.is_short else fill * (1 - slip), 4)

        tl.log_trade_exit(pos.trade_id, fill, reason)
        pnl = pos.pnl_pct(fill)
        logger.info(
            f"CRT EXITED [{'WIN' if pnl > 0 else 'LOSS'}] {pos.side.upper()}: {pos.symbol} "
            f"@ ${fill:.2f} | PnL={pnl:.2%} | {reason} | held={pos.hold_minutes():.0f}min"
        )
        del self.positions[pos.symbol]
        self._save_positions()

    def flatten_for_close(self):
        """EOD flatten — closes longs AND shorts. No overnight CRT exposure."""
        if not config.ENABLE_CRT_STRATEGY or not self.positions:
            return
        logger.warning(f"CRT EOD FLATTEN: closing {len(self.positions)} position(s)")
        for symbol, pos in list(self.positions.items()):
            price = self.client.get_latest_price(symbol) or pos.entry_price
            self._exit_trade(pos, price, "crt_eod_flatten (no overnight holds)")

    # ── Summary ───────────────────────────────────────────────

    def open_positions_summary(self) -> list:
        out = []
        for symbol, pos in self.positions.items():
            price = self.client.get_latest_price(symbol) or pos.entry_price
            out.append({
                "symbol": symbol, "side": pos.side, "entry": pos.entry_price,
                "current": price, "qty": pos.qty,
                "pnl_pct": round(pos.pnl_pct(price) * 100, 2),
                "stop": pos.stop_price, "trailing_stop": pos.trailing_stop,
                "trail_active": pos.trail_active,
                "hold_minutes": round(pos.hold_minutes(), 1),
            })
        return out
