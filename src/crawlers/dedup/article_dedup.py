"""F1 데이터 수집 -- Redis SHA-256 해시 기반 기사 중복 검사기이다.

기사의 content_hash를 Redis에 저장하고, 동일 해시가 이미 존재하면
중복으로 판정한다. TTL 48시간으로 자동 만료된다.
"""
from __future__ import annotations

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.crawlers.models import DeduplicationResult, VerifiedArticle

logger = get_logger(__name__)

# Redis 키 접두사이다
_KEY_PREFIX: str = "dedup:"

# 중복 키 TTL (48시간 = 172800초)이다
_DEDUP_TTL: int = 172800


def _build_key(content_hash: str) -> str:
    """Redis 키를 생성한다. dedup:{hash} 형식이다."""
    return f"{_KEY_PREFIX}{content_hash}"


class ArticleDeduplicator:
    """Redis 기반 기사 중복 검사기이다.

    SHA-256 content_hash를 Redis에 저장하여 중복을 판별한다.
    TTL 48시간으로 자동 만료되어 메모리를 관리한다.
    """

    def __init__(self, cache: CacheClient) -> None:
        """캐시 클라이언트를 주입받아 초기화한다."""
        self._cache = cache

    async def check(self, article: VerifiedArticle) -> DeduplicationResult:
        """기사의 중복 여부를 검사한다.

        Redis에 해시가 존재하면 중복(is_new=False),
        존재하지 않으면 신규(is_new=True)로 판정한다.
        """
        key = _build_key(article.content_hash)
        existing = await self._cache.read(key)

        if existing is not None:
            logger.debug("중복 기사 감지: %s", article.url)
            return DeduplicationResult(
                is_new=False,
                content_hash=article.content_hash,
                existing_url=existing,
            )

        # 신규 기사: Redis에 URL을 저장한다
        await self._cache.write(key, article.url, ttl=_DEDUP_TTL)
        logger.debug("신규 기사 등록: %s", article.url)

        return DeduplicationResult(
            is_new=True,
            content_hash=article.content_hash,
            existing_url=None,
        )
