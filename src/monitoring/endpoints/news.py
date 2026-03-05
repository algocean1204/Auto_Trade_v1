"""F7.7 NewsEndpoints -- 뉴스 수집/조회 API이다.

뉴스 날짜 목록, 일별 뉴스, 기사 상세, 요약, 수동 수집을 제공한다.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

news_router = APIRouter(prefix="/api/news", tags=["news"])

_system: InjectedSystem | None = None


class NewsDatesResponse(BaseModel):
    """뉴스 날짜 목록 응답 모델이다.

    각 항목은 {"date": "2026-03-02", "article_count": 33} 형태의 dict이다.
    Flutter NewsDate.fromJson이 이 형식을 기대한다.
    """

    dates: list[dict[str, Any]] = Field(default_factory=list)


class DailyNewsResponse(BaseModel):
    """일별 뉴스 응답 모델이다."""

    date: str
    articles: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class NewsSummaryResponse(BaseModel):
    """뉴스 요약 응답 모델이다.

    Flutter NewsSummary.fromJson이 최상위에서 date, total_articles, by_category 등
    필드를 직접 읽으므로 summary dict를 래핑 없이 평탄하게 반환한다.
    """

    date: str = ""
    total_articles: int = 0
    by_category: dict[str, Any] = Field(default_factory=dict)
    by_source: dict[str, Any] = Field(default_factory=dict)
    sentiment_distribution: dict[str, Any] = Field(default_factory=dict)
    high_impact_articles: list[dict[str, Any]] = Field(default_factory=list)
    importance_distribution: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class ArticleDetailResponse(BaseModel):
    """기사 상세 응답 모델이다."""

    article: dict[str, Any] = Field(default_factory=dict)


class NewsCollectResponse(BaseModel):
    """뉴스 수집 파이프라인 결과 응답 모델이다.

    파이프라인 완료까지 대기한 뒤 실제 결과를 반환한다.
    """

    status: str
    message: str
    news_count: int = 0
    key_news_count: int = 0
    telegram_sent: bool = False
    crawled_count: int = 0
    translated_count: int = 0
    persisted_count: int = 0


def set_news_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("NewsEndpoints 의존성 주입 완료")


@news_router.get("/dates", response_model=NewsDatesResponse)
async def get_news_dates(limit: int = 30) -> NewsDatesResponse:
    """뉴스가 존재하는 날짜 목록을 반환한다. limit로 최대 개수를 제한한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("news:dates")
        dates = cached if isinstance(cached, list) else []
        return NewsDatesResponse(dates=dates[:limit])
    except HTTPException:
        raise
    except Exception:
        _logger.exception("뉴스 날짜 조회 실패")
        raise HTTPException(status_code=500, detail="날짜 조회 실패") from None


@news_router.get("/daily", response_model=DailyNewsResponse)
async def get_daily_news(
    date: str = "",
    limit: int = 50,
    category: str | None = None,
    impact: str | None = None,
    offset: int = 0,
) -> DailyNewsResponse:
    """일별 뉴스 목록을 반환한다. date 파라미터로 날짜를 지정한다.

    category, impact로 필터링하고 offset/limit로 페이지네이션한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        from datetime import datetime, timezone

        cache = _system.components.cache
        # 날짜 미지정 시 오늘 날짜의 Flutter 형식 데이터를 읽는다
        target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"news:daily:{target_date}"
        cached = await cache.read_json(key)
        articles = cached if isinstance(cached, list) else []

        # Flutter 형식 데이터가 없으면 raw 분류 데이터에서 변환한다
        if not articles and not date:
            from src.orchestration.phases.news_pipeline import _to_flutter_article

            raw = await cache.read_json("news:classified_latest")
            if isinstance(raw, list):
                articles = [_to_flutter_article(a) for a in raw]

        # category 필터링
        if category:
            articles = [
                a for a in articles
                if isinstance(a, dict) and a.get("category") == category
            ]
        # impact 필터링
        if impact:
            articles = [
                a for a in articles
                if isinstance(a, dict) and a.get("impact") == impact
            ]

        total = len(articles)
        # offset + limit 페이지네이션
        articles = articles[offset : offset + limit]

        return DailyNewsResponse(
            date=date or "latest",
            articles=articles,
            total=total,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("일별 뉴스 조회 실패: %s", date)
        raise HTTPException(status_code=500, detail="뉴스 조회 실패") from None


@news_router.get("/summary", response_model=NewsSummaryResponse)
async def get_news_summary(date: str | None = None) -> NewsSummaryResponse:
    """뉴스 요약을 반환한다. date 파라미터로 특정 날짜를 지정할 수 있다.

    Flutter NewsSummary.fromJson이 최상위 필드를 직접 읽으므로
    summary dict를 래핑 없이 평탄하게 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # date 지정 시 해당 날짜 요약, 미지정 시 최신 요약을 읽는다
        key = f"news:summary:{date}" if date else "news:latest_summary"
        cached = await cache.read_json(key)
        if cached and isinstance(cached, dict):
            return NewsSummaryResponse(**cached)
        return NewsSummaryResponse(message="요약 데이터가 없다")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("뉴스 요약 조회 실패")
        raise HTTPException(status_code=500, detail="요약 조회 실패") from None


@news_router.get("/{article_id}", response_model=ArticleDetailResponse)
async def get_article_detail(article_id: str) -> ArticleDetailResponse:
    """기사 상세 정보를 반환한다.

    1차: news:article:{id} 개별 캐시에서 조회한다.
    2차: news:daily:{today} 목록에서 id가 일치하는 기사를 검색한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # 1차: 개별 기사 캐시
        cached = await cache.read_json(f"news:article:{article_id}")
        if cached and isinstance(cached, dict):
            return ArticleDetailResponse(article=cached)

        # 2차: 오늘 날짜 daily 캐시에서 id 매칭 검색
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = await cache.read_json(f"news:daily:{today}")
        if isinstance(daily, list):
            for item in daily:
                if isinstance(item, dict) and item.get("id") == article_id:
                    # 찾은 기사를 개별 캐시에도 저장한다 (다음 조회 시 1차에서 히트)
                    await cache.write_json(
                        f"news:article:{article_id}", item, ttl=7200,
                    )
                    return ArticleDetailResponse(article=item)

        raise HTTPException(status_code=404, detail="기사를 찾을 수 없다")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("기사 상세 조회 실패: %s", article_id)
        raise HTTPException(status_code=500, detail="기사 조회 실패") from None


@news_router.post("/collect", response_model=NewsCollectResponse)
async def trigger_news_collection(
    _key: str = Depends(verify_api_key),
) -> NewsCollectResponse:
    """뉴스 파이프라인을 동기 실행하고 결과를 반환한다.

    크롤링→분류→병합→번역→DB저장→텔레그램 전체 파이프라인을 실행하고
    완료될 때까지 대기한다. 8~15분 소요된다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        from src.orchestration.phases.news_pipeline import run_news_pipeline

        result = await run_news_pipeline(_system)
        _logger.info(
            "수동 뉴스 파이프라인 완료: crawled=%d, classified=%d, high=%d",
            result.crawled_count, result.classified_count,
            result.high_impact_count,
        )
        return NewsCollectResponse(
            status="sent" if result.sent_to_telegram else "sent_no_key_news",
            message=(
                f"크롤링 {result.crawled_count}건, 분류 {result.classified_count}건, "
                f"번역 {result.translated_count}건, 고영향 {result.high_impact_count}건"
            ),
            news_count=result.classified_count,
            key_news_count=result.high_impact_count,
            telegram_sent=result.sent_to_telegram,
            crawled_count=result.crawled_count,
            translated_count=result.translated_count,
            persisted_count=result.persisted_count,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("뉴스 파이프라인 실행 실패")
        raise HTTPException(status_code=500, detail="뉴스 파이프라인 실행 실패") from None


@news_router.post("/collect-and-send", response_model=NewsCollectResponse)
async def collect_and_send_news(
    _key: str = Depends(verify_api_key),
) -> NewsCollectResponse:
    """collect의 별칭이다. Flutter 호환용."""
    return await trigger_news_collection(_key=_key)


class SituationListResponse(BaseModel):
    """상황 보고서 목록 응답 모델이다."""

    situations: list[dict[str, Any]] = Field(default_factory=list)


class ThemeListResponse(BaseModel):
    """뉴스 테마 목록 응답 모델이다."""

    themes: list[dict[str, Any]] = Field(default_factory=list)


@news_router.get("/situations/list", response_model=SituationListResponse)
async def get_situations() -> SituationListResponse:
    """활성 상황 보고서 목록을 반환한다.

    Redis에 캐시된 상황 보고서와 메타데이터를 조회한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache

        # 최신 상황 보고서 (파이프라인 실행 시 저장됨)
        cached_reports = await cache.read_json("news:situation_reports_latest")
        reports: list[dict] = (
            cached_reports if isinstance(cached_reports, list) else []
        )

        # 활성 상황 ID 목록에서 메타데이터도 조회한다
        active_ids = await cache.read_json("situation:active_ids")
        if isinstance(active_ids, list):
            for sid in active_ids:
                meta = await cache.read_json(f"situation:{sid}:meta")
                if isinstance(meta, dict):
                    # 이미 reports에 있는 situation_id는 건너뛴다
                    existing_ids = {r.get("situation_id") for r in reports}
                    if sid not in existing_ids:
                        # 타임라인도 로드한다
                        timeline = await cache.read_json(
                            f"situation:{sid}:timeline",
                        )
                        meta["timeline"] = (
                            timeline if isinstance(timeline, list) else []
                        )
                        reports.append(meta)

        return SituationListResponse(situations=reports)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("상황 보고서 조회 실패")
        raise HTTPException(status_code=500, detail="상황 보고서 조회 실패") from None


@news_router.get("/themes/list", response_model=ThemeListResponse)
async def get_themes() -> ThemeListResponse:
    """뉴스 테마 목록을 반환한다.

    Redis에 캐시된 반복 테마를 조회한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("news:themes_latest")
        themes = cached if isinstance(cached, list) else []
        return ThemeListResponse(themes=themes)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("뉴스 테마 조회 실패")
        raise HTTPException(status_code=500, detail="테마 조회 실패") from None
