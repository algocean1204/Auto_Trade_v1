"""F7.5 AnalysisSchemas -- 분석 API 응답 Pydantic 모델을 정의한다.

analysis 엔드포인트에서 사용하는 모든 요청/응답 모델을 관리한다.
엔드포인트 로직과 스키마 정의를 분리하여 SRP를 준수한다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TickerItem(BaseModel):
    """티커 항목 모델이다."""

    ticker: str
    name: str
    sector: str


class AnalysisTickersResponse(BaseModel):
    """분석 가능 티커 목록 응답 모델이다."""

    tickers: list[TickerItem] = Field(default_factory=list)
    count: int = 0


class ComprehensiveAnalysisResponse(BaseModel):
    """종합 분석 응답 모델이다."""

    ticker: str
    analysis: dict[str, Any] | None = None
    source: str = ""
    message: str = ""


class TickerNewsResponse(BaseModel):
    """티커별 뉴스 응답 모델이다."""

    ticker: str
    articles: list[dict[str, Any]] = Field(default_factory=list)
