"""F7.12 IndicatorSchemas -- 기술 지표 API의 요청/응답 Pydantic 모델을 정의한다.

indicators 엔드포인트에서 사용하는 모든 요청/응답 모델을 관리한다.
엔드포인트 로직과 스키마 정의를 분리하여 SRP를 준수한다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── 요청 모델 ──────────────────────────────────────────────────────────────


class WeightUpdateRequest(BaseModel):
    """가중치 업데이트 요청 모델이다."""

    weights: dict[str, float]


class IndicatorConfigUpdateRequest(BaseModel):
    """지표 설정 업데이트 요청 모델이다."""

    config: dict[str, Any]


# ── 응답 모델 ──────────────────────────────────────────────────────────────


class IndicatorWeightsResponse(BaseModel):
    """지표 가중치 조회 응답 모델이다."""

    weights: dict[str, float]


class IndicatorWeightUpdateResponse(BaseModel):
    """지표 가중치 업데이트 응답 모델이다."""

    status: str
    weights: dict[str, float]


class RsiDataResponse(BaseModel):
    """RSI 데이터 조회 응답 모델이다."""

    rsi_data: dict[str, Any]
    message: str | None


class IndicatorConfigResponse(BaseModel):
    """지표 설정 응답 모델이다."""

    updated: bool
    config: dict[str, Any]


class MacdData(BaseModel):
    """MACD 구성 요소 모델이다."""

    macd: float | None = None
    signal: float | None = None
    histogram: float | None = None


class BollingerData(BaseModel):
    """볼린저 밴드 구성 요소 모델이다."""

    upper: float | None = None
    middle: float | None = None
    lower: float | None = None


class RsiIndicatorItem(BaseModel):
    """개별 RSI 기간 데이터 모델이다. 프론트엔드 RsiIndicator와 일치한다."""

    rsi: float = 50.0
    signal: float = 50.0
    histogram: float = 0.0
    rsi_series: list[float] = Field(default_factory=list)
    signal_series: list[float] = Field(default_factory=list)
    overbought: bool = False
    oversold: bool = False


class TripleRsiResponse(BaseModel):
    """트리플 RSI(7, 14, 21) 응답 모델이다. 프론트엔드 TripleRsiData와 일치한다."""

    rsi_7: RsiIndicatorItem = Field(default_factory=RsiIndicatorItem)
    rsi_14: RsiIndicatorItem = Field(default_factory=RsiIndicatorItem)
    rsi_21: RsiIndicatorItem = Field(default_factory=RsiIndicatorItem)
    consensus: str = "neutral"
    divergence: bool = False
    dates: list[str] = Field(default_factory=list)
    ticker: str = ""
    analysis_ticker: str = ""


class RealtimeIndicatorResponse(BaseModel):
    """실시간 기술 지표 응답 모델이다."""

    ticker: str
    rsi: float | None
    macd: MacdData | None
    bollinger: BollingerData | None
    atr: float | None
    volume: float | None
    timestamp: str
