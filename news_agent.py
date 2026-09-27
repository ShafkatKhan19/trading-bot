# ============================================================
#  news_agent.py — News sentiment sub-agent
#  Scores recent headlines for each ticker: bullish/bearish/neutral,
#  and applies an earnings blackout from REAL earnings dates.
#
#  Rewritten 2026-09-27. The previous version:
#    - matched keywords as substrings, so "ban" hit "bank", "miss" hit
#      "mission", "sec" hit "second"/"sector"
#    - raised an "earnings blackout" whenever any headline contained the
#      word "earnings" or "q1".."q4" — 77 of the 91 entries the news gate
#      blocked (all 11 symbol-days checked were weeks from a real report;
#      e.g. PLTR blocked 2026-09-22..25, next earnings 2026-11-02)
#    - ignored headline age
#
#  Now:
#    - headlines: Alpaca News (symbol-tagged, timestamped; same API keys),
#      Yahoo RSS as fallback; only the last NEWS_LOOKBACK_HOURS
#    - earnings blackout: the earnings date and the next session, from
#      yfinance's earnings calendar (cached daily)
#    - scoring: whole-word keyword matching by default, or Claude when
#      NEWS_SENTIMENT_ENGINE=claude (falls back to keywords on any failure)
# ============================================================

import json
import logging
import os
import re
import time as _time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

import config

logger = logging.getLogger(__name__)

# ── Keyword lists (whole-word / whole-phrase matches only) ────
# Generic words that appear in neutral finance copy ("risk", "loss",
# "decline", "sell", "buy", "profit", "shortage") were removed — they fired
# on analyst boilerplate far more often than on news that moves a stock.
BULLISH_KEYWORDS = [
    "beats", "beat estimates", "record revenue", "record high", "upgrade", "upgraded",
    "outperform", "raises guidance", "raised guidance", "strong demand", "partnership",
    "wins contract", "awarded contract", "breakthrough", "expansion", "revenue growth",
    "bullish", "surge", "surges", "rally", "rallies", "all-time high",
    "raises price target", "price target raised", "buyback",
]
BEARISH_KEYWORDS = [
    "misses", "missed estimates", "downgrade", "downgraded", "underperform",
    "lowers guidance", "cuts guidance", "weak demand", "layoffs", "investigation",
    "sec probe", "sec charges", "lawsuit", "sued", "recall", "tariff", "tariffs",
    "export ban", "sanctions", "crash", "plunge", "plunges", "antitrust",
    "bearish", "slump", "slumps", "disappoints", "price target cut", "lowers price target",
]


def _compile(words):
    return [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in words]


_BULL = _compile(BULLISH_KEYWORDS)
_BEAR = _compile(BEARISH_KEYWORDS)


@dataclass
class SentimentResult:
    symbol: str
    score: float          # -1.0 (very bearish) to +1.0 (very bullish)
    label: str            # 'bullish' | 'bearish' | 'neutral'
    near_earnings: bool   # True = blackout — no new entries
    headline_count: int
    top_headlines: list
    engine: str = "keyword"


# ── Headlines ─────────────────────────────────────────────────

def _alpaca_headlines(symbol: str, since: datetime) -> list:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    client = NewsClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)
    resp = client.get_news(NewsRequest(symbols=symbol, start=since, limit=30))
    items = resp.data.get("news", []) if hasattr(resp, "data") else resp.news
    return [{"title": n.headline, "description": (n.summary or ""),
             "link": n.url or "", "published": n.created_at.isoformat()} for n in items]


def _yahoo_headlines(symbol: str, since: datetime) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code != 200:
        logger.warning(f"Yahoo RSS returned {resp.status_code} for {symbol}")
        return []
    out = []
    for item in ET.fromstring(resp.content).findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        try:
            when = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue                       # undated headline: can't prove it's recent
        if not title or when < since:
            continue
        out.append({"title": title, "description": (item.findtext("description") or "").strip(),
                    "link": (item.findtext("link") or "").strip(), "published": when.isoformat()})
    return out


def fetch_headlines(symbol: str) -> list:
    """Headlines from the last NEWS_LOOKBACK_HOURS: Alpaca News, else Yahoo RSS."""
    since = datetime.now(timezone.utc) - timedelta(hours=config.NEWS_LOOKBACK_HOURS)
    try:
        return _alpaca_headlines(symbol, since)
    except Exception as e:
        logger.warning(f"Alpaca news failed for {symbol} ({e}) — falling back to Yahoo RSS")
    try:
        return _yahoo_headlines(symbol, since)
    except Exception as e:
        logger.error(f"News fetch failed for {symbol}: {e}")
        return []


# ── Earnings calendar ─────────────────────────────────────────

EARNINGS_CACHE = os.path.join("data", "earnings_dates.json")
_earnings: dict = {}


def _load_earnings_cache() -> dict:
    try:
        with open(EARNINGS_CACHE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def earnings_dates(symbol: str, refresh_days: int = 1) -> list[date]:
    """Past and upcoming earnings dates, refreshed at most once per refresh_days."""
    global _earnings
    if not _earnings:
        _earnings = _load_earnings_cache()
    entry = _earnings.get(symbol)
    today = date.today().isoformat()
    if not entry or (date.today() - date.fromisoformat(entry["fetched"])).days >= refresh_days:
        try:
            import yfinance as yf
            df = yf.Ticker(symbol).get_earnings_dates(limit=24)
            dates = sorted({ts.date().isoformat() for ts in df.index})
            entry = {"fetched": today, "dates": dates}
            _earnings[symbol] = entry
            os.makedirs("data", exist_ok=True)
            with open(EARNINGS_CACHE, "w") as f:
                json.dump(_earnings, f, indent=1)
        except Exception as e:
            logger.warning(f"{symbol}: earnings calendar unavailable ({e})")
            if not entry:
                return []
    return [date.fromisoformat(d) for d in entry["dates"]]


def in_earnings_blackout(symbol: str, on: date = None, dates: list = None) -> bool:
    """
    True on an earnings date and the next weekday. The bot flattens every
    position by 15:55, so it can never hold through the after-close report
    itself; the risk is entering on the release/reaction session, when a
    15-minute momentum signal is mostly the earnings gap talking.
    """
    on = on or date.today()
    for e in (dates if dates is not None else earnings_dates(symbol)):
        nxt = e + timedelta(days=3 if e.weekday() == 4 else 1)
        if on == e or on == nxt:
            return True
    return False


# ── Scoring ───────────────────────────────────────────────────

def score_headlines(headlines: list) -> float:
    """Whole-word keyword score in [-1, 1]; 0.0 when nothing matches."""
    bull = bear = 0
    for h in headlines:
        text = f"{h['title']} {h.get('description', '')}" if isinstance(h, dict) else str(h)
        bull += sum(bool(p.search(text)) for p in _BULL)
        bear += sum(bool(p.search(text)) for p in _BEAR)
    total = bull + bear
    return round((bull - bear) / total, 3) if total else 0.0


_CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "score": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["label", "score", "reason"],
    "additionalProperties": False,
}

_CLAUDE_SYSTEM = (
    "You rate recent news for one US stock from the point of view of an intraday "
    "long-only trader deciding whether to open a position in the next few hours. "
    "Judge only what the headlines say about this company's near-term price; ignore "
    "headlines where the stock is only mentioned in passing. Return label "
    "'bearish' only for genuinely negative company-specific news (guidance cut, "
    "downgrade, probe, lawsuit, recall, export restriction), 'bullish' for genuinely "
    "positive company-specific news, else 'neutral'. score is -1.0 to 1.0."
)


def score_with_claude(symbol: str, headlines: list) -> tuple[float, str] | None:
    """Claude classification, or None on any failure (caller falls back)."""
    if not headlines:
        return 0.0, "neutral"
    try:
        import anthropic
        client = anthropic.Anthropic()
        lines = "\n".join(f"- [{h['published'][:16]}] {h['title']}" for h in headlines[:20])
        resp = client.beta.messages.create(
            model=config.NEWS_LLM_MODEL,
            max_tokens=1024,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=_CLAUDE_SYSTEM,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": _CLAUDE_SCHEMA}},
            messages=[{"role": "user", "content": f"Ticker: {symbol}\nHeadlines:\n{lines}"}],
        )
        if resp.stop_reason == "refusal":
            logger.warning(f"{symbol}: Claude declined to rate headlines — keyword fallback")
            return None
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        score = max(-1.0, min(1.0, float(data["score"])))
        logger.info(f"News [{symbol}] Claude: {data['label']} ({score:+.2f}) — {data['reason'][:120]}")
        return round(score, 3), data["label"]
    except Exception as e:
        logger.warning(f"{symbol}: Claude sentiment failed ({e}) — keyword fallback")
        return None


def label_from_score(score: float) -> str:
    if score >= 0.2:
        return "bullish"
    elif score <= -0.2:
        return "bearish"
    return "neutral"


# ── Entry point ───────────────────────────────────────────────

_cache: dict = {}   # symbol -> (monotonic time, SentimentResult)


def analyse(symbol: str) -> SentimentResult:
    """
    Full news check for one ticker. Cached for NEWS_CACHE_MINUTES: exits call
    this every cycle for every open position, and neither the news nor the
    earnings calendar changes that fast.
    """
    hit = _cache.get(symbol)
    if hit and _time.monotonic() - hit[0] < config.NEWS_CACHE_MINUTES * 60:
        return hit[1]

    headlines = fetch_headlines(symbol)
    engine, claude = "keyword", None
    if config.NEWS_SENTIMENT_ENGINE == "claude":
        claude = score_with_claude(symbol, headlines)
    if claude is not None:
        (score, label), engine = claude, "claude"
    else:
        score = score_headlines(headlines)
        label = label_from_score(score)
    near_earnings = in_earnings_blackout(symbol)

    result = SentimentResult(
        symbol=symbol, score=score, label=label, near_earnings=near_earnings,
        headline_count=len(headlines), top_headlines=[h["title"] for h in headlines[:5]],
        engine=engine,
    )
    _cache[symbol] = (_time.monotonic(), result)

    try:
        import trade_logger as tl
        tl.log_news(symbol, headlines, score, label)
    except Exception as e:
        logger.error(f"Failed to persist news for {symbol}: {e}")

    logger.info(
        f"News [{symbol}]: {label} (score={score}, {engine}) | "
        f"headlines={len(headlines)} in {config.NEWS_LOOKBACK_HOURS}h | earnings_blackout={near_earnings}"
    )
    return result


def is_safe_to_enter(sentiment: SentimentResult) -> tuple[bool, str]:
    """Gate function called by strategy.py. Returns (safe, reason)."""
    if sentiment.near_earnings:
        return False, f"{sentiment.symbol}: earnings blackout (earnings date or the session after)"
    if sentiment.label == "bearish":
        return False, f"{sentiment.symbol}: bearish sentiment (score={sentiment.score}, {sentiment.engine})"
    return True, f"{sentiment.symbol}: news OK ({sentiment.label})"
