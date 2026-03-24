"""F1 데이터 수집 -- RSS 피드 크롤러이다.

feedparser로 RSS XML을 파싱하여 RawArticle 목록을 생성한다.
15개 소스(reuters, bloomberg_rss, yahoo_finance, cnbc, marketwatch,
wsj_rss, ft, fed_announcements, ecb_press, bbc_business,
nikkei_asia, scmp, yonhap_en, hankyung, mk)를 처리한다.
"""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser

from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.crawlers.engine.crawler_base import CrawlerBase
from src.crawlers.models import RawArticle, SourceConfig

logger = get_logger(__name__)

# RSS 소스 이름 집합 -- 이 크롤러가 처리 가능한 소스이다
_RSS_SOURCES: set[str] = {
    "reuters", "bloomberg_rss", "yahoo_finance", "cnbc", "marketwatch",
    "wsj_rss", "ft", "fed_announcements", "ecb_press", "bbc_business",
    "nikkei_asia", "scmp", "yonhap_en", "hankyung", "mk",
}

# 한국어 소스 이름 -- language 태그용이다
_KOREAN_SOURCES: set[str] = {"hankyung", "mk"}


def _parse_pub_date(entry: dict) -> datetime | None:
    """RSS entry에서 발행일을 파싱한다. 실패 시 None을 반환한다."""
    raw = entry.get("published") or entry.get("updated")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        return None


def _extract_content(entry: dict) -> str:
    """RSS entry에서 본문을 추출한다. summary 또는 content를 사용한다."""
    # content 필드가 있으면 우선 사용한다
    content_list = entry.get("content", [])
    if content_list:
        return content_list[0].get("value", "")
    return entry.get("summary", "")


def _detect_language(source_name: str) -> str:
    """소스 이름으로 언어를 판별한다."""
    if source_name in _KOREAN_SOURCES:
        return "ko"
    return "en"


def _entry_to_raw_article(entry: dict, source: SourceConfig) -> RawArticle:
    """feedparser entry를 RawArticle로 변환한다."""
    return RawArticle(
        title=entry.get("title", ""),
        content=_extract_content(entry),
        url=entry.get("link", ""),
        source=source.name,
        published_at=_parse_pub_date(entry),
        language=_detect_language(source.name),
        metadata={"source_type": "rss"},
    )


class RssCrawler(CrawlerBase):
    """RSS 피드 크롤러이다. 15개 RSS 소스를 처리한다."""

    def __init__(self, http_client: AsyncHttpClient) -> None:
        """HTTP 클라이언트를 주입받아 초기화한다."""
        super().__init__(http_client)

    def can_handle(self, source: SourceConfig) -> bool:
        """이 크롤러가 해당 소스를 처리할 수 있는지 판별한다."""
        return source.name in _RSS_SOURCES

    async def crawl(self, source: SourceConfig) -> list[RawArticle]:
        """RSS 피드를 가져와 RawArticle 목록으로 변환한다."""
        response = await self._http.get(source.url)
        if not response.ok:
            logger.warning(
                "RSS 응답 실패: %s status=%d", source.name, response.status,
            )
            return []

        return self._parse_feed(response.body, source)

    def _parse_feed(self, body: str, source: SourceConfig) -> list[RawArticle]:
        """RSS XML 본문을 파싱하여 RawArticle 목록을 반환한다."""
        feed = feedparser.parse(body)
        if feed.bozo and not feed.entries:
            logger.warning("RSS 파싱 에러: %s", source.name)
            return []

        articles: list[RawArticle] = []
        for entry in feed.entries:
            article = _entry_to_raw_article(entry, source)
            if article.title and article.url:
                articles.append(article)

        logger.debug(
            "RSS 파싱 완료: %s -> %d건", source.name, len(articles),
        )
        return articles
