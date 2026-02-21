"""
Global crawl source configuration.

Defines 31 news/data sources across US, Europe, Asia, Korea, and global macro.
Each source specifies its type, URL/API details, language, region, and priority.

Priority levels:
  1 = Critical (Reuters, Bloomberg, WSJ, Fed, SEC, FT, ECB, Finviz)
  2 = Important (Yahoo, CNBC, MarketWatch, BBC, Nikkei, SCMP, Yonhap, Fear&Greed, Investing.com)
  3 = Supplementary (Reddit, Stocktwits, Korean news, DART, Polymarket, Kalshi)
  4 = Supplementary-KR (StockNow)

Tier schedule:
  Tier 1 (15min): Finviz news
  Tier 2 (1h): Investing.com, CNN Fear & Greed
  Tier 3 (30min): Polymarket, Kalshi
  Tier 4 (1h): StockNow
"""

from typing import Any

CRAWL_SOURCES: dict[str, dict[str, Any]] = {
    # --- US (11 sources) ---
    "reuters": {
        "name": "Reuters",
        "type": "rss",
        "url": "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best",
        "language": "en",
        "region": "global",
        "priority": 1,
    },
    "bloomberg_rss": {
        "name": "Bloomberg",
        "type": "rss",
        "url": "https://feeds.bloomberg.com/markets/news.rss",
        "language": "en",
        "region": "global",
        "priority": 1,
    },
    "yahoo_finance": {
        "name": "Yahoo Finance",
        "type": "rss",
        "url": "https://finance.yahoo.com/news/rssindex",
        "language": "en",
        "region": "us",
        "priority": 2,
    },
    "cnbc": {
        "name": "CNBC",
        "type": "rss",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "language": "en",
        "region": "us",
        "priority": 2,
    },
    "marketwatch": {
        "name": "MarketWatch",
        "type": "rss",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "language": "en",
        "region": "us",
        "priority": 2,
    },
    "wsj_rss": {
        "name": "WSJ",
        "type": "rss",
        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "language": "en",
        "region": "us",
        "priority": 1,
    },
    "sec_edgar": {
        "name": "SEC EDGAR",
        "type": "api",
        "language": "en",
        "region": "us",
        "priority": 1,
    },
    "reddit_wsb": {
        "name": "Reddit WSB",
        "type": "reddit",
        "subreddit": "wallstreetbets",
        "language": "en",
        "region": "us",
        "priority": 3,
    },
    "reddit_investing": {
        "name": "Reddit Investing",
        "type": "reddit",
        "subreddit": "investing",
        "language": "en",
        "region": "us",
        "priority": 3,
    },
    "stocktwits": {
        "name": "Stocktwits",
        "type": "api",
        "language": "en",
        "region": "us",
        "priority": 3,
    },
    "fed_announcements": {
        "name": "Federal Reserve",
        "type": "rss",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "language": "en",
        "region": "us",
        "priority": 1,
    },
    # --- Europe (3 sources) ---
    "ft": {
        "name": "FT",
        "type": "rss",
        "url": "https://www.ft.com/rss/home",
        "language": "en",
        "region": "eu",
        "priority": 1,
    },
    "ecb_press": {
        "name": "ECB",
        "type": "rss",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "language": "en",
        "region": "eu",
        "priority": 1,
    },
    "bbc_business": {
        "name": "BBC Business",
        "type": "rss",
        "url": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "language": "en",
        "region": "eu",
        "priority": 2,
    },
    # --- Asia (3 sources) ---
    "nikkei_asia": {
        "name": "Nikkei Asia",
        "type": "rss",
        "url": "https://asia.nikkei.com/rss",
        "language": "en",
        "region": "asia",
        "priority": 2,
    },
    "scmp": {
        "name": "SCMP",
        "type": "rss",
        "url": "https://www.scmp.com/rss/91/feed",
        "language": "en",
        "region": "asia",
        "priority": 2,
    },
    "yonhap_en": {
        "name": "Yonhap",
        "type": "rss",
        "url": "https://en.yna.co.kr/RSS/news.xml",
        "language": "en",
        "region": "korea",
        "priority": 2,
    },
    # --- Korea (3 sources) ---
    "hankyung": {
        "name": "Hankyung",
        "type": "rss",
        "url": "https://www.hankyung.com/feed/all-news",
        "language": "ko",
        "region": "korea",
        "priority": 3,
    },
    "mk": {
        "name": "Maeil Business",
        "type": "rss",
        "url": "https://www.mk.co.kr/rss/30000001/",
        "language": "ko",
        "region": "korea",
        "priority": 3,
    },
    "dart": {
        "name": "DART",
        "type": "api",
        "language": "ko",
        "region": "korea",
        "priority": 3,
    },
    # --- Global Macro (1 source -> Investing.com 이전 항목 교체) ---
    "investing_com": {
        "name": "Investing.com Calendar & Index",
        "type": "investing",
        "language": "en",
        "region": "global",
        "priority": 2,
        "tier": 2,
        "schedule_minutes": 60,
    },
    # --- Addendum 27: 6 New Sources ---
    "finviz": {
        "name": "Finviz",
        "type": "finviz",
        "language": "en",
        "region": "us",
        "priority": 1,
        "tier": 1,
        "schedule_minutes": 15,
    },
    "cnn_fear_greed": {
        "name": "CNN Fear & Greed Index",
        "type": "fear_greed",
        "language": "en",
        "region": "us",
        "priority": 2,
        "tier": 2,
        "schedule_minutes": 1440,  # 1일 1회 (장 시작 전)
    },
    "polymarket": {
        "name": "Polymarket Prediction Markets",
        "type": "polymarket",
        "language": "en",
        "region": "global",
        "priority": 3,
        "tier": 3,
        "schedule_minutes": 30,
    },
    "kalshi": {
        "name": "Kalshi Macro Predictions",
        "type": "kalshi",
        "language": "en",
        "region": "us",
        "priority": 3,
        "tier": 3,
        "schedule_minutes": 30,
    },
    "stocknow": {
        "name": "StockNow Korea",
        "type": "stocknow",
        "language": "ko",
        "region": "korea",
        "priority": 4,
        "tier": 4,
        "schedule_minutes": 60,
    },
    # --- FRED Economic Data (시계열 추적) ---
    "fred_data": {
        "name": "FRED Economic Data",
        "type": "fred",
        "language": "en",
        "region": "us",
        "priority": 1,
        "tier": 2,
        "schedule_minutes": 60,
        "api_key_env": "FRED_API_KEY",
        "series": ["DFF", "T10Y2Y", "VIXCLS", "CPIAUCSL", "UNRATE"],
    },
    # --- Finnhub API ---
    "finnhub": {
        "name": "Finnhub",
        "type": "finnhub",
        "language": "en",
        "region": "us",
        "priority": 2,
        "tier": 2,
        "schedule_minutes": 60,
        "api_key": "",  # .env의 FINNHUB_API_KEY 또는 Settings에서 로드
        "tracked_symbols": [
            "SOXL", "QLD", "SSO",
            "NVDA", "AMD", "AVGO", "TSM", "INTC", "MU",
            "AAPL", "MSFT", "AMZN", "GOOGL", "META",
        ],
    },
    # --- Alpha Vantage News Sentiment ---
    "alphavantage": {
        "name": "Alpha Vantage News Sentiment",
        "type": "alphavantage",
        "language": "en",
        "region": "global",
        "priority": 2,
        "tier": 2,
        "schedule_minutes": 30,
        "api_key_env": "ALPHAVANTAGE_API_KEY",
    },
    # --- Naver Finance (네이버 금융 해외증시) ---
    "naver_finance": {
        "name": "Naver Finance Overseas",
        "type": "naver_finance",
        "language": "ko",
        "region": "korea",
        "priority": 2,
        "tier": 2,
        "schedule_minutes": 10,
    },
}


def get_sources_by_type(source_type: str) -> dict[str, dict[str, Any]]:
    """Return sources filtered by type (rss, api, reddit, scraping)."""
    return {
        key: cfg
        for key, cfg in CRAWL_SOURCES.items()
        if cfg["type"] == source_type
    }


def get_sources_by_priority(max_priority: int) -> dict[str, dict[str, Any]]:
    """Return sources with priority <= max_priority (lower = more important)."""
    return {
        key: cfg
        for key, cfg in CRAWL_SOURCES.items()
        if cfg["priority"] <= max_priority
    }


def get_enabled_source_keys() -> list[str]:
    """Return all source keys in priority order."""
    return sorted(CRAWL_SOURCES.keys(), key=lambda k: CRAWL_SOURCES[k]["priority"])


def get_sources_by_tier(tier: int) -> dict[str, dict[str, Any]]:
    """Tier 번호로 소스를 필터링하여 반환한다."""
    return {
        key: cfg
        for key, cfg in CRAWL_SOURCES.items()
        if cfg.get("tier") == tier
    }


def get_tiered_schedule() -> dict[int, dict[str, Any]]:
    """Tier별 스케줄 정보를 반환한다.

    Returns:
        {tier: {"sources": [...], "interval_minutes": N}} 형태의 딕셔너리.
    """
    schedule: dict[int, dict[str, Any]] = {}

    for key, cfg in CRAWL_SOURCES.items():
        tier = cfg.get("tier")
        if tier is None:
            continue

        if tier not in schedule:
            schedule[tier] = {
                "sources": [],
                "interval_minutes": cfg.get("schedule_minutes", 60),
            }
        schedule[tier]["sources"].append(key)

    return schedule
