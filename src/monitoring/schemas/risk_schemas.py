"""리스크 엔드포인트 응답 스키마를 정의한다.

리스크 대시보드 API가 반환하는 모든 Pydantic 모델을 포함한다.
GateEntry, RiskBudgetData, VarData, StreakData, ConcentrationData,
TrailingStopData, RiskDashboardResponse 등을 제공한다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class GateEntry(BaseModel):
    """리스크 게이트 개별 항목이다. 각 게이트의 통과/차단 상태를 표현한다."""

    gate_name: str
    passed: bool
    action: str = "allow"
    message: str = ""
    details: dict[str, Any] = {}


class RiskBudgetData(BaseModel):
    """리스크 예산 현황이다. 일일/주간 손실 예산 소비율을 반환한다."""

    budget_pct: float = 10.0
    consumption_pct: float = 0.0
    budget_amount_usd: float = 0.0
    total_losses_usd: float = 0.0
    remaining_budget_usd: float = 0.0
    current_tier: int = 1
    position_scale: float = 1.0
    daily_limit_pct: float = 0.0
    daily_used_pct: float = 0.0


class VarData(BaseModel):
    """VaR(Value at Risk) 지표 데이터이다."""

    var_pct: float = 0.0
    confidence: float = 0.95
    risk_level: str = "low"
    max_var_pct: float = 5.0
    lookback_days: int = 20
    z_score: float = 1.645


class StreakData(BaseModel):
    """연승/연패 카운터 데이터이다."""

    current_streak: int = 0
    daily_loss_days: int = 0
    daily_loss_streak_threshold: int = 3
    streak_rules: dict[str, Any] = {}
    max_win_streak: int = 0
    max_loss_streak: int = 0


class PositionConcentrationEntry(BaseModel):
    """개별 종목 집중도 항목이다."""

    ticker: str
    market_value: float = 0.0
    weight_pct: float = 0.0


class ConcentrationData(BaseModel):
    """포지션 집중도 현황이다. 종목별 비중 목록을 반환한다."""

    limits: dict[str, Any] = {}
    positions: list[PositionConcentrationEntry] = []


class TrailingStopData(BaseModel):
    """트레일링 스톱 현황이다."""

    active: bool = False
    initial_stop_pct: float = 3.0
    trailing_stop_pct: float = 5.0
    tracked_positions: int = 0
    positions: dict[str, Any] = {}


class RiskDashboardResponse(BaseModel):
    """리스크 대시보드 종합 응답이다.

    기존 플랫 필드(하위 호환) + 중첩 구조(Flutter 대시보드용)를 모두 포함한다.
    """

    # -- 기존 플랫 필드 (하위 호환성 유지) --
    portfolio_var: float
    """포트폴리오 Value at Risk (95%, USD 추정)이다."""
    max_drawdown_pct: float
    """최대 낙폭(%)이다. 음수 값으로 표현한다."""
    current_drawdown_pct: float
    """현재 낙폭(%)이다. 피크 대비 현재 손실률이다."""
    position_concentration: float
    """가장 큰 단일 포지션 비중(%)이다."""
    regime: str
    """현재 시장 레짐이다 (strong_bull / mild_bull / sideways / mild_bear / crash)."""
    vix_current: float
    """현재 VIX 지수이다."""
    risk_score: float
    """종합 리스크 스코어이다 (0.0~10.0, 높을수록 위험)."""
    warnings: list[str]
    """활성화된 리스크 경고 목록이다."""

    # -- 중첩 구조 필드 (Flutter 대시보드용) --
    updated_at: str = ""
    """데이터 갱신 시각 (ISO 8601)이다."""
    gates: list[GateEntry] = []
    """리스크 게이트 통과/차단 상태 목록이다."""
    risk_budget: RiskBudgetData | None = None
    """리스크 예산 현황이다."""
    var_indicator: VarData | None = None
    """VaR 지표 데이터이다."""
    streak_counter: StreakData | None = None
    """연승/연패 카운터이다."""
    concentrations: ConcentrationData | None = None
    """포지션 집중도 현황이다."""
    trailing_stop: TrailingStopData | None = None
    """트레일링 스톱 현황이다."""
