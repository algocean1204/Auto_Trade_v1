"""
뉴스 파이프라인 오케스트레이터.

뉴스 수집 → 분류 → 핵심 필터링 → 번역 → DB 저장 → 텔레그램 전송
전체 파이프라인을 단일 함수로 실행한다.

비용 절감을 위해 핵심뉴스(critical/high/medium)만 번역한다.
부분 실패를 허용하며 에러 발생 시에도 나머지 단계를 계속 진행한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.analysis.classifier import NewsClassifier
    from src.analysis.news_translator import NewsTranslator
    from src.analysis.key_news_filter import KeyNewsFilter
    from src.monitoring.telegram_notifier import TelegramNotifier

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# 텔레그램 전송 최대 핵심뉴스 건수
_MAX_KEY_NEWS_TELEGRAM: int = 10

# 파이프라인 기본 크롤링 모드
_DEFAULT_CRAWL_MODE: str = "delta"

# DB 최신 기사 조회 건수 (분류 대상)
_PIPELINE_ARTICLE_LIMIT: int = 100


class NewsPipeline:
    """뉴스 수집 → 분류 → 핵심 필터링 → 번역 → 텔레그램 전송 파이프라인.

    각 단계는 독립적으로 실행되며 부분 실패를 허용한다.
    핵심뉴스만 번역하여 API 비용을 절감한다.

    사용 예시:
        pipeline = NewsPipeline(
            crawl_engine=ts.crawl_engine,
            classifier=ts.classifier,
            translator=NewsTranslator(ts.claude_client),
            key_filter=KeyNewsFilter(),
            telegram_notifier=ts.telegram_notifier,
        )
        result = await pipeline.collect_and_send()
    """

    def __init__(
        self,
        crawl_engine: Any,
        classifier: NewsClassifier,
        translator: NewsTranslator,
        key_filter: KeyNewsFilter,
        telegram_notifier: TelegramNotifier | None = None,
    ) -> None:
        """NewsPipeline을 초기화한다.

        Args:
            crawl_engine: CrawlEngine 인스턴스. run(mode=...) 메서드를 갖는다.
            classifier: NewsClassifier 인스턴스.
            translator: NewsTranslator 인스턴스.
            key_filter: KeyNewsFilter 인스턴스.
            telegram_notifier: TelegramNotifier 인스턴스. None이면 전송 생략.
        """
        self.crawl_engine = crawl_engine
        self.classifier = classifier
        self.translator = translator
        self.key_filter = key_filter
        self.telegram_notifier = telegram_notifier

        logger.info("NewsPipeline 초기화 완료")

    async def collect_and_send(
        self,
        crawl_mode: str = _DEFAULT_CRAWL_MODE,
        article_limit: int = _PIPELINE_ARTICLE_LIMIT,
        send_telegram: bool = True,
    ) -> dict[str, Any]:
        """뉴스 수집부터 텔레그램 전송까지 전체 파이프라인을 실행한다.

        실행 순서:
            1. 크롤링 (crawl_engine.run)
            2. 최신 기사 조회 (DB)
            3. 뉴스 분류 (classifier)
            4. 핵심뉴스 필터링 (key_filter) — critical/high/medium
            5. 핵심뉴스 한국어 번역 (translator) — 비용 절감
            6. DB 저장 (headline_kr, summary_ko)
            7. 텔레그램 전송 (telegram_notifier)

        Args:
            crawl_mode: 크롤링 모드. "full" 또는 "delta".
            article_limit: 분류 대상 최신 기사 수.
            send_telegram: 텔레그램 전송 여부. False이면 전송 생략.

        Returns:
            파이프라인 실행 결과 딕셔너리:
                - status: "success", "partial", "error"
                - total_count: 전체 수집 기사 수
                - classified_count: 분류된 기사 수
                - key_count: 핵심뉴스 수
                - translated_count: 번역 성공 수
                - sent_articles: 텔레그램 전송된 핵심뉴스 목록
                - errors: 발생한 에러 목록
        """
        result: dict[str, Any] = {
            "status": "success",
            "total_count": 0,
            "classified_count": 0,
            "key_count": 0,
            "translated_count": 0,
            "sent_articles": [],
            "errors": [],
        }

        # KST 기준 현재 시간
        kst = timezone(timedelta(hours=9))
        timestamp = datetime.now(tz=kst).strftime("%Y-%m-%d %H:%M")

        logger.info(
            "========== NewsPipeline 시작 (mode=%s) ==========",
            crawl_mode,
        )

        # ------------------------------------------------------------------
        # 1단계: 크롤링
        # ------------------------------------------------------------------
        crawl_result: dict[str, Any] = {}
        try:
            logger.info("[1/6] 뉴스 크롤링 (mode=%s)...", crawl_mode)
            crawl_result = await self.crawl_engine.run(mode=crawl_mode)
            result["total_count"] = crawl_result.get(
                "saved", crawl_result.get("total_raw", 0)
            )
            logger.info(
                "크롤링 완료: saved=%d, total_raw=%d",
                crawl_result.get("saved", 0),
                crawl_result.get("total_raw", 0),
            )
        except Exception as exc:
            logger.error("크롤링 실패: %s", exc)
            result["errors"].append(f"crawl: {exc}")
            result["status"] = "partial"
            # 크롤링 실패해도 기존 기사로 계속 진행

        # ------------------------------------------------------------------
        # 2단계: 최신 기사 조회
        # ------------------------------------------------------------------
        articles: list[dict[str, Any]] = []
        try:
            logger.info("[2/6] 최신 기사 조회 (limit=%d)...", article_limit)
            articles = await self._fetch_recent_articles(article_limit)
            logger.info("기사 조회 완료: %d건", len(articles))
        except Exception as exc:
            logger.error("기사 조회 실패: %s", exc)
            result["errors"].append(f"fetch: {exc}")
            result["status"] = "error"
            return result

        if not articles:
            logger.info("처리할 기사 없음. 파이프라인 종료.")
            result["status"] = "success"
            return result

        # ------------------------------------------------------------------
        # 3단계: 분류
        # ------------------------------------------------------------------
        classified_signals: list[dict[str, Any]] = []
        try:
            logger.info("[3/6] 뉴스 분류 (%d건)...", len(articles))
            classified_signals = await self.classifier.classify_and_store_batch(articles)
            result["classified_count"] = len(classified_signals)
            logger.info("분류 완료: %d건", len(classified_signals))
        except Exception as exc:
            logger.error("분류 실패: %s", exc)
            result["errors"].append(f"classify: {exc}")
            result["status"] = "partial"
            # 분류 실패 시 원본 기사를 그대로 사용
            classified_signals = []

        # 분류 결과를 articles에 매핑
        articles_with_classification = self._merge_classification(
            articles, classified_signals
        )

        # ------------------------------------------------------------------
        # 4단계: 핵심뉴스 필터링
        # ------------------------------------------------------------------
        key_articles: list[dict[str, Any]] = []
        try:
            logger.info("[4/6] 핵심뉴스 필터링...")
            key_articles = self.key_filter.filter_key_news(articles_with_classification)
            result["key_count"] = len(key_articles)
            logger.info(
                "핵심뉴스 필터링 완료: 전체 %d건 → 핵심 %d건",
                len(articles_with_classification),
                len(key_articles),
            )
        except Exception as exc:
            logger.error("핵심뉴스 필터링 실패: %s", exc)
            result["errors"].append(f"filter: {exc}")
            result["status"] = "partial"

        # ------------------------------------------------------------------
        # 5단계: 핵심뉴스만 번역 (비용 절감)
        # ------------------------------------------------------------------
        translated_key_articles: list[dict[str, Any]] = key_articles.copy()
        if key_articles:
            try:
                logger.info(
                    "[5/6] 핵심뉴스 한국어 번역 (%d건)...",
                    len(key_articles),
                )
                translated = await self.translator.translate_articles(key_articles)
                if translated:
                    translated_key_articles = translated
                    logger.info("번역 완료: %d건", len(translated))
            except Exception as exc:
                logger.error("번역 실패 (원문 사용): %s", exc)
                result["errors"].append(f"translate: {exc}")
                result["status"] = "partial"
                # 번역 실패해도 원문으로 계속 진행

            # DB에 번역 결과 저장
            try:
                logger.info("[5-1/6] 번역 결과 DB 저장...")
                saved_count = await self.translator.translate_and_save(key_articles)
                result["translated_count"] = saved_count
                logger.info("번역 DB 저장 완료: %d건", saved_count)
            except Exception as exc:
                logger.error("번역 DB 저장 실패: %s", exc)
                result["errors"].append(f"translate_save: {exc}")
        else:
            logger.info("[5/6] 핵심뉴스 없음 - 번역 생략")

        # ------------------------------------------------------------------
        # 6단계: 텔레그램 전송
        # ------------------------------------------------------------------
        if send_telegram and self.telegram_notifier:
            try:
                logger.info("[6/6] 텔레그램 핵심뉴스 전송...")
                # 텔레그램 전송 대상: 최대 N건 (중요도 순으로 이미 정렬됨)
                send_targets = translated_key_articles[:_MAX_KEY_NEWS_TELEGRAM]
                result["sent_articles"] = send_targets

                await self.telegram_notifier.send_key_news_alert(
                    key_articles=send_targets,
                    total_count=len(articles),
                    key_count=len(key_articles),
                    timestamp=timestamp,
                )
                logger.info(
                    "텔레그램 전송 완료: %d건",
                    len(send_targets),
                )
            except Exception as exc:
                logger.error("텔레그램 전송 실패: %s", exc)
                result["errors"].append(f"telegram: {exc}")
                result["status"] = "partial"
        else:
            logger.info("[6/6] 텔레그램 전송 생략 (send_telegram=%s)", send_telegram)

        if result["errors"]:
            if result["status"] == "success":
                result["status"] = "partial"

        logger.info(
            "========== NewsPipeline 완료 (status=%s, total=%d, key=%d, translated=%d) ==========",
            result["status"],
            result["total_count"],
            result["key_count"],
            result["translated_count"],
        )
        return result

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _fetch_recent_articles(
        self, limit: int
    ) -> list[dict[str, Any]]:
        """DB에서 최신 기사를 조회한다.

        Args:
            limit: 조회 건수.

        Returns:
            기사 딕셔너리 목록.
        """
        try:
            from sqlalchemy import select
            from src.db.connection import get_session
            from src.db.models import Article

            async with get_session() as session:
                stmt = (
                    select(Article)
                    .order_by(Article.crawled_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                rows = list(result.scalars().all())

            articles = []
            for row in rows:
                articles.append(
                    {
                        "id": str(row.id),
                        "headline": row.headline or "",
                        "content": row.content or "",
                        "source": row.source or "",
                        "url": row.url,
                        "published_at": str(row.published_at) if row.published_at else None,
                        "tickers_mentioned": row.tickers_mentioned or [],
                        "classification": row.classification or {},
                        "sentiment_score": row.sentiment_score,
                        "is_processed": row.is_processed,
                        "headline_kr": row.headline_kr,
                        "summary_ko": row.summary_ko,
                    }
                )

            return articles

        except Exception as exc:
            logger.error("기사 조회 실패: %s", exc)
            raise

    @staticmethod
    def _merge_classification(
        articles: list[dict[str, Any]],
        classified_signals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """기사 목록과 분류 결과를 병합한다.

        분류 결과의 id를 기준으로 기사 딕셔너리에
        classification, tickers_mentioned 필드를 업데이트한다.

        Args:
            articles: 원본 기사 목록.
            classified_signals: 분류 결과 목록.

        Returns:
            분류 정보가 병합된 기사 목록.
        """
        if not classified_signals:
            return articles

        # 분류 결과 인덱스 구성
        signal_map: dict[str, dict[str, Any]] = {
            str(s.get("id", "")): s for s in classified_signals
        }

        merged = []
        for article in articles:
            article_id = str(article.get("id", ""))
            signal = signal_map.get(article_id)

            if signal:
                merged_article = {
                    **article,
                    "classification": {
                        "impact": signal.get("impact", "low"),
                        "direction": signal.get("direction", "neutral"),
                        "category": signal.get("category", "other"),
                        "tickers": signal.get("tickers", []),
                    },
                    "tickers_mentioned": signal.get("tickers", article.get("tickers_mentioned", [])),
                }
            else:
                merged_article = article.copy()

            merged.append(merged_article)

        return merged
