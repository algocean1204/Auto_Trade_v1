"""F1 데이터 수집 -- 수집된 기사 품질 검증기이다.

필드 완전성, 최소 내용 길이, 발행일 유효성, SHA-256 해시를 검증한다.
통과하지 못한 기사는 None으로 반환하여 파이프라인에서 제외된다.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from src.common.logger import get_logger
from src.crawlers.models import RawArticle, VerifiedArticle

logger = get_logger(__name__)

# 최소 본문 길이(문자 수)이다
_MIN_CONTENT_LENGTH: int = 50

# 유효 기사 최대 경과 시간(시간)이다
_MAX_AGE_HOURS: int = 24

# 품질 점수 계산 가중치이다
_SCORE_WEIGHTS: dict[str, float] = {
    "content_length": 0.4,   # 본문 길이 비중
    "has_published": 0.3,    # 발행일 존재 여부
    "title_length": 0.3,     # 제목 길이 비중
}

# 본문 길이 기준 최대 점수 획득 기준(문자 수)이다
_CONTENT_LENGTH_CAP: int = 2000


def _compute_content_hash(title: str, url: str) -> str:
    """제목과 URL의 SHA-256 해시를 생성한다."""
    raw = f"{title}|{url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_within_age_limit(published_at: datetime | None) -> bool:
    """발행일이 24시간 이내인지 검증한다. None이면 통과시킨다."""
    if published_at is None:
        return True
    now = datetime.now(tz=timezone.utc)
    # timezone-naive인 경우 UTC로 간주한다
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    return (now - published_at) < timedelta(hours=_MAX_AGE_HOURS)


def _calculate_quality_score(article: RawArticle) -> float:
    """기사 품질 점수(0.0~1.0)를 계산한다."""
    # 본문 길이 점수: 길수록 높지만 _CONTENT_LENGTH_CAP에서 포화한다
    content_ratio = min(len(article.content) / _CONTENT_LENGTH_CAP, 1.0)
    content_score = content_ratio * _SCORE_WEIGHTS["content_length"]

    # 발행일 존재 여부 점수
    pub_score = _SCORE_WEIGHTS["has_published"] if article.published_at else 0.0

    # 제목 길이 점수: 10자 이상이면 만점이다
    title_ratio = min(len(article.title) / 10, 1.0)
    title_score = title_ratio * _SCORE_WEIGHTS["title_length"]

    return round(content_score + pub_score + title_score, 3)


def _check_required_fields(article: RawArticle) -> bool:
    """필수 필드(title, url)가 비어있지 않은지 검증한다."""
    return bool(article.title.strip() and article.url.strip())


class CrawlVerifier:
    """크롤링된 기사 품질 검증기이다.

    필드 완전성, 최소 내용 길이(50자), 24시간 이내 기사,
    SHA-256 해시 생성을 수행한다.
    """

    def verify(self, article: RawArticle) -> VerifiedArticle | None:
        """기사를 검증한다. 통과 시 VerifiedArticle, 실패 시 None을 반환한다."""
        if not _check_required_fields(article):
            logger.debug("필수 필드 누락: %s", article.url)
            return None

        if len(article.content) < _MIN_CONTENT_LENGTH:
            logger.debug("본문 길이 부족: %s (%d자)", article.url, len(article.content))
            return None

        if not _is_within_age_limit(article.published_at):
            logger.debug("24시간 초과 기사: %s", article.url)
            return None

        content_hash = _compute_content_hash(article.title, article.url)
        quality_score = _calculate_quality_score(article)

        # 발행일이 없으면 현재 시각을 사용한다
        published = article.published_at or datetime.now(tz=timezone.utc)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)

        return VerifiedArticle(
            title=article.title,
            content=article.content,
            url=article.url,
            source=article.source,
            published_at=published,
            language=article.language,
            content_hash=content_hash,
            quality_score=quality_score,
        )
