"""ProfitTargetEndpoints -- 월간 수익 목표 조회/설정 API이다.

월간 목표 달성 현황, 공격성 레벨 업데이트, 월별 이력, 수익 추정치를 제공한다.
ProfitTarget 피처가 있으면 실시간 상태를, 없으면 캐시 또는 기본값을 반환한다.

요청/응답 Pydantic 모델은 profit_target_schemas.py에 정의되어 있다.
"""
from __future__ import annotations

import asyncio
import calendar
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from src.common.logger import get_logger
from src.monitoring.schemas.profit_target_schemas import (
    MonthlyTargetUpdateRequest,
    MonthlyTargetUpdateResponse,
    ProfitTargetAggressionRequest,
    ProfitTargetAggressionResponse,
    ProfitTargetCurrentResponse,
    ProfitTargetHistoryEntry,
    ProfitTargetHistoryResponse,
    ProfitTargetMonthlyResponse,
    ProfitTargetProjectionResponse,
    TimeProgressModel,
)
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

profit_target_router = APIRouter(prefix="/api/target", tags=["profit_target"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None

# 월간 기본 목표 금액 (USD) -- strategy_params.json 우선 사용
_DEFAULT_MONTHLY_TARGET: float = 300.0

# EOD 시퀀스와 동일한 KST 기준으로 월 키를 산출한다
_KST = ZoneInfo("Asia/Seoul")

# 공격성 레벨 선택지이다 (낮을수록 보수적)
_VALID_AGGRESSION_LEVELS: list[str] = ["conservative", "moderate", "aggressive", "max"]

# profit_target:meta의 비원자적 read→modify→write 레이스를 방지한다
_target_meta_lock = asyncio.Lock()


def set_profit_target_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("ProfitTargetEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 공통 헬퍼: 시간 진행 정보 생성
# ---------------------------------------------------------------------------

def _build_time_progress() -> dict:
    """현재 월의 시간 진행 정보 dict를 생성한다.

    Flutter TimeProgress.fromJson()이 기대하는 키:
    year, month, total_days, elapsed_days, remaining_days,
    remaining_trading_days, time_ratio
    """
    # EOD 시퀀스와 동일하게 KST 기준으로 월/일을 산출한다
    now = datetime.now(tz=_KST)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    elapsed = now.day
    remaining = max(0, days_in_month - elapsed)
    # 거래일 비율 약 70%로 추정한다
    remaining_trading = max(1, int(remaining * 0.7))
    time_ratio = round(elapsed / days_in_month, 4) if days_in_month > 0 else 0.0

    return {
        "year": now.year,
        "month": now.month,
        "total_days": days_in_month,
        "elapsed_days": elapsed,
        "remaining_days": remaining,
        "remaining_trading_days": remaining_trading,
        "time_ratio": time_ratio,
    }


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
    # EOD 시퀀스와 동일하게 KST 기준으로 경과일을 산출한다
    now = datetime.now(tz=_KST)
    elapsed_ratio = (now.day - 1) / 30.0
    if elapsed_ratio <= 0:
        return "on_track"
    actual_ratio = current_pnl / target if target > 0 else 0.0
    return "on_track" if actual_ratio >= elapsed_ratio * 0.8 else "behind"


def _parse_year_month(month_str: str) -> tuple[int, int]:
    """'YYYY-MM' 형식의 문자열을 (year, month) 정수 튜플로 파싱한다.

    파싱 실패 시 현재 연도/월을 반환한다.
    """
    try:
        parts = month_str.split("-")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        # EOD가 KST 기준으로 월 키를 기록하므로 폴백도 KST를 사용한다
        now = datetime.now(tz=_KST)
        return now.year, now.month


async def _read_monthly_pnl() -> float:
    """현재 월간 PnL을 읽는다.

    1차: performance:monthly_pnl 캐시에서 읽는다.
    2차: 캐시 미스 시 trades:today에서 실현 PnL(sell 거래)을 합산한다.
    시스템 없으면 0.0 반환한다.
    """
    if _system is None:
        return 0.0
    cache = _system.components.cache

    # 1차: 전용 캐시 키
    monthly_pnl_data = await cache.read_json("performance:monthly_pnl")
    if monthly_pnl_data and isinstance(monthly_pnl_data, dict):
        return float(monthly_pnl_data.get("pnl", 0.0))

    # 2차: trades:today에서 실현 PnL 합산 (폴백)
    try:
        today_trades = await cache.read_json("trades:today")
        if today_trades and isinstance(today_trades, list):
            total_pnl = 0.0
            for t in today_trades:
                if isinstance(t, dict) and t.get("side") == "sell":
                    pnl = t.get("pnl")
                    if pnl is not None and isinstance(pnl, (int, float)):
                        total_pnl += pnl
            return total_pnl
    except Exception as exc:
        _logger.debug("당일 거래 PnL 합산 실패 (무시): %s", exc)

    return 0.0


async def _read_target_meta() -> tuple[str, float]:
    """캐시에서 공격성 레벨과 월간 목표를 읽는다.

    Returns:
        (aggression_level, monthly_target) 튜플이다.
    """
    if _system is None:
        return "moderate", _DEFAULT_MONTHLY_TARGET
    cache = _system.components.cache
    target_meta = await cache.read_json("profit_target:meta")
    aggression = "moderate"
    monthly_target = _DEFAULT_MONTHLY_TARGET
    if target_meta and isinstance(target_meta, dict):
        aggression = str(target_meta.get("aggression_level", "moderate"))
        monthly_target = float(
            target_meta.get("monthly_target", _DEFAULT_MONTHLY_TARGET)
        )
    return aggression, monthly_target


# ---------------------------------------------------------------------------
# 엔드포인트 구현
# ---------------------------------------------------------------------------

@profit_target_router.get("/current", response_model=ProfitTargetCurrentResponse)
async def get_current_target(_auth: str = Depends(verify_api_key)) -> ProfitTargetCurrentResponse:
    """현재 월간 수익 목표 달성 현황을 반환한다.

    Flutter ProfitTargetStatus.fromJson() 키에 맞춘 응답을 생성한다.
    ProfitTarget 피처가 있으면 evaluate()를 호출하고,
    없으면 캐시 또는 기본값을 반환한다.
    """
    tp = _build_time_progress()
    time_progress = TimeProgressModel(**tp)

    if _system is None:
        remaining_trading = tp["remaining_trading_days"]
        daily_rem = round(_DEFAULT_MONTHLY_TARGET / max(1, remaining_trading), 2)
        return ProfitTargetCurrentResponse(
            monthly_target_usd=_DEFAULT_MONTHLY_TARGET,
            month_pnl_usd=0.0,
            achievement_pct=0.0,
            remaining_daily_target_usd=daily_rem,
            time_progress=time_progress,
            aggression_level="moderate",
            auto_adjust=True,
        )
    try:
        current_pnl = await _read_monthly_pnl()
        aggression, monthly_target = await _read_target_meta()

        # ProfitTarget 피처에서 실시간 상태를 읽는다
        profit_target = _system.features.get("profit_target")

        if profit_target is not None:
            status = profit_target.evaluate({"pnl": current_pnl})
            pnl_val = float(status.current_pnl)
            achievement = (pnl_val / monthly_target * 100) if monthly_target > 0 else 0.0
            return ProfitTargetCurrentResponse(
                monthly_target_usd=monthly_target,
                month_pnl_usd=pnl_val,
                achievement_pct=round(achievement, 2),
                remaining_daily_target_usd=float(status.daily_target),
                time_progress=time_progress,
                aggression_level=aggression,
                auto_adjust=True,
            )

        # ProfitTarget 피처 없으면 캐시/기본값으로 계산한다
        achievement = (current_pnl / monthly_target * 100) if monthly_target > 0 else 0.0
        remaining_trading = tp["remaining_trading_days"]
        gap = max(0.0, monthly_target - current_pnl)
        daily_remaining = round(gap / max(1, remaining_trading), 2)

        return ProfitTargetCurrentResponse(
            monthly_target_usd=monthly_target,
            month_pnl_usd=current_pnl,
            achievement_pct=round(achievement, 2),
            remaining_daily_target_usd=daily_remaining,
            time_progress=time_progress,
            aggression_level=aggression,
            auto_adjust=True,
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
        # Lock으로 read→modify→write 레이스를 방지한다
        async with _target_meta_lock:
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
async def get_monthly_target(_auth: str = Depends(verify_api_key)) -> ProfitTargetMonthlyResponse:
    """이번 달 목표 달성 현황을 반환한다."""
    if _system is None:
        # EOD 시퀀스와 동일하게 KST 기준으로 월을 산출한다
        now = datetime.now(tz=_KST)
        return ProfitTargetMonthlyResponse(
            month=now.strftime("%Y-%m"),
            target=_DEFAULT_MONTHLY_TARGET,
            actual=0.0,
            progress_pct=0.0,
            status="on_track",
        )
    try:
        cache = _system.components.cache
        # EOD 시퀀스와 동일하게 KST 기준으로 월을 산출한다
        now = datetime.now(tz=_KST)
        month_str = now.strftime("%Y-%m")

        # 공용 헬퍼로 이번 달 PnL을 읽는다 (캐시 → trades:today 폴백)
        actual = await _read_monthly_pnl()

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
async def get_target_history(limit: int = Query(default=12, ge=1, le=120), _auth: str = Depends(verify_api_key)) -> ProfitTargetHistoryResponse:
    """월간 수익 목표 이력을 반환한다.

    Flutter MonthlyHistory.fromJson()이 기대하는 필드:
    year(int), month(int), target_usd, actual_pnl_usd, achievement_pct

    캐시 키 profit_target:history에서 데이터를 읽는다.
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
            entries: list[ProfitTargetHistoryEntry] = []
            for e in cached[:limit]:
                # 기존 "YYYY-MM" 문자열을 year/month 정수로 분리한다
                month_str = str(e.get("month", ""))
                year_val, month_val = _parse_year_month(month_str)
                target_val = float(e.get("target", _DEFAULT_MONTHLY_TARGET))
                actual_val = float(e.get("actual", 0.0))
                achievement = round(
                    (actual_val / target_val * 100) if target_val > 0 else 0.0,
                    2,
                )
                entries.append(
                    ProfitTargetHistoryEntry(
                        year=year_val,
                        month=month_val,
                        target_usd=target_val,
                        actual_pnl_usd=actual_val,
                        achievement_pct=achievement,
                    )
                )
            return ProfitTargetHistoryResponse(entries=entries)
        return ProfitTargetHistoryResponse(entries=[])
    except Exception:
        _logger.exception("월간 목표 이력 조회 실패")
        raise HTTPException(status_code=500, detail="목표 이력 조회 중 오류가 발생했다") from None


@profit_target_router.get("/projection", response_model=ProfitTargetProjectionResponse)
async def get_projection(_auth: str = Depends(verify_api_key)) -> ProfitTargetProjectionResponse:
    """현재 손익 추이 기반 수익 추정치를 반환한다.

    Flutter ProfitTargetProjection.fromJson()이 기대하는 필드:
    current_pnl_usd, daily_avg_usd, projected_month_end_usd,
    monthly_target_usd, on_track, projected_deficit_usd,
    remaining_daily_target_usd
    """
    if _system is None:
        return ProfitTargetProjectionResponse(
            current_pnl_usd=0.0,
            daily_avg_usd=0.0,
            projected_month_end_usd=0.0,
            monthly_target_usd=_DEFAULT_MONTHLY_TARGET,
            on_track=False,
            projected_deficit_usd=_DEFAULT_MONTHLY_TARGET,
            remaining_daily_target_usd=round(_DEFAULT_MONTHLY_TARGET / 22, 2),
        )
    try:
        tp = _build_time_progress()
        days_elapsed = max(1, tp["elapsed_days"])
        days_in_month = tp["total_days"]
        remaining_trading = max(1, tp["remaining_trading_days"])

        current_pnl = await _read_monthly_pnl()
        _aggression, monthly_target = await _read_target_meta()

        # 일평균 수익 기반 월말 추정이다
        daily_avg = round(current_pnl / days_elapsed, 2)
        projected_month_end = round(daily_avg * days_in_month, 2)

        # 목표 달성 궤도 판단이다
        on_track = projected_month_end >= monthly_target

        # 예상 미달 금액 (목표 초과 시 음수)이다
        projected_deficit = round(monthly_target - projected_month_end, 2)

        # 남은 거래일 기준 일일 필요 수익이다
        gap = max(0.0, monthly_target - current_pnl)
        remaining_daily = round(gap / remaining_trading, 2)

        return ProfitTargetProjectionResponse(
            current_pnl_usd=current_pnl,
            daily_avg_usd=daily_avg,
            projected_month_end_usd=projected_month_end,
            monthly_target_usd=monthly_target,
            on_track=on_track,
            projected_deficit_usd=projected_deficit,
            remaining_daily_target_usd=remaining_daily,
        )
    except Exception:
        _logger.exception("수익 추정치 계산 실패")
        raise HTTPException(status_code=500, detail="수익 추정 중 오류가 발생했다") from None
