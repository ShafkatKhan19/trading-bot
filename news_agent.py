# ============================================================
#  news_agent.py — News sentiment sub-agent
#  Scores recent headlines for each ticker: bullish/bearish/neutral
#  Uses NewsAPI (free tier) + keyword sentiment scoring
#  Phase 2: swap keyword scoring for Claude API sentiment call
# ============================================================

import requests
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
import config

logger = logging.getLogger(__name__)

# ── Sentiment keyword lists ───────────────────────────────────
BULLISH_KEYWORDS = [
    "beats", "beat", "record", "upgrade", "buy", "outperform",
    "raises guidance", "strong demand", "partnership", "contract",
    "breakthrough", "expansion", "revenue growth", "profit",
    "ai demand", "data center", "chip shortage easing", "bullish",
    "surge", "rally", "all-time high", "raises price target"
]

BEARISH_KEYWORDS = [
    "misses", "miss", "downgrade", "sell", "underperform",
    "lowers guidance", "weak demand", "layoffs", "investigation",
    "sec", "lawsuit", "recall", "shortage", "tariff", "ban",
    "sanctions", "crash", "decline", "loss", "warning", "risk",
    "antitrust", "bearish", "slump", "disappoints"
]

BLACKOUT_KEYWORDS = [
    "earnings", "results due", "reports earnings", "quarterly results",
    "q1", "q2", "q3", "q4", "fiscal year"
]


@dataclass
class SentimentResult:
    symbol: str
    score: float          # -1.0 (very bearish) to +1.0 (very bullish)
    label: str            # 'bullish' | 'bearish' | 'neutral'
    near_earnings: bool   # True = blackout — no new entries
    headline_count: int
    top_headlines: list


def fetch_headlines(symbol: str, company_name: str = "") -> list:
    """
    Fetch last 24 hours of headlines for a ticker.
    Falls back to empty list if API key missing or rate limited.
    """
    if not config.NEWS_API_KEY or config.NEWS_API_KEY == "your_newsapi_key_here":
        logger.warning(f"No NEWS_API_KEY set — skipping news for {symbol}")
        return []

    query = f"{symbol} stock" if not company_name else f"{company_name} OR {symbol} stock"
    from_date = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")

    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q":        query,
                "from":     from_date,
                "sortBy":   "publishedAt",
                "language": "en",
                "pageSize": 20,
                "apiKey":   config.NEWS_API_KEY,
            },
            timeout=8
        )
        data = resp.json()
        if data.get("status") != "ok":
            logger.warning(f"NewsAPI error for {symbol}: {data.get('message')}")
            return []
        return [a["title"] + " " + (a.get("description") or "") for a in data.get("articles", [])]
    except Exception as e:
        logger.error(f"News fetch failed for {symbol}: {e}")
        return []


def score_headlines(headlines: list) -> tuple[float, bool]:
    """
    Keyword-based sentiment scoring.
    Returns (score, near_earnings).
    score: -1.0 to +1.0
    near_earnings: True = earnings blackout triggered
    """
    if not headlines:
        return 0.0, False

    bullish_hits = 0
    bearish_hits = 0
    near_earnings = False

    for headline in headlines:
        text = headline.lower()

        for kw in BULLISH_KEYWORDS:
            if kw in text:
                bullish_hits += 1

        for kw in BEARISH_KEYWORDS:
            if kw in text:
                bearish_hits += 1

        for kw in BLACKOUT_KEYWORDS:
            if kw in text:
                near_earnings = True

    total = bullish_hits + bearish_hits
    if total == 0:
        return 0.0, near_earnings

    score = (bullish_hits - bearish_hits) / total
    return round(score, 3), near_earnings


def label_from_score(score: float) -> str:
    if score >= 0.2:
        return "bullish"
    elif score <= -0.2:
        return "bearish"
    return "neutral"


# ── Company name map for better search results ────────────────
COMPANY_NAMES = {
    "NVDA":  "Nvidia",
    "AMD":   "AMD Advanced Micro Devices",
    "MSFT":  "Microsoft",
    "GOOGL": "Alphabet Google",
    "AVGO":  "Broadcom",
    "VRT":   "Vertiv",
    "ETN":   "Eaton",
    "GEV":   "GE Vernova",
    "EQIX":  "Equinix",
    "SMCI":  "Super Micro Computer",
    "UNP":   "Union Pacific",
    "FDX":   "FedEx",
    "QQQ":   "QQQ Nasdaq ETF",
}


def analyse(symbol: str) -> SentimentResult:
    """
    Run full news sentiment analysis for one ticker.
    Returns SentimentResult — used by strategy.py before entry decisions.
    """
    company = COMPANY_NAMES.get(symbol, "")
    headlines = fetch_headlines(symbol, company)
    score, near_earnings = score_headlines(headlines)
    label = label_from_score(score)

    result = SentimentResult(
        symbol=symbol,
        score=score,
        label=label,
        near_earnings=near_earnings,
        headline_count=len(headlines),
        top_headlines=headlines[:3]
    )

    logger.info(
        f"News [{symbol}]: {label} (score={score}) | "
        f"headlines={len(headlines)} | earnings_blackout={near_earnings}"
    )
    return result


def is_safe_to_enter(sentiment: SentimentResult) -> tuple[bool, str]:
    """
    Gate function called by strategy.py.
    Returns (safe, reason).
    """
    if sentiment.near_earnings:
        return False, f"{sentiment.symbol}: earnings blackout active"
    if sentiment.label == "bearish":
        return False, f"{sentiment.symbol}: bearish sentiment (score={sentiment.score})"
    return True, f"{sentiment.symbol}: news OK ({sentiment.label})"
