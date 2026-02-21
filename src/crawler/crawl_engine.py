"""
Unified crawl engine.

Orchestrates all crawlers in parallel, applies deduplication and rule-based
filtering, persists results to PostgreSQL, and manages checkpoints for
delta crawling. Addendum 27에서 6개 신규 소스와 Tier 기반 스케줄링을 추가하였다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.crawler.alphavantage_crawler import AlphaVantageCrawler
from src.crawler.base_crawler import BaseCrawler
from src.crawler.crawl_scheduler import CrawlScheduler
from src.crawler.finnhub_crawler import FinnhubCrawler
from src.crawler.dart_crawler import DARTCrawler
from src.crawler.dedup import DedupChecker
from src.crawler.economic_calendar import EconomicCalendarCrawler
from src.crawler.fear_greed_crawler import FearGreedCrawler
from src.crawler.finviz_crawler import FinvizCrawler
from src.crawler.fred_crawler import FREDCrawler
from src.crawler.investing_crawler import InvestingCrawler
from src.crawler.kalshi_crawler import KalshiCrawler
from src.crawler.naver_crawler import NaverFinanceCrawler
from src.crawler.polymarket_crawler import PolymarketCrawler
from src.crawler.reddit_crawler import RedditCrawler
from src.crawler.rss_crawler import RSSCrawler
from src.crawler.sec_edgar_crawler import SECEdgarCrawler
from src.crawler.sources_config import CRAWL_SOURCES, get_sources_by_tier
from src.crawler.stocknow_crawler import StockNowCrawler
from src.crawler.stocktwits_crawler import StocktwitsCrawler
from src.db.connection import get_redis, get_session
from src.db.models import Article, CrawlCheckpoint
from src.filter.rule_filter import RuleBasedFilter
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Map source type to crawler class
_CRAWLER_REGISTRY: dict[str, type[BaseCrawler]] = {
    "rss": RSSCrawler,
    "reddit": RedditCrawler,
    "sec_edgar": SECEdgarCrawler,
    "dart": DARTCrawler,
    "stocktwits": StocktwitsCrawler,
    "scraping": EconomicCalendarCrawler,
    # Addendum 27 신규 크롤러
    "finviz": FinvizCrawler,
    "fear_greed": FearGreedCrawler,
    "polymarket": PolymarketCrawler,
    "kalshi": KalshiCrawler,
    "stocknow": StockNowCrawler,
    "investing": InvestingCrawler,
    "alphavantage": AlphaVantageCrawler,
    "finnhub": FinnhubCrawler,
    "fred": FREDCrawler,
    "naver_finance": NaverFinanceCrawler,
}

# Special-case source keys that need specific crawler classes
_SOURCE_CRAWLER_OVERRIDES: dict[str, type[BaseCrawler]] = {
    "sec_edgar": SECEdgarCrawler,
    "dart": DARTCrawler,
    "stocktwits": StocktwitsCrawler,
    "investing_com": InvestingCrawler,
    "finviz": FinvizCrawler,
    "cnn_fear_greed": FearGreedCrawler,
    "polymarket": PolymarketCrawler,
    "kalshi": KalshiCrawler,
    "stocknow": StockNowCrawler,
    "alphavantage": AlphaVantageCrawler,
    "finnhub": FinnhubCrawler,
    "fred_data": FREDCrawler,
    "naver_finance": NaverFinanceCrawler,
}

# 개별 크롤러 타임아웃 (초)
_CRAWLER_TIMEOUT = 15

# 실패 시 재시도 횟수
_MAX_RETRIES = 2


class CrawlEngine:
    """Unified crawling engine.

    - Async parallel crawling via asyncio.gather
    - Full / delta modes
    - Redis-based deduplication
    - Rule-based filtering
    - PostgreSQL persistence
    - Checkpoint management
    - Progress reporting (for WebSocket)
    """

    def __init__(self) -> None:
        self._crawlers: dict[str, BaseCrawler] = {}
        self._dedup = DedupChecker()
        self._rule_filter = RuleBasedFilter()
        self.scheduler = CrawlScheduler()
        # 초기화 실패한 크롤러 목록: [(source_key, reason), ...]
        self._failed_crawlers: list[dict[str, str]] = []
        self._build_crawlers()

    def _build_crawlers(self) -> None:
        """Instantiate crawler objects for all configured sources."""
        for source_key, config in CRAWL_SOURCES.items():
            crawler_cls = self._resolve_crawler_class(source_key, config)
            if crawler_cls is None:
                reason = f"source type '{config.get('type')}' 에 대한 크롤러 클래스 없음"
                logger.warning(
                    "No crawler class for source '%s' (type=%s), skipping",
                    source_key, config.get("type"),
                )
                self._failed_crawlers.append({"source_key": source_key, "reason": reason})
                continue
            try:
                self._crawlers[source_key] = crawler_cls(source_key, config)
            except Exception as e:
                reason = str(e)
                logger.error(
                    "Failed to instantiate crawler for '%s': %s", source_key, e, exc_info=True,
                )
                self._failed_crawlers.append({"source_key": source_key, "reason": reason})

        logger.info(
            "CrawlEngine initialized with %d crawlers: %s",
            len(self._crawlers),
            list(self._crawlers.keys()),
        )
        if self._failed_crawlers:
            logger.warning(
                "크롤러 초기화 실패 %d개: %s",
                len(self._failed_crawlers),
                [f["source_key"] for f in self._failed_crawlers],
            )

    def get_crawler_status(self) -> dict[str, Any]:
        """크롤러 초기화 상태를 반환한다.

        성공적으로 초기화된 크롤러 목록과 실패한 크롤러 목록(이유 포함)을 포함한다.

        Returns:
            {
                "active_count": int,
                "active_crawlers": [str, ...],
                "failed_count": int,
                "failed_crawlers": [{"source_key": str, "reason": str}, ...],
            }
        """
        return {
            "active_count": len(self._crawlers),
            "active_crawlers": list(self._crawlers.keys()),
            "failed_count": len(self._failed_crawlers),
            "failed_crawlers": self._failed_crawlers,
        }

    @staticmethod
    def _resolve_crawler_class(
        source_key: str, config: dict[str, Any]
    ) -> type[BaseCrawler] | None:
        """Determine which crawler class to use for a source."""
        # Check explicit overrides first
        if source_key in _SOURCE_CRAWLER_OVERRIDES:
            return _SOURCE_CRAWLER_OVERRIDES[source_key]

        source_type = config.get("type", "")

        # Reddit sources use RedditCrawler
        if source_type == "reddit":
            return RedditCrawler

        # API sources need special handling
        if source_type == "api":
            # sec_edgar, dart, stocktwits handled by overrides above
            return None

        return _CRAWLER_REGISTRY.get(source_type)

    def get_enabled_sources(self) -> list[str]:
        """Return list of enabled source keys."""
        return list(self._crawlers.keys())

    async def get_last_checkpoint(self) -> datetime | None:
        """Retrieve the last crawl checkpoint timestamp from the database."""
        try:
            async with get_session() as session:
                stmt = (
                    select(CrawlCheckpoint)
                    .order_by(CrawlCheckpoint.created_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                checkpoint = result.scalar_one_or_none()
                if checkpoint:
                    return checkpoint.checkpoint_at
        except Exception as e:
            logger.error("Failed to load checkpoint: %s", e)
        return None

    async def _save_checkpoint(
        self, total_articles: int, source_stats: dict[str, Any]
    ) -> None:
        """Save a new crawl checkpoint to the database."""
        try:
            async with get_session() as session:
                cp = CrawlCheckpoint(
                    checkpoint_at=datetime.now(tz=timezone.utc),
                    total_articles=total_articles,
                    source_stats=source_stats,
                )
                session.add(cp)
        except Exception as e:
            logger.error("Failed to save checkpoint: %s", e)

    async def run(
        self,
        mode: str = "full",
        task_id: str | None = None,
        source_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute crawling across all (or specified) sources.

        Args:
            mode: "full" to crawl everything, "delta" to only crawl since
                  last checkpoint.
            task_id: Optional task ID for progress tracking via WebSocket.
            source_keys: Optional list of specific source keys to crawl.
                         If None, crawls all enabled sources.

        Returns:
            Result dict with counts and per-source stats.
        """
        since = None
        if mode == "delta":
            since = await self.get_last_checkpoint()
            if since:
                logger.info("Delta mode: crawling since %s", since.isoformat())
            else:
                logger.info("Delta mode: no checkpoint found, running full crawl")

        # Select crawlers
        if source_keys:
            crawlers = {
                k: c for k, c in self._crawlers.items() if k in source_keys
            }
        else:
            crawlers = self._crawlers

        logger.info(
            "Starting %s crawl with %d sources: %s",
            mode, len(crawlers), list(crawlers.keys()),
        )

        # Parallel crawl
        tasks = {
            key: crawler.safe_crawl(since)
            for key, crawler in crawlers.items()
        }
        raw_results = await asyncio.gather(
            *tasks.values(), return_exceptions=True
        )

        # Collect results per source
        all_articles: list[dict[str, Any]] = []
        source_stats: dict[str, dict[str, int]] = {}

        for source_key, result in zip(tasks.keys(), raw_results):
            if isinstance(result, Exception):
                logger.error(
                    "Crawl exception for %s: %s", source_key, result
                )
                source_stats[source_key] = {"raw": 0, "error": 1}
                continue

            # safe_crawl()는 이제 dict를 반환한다: {"success": bool, "articles": [...], "count": N}
            if isinstance(result, dict):
                articles = result.get("articles", [])
                if not result.get("success", True):
                    source_stats[source_key] = {"raw": 0, "error": 1}
                else:
                    source_stats[source_key] = {"raw": len(articles)}
            else:
                # 하위 호환: 예외적으로 list가 반환된 경우
                articles = result if isinstance(result, list) else []
                source_stats[source_key] = {"raw": len(articles)}
            all_articles.extend(articles)

        logger.info("Raw articles collected: %d", len(all_articles))

        # Deduplication
        unique_articles, dup_count = await self._dedup.deduplicate_batch(
            all_articles
        )
        logger.info(
            "After dedup: %d unique, %d duplicates removed",
            len(unique_articles), dup_count,
        )

        # Rule-based filtering
        filter_results = self._rule_filter.batch_filter(unique_articles)
        kept = filter_results["keep"]
        uncertain = filter_results["uncertain"]
        discarded = filter_results["discard"]

        # Merge kept + uncertain (uncertain goes to Claude later)
        articles_to_save = kept + uncertain

        logger.info(
            "Filter results: %d keep, %d uncertain, %d discard",
            len(kept), len(uncertain), len(discarded),
        )

        # Persist to database
        saved_count = await self._save_articles(articles_to_save)

        # Save checkpoint
        await self._save_checkpoint(saved_count, source_stats)

        # Report progress if task_id provided
        if task_id:
            await self._report_progress(task_id, "completed", {
                "total_raw": len(all_articles),
                "duplicates_removed": dup_count,
                "kept": len(kept),
                "uncertain": len(uncertain),
                "discarded": len(discarded),
                "saved": saved_count,
            })

        result = {
            "mode": mode,
            "total_raw": len(all_articles),
            "duplicates_removed": dup_count,
            "after_dedup": len(unique_articles),
            "kept": len(kept),
            "uncertain": len(uncertain),
            "discarded": len(discarded),
            "saved": saved_count,
            "source_stats": source_stats,
            "crawled_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        logger.info("Crawl complete: %s", result)
        return result

    async def run_with_progress(
        self,
        task_id: str,
        mode: str = "full",
        source_keys: list[str] | None = None,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Execute crawling with per-source progress reporting.

        Designed for the Flutter mobile dashboard's manual crawl feature,
        where real-time progress is sent via WebSocket.

        Args:
            task_id: 태스크 식별자. Redis Pub/Sub 채널에 진행 상황을 게시하는 데 사용된다.
            mode: "full" 또는 "delta".
            source_keys: 크롤링할 소스 키 목록. None이면 전체 소스를 크롤링한다.
            progress_callback: 선택적 콜백. 각 크롤러의 진행 상황이 담긴 dict를 인수로
                호출된다. None이면 Redis Pub/Sub 보고만 수행한다.
        """
        import time as _time

        crawl_start = _time.monotonic()

        since = None
        if mode == "delta":
            since = await self.get_last_checkpoint()

        if source_keys:
            crawlers = {
                k: c for k, c in self._crawlers.items() if k in source_keys
            }
        else:
            crawlers = self._crawlers

        total = len(crawlers)
        all_articles: list[dict[str, Any]] = []
        source_stats: dict[str, dict[str, int]] = {}
        # 각 크롤러의 결과를 순서대로 추적한다.
        crawler_results: list[dict[str, Any]] = []

        # 시작 이벤트 전송
        start_event: dict[str, Any] = {
            "type": "crawl_started",
            "total_crawlers": total,
            "mode": mode,
            "status": "running",
            "message": f"크롤링 시작: {total}개 소스",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        await self._report_progress(task_id, "started", start_event)
        if progress_callback is not None:
            try:
                await progress_callback(start_event)
            except Exception as cb_exc:
                logger.debug("progress_callback 오류 (started): %s", cb_exc)

        # 각 소스를 순차적으로 크롤링하며 진행 이벤트를 전송한다.
        for idx, (source_key, crawler) in enumerate(crawlers.items(), start=1):
            crawler_name = getattr(crawler, "name", source_key)

            # 크롤러 시작 이벤트
            start_ev: dict[str, Any] = {
                "type": "crawler_start",
                "crawler_name": crawler_name,
                "crawler_key": source_key,
                "crawler_index": idx,
                "total_crawlers": total,
                "articles_count": 0,
                "status": "running",
                "message": f"{crawler_name} 크롤링 중...",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
            await self._report_progress(task_id, "crawling", start_ev)
            if progress_callback is not None:
                try:
                    await progress_callback(start_ev)
                except Exception as cb_exc:
                    logger.debug("progress_callback 오류 (start %s): %s", source_key, cb_exc)

            # 실제 크롤링 실행 (safe_crawl은 dict를 반환한다)
            crawl_result = await crawler.safe_crawl(since)
            articles = crawl_result.get("articles", [])
            count = crawl_result.get("count", len(articles))
            crawl_success = crawl_result.get("success", True)
            if crawl_success:
                source_stats[source_key] = {"raw": count}
            else:
                source_stats[source_key] = {"raw": 0, "error": 1}
            all_articles.extend(articles)

            # 크롤러 완료 이벤트
            done_ev: dict[str, Any] = {
                "type": "crawler_done",
                "crawler_name": crawler_name,
                "crawler_key": source_key,
                "crawler_index": idx,
                "total_crawlers": total,
                "articles_count": count,
                "status": "completed" if crawl_success else "error",
                "message": f"{crawler_name} 완료: {count}건" if crawl_success else f"{crawler_name} 실패: {crawl_result.get('error', '알 수 없는 오류')}",
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
            await self._report_progress(task_id, "crawling", done_ev)
            if progress_callback is not None:
                try:
                    await progress_callback(done_ev)
                except Exception as cb_exc:
                    logger.debug("progress_callback 오류 (done %s): %s", source_key, cb_exc)

            crawler_results.append({
                "name": crawler_name,
                "key": source_key,
                "count": count,
                "status": "completed" if crawl_success else "error",
            })

        # 중복 제거 + 필터링 + 저장
        unique_articles, dup_count = await self._dedup.deduplicate_batch(
            all_articles
        )
        filter_results = self._rule_filter.batch_filter(unique_articles)
        articles_to_save = filter_results["keep"] + filter_results["uncertain"]
        saved_count = await self._save_articles(articles_to_save)
        await self._save_checkpoint(saved_count, source_stats)

        duration = round(_time.monotonic() - crawl_start, 2)

        # 최종 요약 이벤트
        summary_ev: dict[str, Any] = {
            "type": "crawl_summary",
            "total_articles": len(all_articles),
            "unique_articles": len(unique_articles),
            "saved_articles": saved_count,
            "duplicates_removed": dup_count,
            "kept": len(filter_results["keep"]),
            "uncertain": len(filter_results["uncertain"]),
            "discarded": len(filter_results["discard"]),
            "duration_seconds": duration,
            "crawler_results": crawler_results,
            "status": "completed",
            "message": f"크롤링 완료: {saved_count}건 저장",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        await self._report_progress(task_id, "completed", summary_ev)
        if progress_callback is not None:
            try:
                await progress_callback(summary_ev)
            except Exception as cb_exc:
                logger.debug("progress_callback 오류 (summary): %s", cb_exc)

        result = {
            "mode": mode,
            "total_raw": len(all_articles),
            "duplicates_removed": dup_count,
            "after_dedup": len(unique_articles),
            "kept": len(filter_results["keep"]),
            "uncertain": len(filter_results["uncertain"]),
            "discarded": len(filter_results["discard"]),
            "saved": saved_count,
            "duration_seconds": duration,
            "crawler_results": crawler_results,
            "source_stats": source_stats,
            "crawled_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        return result

    async def _save_articles(
        self, articles: list[dict[str, Any]]
    ) -> int:
        """Persist articles to the database using upsert (on content_hash conflict)."""
        if not articles:
            return 0

        saved = 0
        try:
            async with get_session() as session:
                for article in articles:
                    content_hash = article.get("content_hash", "")
                    if not content_hash:
                        continue

                    stmt = pg_insert(Article).values(
                        id=str(uuid4()),
                        source=article.get("source", "unknown"),
                        headline=article.get("headline", "")[:10000],
                        content=article.get("content", "")[:50000] or None,
                        url=article.get("url", "") or None,
                        published_at=article.get("published_at"),
                        language=article.get("language", "en"),
                        tickers_mentioned=article.get("tickers_mentioned", []),
                        content_hash=content_hash,
                        is_processed=False,
                    ).on_conflict_do_nothing(
                        index_elements=["content_hash"]
                    )
                    result = await session.execute(stmt)
                    if result.rowcount > 0:
                        saved += 1

        except Exception as e:
            logger.error("Failed to save articles: %s", e, exc_info=True)

        logger.info("Saved %d/%d articles to database", saved, len(articles))
        return saved

    async def _report_progress(
        self, task_id: str, status: str, data: dict[str, Any]
    ) -> None:
        """Publish crawl progress to Redis for WebSocket consumers."""
        try:
            r = get_redis()
            import json
            message = json.dumps({
                "task_id": task_id,
                "status": status,
                "data": data,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            })
            await r.publish(f"crawl:progress:{task_id}", message)
        except Exception as e:
            logger.debug("Progress report failed: %s", e)

    async def get_crawl_stats(self) -> dict[str, Any]:
        """Return current crawl engine statistics."""
        dedup_stats = await self._dedup.get_stats()
        filter_stats = self._rule_filter.get_stats()

        return {
            "enabled_sources": self.get_enabled_sources(),
            "total_sources": len(self._crawlers),
            "dedup": dedup_stats,
            "filter": filter_stats,
        }

    async def run_tier(
        self,
        tier: int,
        mode: str = "delta",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """특정 Tier의 크롤러만 실행한다.

        Tier 기반 스케줄링에서 사용된다:
          - Tier 1 (15분): Finviz 뉴스
          - Tier 2 (1시간): Investing.com, CNN Fear & Greed
          - Tier 3 (30분): Polymarket, Kalshi
          - Tier 4 (1시간): StockNow

        Args:
            tier: 실행할 Tier 번호 (1-4).
            mode: "full" 또는 "delta".
            task_id: 진행 상황 추적용 태스크 ID.

        Returns:
            실행 결과 딕셔너리.
        """
        tier_sources = get_sources_by_tier(tier)
        source_keys = list(tier_sources.keys())

        if not source_keys:
            logger.warning("Tier %d에 등록된 소스 없음", tier)
            return {"tier": tier, "sources": [], "total_raw": 0}

        logger.info(
            "Tier %d 크롤링 시작: %s", tier, source_keys
        )

        return await self.run(
            mode=mode,
            task_id=task_id,
            source_keys=source_keys,
        )

    async def run_fault_isolated(
        self,
        source_keys: list[str] | None = None,
        timeout: int = _CRAWLER_TIMEOUT,
        retries: int = _MAX_RETRIES,
    ) -> dict[str, Any]:
        """각 크롤러를 독립적으로 실행하여 장애를 격리한다.

        개별 크롤러에 타임아웃과 재시도를 적용하여,
        한 크롤러의 실패가 다른 크롤러에 영향을 주지 않는다.

        Args:
            source_keys: 실행할 소스 키 목록. None이면 전체.
            timeout: 개별 크롤러 타임아웃 (초).
            retries: 실패 시 재시도 횟수.

        Returns:
            실행 결과 딕셔너리.
        """
        if source_keys:
            crawlers = {
                k: c for k, c in self._crawlers.items() if k in source_keys
            }
        else:
            crawlers = self._crawlers

        all_articles: list[dict[str, Any]] = []
        source_stats: dict[str, dict[str, Any]] = {}

        async def _run_single(
            key: str, crawler: BaseCrawler
        ) -> tuple[str, list[dict[str, Any]], bool]:
            """단일 크롤러를 타임아웃 + 재시도로 실행한다."""
            for attempt in range(1, retries + 1):
                try:
                    crawl_result = await asyncio.wait_for(
                        crawler.safe_crawl(None),
                        timeout=timeout,
                    )
                    # safe_crawl은 dict를 반환한다
                    articles = crawl_result.get("articles", [])
                    success = crawl_result.get("success", True)
                    return key, articles, success
                except asyncio.TimeoutError:
                    logger.warning(
                        "[%s] 타임아웃 (%ds), 재시도 %d/%d",
                        key, timeout, attempt, retries,
                    )
                except Exception as e:
                    logger.warning(
                        "[%s] 실행 실패 (시도 %d/%d): %s",
                        key, attempt, retries, e,
                    )
            return key, [], False

        tasks = [
            _run_single(key, crawler)
            for key, crawler in crawlers.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("크롤러 실행 예외: %s", result)
                continue
            key, articles, success = result
            source_stats[key] = {
                "raw": len(articles),
                "success": success,
            }
            all_articles.extend(articles)

        logger.info(
            "장애 격리 크롤링 완료: %d건 수집, 소스 %d개",
            len(all_articles), len(source_stats),
        )

        return {
            "total_raw": len(all_articles),
            "source_stats": source_stats,
            "articles": all_articles,
            "crawled_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def run_scheduled(
        self,
        mode: str = "delta",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Night/Day 스케줄러 기반으로 due 소스만 크롤링한다.

        CrawlScheduler가 KST 시각에 따라 night/day 모드를 판별하고,
        각 소스별 간격을 확인하여 크롤링이 필요한 소스만 선별한다.
        크롤링 완료 후 스케줄러에 완료 시각을 기록한다.

        기존 run(), run_tier(), run_fault_isolated()와 병행 사용 가능하다.

        Args:
            mode: "full" 또는 "delta". 기본값은 "delta".
            task_id: 진행 상황 추적용 태스크 ID.

        Returns:
            실행 결과 딕셔너리. due 소스가 없으면 빈 결과를 반환한다.
        """
        try:
            current_mode = self.scheduler.get_mode()
            available = self.get_enabled_sources()
            due_sources = self.scheduler.get_due_sources(available)

            logger.info(
                "스케줄 크롤링 시작 (mode=%s, schedule=%s, due=%d/%d): %s",
                mode, current_mode, len(due_sources), len(available), due_sources,
            )

            if not due_sources:
                logger.info("스케줄 크롤링: due 소스 없음, 건너뜀")
                return {
                    "mode": mode,
                    "schedule_mode": current_mode,
                    "total_raw": 0,
                    "saved": 0,
                    "due_sources": [],
                    "skipped_sources": available,
                    "source_stats": {},
                    "crawled_at": datetime.now(tz=timezone.utc).isoformat(),
                }

            # 기존 run() 메서드에 due 소스만 전달
            result = await self.run(
                mode=mode,
                task_id=task_id,
                source_keys=due_sources,
            )

            # 성공적으로 크롤링된 소스의 시각 기록
            source_stats = result.get("source_stats", {})
            for source_key in due_sources:
                stats = source_stats.get(source_key, {})
                # 에러가 아닌 소스만 기록 (에러 소스는 다음 주기에 재시도)
                if not stats.get("error"):
                    self.scheduler.record_crawl(source_key)

            # 스케줄 정보 추가
            result["schedule_mode"] = current_mode
            result["due_sources"] = due_sources
            result["skipped_sources"] = [
                s for s in available if s not in due_sources
            ]

            logger.info(
                "스케줄 크롤링 완료 (schedule=%s): due=%d, saved=%d",
                current_mode, len(due_sources), result.get("saved", 0),
            )

            return result

        except Exception as e:
            logger.error("스케줄 크롤링 실행 실패: %s", e, exc_info=True)
            return {
                "mode": mode,
                "schedule_mode": self.scheduler.get_mode(),
                "total_raw": 0,
                "saved": 0,
                "error": str(e),
                "crawled_at": datetime.now(tz=timezone.utc).isoformat(),
            }

    async def cleanup(self) -> None:
        """Clean up resources (close shared aiohttp session)."""
        await BaseCrawler.close_session()
        logger.info("CrawlEngine cleanup complete")
