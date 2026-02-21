"""뉴스 수집 및 텔레그램 전송 API 엔드포인트.

대시보드의 "뉴스 수집 & 전송" 버튼에서 호출한다.
크롤링 -> 분류 -> 핵심뉴스 필터링 -> 한국어 번역 -> 텔레그램 전송 파이프라인을 실행한다.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.monitoring.auth import verify_api_key
from src.monitoring.schemas import ErrorResponse
from src.utils.logger import get_logger

logger = get_logger(__name__)

news_collect_router = APIRouter(prefix="/api/news", tags=["news-collect"])

# ---------------------------------------------------------------------------
# 의존성 레지스트리 -- set_news_collect_deps() 호출로 주입된다.
# ---------------------------------------------------------------------------

_crawl_engine: Any = None
_classifier: Any = None
_claude_client: Any = None
_telegram_notifier: Any = None

# 상수
_ARTICLE_LIMIT: int = 30  # 분류 대상 최신 기사 조회 건수
_MAX_HIGH_IMPACT_TELEGRAM: int = 10  # 텔레그램 전송 핵심뉴스 최대 건수
_MAX_TICKERS_PER_SIGNAL: int = 5  # 신호당 최대 표시 종목 수


def set_news_collect_deps(
    crawl_engine: Any = None,
    classifier: Any = None,
    claude_client: Any = None,
    telegram_notifier: Any = None,
) -> None:
    """뉴스 수집 엔드포인트에 필요한 의존성을 주입한다.

    api_server.py의 set_dependencies()에서 호출한다.

    Args:
        crawl_engine: CrawlEngine 인스턴스.
        classifier: NewsClassifier 인스턴스.
        claude_client: ClaudeClient 인스턴스 (번역용).
        telegram_notifier: TelegramNotifier 인스턴스.
    """
    global _crawl_engine, _classifier, _claude_client, _telegram_notifier
    _crawl_engine = crawl_engine
    _classifier = classifier
    _claude_client = claude_client
    _telegram_notifier = telegram_notifier


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------


async def _fetch_latest_articles(limit: int = _ARTICLE_LIMIT) -> list[dict[str, Any]]:
    """최신 기사를 DB에서 가져온다.

    Args:
        limit: 조회할 최대 기사 수.

    Returns:
        기사 딕셔너리 목록.
    """
    from sqlalchemy import select

    from src.db.connection import get_session
    from src.db.models import Article

    async with get_session() as session:
        stmt = (
            select(Article)
            .order_by(Article.published_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        articles = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "title": a.headline,
            "content": a.content or "",
            "source": a.source,
            "url": a.url,
            "published_at": a.published_at,
        }
        for a in articles
    ]


async def _fetch_article_objects_for_translation(
    article_ids: list[str],
) -> list[Any]:
    """번역 대상 Article ORM 객체를 DB에서 가져온다.

    Args:
        article_ids: 기사 ID 목록 (문자열).

    Returns:
        Article ORM 객체 목록.
    """
    from sqlalchemy import select

    from src.db.connection import get_session
    from src.db.models import Article

    async with get_session() as session:
        stmt = (
            select(Article)
            .where(Article.id.in_(article_ids))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _build_telegram_message(
    classified_signals: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    translated_articles: list[Any] | None = None,
) -> tuple[str, str, int, int]:
    """텔레그램 전송용 메시지를 구성한다.

    Args:
        classified_signals: 분류 결과 목록.
        articles: 원본 기사 딕셔너리 목록.
        translated_articles: 번역된 Article ORM 객체 목록 (있을 경우).

    Returns:
        (title, message, high_count, total_count) 튜플.
    """
    high_impact = [s for s in classified_signals if s.get("impact") == "high"]
    medium_count = sum(1 for s in classified_signals if s.get("impact") == "medium")
    low_count = sum(1 for s in classified_signals if s.get("impact") == "low")

    article_map = {str(a.get("id", "")): a for a in articles}

    # 번역된 기사 매핑 (있을 경우)
    translated_map: dict[str, Any] = {}
    if translated_articles:
        for art in translated_articles:
            translated_map[str(art.id)] = art

    msg_lines: list[str] = []
    for sig in high_impact[:_MAX_HIGH_IMPACT_TELEGRAM]:
        article = article_map.get(str(sig.get("id", "")), {})
        art_id = str(sig.get("id", ""))

        # 번역된 헤드라인이 있으면 사용, 없으면 원문
        translated_art = translated_map.get(art_id)
        if translated_art and getattr(translated_art, "headline_kr", None):
            title = translated_art.headline_kr
        else:
            title = article.get("title", sig.get("id", "N/A"))

        tickers = ", ".join(sig.get("tickers", [])[:_MAX_TICKERS_PER_SIGNAL])
        direction = sig.get("direction", "neutral")
        score = sig.get("sentiment_score", 0.0)
        category = sig.get("category", "other")
        direction_emoji = (
            "\U0001f4c8" if direction == "bullish"
            else "\U0001f4c9" if direction == "bearish"
            else "\u27a1\ufe0f"
        )
        msg_lines.append(
            f"{direction_emoji} [{category.upper()}] {title}\n"
            f"  종목: {tickers} | 감성: {score:+.2f}"
        )

    # 요약 행 추가
    summary_line = (
        f"\n---\n"
        f"전체: {len(classified_signals)}건 | "
        f"HIGH: {len(high_impact)}건 | "
        f"MEDIUM: {medium_count}건 | "
        f"LOW: {low_count}건"
    )

    news_title = f"뉴스 수집 & 분류 완료 ({len(high_impact)}건 핵심)"
    news_message = "\n\n".join(msg_lines) + summary_line if msg_lines else summary_line.strip()

    return news_title, news_message, len(high_impact), len(classified_signals)


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@news_collect_router.post(
    "/collect-and-send",
    responses={
        200: {"description": "뉴스 수집 및 전송 성공"},
        503: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    dependencies=[Depends(verify_api_key)],
)
async def collect_and_send_news() -> JSONResponse:
    """뉴스 수집 -> 분류 -> 핵심뉴스 번역 -> 텔레그램 전송 파이프라인을 실행한다.

    1. CrawlEngine으로 전체 크롤링을 실행한다.
    2. NewsClassifier로 최신 기사를 분류한다.
    3. 핵심뉴스(high/critical impact)를 필터링한다.
    4. 핵심뉴스를 한국어로 번역한다 (Claude Sonnet).
    5. 텔레그램으로 요약 전송한다.

    Returns:
        status: "sent" | "sent_no_key_news"
        news_count: 전체 분류된 뉴스 수.
        key_news_count: 핵심뉴스(high impact) 수.
        crawl_saved: 크롤링으로 저장된 기사 수.
        telegram_sent: 텔레그램 전송 성공 여부.
    """
    # 의존성 확인
    if _crawl_engine is None:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "CrawlEngine이 초기화되지 않았습니다.",
                "error_code": "CRAWL_ENGINE_NOT_READY",
            },
        )

    if _classifier is None:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "NewsClassifier가 초기화되지 않았습니다.",
                "error_code": "CLASSIFIER_NOT_READY",
            },
        )

    try:
        # Step 1: 크롤링 실행
        logger.info("[뉴스 수집] Step 1: 크롤링 시작...")
        crawl_result = await _crawl_engine.run_fault_isolated()
        crawl_saved = crawl_result.get("total_raw", 0)
        logger.info("[뉴스 수집] 크롤링 완료: %d건 수집", crawl_saved)

        # Step 2: 최신 기사 가져오기 및 분류
        logger.info("[뉴스 수집] Step 2: 최신 기사 분류 시작...")
        articles = await _fetch_latest_articles(limit=_ARTICLE_LIMIT)
        classified_signals = await _classifier.classify_and_store_batch(articles)
        logger.info("[뉴스 수집] 분류 완료: %d건", len(classified_signals))

        # Step 3: 핵심뉴스 필터링
        high_impact_signals = [
            s for s in classified_signals if s.get("impact") == "high"
        ]
        logger.info("[뉴스 수집] 핵심뉴스: %d건", len(high_impact_signals))

        # Step 4: 핵심뉴스 한국어 번역 (classifier에 번역 기능 내장)
        translated_articles = None
        if high_impact_signals and _classifier:
            try:
                logger.info("[뉴스 수집] Step 3: 핵심뉴스 한국어 번역 시작...")
                high_impact_ids = [
                    str(s.get("id", "")) for s in high_impact_signals
                ]
                article_objs = await _fetch_article_objects_for_translation(
                    high_impact_ids
                )
                if article_objs:
                    translated_count = await _classifier.translate_and_analyze_batch(
                        article_objs
                    )
                    logger.info(
                        "[뉴스 수집] 번역 완료: %d/%d건",
                        translated_count, len(article_objs),
                    )
                    # 번역 후 다시 DB에서 가져오기 (업데이트된 값 반영)
                    translated_articles = await _fetch_article_objects_for_translation(
                        high_impact_ids
                    )
            except Exception as exc:
                logger.warning("[뉴스 수집] 번역 실패 (계속 진행): %s", exc)

        # Step 5: 텔레그램 전송
        telegram_sent = False
        if _telegram_notifier and classified_signals:
            try:
                logger.info("[뉴스 수집] Step 4: 텔레그램 전송 시작...")
                title, message, high_count, total_count = _build_telegram_message(
                    classified_signals, articles, translated_articles
                )
                telegram_sent = await _telegram_notifier.send_message(
                    title=title,
                    message=message,
                    severity="warning" if high_count > 0 else "info",
                )
                logger.info(
                    "[뉴스 수집] 텔레그램 전송 %s",
                    "성공" if telegram_sent else "실패",
                )
            except Exception as exc:
                logger.warning("[뉴스 수집] 텔레그램 전송 실패: %s", exc)

        status = "sent" if len(high_impact_signals) > 0 else "sent_no_key_news"

        return JSONResponse(
            status_code=200,
            content={
                "status": status,
                "news_count": len(classified_signals),
                "key_news_count": len(high_impact_signals),
                "crawl_saved": crawl_saved,
                "telegram_sent": telegram_sent,
            },
        )

    except Exception as exc:
        logger.exception("[뉴스 수집] 파이프라인 실행 실패: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"뉴스 수집 실패: {exc}",
                "error_code": "NEWS_COLLECT_FAILED",
            },
        )
