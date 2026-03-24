"""F1 데이터 수집 -- 공용 Pydantic 모델이다."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    """크롤러 소스 설정이다."""

    name: str
    url: str
    source_type: str  # rss, api, scraping, social, prediction
    priority: int = 5  # 1(최고)~10(최저)
    timeout: int = 10
    enabled: bool = True


class RawArticle(BaseModel):
    """크롤러에서 수집된 원시 기사이다."""

    title: str
    content: str
    url: str
    source: str
    published_at: datetime | None = None
    language: str = "en"
    metadata: dict = Field(default_factory=dict)


class VerifiedArticle(BaseModel):
    """검증 통과한 기사이다."""

    title: str
    content: str
    url: str
    source: str
    published_at: datetime
    language: str
    content_hash: str
    quality_score: float


class CrawlSchedule(BaseModel):
    """크롤링 스케줄이다."""

    session_type: str
    active_sources: list[SourceConfig]
    intervals: dict[str, int]
    is_fast_mode: bool = False


class DeduplicationResult(BaseModel):
    """중복 검사 결과이다."""

    is_new: bool
    content_hash: str
    existing_url: str | None = None


class PersistResult(BaseModel):
    """기사 저장 결과이다."""

    article_id: str
    is_new: bool


class CrawlResult(BaseModel):
    """크롤링 전체 결과이다."""

    total: int
    new_count: int
    failed_sources: list[str]
    duration_seconds: float


class AiContext(BaseModel):
    """AI 분석용 컨텍스트이다."""

    context_text: str
    article_count: int
    truncated: bool
