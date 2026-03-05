"""FF 피드백 -- 공용 모델이다."""

from __future__ import annotations

from pydantic import BaseModel


class DailyFeedbackResult(BaseModel):
    """일일 피드백 분석 결과이다."""

    summary: dict
    lessons: list[str]
    improvements: list[str]


class WeeklyReport(BaseModel):
    """주간 성과 분석 보고서이다."""

    win_rate: float
    total_pnl: float
    best_trade: dict
    worst_trade: dict
    patterns: list[str]


class UpdateResult(BaseModel):
    """RAG 문서 업데이트 결과이다."""

    documents_added: int
    embeddings_created: int


class AdjustmentResult(BaseModel):
    """파라미터 조정 결과이다."""

    adjusted_keys: list[str]
    before_after: dict[str, dict]


class TimePerformanceResult(BaseModel):
    """시간대별 성과 분석 결과이다."""

    hourly_pnl: dict[int, float]
    best_hours: list[int]
    worst_hours: list[int]


class DailyReport(BaseModel):
    """일일 Markdown 보고서이다."""

    markdown_text: str
    summary_dict: dict
    report_path: str
