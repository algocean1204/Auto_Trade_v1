"""TiltDetector (F6.8) -- 감정적 매매를 방지한다.

연속 3손실/10분 또는 -2%/30분 조건 충족 시 1시간 매매를 잠근다.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from src.common.event_bus import get_event_bus
from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 상수 --
_MAX_CONSECUTIVE: int = 3
_CONSECUTIVE_WINDOW_MINUTES: int = 10
_PNL_THRESHOLD_PCT: float = -2.0
_PNL_WINDOW_MINUTES: int = 30
_DEFAULT_LOCK_MINUTES: int = 60
_MAX_TRADE_HISTORY: int = 100


class TiltStatus(BaseModel):
    """틸트 상태이다."""

    is_tilted: bool
    reason: str = ""
    locked_until: datetime | None = None
    consecutive_losses: int = 0


class _TradeRecord:
    """거래 기록 엔트리이다."""

    __slots__ = ("pnl", "timestamp")

    def __init__(self, pnl: float, timestamp: datetime) -> None:
        self.pnl = pnl
        self.timestamp = timestamp


class TiltDetector:
    """틸트 감지기이다. 감정적 매매를 방지한다.

    두 가지 조건 중 하나라도 충족되면 틸트로 판정한다:
    1. 10분 내 연속 3회 손절
    2. 30분 내 누적 -2% 이상 손실
    """

    def __init__(
        self,
        max_consecutive: int = _MAX_CONSECUTIVE,
        lock_minutes: int = _DEFAULT_LOCK_MINUTES,
    ) -> None:
        """초기화한다.

        Args:
            max_consecutive: 연속 손절 허용 횟수. 기본 3.
            lock_minutes: 틸트 시 잠금 시간(분). 기본 60.
        """
        self._max_consecutive = max_consecutive
        self._lock_minutes = lock_minutes
        self._locked_until: datetime | None = None
        self._trades: deque[_TradeRecord] = deque(
            maxlen=_MAX_TRADE_HISTORY,
        )
        self._consecutive_losses: int = 0
        self._event_bus = get_event_bus()

    def record_trade_result(self, pnl: float) -> None:
        """거래 결과를 기록한다.

        Args:
            pnl: 손익(%). 음수=손실, 양수=이익.
        """
        now = datetime.now(tz=timezone.utc)
        self._trades.append(_TradeRecord(pnl=pnl, timestamp=now))

        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        _logger.debug(
            "TiltDetector 거래 기록: %.2f%% (연속손실=%d)",
            pnl, self._consecutive_losses,
        )

    def check_tilt(self) -> TiltStatus:
        """틸트 상태를 확인한다."""
        # 이미 잠금 상태인지 먼저 확인
        if self._is_currently_locked():
            return TiltStatus(
                is_tilted=True,
                reason="틸트 잠금 유지 중",
                locked_until=self._locked_until,
                consecutive_losses=self._consecutive_losses,
            )

        # 조건 1: 연속 손절 확인
        reason_1 = self._check_consecutive_losses()
        if reason_1:
            return self._activate_tilt(reason_1)

        # 조건 2: 누적 손실 확인
        reason_2 = self._check_cumulative_loss()
        if reason_2:
            return self._activate_tilt(reason_2)

        return TiltStatus(
            is_tilted=False,
            consecutive_losses=self._consecutive_losses,
        )

    def reset(self) -> None:
        """일일 리셋한다."""
        self._locked_until = None
        self._trades.clear()
        self._consecutive_losses = 0
        _logger.info("TiltDetector 일일 리셋 완료")

    def _is_currently_locked(self) -> bool:
        """현재 잠금 상태인지 확인한다."""
        if self._locked_until is None:
            return False
        now = datetime.now(tz=timezone.utc)
        if now >= self._locked_until:
            self._locked_until = None
            return False
        return True

    def _check_consecutive_losses(self) -> str:
        """10분 내 연속 손절 조건을 확인한다."""
        if self._consecutive_losses < self._max_consecutive:
            return ""
        # 최근 연속 손실이 10분 이내인지 확인
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(minutes=_CONSECUTIVE_WINDOW_MINUTES)
        recent_losses = [
            t for t in self._trades
            if t.pnl < 0 and t.timestamp >= cutoff
        ]
        if len(recent_losses) >= self._max_consecutive:
            return (
                f"연속{self._max_consecutive}손절/"
                f"{_CONSECUTIVE_WINDOW_MINUTES}분"
            )
        return ""

    def _check_cumulative_loss(self) -> str:
        """30분 내 누적 손실 조건을 확인한다."""
        now = datetime.now(tz=timezone.utc)
        cutoff = now - timedelta(minutes=_PNL_WINDOW_MINUTES)
        recent_pnl = sum(
            t.pnl for t in self._trades if t.timestamp >= cutoff
        )
        if recent_pnl <= _PNL_THRESHOLD_PCT:
            return (
                f"누적{recent_pnl:.1f}%/"
                f"{_PNL_WINDOW_MINUTES}분"
            )
        return ""

    def _activate_tilt(self, reason: str) -> TiltStatus:
        """틸트를 활성화하고 잠금을 설정한다."""
        now = datetime.now(tz=timezone.utc)
        self._locked_until = now + timedelta(
            minutes=self._lock_minutes,
        )
        _logger.warning(
            "틸트 감지: %s -> %d분 잠금",
            reason, self._lock_minutes,
        )
        return TiltStatus(
            is_tilted=True,
            reason=reason,
            locked_until=self._locked_until,
            consecutive_losses=self._consecutive_losses,
        )
