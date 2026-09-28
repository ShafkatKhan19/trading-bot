# ============================================================
#  market_studies.py — Descriptive studies of how SPY behaves.
#
#  NOT strategy tests: nothing here has a verdict, and nothing here may be
#  traded without its own pre-registration. To keep future tests honest,
#  every study uses the IN-SAMPLE years only (2016-01-04 up to the start of
#  the out-of-sample period used by every pre-registered test so far,
#  2023-07-06). The later data stays unseen for designing ideas.
#
#  With ~60 cells below, ~3 will look "significant" (|t| >= 2) by chance.
#
#  Data (all free): SPY daily and 30-minute bars already cached by
#  round2_data.py / h7_research.py; VIX daily closes from yfinance.
#
#    python market_studies.py
# ============================================================

import json
import math
import os

import numpy as np
import pandas as pd

import daily_research as r1

OUT = os.path.join("data", "studies")
ET = "America/New_York"


def cell(r: pd.Series) -> dict:
    r = r.dropna()
    n = len(r)
    sd = r.std(ddof=1) if n > 1 else float("nan")
    return {"n": n, "mean_pct": round(r.mean() * 100, 3), "up_pct": round((r > 0).mean() * 100, 1),
            "t": round(r.mean() / (sd / math.sqrt(n)), 2) if n > 1 and sd > 0 else None}


def table(title: str, rows: dict, note: str = "") -> str:
    lines = [f"\n{title}" + (f"  ({note})" if note else ""),
             f"  {'':<28}{'days':>6}{'mean %':>9}{'up %':>7}{'t':>7}"]
    for k, c in rows.items():
        t = f"{c['t']:+.2f}" if c["t"] is not None else "   —"
        lines.append(f"  {k:<28}{c['n']:>6}{c['mean_pct']:>+9.3f}{c['up_pct']:>7.1f}{t:>7}")
    return "\n".join(lines)


def load():
    spy = pd.read_pickle(os.path.join("data", "round2", "bars", "SPY.pkl"))
    bench = r1.run_monthly(spy[["open"]].rename(columns={"open": "SPY"}),
                           spy[["close"]].rename(columns={"close": "SPY"}), lambda i: {"SPY": 1.0}, 0.0)
    cutoff = r1.split(bench)[1].index[0]           # first OOS day of every registered test
    import yfinance as yf
    vix = yf.download("^VIX", start="2015-06-01", end="2026-09-26", progress=False,
                      auto_adjust=False)["Close"].squeeze()
    vix.index = pd.DatetimeIndex(vix.index.date)
    bars = pd.read_pickle(os.path.join("data", "h7", "SPY_30Min.pkl"))
    return spy, vix, bars, cutoff


def main():
    os.makedirs(OUT, exist_ok=True)
    spy, vix, bars, cutoff = load()
    c, o = spy["close"], spy["open"]
    ret = c.pct_change()
    ins = spy.index < cutoff                       # in-sample mask: every study below uses it
    report, text = {"in_sample": f"{spy.index[0].date()} -> {(cutoff - pd.Timedelta(days=1)).date()}"}, []
    text.append(f"SPY market studies — in-sample only: {report['in_sample']}  "
                f"(out-of-sample from {cutoff.date()} deliberately unused)")

    # 1. What a day looks like
    r = ret[ins].dropna()
    prof = {"days": len(r), "mean_pct": round(r.mean() * 100, 3), "stdev_pct": round(r.std() * 100, 3),
            "up_days_pct": round((r > 0).mean() * 100, 1),
            "days_beyond_2pct": int((r.abs() > 0.02).sum()), "days_beyond_3pct": int((r.abs() > 0.03).sum()),
            "normal_would_expect_beyond_3pct": round(len(r) * 2 * (1 - 0.5 * (1 + math.erf(0.03 / r.std() / math.sqrt(2)))), 1),
            "lag1_autocorr": round(r.autocorr(1), 3),
            "best_10_days_share_of_total_return": None}
    total = (1 + r).prod() - 1
    without_best10 = (1 + r.drop(r.nlargest(10).index)).prod() - 1
    prof["best_10_days_share_of_total_return"] = f"{total:.1%} total; {without_best10:.1%} without the 10 best days"
    report["1_day_profile"] = prof
    text.append("\n1. What a day looks like\n" + "\n".join(f"  {k}: {v}" for k, v in prof.items()))

    # 2. Day of week
    dow = {d: cell(ret[ins & (spy.index.dayofweek == i)]) for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"])}
    report["2_day_of_week"] = dow
    text.append(table("2. Day of week", dow))

    # 3. Turn of month: trading-day position relative to month end
    days = pd.Series(spy.index, index=spy.index)
    month = days.dt.to_period("M")
    pos_fwd = days.groupby(month).cumcount() + 1                         # 1 = first day of month
    pos_back = days.groupby(month).cumcount(ascending=False) + 1         # 1 = last day of month
    tom = {}
    for k in (4, 3, 2, 1):
        tom[f"last-{k - 1} (day -{k})" if k > 1 else "last day of month"] = cell(ret[ins & (pos_back == k).to_numpy()])
    for k in (1, 2, 3, 4):
        tom[f"day +{k} of new month"] = cell(ret[ins & (pos_fwd == k).to_numpy()])
    other = ins & (pos_back > 4).to_numpy() & (pos_fwd > 4).to_numpy()
    tom["all other days"] = cell(ret[other])
    report["3_turn_of_month"] = tom
    text.append(table("3. Turn of month", tom, "literature: last day + first 3 days"))

    # 4. Overnight vs intraday
    on = (o / c.shift(1) - 1)[ins]
    intra = (c / o - 1)[ins]
    split = {"overnight (close->open)": cell(on), "intraday (open->close)": cell(intra)}
    split_cum = {"overnight_cum": f"{(1 + on.dropna()).prod() - 1:+.1%}",
                 "intraday_cum": f"{(1 + intra.dropna()).prod() - 1:+.1%}"}
    report["4_overnight_vs_intraday"] = {**split, **split_cum}
    text.append(table("4. Overnight vs intraday", split) +
                f"\n  cumulative: overnight {split_cum['overnight_cum']}, intraday {split_cum['intraday_cum']}")

    # 5. Volatility regimes (VIX at the prior close) -> next day / next 21 days
    v = vix.reindex(spy.index).ffill().shift(1)
    fwd21 = c.shift(-21) / c - 1
    fwd21_ins = fwd21.where(ins & (spy.index + pd.Timedelta(days=31) < cutoff))   # 21d window stays in-sample
    vol = {}
    for lo, hi in ((0, 15), (15, 20), (20, 30), (30, 999)):
        m = (v >= lo) & (v < hi)
        label = f"VIX {lo}-{hi}" if hi < 999 else f"VIX {lo}+"
        vol[label + " · next day"] = cell(ret[ins & m])
        vol[label + " · next 21d"] = cell(fwd21_ins[m])
    report["5_vix_regimes"] = vol
    text.append(table("5. Volatility regimes (VIX at prior close)", vol, "21d windows overlap: t overstated"))

    # 6. After big down days
    big = {}
    for thr in (-0.02, -0.03):
        m = (ret <= thr).shift(1, fill_value=False)
        big[f"day after <= {thr:.0%}"] = cell(ret[ins & m])
        m5 = (ret <= thr)
        big[f"next 21d after <= {thr:.0%}"] = cell(fwd21_ins[m5])
    big["any day · next day"] = cell(ret[ins])
    big["any day · next 21d"] = cell(fwd21_ins)
    report["6_after_big_drops"] = big
    text.append(table("6. After big down days", big, "few cases; overlapping windows"))

    # 7. Trend: above / below the 200-day average
    sma = c.rolling(200).mean().shift(1)
    above = (c.shift(1) > sma)
    has = sma.notna()
    tr = {"above 200d · next day": cell(ret[ins & has & above]),
          "below 200d · next day": cell(ret[ins & has & ~above]),
          "above 200d · next 21d": cell(fwd21_ins[has & above]),
          "below 200d · next 21d": cell(fwd21_ins[has & ~above])}
    tr_vol = {"above": round(ret[ins & has & above].std() * math.sqrt(252) * 100, 1),
              "below": round(ret[ins & has & ~above].std() * math.sqrt(252) * 100, 1)}
    report["7_trend_200d"] = {**tr, "annualized_vol_pct": tr_vol}
    text.append(table("7. Trend (SPY vs 200-day average)", tr) +
                f"\n  annualized volatility: above {tr_vol['above']}%, below {tr_vol['below']}%")

    # 8. Intraday shape: each 30-minute bar of the regular session
    b = bars[(bars.index.time >= pd.Timestamp("09:30").time()) & (bars.index.time <= pd.Timestamp("15:30").time())]
    b = b[pd.DatetimeIndex(b.index.date) < cutoff]
    cal = pd.read_pickle(os.path.join("data", "h7", "calendar.pkl"))
    early = set(cal.loc[cal["close"] != pd.Timestamp("16:00").time(), "date"].dt.date)
    b = b[[d not in early for d in b.index.date]]      # their afternoon bars are after-hours trading
    br = b["close"] / b["open"] - 1
    shape = {}
    for t, g in br.groupby(b.index.time):
        cc = cell(g)
        cc["avg_abs_move_pct"] = round(g.abs().mean() * 100, 3)
        shape[t.strftime("%H:%M")] = cc
    report["8_intraday_shape"] = shape
    lines = ["\n8. Intraday shape (30-min bars, open->close within the bar)",
             f"  {'bar':<8}{'mean %':>9}{'up %':>7}{'t':>7}{'avg |move| %':>14}"]
    for k, cc in shape.items():
        lines.append(f"  {k:<8}{cc['mean_pct']:>+9.3f}{cc['up_pct']:>7.1f}{cc['t']:>+7.2f}{cc['avg_abs_move_pct']:>14.3f}")
    text.append("\n".join(lines))

    # 9. Costs vs typical moves: why holding period matters
    rt_cost = 2 * 0.0005
    horizons = {"30 minutes": br.abs().mean(), "1 day": r.abs().mean(),
                "1 week": (c.shift(-5) / c - 1)[ins].abs().mean(),
                "1 month": (c.shift(-21) / c - 1)[ins].abs().mean()}
    cost = {h: {"avg_abs_move_pct": round(m * 100, 3), "round_trip_cost_share_pct": round(rt_cost / m * 100, 1)}
            for h, m in horizons.items()}
    report["9_costs_vs_moves"] = cost
    text.append("\n9. Costs vs typical moves (round trip at 5 bps/side = 0.10%)\n" +
                "\n".join(f"  {h:<12} avg move {x['avg_abs_move_pct']:.3f}%  -> cost eats "
                          f"{x['round_trip_cost_share_pct']:.0f}% of a typical move" for h, x in cost.items()))

    with open(os.path.join(OUT, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    out = "\n".join(text)
    with open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8") as f:
        f.write(out)
    print(out)
    print(f"\n-> {OUT}/report.json, report.txt")


if __name__ == "__main__":
    main()
