"""
Stocktwits API crawler.

Fetches trending messages for tracked symbols via the Stocktwits API.
Requires STOCKTWITS_ACCESS_TOKEN environment variable for authenticated access.
Falls back to public (unauthenticated) API if token is not set.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

_STOCKTWITS_API = "https://api.stocktwits.com/api/2"

# Default symbols to track (major ETFs and indices)
_DEFAULT_SYMBOLS = [
    "SPY", "QQQ", "TQQQ", "SQQQ", "SOXL", "SOXS",
    "UVXY", "TLT", "GLD", "AAPL", "MSFT", "NVDA",
    "TSLA", "AMZN", "META", "GOOGL",
]


class StocktwitsCrawler(BaseCrawler):
    """Crawls Stocktwits for trending messages on key symbols.

    Monitors community sentiment for tracked stocks and ETFs.
    The public API is rate-limited to 200 requests per hour.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self._access_token = os.getenv("STOCKTWITS_ACCESS_TOKEN", "")
        self._symbols = source_config.get("symbols", _DEFAULT_SYMBOLS)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch trending messages and symbol streams."""
        articles: list[dict[str, Any]] = []

        # Fetch trending stream
        trending = await self._fetch_trending()
        articles.extend(trending)

        # Fetch per-symbol streams (limit to top 5 symbols to respect rate limits)
        for symbol in self._symbols[:5]:
            msgs = await self._fetch_symbol_stream(symbol)
            for msg in msgs:
                if since and msg["published_at"] < since:
                    continue
                articles.append(msg)

        return articles

    async def _fetch_trending(self) -> list[dict[str, Any]]:
        """Fetch the trending stream from Stocktwits."""
        session = await self.get_session()

        url = f"{_STOCKTWITS_API}/streams/trending.json"
        params = self._build_params()

        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] HTTP %d from trending", self.name, resp.status
                    )
                    return []
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("[%s] Trending fetch error: %s", self.name, e)
            return []

        return self._parse_messages(data.get("messages", []))

    async def _fetch_symbol_stream(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch the message stream for a specific symbol."""
        session = await self.get_session()

        url = f"{_STOCKTWITS_API}/streams/symbol/{symbol}.json"
        params = self._build_params()

        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 404:
                    return []
                if resp.status != 200:
                    logger.warning(
                        "[%s] HTTP %d for %s",
                        self.name, resp.status, symbol,
                    )
                    return []
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("[%s] Symbol %s fetch error: %s", self.name, symbol, e)
            return []

        return self._parse_messages(data.get("messages", []))

    def _build_params(self) -> dict[str, str]:
        """Build query parameters, including access token if available."""
        params: dict[str, str] = {}
        if self._access_token:
            params["access_token"] = self._access_token
        return params

    def _parse_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parse Stocktwits messages into standardized article dicts."""
        articles: list[dict[str, Any]] = []

        for msg in messages:
            body = msg.get("body", "").strip()
            if not body:
                continue

            msg_id = msg.get("id", "")
            created_at_str = msg.get("created_at", "")
            published_at = self._parse_timestamp(created_at_str)

            # Extract symbols mentioned
            symbols = [
                s.get("symbol", "")
                for s in msg.get("symbols", [])
                if s.get("symbol")
            ]

            sentiment = msg.get("entities", {}).get("sentiment", {})
            sentiment_label = sentiment.get("basic") if sentiment else None

            user = msg.get("user", {})
            username = user.get("username", "anonymous")

            url = f"https://stocktwits.com/message/{msg_id}" if msg_id else ""

            articles.append({
                "headline": body[:200],  # Use first 200 chars as headline
                "content": body,
                "url": url,
                "published_at": published_at,
                "source": self.source_key,
                "language": self.language,
                "metadata": {
                    "symbols": symbols,
                    "sentiment": sentiment_label,
                    "username": username,
                    "message_id": msg_id,
                },
            })

        return articles

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime:
        """Parse Stocktwits timestamp (ISO 8601 format)."""
        if not ts_str:
            return datetime.now(tz=timezone.utc)
        try:
            # Stocktwits uses format like "2024-01-15T10:30:00Z"
            from datetime import datetime as dt
            clean = ts_str.replace("Z", "+00:00")
            return dt.fromisoformat(clean)
        except (ValueError, TypeError):
            return datetime.now(tz=timezone.utc)
