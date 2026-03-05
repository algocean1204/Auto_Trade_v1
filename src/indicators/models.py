"""F3 지표 -- 공용 Pydantic 모델이다."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TechnicalIndicators(BaseModel):
    """기술적 지표 종합 결과이다."""

    rsi: float
    macd: float
    macd_signal: float
    macd_histogram: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    atr: float
    ema_20: float
    ema_50: float
    sma_200: float


class Candle5m(BaseModel):
    """5분봉 캔들이다."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class IntradayIndicators(BaseModel):
    """장중 지표이다."""

    vwap: float
    intraday_rsi: float
    bb_upper: float
    bb_middle: float
    bb_lower: float


class MomentumScore(BaseModel):
    """크로스 에셋 모멘텀 점수이다."""

    alignment: float
    divergence: float
    leader_scores: dict[str, float]
    has_bullish_divergence: bool
    has_bearish_divergence: bool


class VolumeProfileResult(BaseModel):
    """볼륨 프로파일 결과이다."""

    poc_price: float
    value_area_high: float
    value_area_low: float
    is_above_poc: bool
    support_level: float | None = None
    resistance_level: float | None = None
    signals: list[str] = []


class WhaleSignal(BaseModel):
    """고래 활동 결과이다."""

    block_score: float
    iceberg_score: float
    direction: str
    total_score: float
    block_count: int
    iceberg_count: int


class DivergenceSignal(BaseModel):
    """다이버전스 신호이다."""

    type: str  # bullish / bearish / none
    strength: float
    confidence: float


class ContangoState(BaseModel):
    """콘탱고 상태이다."""

    contango_ratio: float
    drag_estimate: float
    signal: str  # contango / backwardation / neutral


class NAVPremiumState(BaseModel):
    """NAV 프리미엄 상태이다."""

    premium_pct: float
    multiplier_adjustment: float


class OrderFlowSnapshot(BaseModel):
    """주문 흐름 스냅샷이다."""

    obi: float
    cvd: float
    vpin: float
    execution_strength: float


class DecayScore(BaseModel):
    """레버리지 디케이 점수이다."""

    decay_pct: float
    force_exit: bool


class HistoryPattern(BaseModel):
    """과거 패턴 분석이다."""

    patterns: list[str]
    support_levels: list[float]
    resistance_levels: list[float]


class AggregatedScore(BaseModel):
    """종합 점수이다."""

    total_score: float
    components: dict[str, float]


class IndicatorBundle(BaseModel):
    """지표 묶음 (F4 Strategy에서 사용)이다."""

    technical: TechnicalIndicators | None = None
    intraday: IntradayIndicators | None = None
    momentum: MomentumScore | None = None
    volume_profile: VolumeProfileResult | None = None
    whale: WhaleSignal | None = None
    order_flow: OrderFlowSnapshot | None = None
    contango: ContangoState | None = None
    nav_premium: NAVPremiumState | None = None
    decay: DecayScore | None = None
