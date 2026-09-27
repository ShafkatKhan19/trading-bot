# ============================================================
#  daily_research.py — Test of the three pre-registered low-frequency
#  ETF strategies in PREREGISTRATION_2026-09-27_daily.md.
#
#  Event-driven, share-level simulation:
#    - signals computed on the CLOSE of day t (completed bars only)
#    - orders fill at the OPEN of day t+1, sells before buys
#    - COST per side charged on every fill's notional
#    - equity marked at each close
#  Rules and verdict criteria are fixed by the pre-registration; do not
#  change them here and re-run to "improve" a result.
#
#    python daily_research.py            # download (cached) + run + verdict
# ============================================================

import math
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config

CACHE      = os.path.join("data", "daily")
START      = "2015-01-01"
EVAL_START = "2016-01-04"
SECTORS    = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
UNIVERSE   = ["SPY", "QQQ", "IWM", "DIA"] + SECTORS
COST       = 0.0005           # pre-registered: 5 bps per side
COSTS      = (0.0002, 0.0005, 0.0010)
OOS_FRAC   = 0.30
MIN_T      = 2.4
MAX_DD     = 0.20
MIN_H1_TRADES = 100


# ── data ──────────────────────────────────────────────────────
def download(symbols=UNIVERSE):
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    os.makedirs(CACHE, exist_ok=True)
    client = StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    end = datetime.now(timezone.utc) - timedelta(minutes=20)
    for s in symbols:
        path = os.path.join(CACHE, f"{s}.pkl")
        if os.path.exists(path):
            continue
        req = StockBarsRequest(symbol_or_symbols=s, timeframe=TimeFrame.Day,
                               start=datetime.fromisoformat(START).replace(tzinfo=timezone.utc),
                               end=end, feed=DataFeed.SIP, adjustment=Adjustment.ALL)
        df = client.get_stock_bars(req).df.xs(s, level="symbol")
        df.index = pd.DatetimeIndex([t.tz_convert("America/New_York").date() for t in df.index])
        df[["open", "high", "low", "close", "volume"]].to_pickle(path)
        print(f"  {s}: {len(df)} daily bars")


def load_panel(symbols=UNIVERSE):
    frames = {s: pd.read_pickle(os.path.join(CACHE, f"{s}.pkl")) for s in symbols}
    opens  = pd.DataFrame({s: f["open"] for s, f in frames.items()}).sort_index()
    closes = pd.DataFrame({s: f["close"] for s, f in frames.items()}).sort_index()
    return opens, closes


# ── indicators ────────────────────────────────────────────────
def rsi_wilder(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn
    return 100 - 100 / (1 + rs)


# ── simulation core ───────────────────────────────────────────
class Book:
    """Shares + cash; fills at a given price with a per-side cost."""

    def __init__(self, cash: float, cost: float):
        self.cash, self.cost, self.sh = cash, cost, {}

    def value(self, px: pd.Series) -> float:
        return self.cash + sum(q * px[s] for s, q in self.sh.items())

    def trade(self, s: str, qty: float, price: float):
        if abs(qty) < 1e-12:
            return
        self.cash -= qty * price + abs(qty) * price * self.cost
        self.sh[s] = self.sh.get(s, 0.0) + qty
        if abs(self.sh[s]) < 1e-12:
            del self.sh[s]

    def rebalance(self, target: dict, px: pd.Series, equity: float):
        """Move to target weights at prices px; sells first so buys use the proceeds."""
        want = {s: w * equity / px[s] for s, w in target.items() if w > 0}
        for s in list(self.sh):
            d = want.get(s, 0.0) - self.sh[s]
            if d < 0:
                self.trade(s, d, px[s])
        for s, q in want.items():
            d = q - self.sh.get(s, 0.0)
            if d > 0:
                # never spend cash we don't have (costs can make the last buy overshoot)
                d = min(d, max(0.0, self.cash) / (px[s] * (1 + self.cost)))
                self.trade(s, d, px[s])


def run_monthly(opens, closes, choose, cost):
    """choose(i) -> target weights from data up to close of day i; filled next open."""
    days = closes.index
    month_end = [i for i in range(len(days) - 1) if days[i].month != days[i + 1].month]
    rebal_on = {i + 1 for i in month_end}               # fill day
    decide = {i + 1: i for i in month_end}
    b, eq = Book(500.0, cost), []
    start = days.searchsorted(pd.Timestamp(EVAL_START))
    # take the first position on the first evaluation day
    rebal_on.add(start); decide[start] = start - 1
    for i in range(start, len(days)):
        if i in rebal_on:
            prev_eq = b.value(closes.iloc[i - 1])
            b.rebalance(choose(decide[i]), opens.iloc[i], prev_eq)
        eq.append(b.value(closes.iloc[i]))
    return pd.Series(eq, index=days[start:])


def run_h1(opens, closes, cost):
    sma200 = closes.rolling(200).mean()
    sma5   = closes.rolling(5).mean()
    rsi2   = closes.apply(lambda c: rsi_wilder(c, 2))
    days = closes.index
    start = days.searchsorted(pd.Timestamp(EVAL_START))
    b, eq, trades = Book(500.0, cost), [], []
    held = {}                        # sym -> (entry_day_index, entry_price, qty)
    sells, buys = [], []             # decided at close i-1, filled at open i
    for i in range(start, len(days)):
        o, c = opens.iloc[i], closes.iloc[i]
        prev_eq = b.value(closes.iloc[i - 1])
        for s in sells:
            e_i, e_px, q = held.pop(s)
            b.trade(s, -q, o[s])
            trades.append(dict(symbol=s, entry=days[e_i], exit=days[i], days=i - e_i,
                               net=(o[s] * (1 - cost)) / (e_px * (1 + cost)) - 1))
        for s in buys:
            q = min(0.20 * prev_eq, max(0.0, b.cash) / (1 + cost)) / o[s]
            if q > 0:
                b.trade(s, q, o[s])
                held[s] = (i, o[s], q)
        eq.append(b.value(c))
        # decisions at today's close for tomorrow's open
        sells = [s for s, (e_i, _, _) in held.items()
                 if c[s] > sma5[s].iloc[i] or (i - e_i + 1) >= 10]
        free = 5 - (len(held) - len(sells))
        cands = [(rsi2[s].iloc[i], s) for s in UNIVERSE
                 if s not in held and c[s] > sma200[s].iloc[i] and rsi2[s].iloc[i] < 10]
        buys = [s for _, s in sorted(cands)[:max(0, free)]]
    return pd.Series(eq, index=days[start:]), pd.DataFrame(trades)


def h2_choose(closes):
    sma = closes["SPY"].rolling(200).mean()
    return lambda i: {"SPY": 1.0} if closes["SPY"].iloc[i] > sma.iloc[i] else {}


def h3_choose(closes):
    sma = closes[SECTORS].rolling(200).mean()
    mom = closes[SECTORS] / closes[SECTORS].shift(126) - 1
    def choose(i):
        top = mom.iloc[i].sort_values(ascending=False).index[:3]
        return {s: 1 / 3 for s in top if closes[s].iloc[i] > sma[s].iloc[i]}
    return choose


# ── statistics ────────────────────────────────────────────────
def stats(equity: pd.Series) -> dict:
    r = equity.pct_change().dropna()
    n, sd = len(r), r.std(ddof=1)
    peak = equity.cummax()
    years = n / 252
    return {
        "days": n,
        "cagr": (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0,
        "sharpe": r.mean() / sd * math.sqrt(252) if sd > 0 else 0.0,
        "t": r.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0,
        "max_dd": float(((peak - equity) / peak).max()),
        "exposure": float((r != 0).mean()),
    }


def split(equity: pd.Series):
    cut = int(len(equity) * (1 - OOS_FRAC))
    # OOS equity starts at the last IS close so its first return is a real day
    return equity.iloc[:cut + 1], equity.iloc[cut:]


def verdict(name, oos, bench_oos, n_trades=None):
    fails = []
    if oos["t"] < MIN_T:
        fails.append(f"t {oos['t']:.2f} < {MIN_T}")
    if oos["sharpe"] < bench_oos["sharpe"]:
        fails.append(f"Sharpe {oos['sharpe']:.2f} < SPY buy&hold {bench_oos['sharpe']:.2f}")
    if oos["max_dd"] > MAX_DD:
        fails.append(f"max drawdown {oos['max_dd']:.1%} > {MAX_DD:.0%}")
    if n_trades is not None and n_trades < MIN_H1_TRADES:
        fails.append(f"only {n_trades} OOS trades < {MIN_H1_TRADES}")
    return ("PASS" if not fails else "FAIL"), fails


def fmt(label, s):
    return (f"  {label:<14} CAGR {s['cagr']:+6.1%}  Sharpe {s['sharpe']:5.2f}  t {s['t']:+5.2f}  "
            f"maxDD {s['max_dd']:5.1%}  in-market {s['exposure']:4.0%}")


def main():
    download()
    opens, closes = load_panel()
    opens, closes = opens.dropna(), closes.dropna()
    print(f"Data {closes.index[0]} -> {closes.index[-1]}, {len(UNIVERSE)} ETFs")

    runs = {}
    for c in COSTS:
        bench = run_monthly(opens, closes, lambda i: {"SPY": 1.0}, c)
        h1, h1_trades = run_h1(opens, closes, c)
        runs[c] = {"SPY buy&hold": (bench, None),
                   "H1 RSI2 pullback": (h1, h1_trades),
                   "H2 SPY 200d trend": (run_monthly(opens, closes, h2_choose(closes), c), None),
                   "H3 sector momentum": (run_monthly(opens, closes, h3_choose(closes), c), None)}

    base = runs[COST]
    b_is, b_oos = split(base["SPY buy&hold"][0])
    print(f"\nIn-sample {b_is.index[0]} -> {b_is.index[-1]} | "
          f"OUT-OF-SAMPLE {b_oos.index[0]} -> {b_oos.index[-1]} | cost {COST:.2%}/side\n")
    for name, (eq, trades) in base.items():
        e_is, e_oos = split(eq)
        print(name)
        print(fmt("in-sample", stats(e_is)))
        print(fmt("OUT-OF-SAMPLE", stats(e_oos)))
        if name.startswith("SPY"):
            print()
            continue
        n_oos = None
        if trades is not None and len(trades):
            t_oos = trades[pd.to_datetime(trades["entry"]) >= pd.Timestamp(e_oos.index[0])]
            n_oos = len(t_oos)
            print(f"  trades: {len(trades)} total, {n_oos} OOS, OOS win {(t_oos.net > 0).mean():.1%}, "
                  f"avg {t_oos.net.mean():+.2%}/trade, avg hold {t_oos.days.mean():.1f}d")
        v, why = verdict(name, stats(e_oos), stats(b_oos), n_oos)
        print(f"  VERDICT: {v}" + "".join(f"\n    - {w}" for w in why) + "\n")

    print("Cost sensitivity (OUT-OF-SAMPLE Sharpe / CAGR):")
    for name in base:
        cells = []
        for c in COSTS:
            s = stats(split(runs[c][name][0])[1])
            cells.append(f"{c:.2%}: {s['sharpe']:.2f} / {s['cagr']:+.1%}")
        print(f"  {name:<20} " + " | ".join(cells))


if __name__ == "__main__":
    main()
