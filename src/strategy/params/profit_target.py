"""F4 수익 목표 추적 -- 월간 $300 최소 수익 목표를 추적한다."""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.logger import get_logger
from src.strategy.models import TargetStatus

logger = get_logger(__name__)

# 월간 최소 수익 목표 (생존 매매)
_MONTHLY_TARGET = 300.0

# 월 거래일 수 (평균)
_TRADING_DAYS_PER_MONTH = 22


def _get_days_remaining() -> int:
    """이번 달 남은 거래일 수를 추정한다."""
    now = datetime.now(tz=timezone.utc)
    days_in_month = 30  # 간이 추정
    days_passed = now.day
    remaining = max(1, days_in_month - days_passed)
    # 거래일 비율 적용 (약 70%)
    return max(1, int(remaining * 0.7))


def _calculate_daily_target(
    current_pnl: float,
    target: float,
    days_remaining: int,
) -> float:
    """남은 일수 대비 일일 필요 수익을 계산한다."""
    gap = target - current_pnl
    if gap <= 0:
        return 0.0
    return round(gap / days_remaining, 2)


def _check_on_track(current_pnl: float, target: float) -> bool:
    """목표 달성 진행 여부를 판단한다."""
    now = datetime.now(tz=timezone.utc)
    day_of_month = now.day
    # 경과 비율 대비 수익 비율로 판단한다
    expected_ratio = day_of_month / 30.0
    actual_ratio = current_pnl / target if target > 0 else 0.0
    return actual_ratio >= expected_ratio * 0.8  # 80% 이상이면 정상 궤도


class ProfitTarget:
    """월간 수익 목표를 추적한다."""

    def __init__(self, target_pnl: float = _MONTHLY_TARGET) -> None:
        """목표 금액을 설정한다."""
        self._target = target_pnl

    def evaluate(self, monthly_pnl: dict) -> TargetStatus:
        """현재 월간 손익 기준으로 목표 상태를 반환한다.

        Args:
            monthly_pnl: trades(거래 수), pnl(누적 손익 $) 키 포함
        """
        current_pnl = monthly_pnl.get("pnl", 0.0)
        days_remaining = _get_days_remaining()
        daily_target = _calculate_daily_target(current_pnl, self._target, days_remaining)
        on_track = _check_on_track(current_pnl, self._target)

        status = TargetStatus(
            current_pnl=current_pnl,
            target_pnl=self._target,
            on_track=on_track,
            days_remaining=days_remaining,
            daily_target=daily_target,
        )

        logger.info(
            "수익 목표: $%.2f/$%.2f on_track=%s daily=$%.2f remain=%dd",
            current_pnl, self._target, on_track, daily_target, days_remaining,
        )
        return status
