"""FS 스캘핑 -- 공용 모델이다."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScalpingDecision(BaseModel):
    """스캘핑 진입 가능 여부 판단 결과이다."""

    safe_to_trade: bool
    adjusted_size: float
    warnings: list[str] = Field(default_factory=list)


class DepthAnalysis(BaseModel):
    """호가창 깊이 분석 결과이다."""

    depth_score: float
    imbalance: float
    support_levels: list[float] = Field(default_factory=list)


class ImpactEstimate(BaseModel):
    """시장 충격 추정 결과이다."""

    expected_slippage_pct: float
    impact_cost: float


class SpreadState(BaseModel):
    """실시간 스프레드 상태이다."""

    current_spread: float
    avg_spread: float
    spread_z_score: float


class OptimalSize(BaseModel):
    """최적 주문 사이즈 결과이다."""

    max_shares: int
    recommended_shares: int


class SpoofingSignal(BaseModel):
    """스푸핑 탐지 결과이다."""

    detected: bool
    pattern_type: str = ""
    confidence: float = 0.0


class TimeStopResult(BaseModel):
    """시간 기반 청산 판단 결과이다."""

    should_exit: bool
    elapsed_seconds: int
    reason: str = ""
