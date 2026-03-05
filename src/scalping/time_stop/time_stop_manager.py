"""FS 시간 기반 청산 관리 -- 진입 후 경과 시간으로 청산을 판단한다.

스캘핑 포지션이 일정 시간 내 목표 수익에 도달하지 못하면
시간 기반 손절(time stop)을 실행하여 기회비용을 절감한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.logger import get_logger
from src.scalping.models import TimeStopResult

_logger = get_logger(__name__)

# 기본 최대 보유 시간(초)이다
_DEFAULT_MAX_HOLD = 120

# 경고 단계 임계값 (전체 시간의 비율)이다
_WARNING_THRESHOLD = 0.75
_CRITICAL_THRESHOLD = 0.9


def _elapsed_seconds(
    entry_time: datetime,
    now: datetime | None = None,
) -> int:
    """진입 시간부터 현재까지 경과 초를 계산한다."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    # timezone aware 변환한다
    if entry_time.tzinfo is None:
        entry_time = entry_time.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - entry_time
    return max(0, int(delta.total_seconds()))


def _determine_reason(
    elapsed: int,
    max_hold: int,
) -> str:
    """경과 시간에 따른 청산 사유를 결정한다."""
    if elapsed >= max_hold:
        return f"시간 초과: {elapsed}초 >= {max_hold}초 (최대 보유 시간 도달)"
    ratio = elapsed / max_hold if max_hold > 0 else 0
    if ratio >= _CRITICAL_THRESHOLD:
        return f"임계 경고: {elapsed}초 (최대의 {ratio:.0%})"
    if ratio >= _WARNING_THRESHOLD:
        return f"경고: {elapsed}초 (최대의 {ratio:.0%})"
    return ""


class TimeStopManager:
    """시간 기반 청산 관리자이다.

    진입 시간과 최대 보유 시간을 기준으로
    포지션의 시간 초과 여부를 판단한다.
    """

    def __init__(
        self,
        max_hold_seconds: int = _DEFAULT_MAX_HOLD,
    ) -> None:
        """최대 보유 시간(초)으로 초기화한다."""
        self._max_hold = max_hold_seconds

    def check(
        self,
        entry_time: datetime,
        now: datetime | None = None,
    ) -> TimeStopResult:
        """진입 시간 기준 시간 초과 여부를 판단한다.

        should_exit=True이면 즉시 청산이 권장된다.
        """
        elapsed = _elapsed_seconds(entry_time, now)
        should_exit = elapsed >= self._max_hold
        reason = _determine_reason(elapsed, self._max_hold)
        if should_exit:
            _logger.info("TimeStop 발동: %s", reason)
        return TimeStopResult(
            should_exit=should_exit,
            elapsed_seconds=elapsed,
            reason=reason,
        )

    @property
    def max_hold_seconds(self) -> int:
        """최대 보유 시간(초)을 반환한다."""
        return self._max_hold

    def update_max_hold(self, new_max: int) -> None:
        """최대 보유 시간을 동적으로 변경한다."""
        if new_max <= 0:
            _logger.warning("유효하지 않은 max_hold: %d, 무시", new_max)
            return
        self._max_hold = new_max
        _logger.info("TimeStop max_hold 변경: %d초", new_max)
