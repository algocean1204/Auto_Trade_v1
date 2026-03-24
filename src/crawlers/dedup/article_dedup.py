"""F1 데이터 수집 -- SHA-256 해시 기반 기사 중복 검사기이다.

기사의 content_hash를 캐시에 저장하고, 동일 해시가 이미 존재하면
중복으로 판정한다. TTL 48시간으로 자동 만료된다.
URL 정규화를 적용하여 utm 파라미터/www 등 변형에 의한 오판을 방지한다.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.crawlers.models import DeduplicationResult, VerifiedArticle

logger = get_logger(__name__)

# 캐시 키 접두사이다
_KEY_PREFIX: str = "dedup:"

# 중복 키 TTL (48시간 = 172800초)이다
_DEDUP_TTL: int = 172800

# URL 정규화 시 제거할 쿼리 파라미터 접두사이다
_STRIP_PARAMS: set[str] = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "referrer", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
}


def _normalize_url(url: str) -> str:
    """URL을 정규화한다. 추적 파라미터/www/trailing slash를 제거한다."""
    parsed = urlparse(url)
    # www. 제거
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    # 추적 파라미터 제거
    params = parse_qs(parsed.query, keep_blank_values=False)
    cleaned = {k: v for k, v in params.items() if k not in _STRIP_PARAMS}
    query = urlencode(cleaned, doseq=True) if cleaned else ""
    # trailing slash 제거
    path = parsed.path.rstrip("/")
    return urlunparse(("https", host, path, "", query, ""))


def _build_key(content_hash: str) -> str:
    """캐시 키를 생성한다. dedup:{hash} 형식이다."""
    return f"{_KEY_PREFIX}{content_hash}"


class ArticleDeduplicator:
    """캐시 기반 기사 중복 검사기이다.

    SHA-256 content_hash를 캐시에 저장하여 중복을 판별한다.
    TTL 48시간으로 자동 만료되어 메모리를 관리한다.
    """

    def __init__(self, cache: CacheClient) -> None:
        """캐시 클라이언트를 주입받아 초기화한다."""
        self._cache = cache

    async def check(self, article: VerifiedArticle) -> DeduplicationResult:
        """기사의 중복 여부를 검사한다.

        캐시에 해시가 존재하면 중복(is_new=False),
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

        # 신규 기사: 캐시에 URL을 저장한다
        await self._cache.write(key, article.url, ttl=_DEDUP_TTL)
        logger.debug("신규 기사 등록: %s", article.url)

        return DeduplicationResult(
            is_new=True,
            content_hash=article.content_hash,
            existing_url=None,
        )

    async def warm_from_db(self, hashes: set[str]) -> int:
        """DB의 기존 content_hash로 캐시를 예열한다.

        서버 재시작 후 InMemoryCache가 비어있을 때 호출하여
        이미 DB에 저장된 기사의 재크롤링을 방지한다.
        이미 캐시에 존재하는 해시는 건너뛴다.
        """
        warmed = 0
        for h in hashes:
            key = _build_key(h)
            existing = await self._cache.read(key)
            if existing is None:
                await self._cache.write(key, "db_warmed", ttl=_DEDUP_TTL)
                warmed += 1
        if warmed > 0:
            logger.info("dedup 캐시 예열 완료: %d건 (DB 기반)", warmed)
        return warmed
