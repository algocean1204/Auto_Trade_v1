"""기사 DB 저장 -- 분류된 뉴스를 articles 테이블에 영구 저장한다."""
from __future__ import annotations

import hashlib

from sqlalchemy import select

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
