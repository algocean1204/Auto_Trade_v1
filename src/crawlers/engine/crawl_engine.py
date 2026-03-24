"""F1 데이터 수집 -- 전체 크롤링 파이프라인 오케스트레이션 엔진이다.

CrawlSchedule에 따라 크롤러를 실행하고, 검증/중복제거/이벤트 발행을
순차적으로 처리한다. 개별 소스 실패는 격리하여 전체에 영향을 주지 않는다.
"""
from __future__ import annotations

import asyncio
import time

from src.common.event_bus import EventBus, EventType
from src.common.logger import get_logger
from src.crawlers.dedup.article_dedup import ArticleDeduplicator
from src.crawlers.engine.crawler_base import CrawlerBase
from src.crawlers.models import (
    CrawlResult,
    CrawlSchedule,
    RawArticle,
    SourceConfig,
    VerifiedArticle,
)
from src.crawlers.verifier.crawl_verifier import CrawlVerifier

logger = get_logger(__name__)


def _select_crawler(
    source: SourceConfig, crawlers: list[CrawlerBase],
) -> CrawlerBase | None:
    """소스에 맞는 크롤러를 선택한다. can_handle 메서드로 판별한다."""
    for crawler in crawlers:
        if hasattr(crawler, "can_handle") and crawler.can_handle(source):
            return crawler
    return None


class CrawlEngine:
    """크롤링 파이프라인 오케스트레이터이다.

    스케줄 -> 크롤링 -> 검증 -> 중복제거 -> 이벤트 발행 순서로 처리한다.
    """

    def __init__(
        self,
        crawlers: list[CrawlerBase],
        verifier: CrawlVerifier,
        dedup: ArticleDeduplicator,
        event_bus: EventBus,
    ) -> None:
        """파이프라인 구성 요소를 주입받아 초기화한다."""
        self._crawlers = crawlers
        self._verifier = verifier
        self._dedup = dedup
        self._event_bus = event_bus

    async def run(self, schedule: CrawlSchedule) -> CrawlResult:
        """크롤링 파이프라인 전체를 실행한다."""
        start = time.monotonic()
        failed_sources: list[str] = []

        # 소스별 크롤링을 병렬로 실행한다
        matched_sources, tasks = self._create_crawl_tasks(schedule.active_sources)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 결과를 수집한다 (매칭된 소스만 전달하여 인덱스 일치를 보장한다)
        raw_articles, source_failures = self._collect_results(
            matched_sources, results,
        )
        failed_sources.extend(source_failures)
        total = len(raw_articles)

        # 검증 + 중복제거 + 이벤트 발행
        new_count = await self._process_articles(raw_articles)

        duration = time.monotonic() - start
        logger.info(
            "크롤링 완료: total=%d, new=%d, failed=%d, %.1f초",
            total, new_count, len(failed_sources), duration,
        )

        return CrawlResult(
            total=total,
            new_count=new_count,
            failed_sources=failed_sources,
            duration_seconds=round(duration, 2),
        )

    def _create_crawl_tasks(
        self, sources: list[SourceConfig],
    ) -> tuple[list[SourceConfig], list[asyncio.Task]]:
        """소스별 크롤링 태스크를 생성한다. 매칭된 소스와 태스크를 함께 반환한다."""
        matched_sources: list[SourceConfig] = []
        tasks: list[asyncio.Task] = []
        for source in sources:
            crawler = _select_crawler(source, self._crawlers)
            if crawler is None:
                logger.warning("크롤러 미매칭: %s", source.name)
                continue
            matched_sources.append(source)
            tasks.append(asyncio.create_task(crawler.safe_crawl(source)))
        return matched_sources, tasks

    def _collect_results(
        self,
        sources: list[SourceConfig],
        results: list,
    ) -> tuple[list[RawArticle], list[str]]:
        """크롤링 결과를 수집하고 실패 소스를 분류한다."""
        articles: list[RawArticle] = []
        failed: list[str] = []

        for i, result in enumerate(results):
            source_name = sources[i].name if i < len(sources) else "unknown"
            if isinstance(result, Exception):
                logger.exception("크롤링 예외: %s", source_name)
                failed.append(source_name)
            elif isinstance(result, list):
                articles.extend(result)
            else:
                failed.append(source_name)

        return articles, failed

    async def _process_articles(
        self, articles: list[RawArticle],
    ) -> int:
        """기사를 검증하고 중복을 제거한 뒤 이벤트를 발행한다."""
        new_count = 0
        for article in articles:
            verified = self._verifier.verify(article)
            if verified is None:
                continue

            dedup_result = await self._dedup.check(verified)
            if not dedup_result.is_new:
                continue

            await self._publish_article(verified)
            new_count += 1

        return new_count

    async def _publish_article(self, article: VerifiedArticle) -> None:
        """검증된 신규 기사를 EventBus로 발행한다."""
        try:
            await self._event_bus.publish(
                EventType.ARTICLE_COLLECTED, article,
            )
        except Exception:
            logger.exception("기사 이벤트 발행 실패: %s", article.url)
