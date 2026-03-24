"""기사 DB 저장 -- 분류된 뉴스를 articles 테이블에 영구 저장한다."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger
from src.db.models import Article

logger = get_logger(__name__)


async def persist_articles(
    db: SessionFactory,
    classified: list[dict],
) -> tuple[int, int]:
    """ClassifiedNews dict 리스트를 articles 테이블에 저장한다.

    URL 기준 UPSERT (중복 URL은 건너뜀). (저장 건수, 실패 건수) 튜플을 반환한다.
    기사별 독립 세션을 사용하여 개별 실패가 다른 기사에 영향을 주지 않는다.
    """
    if not classified:
        return 0, 0

    saved = 0
    failed = 0
    for item in classified:
        url = item.get("url", "")
        if not url:
            continue
        try:
            async with db.get_session() as session:
                # URL 기준 존재 확인
                exists = await session.execute(
                    select(Article.id).where(Article.url == url).limit(1),
                )
                if exists.scalar_one_or_none() is not None:
                    continue

                content = item.get("content", "")
                content_hash = hashlib.sha256(content.encode()).hexdigest()

                article = Article(
                    title=item.get("title", ""),
                    content=content,
                    url=url,
                    source=item.get("source", ""),
                    published_at=item.get("published_at"),
                    content_hash=content_hash,
                    impact_score=item.get("impact_score", 0.0),
                    direction=item.get("direction", "neutral"),
                    category=item.get("category", ""),
                )
                session.add(article)
            saved += 1
        except Exception as exc:
            failed += 1
            logger.warning("[Step 3.5] 기사 저장 실패 (건너뜀): %s -- %s", url[:80], exc)

    logger.info("[Step 3.5] DB 저장 완료: 성공=%d, 실패=%d, 전체=%d건", saved, failed, len(classified))
    return saved, failed


async def get_last_article_time(db: SessionFactory) -> datetime | None:
    """DB에 저장된 마지막 기사의 created_at을 반환한다.

    파이프라인 시작 시 호출하여 이 시점 이후의 뉴스만 처리하도록 한다.
    기사가 없으면 None을 반환한다.
    """
    try:
        async with db.get_session() as session:
            result = await session.execute(
                select(func.max(Article.created_at)),
            )
            return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("마지막 기사 시각 조회 실패: %s", exc)
        return None


async def get_recent_content_hashes(
    db: SessionFactory,
    hours: int = 72,
) -> set[str]:
    """최근 N시간 이내 기사의 content_hash 집합을 반환한다.

    서버 재시작 후 dedup 캐시 예열에 사용한다.
    InMemoryCache는 휘발성이므로 DB 기반으로 복구해야 중복 크롤링을 방지한다.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with db.get_session() as session:
            result = await session.execute(
                select(Article.content_hash).where(
                    Article.created_at >= cutoff,
                    Article.content_hash.is_not(None),
                ),
            )
            hashes = {row[0] for row in result.all() if row[0]}
            logger.info("DB에서 최근 %d시간 기사 해시 %d건 조회", hours, len(hashes))
            return hashes
    except Exception as exc:
        logger.warning("기사 해시 조회 실패: %s", exc)
        return set()
