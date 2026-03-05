"""F6 리스크/안전 -- 공용 Pydantic 모델이다."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ConcentrationResult(BaseModel):
    """집중도 검사 결과이다."""

    exceeded: bool
    ticker: str = ""
    current_pct: float = 0.0
    max_allowed_pct: float = 15.0


class VaRResult(BaseModel):
    """VaR 계산 결과이다."""

    var_99: float
    expected_shortfall: float


class PositionSizeResult(BaseModel):
    """포지션 사이징 결과이다."""

    kelly_pct: float
    adjusted_pct: float
    max_position: float


class StopLossResult(BaseModel):
    """손절가 계산 결과이다."""

    stop_price: float
    trailing_pct: float
    break_even_active: bool


class FrictionResult(BaseModel):
    """마찰 비용 결과이다."""

    spread_cost: float
    slippage_cost: float
    total_friction: float
    min_gain_hurdle: float


class MultiplierResult(BaseModel):
    """하우스 머니 배수 결과이다."""

    multiplier: float
    pnl_band: str


class AccountSafetyResult(BaseModel):
    """계좌 안전 결과이다."""

    should_stop: bool
    reason: str = ""


class QuotaResult(BaseModel):
    """API 쿼터 결과이다."""

    allowed: bool
    remaining: int
    reset_at: datetime | None = None


class LiquidityBias(BaseModel):
    """유동성 바이어스이다."""

    net_liquidity_bn: float
    bias: str  # INJECT/DRAIN/NEUTRAL
    multiplier: float


class StreakResult(BaseModel):
    """연패 추적 결과이다."""

    consecutive_losses: int
    max_streak: int
    risk_level: str  # low/medium/high/critical
