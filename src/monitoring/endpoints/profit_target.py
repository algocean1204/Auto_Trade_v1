"""ProfitTargetEndpoints -- 월간 수익 목표 조회/설정 API이다.

월간 목표 달성 현황, 공격성 레벨 업데이트, 월별 이력, 수익 추정치를 제공한다.
ProfitTarget 피처가 있으면 실시간 상태를, 없으면 Redis 캐시 또는 기본값을 반환한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

profit_target_router = APIRouter(prefix="/api/target", tags=["profit_target"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None

# 월간 기본 목표 금액 (USD) -- strategy_params.json 우선 사용
_DEFAULT_MONTHLY_TARGET: float = 300.0

# 공격성 레벨 선택지이다 (낮을수록 보수적)
_VALID_AGGRESSION_LEVELS: list[str] = ["conservative", "moderate", "aggressive", "max"]


def set_profit_target_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("ProfitTargetEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 응답 모델 정의
# ---------------------------------------------------------------------------

class ProfitTargetCurrentResponse(BaseModel):
    """현재 수익 목표 달성 현황 응답이다."""

    monthly_target: float
    """이번 달 목표 금액(USD)이다."""
    current_pnl: float
    """현재까지 달성한 손익(USD)이다."""
    progress_pct: float
    """목표 대비 달성률(0~100+%)이다."""
    days_remaining: int
    """이번 달 남은 영업일 수이다."""
    daily_target_remaining: float
    """목표 달성을 위한 남은 일일 필요 수익(USD)이다."""
    aggression_level: str
    """현재 공격성 레벨이다 (conservative / moderate / aggressive / max)."""


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
    """월간 수익 목표 이력 항목이다."""

    month: str
    """연월(YYYY-MM)이다."""
    target: float
    """목표 금액(USD)이다."""
    actual: float
    """실현 금액(USD)이다."""
    achieved: bool
    """목표 달성 여부이다."""


class ProfitTargetHistoryResponse(BaseModel):
    """월간 수익 목표 이력 응답이다."""

    entries: list[ProfitTargetHistoryEntry]
    """월별 목표 이력 목록이다."""


class ProfitTargetProjectionResponse(BaseModel):
    """수익 추정 응답이다."""

    projected_monthly: float
    """이번 달 예상 총 수익(USD)이다."""
    projected_annual: float
    """연간 예상 수익(USD)이다."""
    confidence: float
    """추정 신뢰도(0.0~1.0)이다."""
    based_on_days: int
    """추정 기준 경과 일수이다."""


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def _get_aggression_multiplier(level: str) -> float:
    """공격성 레벨에 따른 목표 배수를 반환한다.

    conservative=0.7x, moderate=1.0x, aggressive=1.5x, max=2.0x이다.
    """
    multipliers: dict[str, float] = {
        "conservative": 0.7,
        "moderate": 1.0,
        "aggressive": 1.5,
        "max": 2.0,
    }
    return multipliers.get(level, 1.0)


def _determine_status(
    current_pnl: float,
    target: float,
    days_remaining: int,
) -> str:
    """현재 손익과 목표를 기반으로 달성 상태를 반환한다."""
    if current_pnl >= target:
        return "achieved"
    if days_remaining <= 0:
        return "failed"
    now = datetime.now(tz=timezone.utc)
    elapsed_ratio = (now.day - 1) / 30.0
    if elapsed_ratio <= 0:
        return "on_track"
    actual_ratio = current_pnl / target if target > 0 else 0.0
    return "on_track" if actual_ratio >= elapsed_ratio * 0.8 else "behind"


# ---------------------------------------------------------------------------
# 엔드포인트 구현
# ---------------------------------------------------------------------------

@profit_target_router.get("/current", response_model=ProfitTargetCurrentResponse)
async def get_current_target() -> ProfitTargetCurrentResponse:
    """현재 월간 수익 목표 달성 현황을 반환한다.

    ProfitTarget 피처가 있으면 evaluate()를 호출한다.
    없으면 Redis 캐시 또는 기본값을 반환한다.
    """
    if _system is None:
        return ProfitTargetCurrentResponse(
            monthly_target=_DEFAULT_MONTHLY_TARGET,
            current_pnl=0.0,
            progress_pct=0.0,
            days_remaining=22,
            daily_target_remaining=_DEFAULT_MONTHLY_TARGET / 22,
            aggression_level="moderate",
        )
    try:
        # ProfitTarget 피처에서 실시간 상태를 읽는다
        profit_target = _system.features.get("profit_target")
        cache = _system.components.cache

        # 현재 월간 PnL은 캐시에서 읽는다
        monthly_pnl_data = await cache.read_json("performance:monthly_pnl")
        current_pnl = 0.0
        if monthly_pnl_data and isinstance(monthly_pnl_data, dict):
            current_pnl = float(monthly_pnl_data.get("pnl", 0.0))

        # 공격성 레벨 및 목표 금액을 캐시에서 읽는다
        target_meta = await cache.read_json("profit_target:meta")
        aggression = "moderate"
        monthly_target = _DEFAULT_MONTHLY_TARGET

        if target_meta and isinstance(target_meta, dict):
            aggression = str(target_meta.get("aggression_level", "moderate"))
            monthly_target = float(
                target_meta.get("monthly_target", _DEFAULT_MONTHLY_TARGET)
            )

        if profit_target is not None:
            status = profit_target.evaluate({"pnl": current_pnl})
            progress = (current_pnl / monthly_target * 100) if monthly_target > 0 else 0.0
            return ProfitTargetCurrentResponse(
                monthly_target=monthly_target,
                current_pnl=float(status.current_pnl),
                progress_pct=round(progress, 2),
                days_remaining=int(status.days_remaining),
                daily_target_remaining=float(status.daily_target),
                aggression_level=aggression,
            )

        # ProfitTarget 없으면 캐시 또는 기본값 반환
        progress = (current_pnl / monthly_target * 100) if monthly_target > 0 else 0.0
        now = datetime.now(tz=timezone.utc)
        days_remaining = max(1, int((30 - now.day) * 0.7))
        gap = max(0.0, monthly_target - current_pnl)
        daily_remaining = round(gap / days_remaining, 2) if days_remaining > 0 else 0.0

        return ProfitTargetCurrentResponse(
            monthly_target=monthly_target,
            current_pnl=current_pnl,
            progress_pct=round(progress, 2),
            days_remaining=days_remaining,
            daily_target_remaining=daily_remaining,
            aggression_level=aggression,
        )
    except Exception:
        _logger.exception("현재 수익 목표 조회 실패")
        raise HTTPException(status_code=500, detail="수익 목표 조회 중 오류가 발생했다") from None


@profit_target_router.put("/aggression", response_model=ProfitTargetAggressionResponse)
async def update_aggression(
    req: ProfitTargetAggressionRequest,
    _key: str = Depends(verify_api_key),
) -> ProfitTargetAggressionResponse:
    """공격성 레벨을 업데이트한다. 인증 필수.

    공격성 레벨에 따라 월간 목표 금액이 자동 조정된다.
    유효한 레벨: conservative, moderate, aggressive, max.
    """
    if req.aggression_level not in _VALID_AGGRESSION_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"유효하지 않은 공격성 레벨이다. 선택 가능: {_VALID_AGGRESSION_LEVELS}",
        )
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중이다")
    try:
        multiplier = _get_aggression_multiplier(req.aggression_level)
        new_target = round(_DEFAULT_MONTHLY_TARGET * multiplier, 2)

        # 메타 정보를 캐시에 저장하여 이후 조회에서 사용한다
        cache = _system.components.cache
        await cache.write_json(
            "profit_target:meta",
            {
                "aggression_level": req.aggression_level,
                "monthly_target": new_target,
            },
        )

        _logger.info(
            "공격성 레벨 업데이트: %s → 월간 목표 $%.2f",
            req.aggression_level, new_target,
        )
        return ProfitTargetAggressionResponse(
            aggression_level=req.aggression_level,
            monthly_target=new_target,
            updated=True,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("공격성 레벨 업데이트 실패")
        raise HTTPException(status_code=500, detail="공격성 레벨 업데이트 중 오류가 발생했다") from None


class MonthlyTargetUpdateRequest(BaseModel):
    """월간 목표 금액 수정 요청이다."""

    monthly_target_usd: float
    """새 월간 목표 금액(USD)이다."""


class MonthlyTargetUpdateResponse(BaseModel):
    """월간 목표 금액 수정 응답이다."""

    monthly_target: float
    updated: bool


@profit_target_router.put("/monthly", response_model=MonthlyTargetUpdateResponse)
async def update_monthly_target(
    req: MonthlyTargetUpdateRequest,
    _key: str = Depends(verify_api_key),
) -> MonthlyTargetUpdateResponse:
    """월간 목표 금액을 직접 설정한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중이다")
    if req.monthly_target_usd <= 0:
        raise HTTPException(status_code=422, detail="목표 금액은 0보다 커야 한다")
    try:
        cache = _system.components.cache
        # 기존 메타에서 aggression만 유지하고 target을 갱신한다
        target_meta = await cache.read_json("profit_target:meta")
        aggression = "moderate"
        if target_meta and isinstance(target_meta, dict):
            aggression = str(target_meta.get("aggression_level", "moderate"))
        await cache.write_json(
            "profit_target:meta",
            {
                "aggression_level": aggression,
                "monthly_target": req.monthly_target_usd,
            },
        )
        _logger.info("월간 목표 직접 설정: $%.2f", req.monthly_target_usd)
        return MonthlyTargetUpdateResponse(
            monthly_target=req.monthly_target_usd, updated=True,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("월간 목표 설정 실패")
        raise HTTPException(status_code=500, detail="월간 목표 설정 중 오류가 발생했다") from None


@profit_target_router.get("/monthly", response_model=ProfitTargetMonthlyResponse)
async def get_monthly_target() -> ProfitTargetMonthlyResponse:
    """이번 달 목표 달성 현황을 반환한다."""
    if _system is None:
        now = datetime.now(tz=timezone.utc)
        return ProfitTargetMonthlyResponse(
            month=now.strftime("%Y-%m"),
            target=_DEFAULT_MONTHLY_TARGET,
            actual=0.0,
            progress_pct=0.0,
            status="on_track",
        )
    try:
        cache = _system.components.cache
        now = datetime.now(tz=timezone.utc)
        month_str = now.strftime("%Y-%m")

        # 이번 달 PnL 캐시를 읽는다
        monthly_pnl_data = await cache.read_json("performance:monthly_pnl")
        actual = 0.0
        if monthly_pnl_data and isinstance(monthly_pnl_data, dict):
            actual = float(monthly_pnl_data.get("pnl", 0.0))

        # 공격성 레벨 및 목표 금액을 캐시에서 읽는다
        target_meta = await cache.read_json("profit_target:meta")
        monthly_target = _DEFAULT_MONTHLY_TARGET
        if target_meta and isinstance(target_meta, dict):
            monthly_target = float(target_meta.get("monthly_target", _DEFAULT_MONTHLY_TARGET))

        progress = (actual / monthly_target * 100) if monthly_target > 0 else 0.0
        days_remaining = max(0, int((30 - now.day) * 0.7))
        status = _determine_status(actual, monthly_target, days_remaining)

        return ProfitTargetMonthlyResponse(
            month=month_str,
            target=monthly_target,
            actual=actual,
            progress_pct=round(progress, 2),
            status=status,
        )
    except Exception:
        _logger.exception("이번 달 목표 현황 조회 실패")
        raise HTTPException(status_code=500, detail="월간 목표 조회 중 오류가 발생했다") from None


@profit_target_router.get("/history", response_model=ProfitTargetHistoryResponse)
async def get_target_history(limit: int = 12) -> ProfitTargetHistoryResponse:
    """월간 수익 목표 이력을 반환한다.

    Redis 캐시 키 profit_target:history에서 데이터를 읽는다.
    캐시 미스 시 빈 목록을 반환한다.

    Args:
        limit: 반환할 최대 월 수이다 (기본 12개월).
    """
    if _system is None:
        return ProfitTargetHistoryResponse(entries=[])
    try:
        cache = _system.components.cache
        cached = await cache.read_json("profit_target:history")
        if cached and isinstance(cached, list):
            entries = [
                ProfitTargetHistoryEntry(
                    month=str(e.get("month", "")),
                    target=float(e.get("target", _DEFAULT_MONTHLY_TARGET)),
                    actual=float(e.get("actual", 0.0)),
                    achieved=bool(e.get("achieved", False)),
                )
                for e in cached[:limit]
            ]
            return ProfitTargetHistoryResponse(entries=entries)
        return ProfitTargetHistoryResponse(entries=[])
    except Exception:
        _logger.exception("월간 목표 이력 조회 실패")
        raise HTTPException(status_code=500, detail="목표 이력 조회 중 오류가 발생했다") from None


@profit_target_router.get("/projection", response_model=ProfitTargetProjectionResponse)
async def get_projection() -> ProfitTargetProjectionResponse:
    """현재 손익 추이 기반 수익 추정치를 반환한다.

    경과 일수 대비 현재 PnL로 월간 및 연간 수익을 추정한다.
    """
    if _system is None:
        return ProfitTargetProjectionResponse(
            projected_monthly=0.0,
            projected_annual=0.0,
            confidence=0.0,
            based_on_days=0,
        )
    try:
        cache = _system.components.cache
        now = datetime.now(tz=timezone.utc)
        days_elapsed = max(1, now.day)

        # 현재 월간 PnL을 읽는다
        monthly_pnl_data = await cache.read_json("performance:monthly_pnl")
        current_pnl = 0.0
        if monthly_pnl_data and isinstance(monthly_pnl_data, dict):
            current_pnl = float(monthly_pnl_data.get("pnl", 0.0))

        # 일평균 수익 기반 월간/연간 추정이다
        daily_avg = current_pnl / days_elapsed
        projected_monthly = round(daily_avg * 22, 2)  # 월 22 거래일 기준
        projected_annual = round(daily_avg * 252, 2)  # 연 252 거래일 기준

        # 경과 일수가 많을수록 신뢰도가 높다 (최대 0.95)
        confidence = min(0.95, days_elapsed / 22.0)

        return ProfitTargetProjectionResponse(
            projected_monthly=projected_monthly,
            projected_annual=projected_annual,
            confidence=round(confidence, 2),
            based_on_days=days_elapsed,
        )
    except Exception:
        _logger.exception("수익 추정치 계산 실패")
        raise HTTPException(status_code=500, detail="수익 추정 중 오류가 발생했다") from None
