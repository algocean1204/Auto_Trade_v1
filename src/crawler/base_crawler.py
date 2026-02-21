"""
Abstract base class for all crawlers.

Every concrete crawler (RSS, Reddit, SEC, DART, Stocktwits, Economic Calendar)
inherits from BaseCrawler and implements the `crawl` method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import aiohttp

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_CRAWLER_TIMEOUT_TOTAL: float = 30.0
_CRAWLER_TIMEOUT_CONNECT: float = 10.0


class BaseCrawler(ABC):
    """Abstract base for all news/data crawlers.

    Attributes:
        config: Source configuration dict from sources_config.CRAWL_SOURCES.
        name: Human-readable source name.
        source_key: Internal source key (e.g. "reuters", "sec_edgar").
        language: Default language code for this source.
    """

    # Shared aiohttp session across all crawler instances
    _shared_session: aiohttp.ClientSession | None = None

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        self.source_key = source_key
        self.config = source_config
        self.name = source_config["name"]
        self.language = source_config.get("language", "en")

    @abstractmethod
    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Execute crawling. Return articles published after `since`.

        Each returned dict must contain:
            - headline (str): Article title / headline
            - content (str): Body text or summary (may be empty)
            - url (str): Link to original article
            - published_at (datetime): Publication timestamp (UTC)
            - source (str): Source key matching sources_config key
            - language (str): ISO language code
        """

    async def safe_crawl(self, since: datetime | None = None) -> dict[str, Any]:
        """안전한 크롤링을 수행한다.

        성공/실패를 명시적으로 구분하여 반환하므로 호출자가
        "0개 수집(정상)"과 "에러로 인한 0개"를 구별할 수 있다.

        Returns:
            성공 시: {"success": True, "articles": [...], "count": N}
            실패 시: {"success": False, "articles": [], "error": "...", "count": 0}
        """
        try:
            articles = await self.crawl(since)
            logger.info(
                "[%s] Crawled %d articles", self.name, len(articles)
            )
            return {"success": True, "articles": articles, "count": len(articles)}
        except Exception as e:
            logger.error("[%s] Crawl failed: %s", self.name, e, exc_info=True)
            return {"success": False, "articles": [], "error": str(e), "count": 0}

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        """Return shared aiohttp session, creating one if needed."""
        if cls._shared_session is None or cls._shared_session.closed:
            timeout = aiohttp.ClientTimeout(
                total=_CRAWLER_TIMEOUT_TOTAL,
                connect=_CRAWLER_TIMEOUT_CONNECT,
            )
            cls._shared_session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": (
                        "TradingBot/2.0 (Financial News Aggregator; "
                        "contact: admin@localhost)"
                    )
                },
            )
        return cls._shared_session

    @classmethod
    async def close_session(cls) -> None:
        """Close the shared aiohttp session."""
        if cls._shared_session is not None and not cls._shared_session.closed:
            await cls._shared_session.close()
            cls._shared_session = None
