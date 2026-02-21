"""
Flutter 대시보드용 뉴스 기사 API 엔드포인트.

PostgreSQL articles 테이블에서 크롤링된 뉴스 기사를
날짜 목록, 일별 기사 목록, 기사 상세, 일별 요약 형태로 제공한다.

엔드포인트 등록 순서 (중요):
    /dates  → /summary  → /daily  → /{article_id}
    /summary 가 /{article_id} 보다 먼저 등록되어야 "summary"가
    article_id 로 매칭되지 않는다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import DATE

from src.db.connection import get_session
from src.db.models import Article
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _article_to_dict(article: Article, full_content: bool = False) -> dict[str, Any]:
    """Article ORM 객체를 JSON 직렬화 가능한 딕셔너리로 변환한다.

    Args:
        article: Article ORM 인스턴스.
        full_content: True이면 content 전체를 반환하고,
                      False이면 최대 500자로 잘라서 반환한다.

    Returns:
        Flutter 대시보드가 소비할 기사 딕셔너리.
    """
    classification = article.classification or {}
    content = article.content or ""
    return {
        "id": str(article.id),
        "headline": article.headline,
        "headline_kr": article.headline_kr,
        "content": content if full_content else content[:500],
        "summary_ko": article.summary_ko,
        "companies_impact": article.companies_impact,
        "url": article.url,
        "source": article.source,
        "published_at": (
            article.published_at.isoformat() if article.published_at else None
        ),
        "tickers": article.tickers_mentioned or [],
        "sentiment_score": article.sentiment_score,
        "impact": classification.get("impact", "low"),
        "direction": classification.get("direction", "neutral"),
        "category": classification.get("category", "other"),
        "importance": classification.get("importance", "normal"),
    }


# ---------------------------------------------------------------------------
# GET /api/news/dates
# ---------------------------------------------------------------------------


@router.get("/dates")
async def get_news_dates(
    limit: int = Query(default=30, ge=1, le=90),
) -> dict[str, Any]:
    """뉴스가 존재하는 날짜 목록을 최신순으로 반환한다.

    영문(language="en") 기사만 집계하며, 날짜별 기사 건수도 함께 반환한다.

    Args:
        limit: 반환할 최대 날짜 수 (1~90, 기본 30).

    Returns:
        dates 키에 {"date": "YYYY-MM-DD", "article_count": N} 리스트를 담은 딕셔너리.
    """
    try:
        async with get_session() as session:
            result = await session.execute(
                select(
                    cast(Article.published_at, DATE).label("date"),
                    func.count(Article.id).label("count"),
                )
                .where(Article.published_at.isnot(None))
                .where(Article.language == "en")
                .group_by(cast(Article.published_at, DATE))
                .order_by(cast(Article.published_at, DATE).desc())
                .limit(limit)
            )
            dates = [
                {"date": str(row.date), "article_count": row.count}
                for row in result
            ]
        return {"dates": dates}
    except Exception as exc:
        logger.error("뉴스 날짜 목록 조회 실패: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="뉴스 날짜 목록 조회 중 오류가 발생했습니다",
        )


# ---------------------------------------------------------------------------
# GET /api/news/summary  (반드시 /{article_id} 보다 먼저 등록)
# ---------------------------------------------------------------------------


@router.get("/summary")
async def get_news_summary(
    date: str | None = Query(default=None),
) -> dict[str, Any]:
    """일별 뉴스 요약을 반환한다.

    카테고리별 기사 건수, 소스별 건수, 감성 분포, 고영향 주요 기사 목록을 제공한다.
    date 파라미터를 생략하면 UTC 오늘 날짜 기준으로 집계한다.

    Args:
        date: 조회할 날짜 (YYYY-MM-DD). 생략 시 오늘.

    Returns:
        date, total_articles, by_category, by_source,
        sentiment_distribution, high_impact_articles 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 400: 날짜 형식이 잘못된 경우.
        HTTPException 500: DB 조회 오류.
    """
    try:
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        else:
            target_date = datetime.now(timezone.utc).date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력하세요.",
        )

    start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    try:
        async with get_session() as session:
            result = await session.execute(
                select(Article)
                .where(Article.published_at >= start_dt)
                .where(Article.published_at < end_dt)
                .where(Article.language == "en")
                .order_by(Article.published_at.desc())
            )
            articles = result.scalars().all()
    except Exception as exc:
        logger.error("뉴스 요약 DB 조회 실패 (date=%s): %s", target_date, exc)
        raise HTTPException(
            status_code=500,
            detail="뉴스 요약 조회 중 오류가 발생했습니다",
        )

    # 집계
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    sentiment_dist: dict[str, int] = {"bullish": 0, "bearish": 0, "neutral": 0}
    importance_dist: dict[str, int] = {"critical": 0, "key": 0, "normal": 0}
    high_impact_articles: list[dict[str, Any]] = []

    for a in articles:
        classification = a.classification or {}
        category = classification.get("category", "other")
        impact = classification.get("impact", "low")
        direction = classification.get("direction", "neutral")
        importance = classification.get("importance", "normal")

        # 카테고리별 집계
        by_category[category] = by_category.get(category, 0) + 1

        # 소스별 집계
        by_source[a.source] = by_source.get(a.source, 0) + 1

        # 감성 분포 집계
        if direction == "bullish":
            sentiment_dist["bullish"] += 1
        elif direction == "bearish":
            sentiment_dist["bearish"] += 1
        else:
            sentiment_dist["neutral"] += 1

        # 중요도 분포 집계
        if importance in importance_dist:
            importance_dist[importance] += 1
        else:
            importance_dist["normal"] += 1

        # 고영향 기사 수집 (impact==high 또는 importance==critical)
        if impact == "high" or importance == "critical":
            high_impact_articles.append(_article_to_dict(a))

    # 고영향 기사: 감성 점수 절대값 내림차순 정렬 후 상위 10개
    high_impact_articles.sort(
        key=lambda x: abs(x.get("sentiment_score") or 0.0),
        reverse=True,
    )

    return {
        "date": str(target_date),
        "total_articles": len(articles),
        "by_category": by_category,
        "by_source": by_source,
        "sentiment_distribution": sentiment_dist,
        "importance_distribution": importance_dist,
        "high_impact_articles": high_impact_articles[:10],
    }


# ---------------------------------------------------------------------------
# GET /api/news/daily
# ---------------------------------------------------------------------------


@router.get("/daily")
async def get_daily_news(
    date: str = Query(..., description="조회할 날짜 (YYYY-MM-DD)"),
    category: str | None = Query(default=None, description="카테고리 필터"),
    impact: str | None = Query(default=None, description="영향도 필터 (high/medium/low)"),
    importance: str | None = Query(default=None, description="중요도 필터 (critical/key/normal)"),
    source: str | None = Query(default=None, description="뉴스 소스 필터"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """특정 날짜의 뉴스 기사 목록을 반환한다.

    카테고리, 영향도, 중요도, 소스로 필터링하고 페이지네이션을 지원한다.
    content는 최대 500자로 잘라서 반환한다 (목록 뷰 최적화).

    Args:
        date: 조회할 날짜 (YYYY-MM-DD, 필수).
        category: 카테고리 필터 (macro/earnings/company/sector/policy/geopolitics).
        impact: 영향도 필터 (high/medium/low).
        importance: 중요도 필터 (critical/key/normal).
                    critical = 모니터링 종목 직접 언급 + high impact.
                    key = 모니터링 섹터 관련 + medium 이상 impact.
                    normal = 그 외.
        source: 뉴스 소스 이름 필터.
        limit: 페이지당 최대 기사 수 (1~200, 기본 50).
        offset: 페이지네이션 오프셋 (기본 0).

    Returns:
        date, total, articles 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 400: 날짜 형식이 잘못된 경우.
        HTTPException 500: DB 조회 오류.
    """
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력하세요.",
        )

    # importance 값 검증
    _valid_importance = {"critical", "key", "normal"}
    if importance is not None and importance not in _valid_importance:
        raise HTTPException(
            status_code=400,
            detail=f"importance는 {_valid_importance} 중 하나여야 합니다.",
        )

    start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    try:
        async with get_session() as session:
            # 기본 쿼리 빌드
            base_query = (
                select(Article)
                .where(Article.published_at >= start_dt)
                .where(Article.published_at < end_dt)
                .where(Article.language == "en")
            )

            # 선택적 필터 적용
            if category:
                base_query = base_query.where(
                    Article.classification["category"].astext == category
                )
            if impact:
                base_query = base_query.where(
                    Article.classification["impact"].astext == impact
                )
            if importance:
                base_query = base_query.where(
                    Article.classification["importance"].astext == importance
                )
            if source:
                base_query = base_query.where(Article.source == source)

            # 전체 건수 집계
            count_query = select(func.count()).select_from(base_query.subquery())
            total_result = await session.execute(count_query)
            total = total_result.scalar() or 0

            # 기사 목록 조회
            articles_query = (
                base_query
                .order_by(Article.published_at.desc())
                .offset(offset)
                .limit(min(limit, 200))
            )
            result = await session.execute(articles_query)
            articles = result.scalars().all()

        return {
            "date": date,
            "total": total,
            "articles": [_article_to_dict(a) for a in articles],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "일별 뉴스 조회 실패 (date=%s, category=%s, impact=%s, importance=%s): %s",
            date, category, impact, importance, exc,
        )
        raise HTTPException(
            status_code=500,
            detail="일별 뉴스 조회 중 오류가 발생했습니다",
        )


# ---------------------------------------------------------------------------
# GET /api/news/{article_id}  (반드시 마지막에 등록)
# ---------------------------------------------------------------------------


@router.get("/{article_id}")
async def get_article_detail(article_id: str) -> dict[str, Any]:
    """기사 상세 내용을 반환한다.

    content 전체와 is_processed, crawled_at 등 메타데이터를 포함한다.

    Args:
        article_id: UUID 형식의 기사 ID.

    Returns:
        id, headline, content(전체), url, source, published_at,
        tickers, sentiment_score, impact, direction, category,
        is_processed, crawled_at 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 404: 해당 ID의 기사가 존재하지 않거나 UUID 형식이 잘못된 경우.
        HTTPException 500: DB 조회 오류.
    """
    # UUID 형식 검증: 잘못된 형식이면 즉시 404 반환 (DB 조회 없이 처리)
    try:
        parsed_id = uuid.UUID(article_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="기사를 찾을 수 없습니다.",
        )

    try:
        async with get_session() as session:
            result = await session.execute(
                select(Article).where(Article.id == str(parsed_id))
            )
            article = result.scalar_one_or_none()

        if article is None:
            raise HTTPException(
                status_code=404,
                detail="기사를 찾을 수 없습니다.",
            )

        classification = article.classification or {}
        return {
            "id": str(article.id),
            "headline": article.headline,
            "headline_kr": article.headline_kr,
            "content": article.content,
            "summary_ko": article.summary_ko,
            "companies_impact": article.companies_impact,
            "url": article.url,
            "source": article.source,
            "published_at": (
                article.published_at.isoformat() if article.published_at else None
            ),
            "tickers": article.tickers_mentioned or [],
            "sentiment_score": article.sentiment_score,
            "impact": classification.get("impact", "low"),
            "direction": classification.get("direction", "neutral"),
            "category": classification.get("category", "other"),
            "is_processed": article.is_processed,
            "crawled_at": (
                article.crawled_at.isoformat() if article.crawled_at else None
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("기사 상세 조회 실패 (article_id=%s): %s", article_id, exc)
        raise HTTPException(
            status_code=500,
            detail="기사 상세 조회 중 오류가 발생했습니다",
        )
