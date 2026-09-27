# ============================================================
#  intraday_backtest.py — Replay of what paper_runner.py actually runs
#
#  backtest_runner.py tests the OLD daily/4H swing rules. The live bot runs
#  DAY_TRADING_MODE (15Min signals, minute-based exits, EOD flatten) plus the
#  CRT 8AM-box model, and neither had any backtest. This replays both books
#  together, cycle by cycle, reusing the live code's own decision functions
#  (signals.analyse, crt_strategy.compute_range/detect_setup) so the test
#  cannot drift from the thing being tested.
#
#  Mirrors the live loop:
#    - 5-minute cycles 09:30-16:00 ET; per cycle: swing exits, swing entries,
#      CRT exits, CRT entries (paper_runner.run_cycle order)
#    - DATA DELAY: bars are only usable once fully inside the free SIP feed
#      (end = now - 16min), exactly as alpaca_client.get_bars serves them in
#      BAR_FEED="sip_delayed" mode. A bar closing at T drives decisions from
#      the first cycle >= T + 16min.
#    - Swing stops are POLLED (checked at cycle prices, filled at market);
#      CRT stops REST at the broker (filled intrabar at min(stop, bar open)
#      for longs — gaps punch through — max(...) for shorts)
#    - EOD flatten at EOD_FLATTEN_TIME; no entries at/after it
#    - $500 capital cap, conviction sizing, T+1 settled-cash budget,
#      CRT shorts off for a cash account, VIX spike gate, QQQ 50MA regime,
#      stock 50MA uptrend, stop-loss cooldown, macro blackout, daily and
#      cumulative kill switches
#
#  Known, documented differences from live:
#    - News gate: the earnings blackout IS replayed (real historical earnings
#      dates); the bearish-headline check is not (no headline archive). Live
#      can only block more entries than the backtest takes, never fewer.
#    - Daily context (QQQ regime, VIXY, stock 50MA) uses prior-day closes,
#      evaluated once per session; live re-reads it every cycle including
#      today's partial bar, so live can block entries mid-session on a VIX
#      spike that the backtest trades through. Biases the backtest OPTIMISTIC.
#    - News-reversal exit (bearish headline while in profit) is not replayed.
#    - Cycle price = open of the 5Min bar at the cycle time (SIP). Live uses
#      the IEX quote midpoint — same price for these liquid names in RTH.
#
#  Costs: every fill is charged COST per side on top of the reference price,
#  reported at several levels; the validation verdict uses VERDICT_COST.
#
#    python intraday_backtest.py            # full run + validation report
# ============================================================

import argparse
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

import config
import crt_strategy as crt
import macro_calendar as macro
import news_agent
import signals as sig
import validation
from intraday_data import load
from sizing import floor_qty

DATA_DELAY    = timedelta(minutes=config.SIP_DELAY_MINUTES)   # BAR_FEED="sip_delayed"
CYCLE         = timedelta(minutes=5)
BAR15         = timedelta(minutes=15)
BAR5          = timedelta(minutes=5)
SIGNAL_WINDOW = timedelta(days=10)      # paper_runner: 15Min bars, days=10
COST_LEVELS   = (0.0005, 0.0010, 0.0020)
VERDICT_COST  = 0.0010                  # pre-registered: 10 bps per side
OUT_CSV       = "data/intraday_trades.csv"

# NYSE 13:00 early closes inside the data window.
HALF_DAYS = {date(2024, 7, 3), date(2024, 11, 29), date(2024, 12, 24),
             date(2025, 7, 3), date(2025, 11, 28), date(2025, 12, 24),
             date(2026, 11, 27), date(2026, 12, 24)}


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def resample_15(d5: pd.DataFrame) -> pd.DataFrame:
    """5Min -> 15Min, stamped at bar open like Alpaca's own 15Min bars."""
    out = d5.resample("15min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna(subset=["open"])


@dataclass
class Pos:
    book: str            # "swing" | "crt"
    symbol: str
    side: str            # crt.LONG | crt.SHORT
    entry: float
    qty: float
    stop: float
    entry_time: datetime
    session: date
    score: int = 0
    target: float = None
    trailing: float = None
    extreme: float = None
    trail_active: bool = False

    def __post_init__(self):
        self.trailing = self.stop
        self.extreme  = self.entry

    @property
    def short(self) -> bool:
        return self.side == crt.SHORT

    def gross_pct(self, px: float) -> float:
        return (self.entry - px) / self.entry if self.short else (px - self.entry) / self.entry

    def update_trail(self, px: float):
        """Same ratchet as strategy.Position / CRTPosition.update_trailing_stop."""
        if self.short:
            self.extreme = min(self.extreme, px)
            if px <= self.entry * (1 - config.TRAIL_ACTIVATION_PCT):
                self.trail_active = True
            if self.trail_active:
                self.trailing = min(self.trailing, round(self.extreme * (1 + config.TRAIL_STOP_PCT), 2))
        else:
            self.extreme = max(self.extreme, px)
            if px >= self.entry * (1 + config.TRAIL_ACTIVATION_PCT):
                self.trail_active = True
            if self.trail_active:
                self.trailing = max(self.trailing, round(self.extreme * (1 - config.TRAIL_STOP_PCT), 2))


def net_pct(side: str, entry: float, exit_: float, cost: float) -> float:
    if side == crt.SHORT:
        return (entry * (1 - cost) - exit_ * (1 + cost)) / entry
    return (exit_ * (1 - cost) - entry * (1 + cost)) / entry


class Replay:
    def __init__(self, start: date, end: date):
        logging.disable(logging.WARNING)   # live code logs every rejection
        self.syms  = list(config.TICKERS)
        self.d5    = {s: load(s, "5Min") for s in self.syms}
        self.d15   = {s: resample_15(self.d5[s]) for s in self.syms}
        self.daily = {s: load(s, "1Day") for s in self.syms}
        self.qqq   = load(config.REGIME_TICKER, "1Day")
        self.vixy  = load(config.VIX_TICKER, "1Day")
        for df in [self.qqq, self.vixy, *self.daily.values()]:
            df.index = pd.DatetimeIndex([ts.date() for ts in df.index])
        first5 = max(df.index[0] for df in self.d5.values()).date() + timedelta(days=12)
        self.sessions = [d.date() for d in self.qqq.index
                         if max(start, first5) <= d.date() <= end]
        self.earn  = {s: news_agent.earnings_dates(s) for s in self.syms}
        self.idx5  = {s: self.d5[s].index for s in self.syms}
        self.idx15 = {s: self.d15[s].index for s in self.syms}
        self.flat  = _t(config.EOD_FLATTEN_TIME)

        self.equity     = config.ACCOUNT_CAPITAL
        self.peak       = self.equity
        self.halted     = False                # cumulative kill switch
        self.trades     = []
        self.last_exit  = {}                   # symbol -> (reason, date)
        self.sig_cache  = {}

    # ── data access with the live delay ───────────────────────
    def price_at(self, s: str, ts) -> float | None:
        idx = self.idx5[s]
        i = idx.searchsorted(ts, "left")
        if i < len(idx) and idx[i] == ts:
            return float(self.d5[s]["open"].iat[i])
        return float(self.d5[s]["close"].iat[i - 1]) if i > 0 else None

    def avail15(self, s: str, now) -> tuple[int, int]:
        """[i0, i1) slice of 15Min bars usable at `now`: complete by now - DATA_DELAY."""
        idx = self.idx15[s]
        i1 = idx.searchsorted(now - DATA_DELAY - BAR15, "right")
        i0 = idx.searchsorted(now - SIGNAL_WINDOW, "left")
        return i0, i1

    # ── gates shared with live ────────────────────────────────
    def daily_ctx(self, d: date) -> tuple[bool, bool, dict]:
        prior = lambda df, n: df[df.index < pd.Timestamp(d)].tail(n)
        q = prior(self.qqq, 85)
        regime = sig.is_market_bullish(q)
        vix_ok = sig.is_volatility_safe(prior(self.vixy, 30))
        up = {s: sig.is_stock_in_uptrend(prior(self.daily[s], 85), q) for s in self.syms}
        return regime, vix_ok, up

    def in_cooldown(self, s: str, d: date) -> bool:
        last = self.last_exit.get(s)
        return bool(last and "stop_loss" in last[0] and (d - last[1]).days < config.TICKER_COOLDOWN_DAYS)

    def swing_signal(self, s: str, now):
        i0, i1 = self.avail15(s, now)
        if i1 <= 0:
            return None
        key = (s, i1)
        if key not in self.sig_cache:
            rules = config.get_segment_rules(s)
            r = sig.analyse(s, self.d15[s].iloc[i0:i1], rules)
            ok = (r.is_entry_valid(rules["min_signal_score"])
                  and not r.candlestick_warning
                  and not (config.REQUIRE_ATTENTION_ON_BORDERLINE
                           and r.score == rules["min_signal_score"] and not r.attention_confirms)
                  and not (config.REQUIRE_TIER1_SIGNALS and not sig.has_tier1_signals(r))
                  and not (r.rsi is not None and r.rsi < rules["rsi_min_entry"]))
            self.sig_cache[key] = r.score if ok else None
        return self.sig_cache[key]

    def deteriorating(self, s: str, now, px: float) -> bool:
        _, i1 = self.avail15(s, now)
        n = config.NO_PROGRESS_MA_PERIOD
        if i1 < n:
            return True
        return px < float(self.d15[s]["close"].iloc[i1 - n:i1].mean())

    # ── bookkeeping ───────────────────────────────────────────
    def close(self, pos: Pos, px: float, when, reason: str, book: dict):
        g = pos.gross_pct(px)
        pnl = net_pct(pos.side, pos.entry, px, VERDICT_COST) * pos.entry * pos.qty
        self.equity += pnl
        self.day_realized += pnl
        self.trades.append(dict(strategy=pos.book, symbol=pos.symbol, side=pos.side,
                                session=pos.session, entry_time=pos.entry_time, exit_time=when,
                                entry_price=pos.entry, exit_price=px, qty=pos.qty,
                                gross_pct=g, exit_reason=reason, score=pos.score))
        self.last_exit[pos.symbol] = (reason, pos.session)
        del book[pos.symbol]

    def size(self, s: str, px: float, frac: float, whole: bool = False) -> float:
        capital = min(self.equity, config.ACCOUNT_CAPITAL)
        qty = capital * config.MAX_POSITION_PCT * frac / px
        if whole:
            return float(int(qty))
        qty = floor_qty(qty)
        if config.ENFORCE_T1_SETTLEMENT and qty * px > self.cash_left:
            qty = floor_qty(self.cash_left / px)
        return qty if qty >= 0.01 else 0.0

    # ── one session ───────────────────────────────────────────
    def run_day(self, d: date):
        regime, vix_ok, uptrend = self.daily_ctx(d)
        close_t = time(13, 0) if d in HALF_DAYS else time(16, 0)
        flat_t  = (datetime.combine(d, close_t) - timedelta(minutes=5)).time() \
            if d in HALF_DAYS else self.flat
        at = lambda tt: pd.Timestamp(datetime.combine(d, tt), tz="America/New_York")
        day0, day1 = at(time(0)), at(time(0)) + timedelta(days=1)

        def day_slice(df):
            return df.iloc[df.index.searchsorted(day0, "left"):df.index.searchsorted(day1, "left")]

        self.cash_left = min(self.equity, config.ACCOUNT_CAPITAL)
        self.day_realized = 0.0
        day_base = min(self.equity, config.ACCOUNT_CAPITAL)
        day_killed = False
        swing, book = {}, {}

        # CRT: box + first confirmed setup per symbol (detect_setup is sequential
        # and stops at the first BOS, so running it once on the whole session
        # equals running it every cycle on growing data).
        pending = {}
        crt_skip = macro.crt_blocked_today(d)
        if config.ENABLE_CRT_STRATEGY and not crt_skip:
            for s in config.CRT_SYMBOLS:
                rng = crt.compute_range(day_slice(self.d15[s]), d)
                if rng is None or rng["width_pct"] < config.CRT_MIN_RANGE_PCT:
                    continue
                st = crt.detect_setup(day_slice(self.d5[s]), rng, d)
                if st["stage"] == "confirmed":
                    ready = (st["entry_time"] + BAR5 + DATA_DELAY).ceil("5min")
                    pending[s] = (st, rng, ready)

        now = at(time(9, 30))
        end = at(close_t)
        while now <= end:
            # CRT resting stops fire intrabar over the bar that just finished.
            for s, p in list(book.items()):
                i = self.idx5[s].searchsorted(now - BAR5, "left")
                if i < len(self.idx5[s]) and self.idx5[s][i] == now - BAR5 and self.idx5[s][i] >= p.entry_time:
                    bar = self.d5[s].iloc[i]
                    if (p.short and bar.high >= p.stop) or (not p.short and bar.low <= p.stop):
                        fill = max(p.stop, bar.open) if p.short else min(p.stop, bar.open)
                        self.close(p, float(fill), now - BAR5, "crt_broker_stop", book)

            px = {s: self.price_at(s, now) for s in self.syms}
            # A held symbol with no bar yet at `now` keeps its entry price as the mark.
            for bk in (swing, book):
                for s, p in bk.items():
                    px[s] = px[s] or p.entry

            # Kill switches (daily on capped base, cumulative from peak).
            unreal = sum(p.gross_pct(px[s]) * p.entry * p.qty for bk in (swing, book)
                         for s, p in bk.items())
            if not day_killed and (self.day_realized + unreal) <= -config.KILL_SWITCH_PCT * day_base:
                day_killed = True
                for bk, tag in ((swing, "kill_switch"), (book, "kill_switch")):
                    for s, p in list(bk.items()):
                        self.close(p, px[s], now, tag, bk)
            self.peak = max(self.peak, self.equity)
            if (self.peak - self.equity) / min(self.peak, config.ACCOUNT_CAPITAL) >= config.CUMULATIVE_KILL_SWITCH_PCT:
                self.halted = True
                for bk in (swing, book):
                    for s, p in list(bk.items()):
                        self.close(p, px[s], now, "cumulative_kill_switch", bk)
                return

            # EOD flatten.
            if now.time() >= flat_t:
                for bk in (swing, book):
                    for s, p in list(bk.items()):
                        self.close(p, px[s], now, "eod_flatten", bk)
                now += CYCLE
                continue

            # ── swing exits (polled) ──
            for s, p in list(swing.items()):
                c = px[s]
                held = (now - p.entry_time).total_seconds() / 60
                if c <= p.stop:
                    self.close(p, c, now, "stop_loss", swing); continue
                p.update_trail(c)
                if p.trail_active and c <= p.trailing:
                    self.close(p, c, now, "trailing_stop", swing); continue
                if (held >= config.NO_PROGRESS_MINUTES
                        and p.gross_pct(c) < config.NO_PROGRESS_MIN_GAIN_INTRADAY
                        and self.deteriorating(s, now, c)):
                    self.close(p, c, now, "no_progress", swing); continue
                if held >= config.MAX_HOLD_MINUTES:
                    self.close(p, c, now, "time_exit", swing); continue

            blocked = day_killed or bool(macro.entry_blocked(now.to_pydatetime()))

            # ── swing entries ──
            if regime and vix_ok and not blocked:
                for s in self.syms:
                    if s in swing or len(swing) >= config.MAX_OPEN_POSITIONS or not uptrend[s]:
                        continue
                    if self.in_cooldown(s, d):
                        continue
                    if news_agent.in_earnings_blackout(s, d, self.earn[s]):
                        continue
                    score = self.swing_signal(s, now)
                    if score is None or not px[s]:
                        continue
                    mult = config.SCORE_POSITION_MULTIPLIERS.get(score, 0.5)
                    qty = self.size(s, px[s], mult)
                    if qty <= 0:
                        continue
                    rules = config.get_segment_rules(s)
                    swing[s] = Pos("swing", s, crt.LONG, px[s], qty,
                                   round(px[s] * (1 - rules["stop_loss_pct"]), 2), now, d, score)
                    self.cash_left -= qty * px[s]

            # ── CRT exits (polled target / trail; stop is at the broker) ──
            for s, p in list(book.items()):
                c = px[s]
                if (p.short and c >= p.stop) or (not p.short and c <= p.stop):
                    self.close(p, c, now, "crt_stop_loss", book); continue
                if (p.short and c <= p.target) or (not p.short and c >= p.target):
                    self.close(p, c, now, "crt_target", book); continue
                p.update_trail(c)
                if p.trail_active and ((p.short and c >= p.trailing) or (not p.short and c <= p.trailing)):
                    self.close(p, c, now, "crt_trailing_stop", book); continue

            # ── CRT entries ──
            if vix_ok and not blocked:
                for s in config.CRT_SYMBOLS:
                    if s not in pending or s in book:
                        continue
                    st, rng, ready = pending[s]
                    if now < ready:
                        continue
                    if s in swing:
                        continue                       # live logs and retries next cycle
                    if len(book) >= config.CRT_MAX_OPEN_POSITIONS:
                        break
                    del pending[s]                     # from here the day's setup is consumed
                    c, side, stop = px[s], st["bias"], st["stop_price"]
                    if not c or (side == crt.SHORT and stop <= c) or (side == crt.LONG and stop >= c):
                        continue
                    if side == crt.SHORT and not config.CRT_ALLOW_SHORTS:
                        continue
                    target = rng["low"] if side == crt.SHORT else rng["high"]
                    risk = abs(c - stop)
                    if risk <= 0 or abs(target - c) / risk < config.CRT_MIN_RR:
                        continue
                    qty = self.size(s, c, 1.0, whole=(side == crt.SHORT))
                    if qty <= 0 or (side == crt.SHORT and qty < 1):
                        continue
                    book[s] = Pos("crt", s, side, c, qty, stop, now, d, target=target)
                    if side == crt.LONG:
                        self.cash_left -= qty * c
            now += CYCLE

        for bk in (swing, book):                        # safety: nothing overnight
            for s, p in list(bk.items()):
                self.close(p, self.price_at(s, end), end, "eod_flatten", bk)

    def run(self) -> pd.DataFrame:
        for i, d in enumerate(self.sessions):
            if self.halted:
                print(f"  cumulative kill switch tripped — stopped on {d}")
                break
            self.run_day(d)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(self.sessions)} sessions | trades {len(self.trades)} "
                      f"| equity ${self.equity:.2f}", flush=True)
        return pd.DataFrame(self.trades)


def with_costs(trades: pd.DataFrame, cost: float) -> pd.DataFrame:
    t = trades.copy()
    t["cost_per_side"] = cost
    t["net_pct"] = [net_pct(s, e, x, cost) for s, e, x in
                    zip(t["side"], t["entry_price"], t["exit_price"])]
    t["net_usd"] = t["net_pct"] * t["entry_price"] * t["qty"]
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    a = ap.parse_args()

    rep = Replay(date.fromisoformat(a.start), date.fromisoformat(a.end))
    print(f"Replaying {len(rep.sessions)} sessions {rep.sessions[0]} -> {rep.sessions[-1]}")
    trades = rep.run()
    if trades.empty:
        print("No trades.")
        return
    with_costs(trades, VERDICT_COST).to_csv(OUT_CSV, index=False)

    print("\nExit reasons:")
    print(trades.groupby(["strategy", "exit_reason"]).size().to_string())
    print("\nCost sensitivity (all sessions):")
    for strat in sorted(trades["strategy"].unique()):
        for c in COST_LEVELS:
            t = with_costs(trades[trades["strategy"] == strat], c)
            print(f"  {strat:<6} {c:.2%}/side: n={len(t)} mean={t['net_pct'].mean():+.3%} "
                  f"win={(t['net_pct'] > 0).mean():.1%} net=${t['net_usd'].sum():+.2f}")
    print(f"\n=== Pre-registered verdict (cost {VERDICT_COST:.2%}/side) ===")
    t = with_costs(trades, VERDICT_COST)
    for strat in sorted(t["strategy"].unique()):
        r = validation.evaluate(t, strat)
        validation.save(r)
        print(validation.format_report(r))


if __name__ == "__main__":
    main()
