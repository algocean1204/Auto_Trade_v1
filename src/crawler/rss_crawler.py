"""
RSS/Atom feed crawler.

Covers most sources: Reuters, Bloomberg, Yahoo Finance, CNBC, MarketWatch,
WSJ, Federal Reserve, FT, ECB, BBC, Nikkei Asia, SCMP, Yonhap,
Hankyung, Maeil Business.
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RSSCrawler(BaseCrawler):
    """Generic RSS/Atom feed crawler using feedparser.

    Uses aiohttp to fetch the raw feed asynchronously, then feedparser
    to parse the XML. Supports both RSS 2.0 and Atom feed formats.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self.feed_url: str = source_config["url"]

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Fetch and parse RSS feed, returning articles after `since`."""
        session = await self.get_session()
        try:
            async with session.get(self.feed_url) as response:
                if response.status != 200:
                    logger.warning(
                        "[%s] HTTP %d from %s",
                        self.name, response.status, self.feed_url,
                    )
                    return []
                raw = await response.text()
        except Exception as e:
            logger.error("[%s] Failed to fetch feed: %s", self.name, e)
            return []

        feed = feedparser.parse(raw)

        if feed.bozo and not feed.entries:
            logger.warning(
                "[%s] Feed parse error: %s", self.name, feed.bozo_exception
            )
            return []

        articles: list[dict[str, Any]] = []
        for entry in feed.entries:
            article = self._parse_entry(entry)
            if article is None:
                continue

            if since and article["published_at"] < since:
                continue

            articles.append(article)

        return articles

    def _parse_entry(self, entry: Any) -> dict[str, Any] | None:
        """Parse a single feed entry into a standardized article dict."""
        headline = getattr(entry, "title", "").strip()
        if not headline:
            return None

        # Extract content: prefer content field, fall back to summary/description
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content = entry.summary or ""
        elif hasattr(entry, "description"):
            content = entry.description or ""

        # Strip HTML tags from content (simple approach)
        content = self._strip_html(content)

        # Extract URL
        url = getattr(entry, "link", "")

        # Parse publication date — None 반환 시 해당 기사를 스킵한다.
        published_at = self._parse_date(entry)
        if published_at is None:
            logger.debug(
                "[%s] 날짜 파싱 실패로 기사 스킵: headline=%s",
                self.name, headline[:80],
            )
            return None

        return {
            "headline": headline,
            "content": content[:5000],  # Limit content length
            "url": url,
            "published_at": published_at,
            "source": self.source_key,
            "language": self.language,
        }

    def _parse_date(self, entry: Any) -> datetime | None:
        """Extract and parse publication date from a feed entry.

        Returns:
            파싱된 UTC datetime. 모든 시도가 실패하면 None을 반환한다.
            과거 기사가 오늘 날짜로 잘못 기록되는 문제를 방지하기 위해
            fallback으로 현재 시간을 반환하지 않는다.
        """
        # Try standard feedparser parsed date first
        for date_field in ("published_parsed", "updated_parsed"):
            parsed = getattr(entry, date_field, None)
            if parsed:
                try:
                    from calendar import timegm
                    ts = timegm(parsed)
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except (ValueError, OverflowError):
                    pass

        # Try raw date string
        for raw_field in ("published", "updated", "created"):
            raw = getattr(entry, raw_field, None)
            if raw:
                try:
                    return parsedate_to_datetime(raw).astimezone(timezone.utc)
                except (ValueError, TypeError):
                    pass

        # 날짜 파싱 실패 — None 반환 (현재 시간 폴백 제거)
        logger.debug(
            "[%s] 날짜 필드를 찾을 수 없음: entry_id=%s",
            self.name, getattr(entry, "id", "unknown"),
        )
        return None

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from text (lightweight, no extra dependency)."""
        import re
        clean = re.sub(r"<[^>]+>", " ", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean
