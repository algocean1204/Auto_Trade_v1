"""ProfitTarget 스키마 -- 월간 수익 목표 API 요청/응답 모델을 정의한다.

Flutter 프론트엔드(profit_target_models.dart)가 기대하는 JSON 키 이름에 맞춰
응답 모델 필드를 정의한다. 요청 모델도 포함한다.
"""
from __future__ import annotations

from pydantic import BaseModel


class TimeProgressModel(BaseModel):
    """월 시간 진행 정보 (ProfitTargetStatus.time_progress)이다."""

    year: int
    month: int
    total_days: int
    elapsed_days: int
    remaining_days: int
    remaining_trading_days: int
    time_ratio: float


class ProfitTargetCurrentResponse(BaseModel):
    """현재 수익 목표 달성 현황 응답이다.

    Flutter ProfitTargetStatus.fromJson()이 기대하는 필드 이름과 일치한다.
    """

    monthly_target_usd: float
    """이번 달 목표 금액(USD)이다."""
    month_pnl_usd: float
    """현재까지 달성한 월간 누적 PnL(USD)이다."""
    achievement_pct: float
    """목표 대비 달성률(0~100+%)이다."""
    remaining_daily_target_usd: float
    """목표 달성을 위한 남은 일일 필요 수익(USD)이다."""
    time_progress: TimeProgressModel
    """월 시간 진행 정보이다."""
    aggression_level: str
    """현재 공격성 레벨이다 (conservative / moderate / aggressive / max)."""
    auto_adjust: bool
    """자동 조정 활성화 여부이다."""


class ProfitTargetAggressionRequest(BaseModel):
    """공격성 레벨 업데이트 요청이다."""

    aggression_level: str
    """새로운 공격성 레벨이다."""


class ProfitTargetAggressionResponse(BaseModel):
    """공격성 레벨 업데이트 응답이다."""

    aggression_level: str
    """업데이트된 공격성 레벨이다."""
    monthly_target: float
    """공격성 레벨에 따라 조정된 월간 목표(USD)이다."""
    updated: bool
    """업데이트 성공 여부이다."""


class ProfitTargetMonthlyResponse(BaseModel):
    """이번 달 목표 현황 응답이다."""

    month: str
    """연월(YYYY-MM)이다."""
    target: float
    """목표 금액(USD)이다."""
    actual: float
    """실현 금액(USD)이다."""
    progress_pct: float
    """달성률(%)이다."""
    status: str
    """달성 상태이다 (on_track / behind / achieved / failed)."""


class ProfitTargetHistoryEntry(BaseModel):
    """월간 수익 목표 이력 항목이다.

    Flutter MonthlyHistory.fromJson()이 기대하는 필드:
    year(int), month(int), target_usd, actual_pnl_usd, achievement_pct
    """

    year: int
    """연도이다."""
    month: int
    """월(1~12)이다."""
    target_usd: float
    """목표 금액(USD)이다."""
    actual_pnl_usd: float
    """실현 PnL(USD)이다."""
    achievement_pct: float
    """달성률(%)이다."""


class ProfitTargetHistoryResponse(BaseModel):
    """월간 수익 목표 이력 응답이다."""

    entries: list[ProfitTargetHistoryEntry]
    """월별 목표 이력 목록이다."""


class ProfitTargetProjectionResponse(BaseModel):
    """수익 추정 응답이다.

    Flutter ProfitTargetProjection.fromJson()이 기대하는 필드:
    current_pnl_usd, daily_avg_usd, projected_month_end_usd,
    monthly_target_usd, on_track, projected_deficit_usd,
    remaining_daily_target_usd
    """

    current_pnl_usd: float
    """현재 월간 누적 PnL(USD)이다."""
    daily_avg_usd: float
    """일평균 수익(USD)이다."""
    projected_month_end_usd: float
    """월말 예상 누적 PnL(USD)이다."""
    monthly_target_usd: float
    """월간 목표 금액(USD)이다."""
    on_track: bool
    """목표 달성 궤도 여부이다."""
    projected_deficit_usd: float
    """예상 미달 금액(USD)이다. 목표 초과 시 음수이다."""
    remaining_daily_target_usd: float
    """남은 거래일 기준 일일 필요 수익(USD)이다."""


class MonthlyTargetUpdateRequest(BaseModel):
    """월간 목표 금액 수정 요청이다."""

    monthly_target_usd: float
    """새 월간 목표 금액(USD)이다."""


class MonthlyTargetUpdateResponse(BaseModel):
    """월간 목표 금액 수정 응답이다."""

    monthly_target: float
    updated: bool
