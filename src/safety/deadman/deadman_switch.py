"""DeadmanSwitch (F6.12) -- 데이터 무응답 시 안전 조치를 취한다.

WebSocket 등 실시간 데이터가 일정 시간 이상 미수신되면
Beast 모드 포지션을 긴급 청산한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 기본 타임아웃 --
_DEFAULT_TIMEOUT: float = 10.0


class DeadmanSwitch:
    """데드맨 스위치이다. 데이터 무응답 시 안전 조치한다.

    heartbeat()가 timeout_seconds 이내에 호출되지 않으면
    is_triggered()가 True를 반환한다.
    """

    def __init__(
        self, timeout_seconds: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """초기화한다.

        Args:
            timeout_seconds: 무응답 임계 시간(초). 기본 10초.
        """
        self._timeout = timeout_seconds
        self._last_heartbeat: datetime = datetime.now(
            tz=timezone.utc,
        )
        self._triggered_count: int = 0

    def heartbeat(self) -> None:
        """데이터 수신 시 호출한다.

        타임스탬프를 갱신하여 트리거를 방지한다.
        """
        self._last_heartbeat = datetime.now(tz=timezone.utc)

    def is_triggered(self) -> bool:
        """타임아웃 초과 여부를 반환한다.

        마지막 heartbeat 이후 timeout_seconds 이상 경과하면
        True를 반환하고 트리거 횟수를 증가시킨다.
        """
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - self._last_heartbeat).total_seconds()

        if elapsed > self._timeout:
            self._triggered_count += 1
            _logger.warning(
                "DeadmanSwitch 트리거: %.1f초 무응답 "
                "(임계=%.1f초, 누적=%d회)",
                elapsed, self._timeout, self._triggered_count,
            )
            return True
        return False

    def get_elapsed_seconds(self) -> float:
        """마지막 heartbeat 이후 경과 시간(초)을 반환한다."""
        now = datetime.now(tz=timezone.utc)
        return (now - self._last_heartbeat).total_seconds()

    def get_triggered_count(self) -> int:
        """누적 트리거 횟수를 반환한다."""
        return self._triggered_count

    def reset(self) -> None:
        """일일 리셋한다. heartbeat를 현재 시각으로 갱신한다."""
        self._last_heartbeat = datetime.now(tz=timezone.utc)
        self._triggered_count = 0
        _logger.info("DeadmanSwitch 리셋 완료")
