"""
Claude API Quota 관리
- 사전 잔여량 체크
- 매 호출 전 90% 도달 여부 확인
- 429 에러 시 재시도 (10s, 30s, 60s)
- Quota 초과 시 로컬 Fallback 전환 트리거
- local 모드(MAX 플랜)에서는 Quota 추적을 건너뛴다 (무제한)
"""

import asyncio
from datetime import datetime, timedelta, timezone

from src.utils.logger import get_logger

logger = get_logger(__name__)


class QuotaExhaustedError(Exception):
    """Quota 소진 에러.

    이 에러가 발생하면 호출부에서 로컬 Fallback 전략으로 전환해야 한다.
    """

    pass


class QuotaGuard:
    """Claude API 호출 Quota를 관리한다.

    슬라이딩 윈도우 방식으로 호출 횟수를 추적하며,
    90% 이상 사용 시 호출을 차단하고 QuotaExhaustedError를 발생시킨다.

    local 모드(Claude Code MAX 플랜)에서는 Quota 제한이 없으므로,
    모든 Quota 체크를 건너뛰고 항상 호출을 허용한다.

    Quota 계산 참고 (Thinking.md Addendum 7.2):
        - 야간(23:00~09:00): Sonnet ~37회 + Opus ~26회 = Sonnet 환산 ~115회
        - $100 플랜 5시간 창 ~225회 -> 51% 사용
        - Opus 1회 = Sonnet 3회 환산

    Attributes:
        claude_client: ClaudeClient 인스턴스.
        max_calls: 윈도우 내 최대 허용 호출 횟수.
        window_hours: 슬라이딩 윈도우 크기 (시간).
        call_history: 윈도우 내 호출 시간 기록 리스트.
        _local_mode: True이면 Quota 추적을 건너뛴다.
    """

    # 429 에러 발생 시 재시도 간격 (초)
    RETRY_DELAYS: list[int] = [10, 30, 60]

    def __init__(
        self,
        claude_client: object,
        max_calls_per_window: int = 225,
        window_hours: int = 5,
    ) -> None:
        """QuotaGuard를 초기화한다.

        Args:
            claude_client: ClaudeClient 인스턴스.
            max_calls_per_window: 윈도우 내 최대 호출 횟수. local 모드에서는 무시된다.
            window_hours: 슬라이딩 윈도우 크기 (시간).
        """
        self.claude_client = claude_client
        self.max_calls: int = max_calls_per_window
        self.window_hours: int = window_hours
        self.call_history: list[datetime] = []

        # ClaudeClient 인스턴스에서 모드를 읽는다.
        self._local_mode: bool = getattr(claude_client, "mode", "api") == "local"

        if self._local_mode:
            logger.info(
                "QuotaGuard 초기화 | local 모드 (MAX 플랜) - Quota 추적 비활성화"
            )
        else:
            logger.info(
                "QuotaGuard 초기화 | api 모드 | max_calls=%d | window=%dh",
                self.max_calls,
                self.window_hours,
            )

    def get_remaining(self) -> int:
        """현재 윈도우 내 남은 호출 가능 횟수를 반환한다.

        local 모드에서는 항상 max_calls를 반환한다 (무제한 처리).

        Returns:
            남은 호출 가능 횟수.
        """
        if self._local_mode:
            return self.max_calls  # 무제한이므로 최댓값 반환
        self._cleanup_old_calls()
        remaining = self.max_calls - len(self.call_history)
        return max(remaining, 0)

    def get_usage_pct(self) -> float:
        """현재 사용률을 백분율로 반환한다.

        local 모드에서는 항상 0.0을 반환한다.

        Returns:
            0.0~100.0 범위의 사용률.
        """
        if self._local_mode:
            return 0.0
        self._cleanup_old_calls()
        if self.max_calls == 0:
            return 100.0
        return (len(self.call_history) / self.max_calls) * 100.0

    def can_call(self) -> bool:
        """호출 가능 여부를 확인한다.

        local 모드에서는 항상 True를 반환한다.
        api 모드에서는 사용률이 90% 미만이면 True를 반환한다.

        Returns:
            True이면 호출 가능.
        """
        if self._local_mode:
            return True

        usage = self.get_usage_pct()
        can = usage < 90.0
        if not can:
            logger.warning(
                "Quota 한도 근접 | usage=%.1f%% | remaining=%d",
                usage,
                self.get_remaining(),
            )
        return can

    def record_call(self) -> None:
        """호출 시간을 기록한다. local 모드에서는 아무 작업도 수행하지 않는다."""
        if self._local_mode:
            return

        now = datetime.now(tz=timezone.utc)
        self.call_history.append(now)
        logger.debug(
            "호출 기록 | total_in_window=%d | remaining=%d",
            len(self.call_history),
            self.get_remaining(),
        )

    async def safe_call(self, prompt: str, task_type: str, **kwargs: object) -> dict:
        """Quota 체크 후 안전하게 Claude를 호출한다.

        local 모드에서는 Quota 체크를 건너뛰고 직접 claude_client.call()을 호출한다.

        api 모드 흐름:
            1. can_call() 체크
            2. 호출 가능 -> Claude 호출 + record_call()
            3. Quota 부족 -> QuotaExhaustedError 발생 (Fallback이 처리)
            4. 429 에러 -> 재시도 3회 (10s, 30s, 60s)

        Args:
            prompt: Claude에 전달할 프롬프트.
            task_type: 태스크 유형 (모델 라우팅에 사용).
            **kwargs: ClaudeClient.call()에 전달할 추가 인자.

        Returns:
            Claude 응답 딕셔너리.

        Raises:
            QuotaExhaustedError: api 모드에서 Quota가 소진되었을 때.
            anthropic.RateLimitError: api 모드에서 재시도 3회 후에도 429 에러가 지속될 때.
        """
        # local 모드: Quota 제한 없이 바로 호출한다.
        if self._local_mode:
            logger.debug("local 모드 safe_call | task=%s", task_type)
            return await self.claude_client.call(
                prompt=prompt, task_type=task_type, **kwargs
            )

        # api 모드: 기존 Quota 체크 + 재시도 로직
        if not self.can_call():
            remaining = self.get_remaining()
            usage_pct = self.get_usage_pct()
            logger.error(
                "Quota 소진 | remaining=%d | usage=%.1f%% | Fallback 전환 필요",
                remaining,
                usage_pct,
            )
            raise QuotaExhaustedError(
                f"Claude API Quota 소진: 사용률 {usage_pct:.1f}%, "
                f"남은 호출 {remaining}회"
            )

        try:
            import anthropic as _anthropic
        except ImportError:
            _anthropic = None  # type: ignore[assignment]

        last_error: Exception | None = None

        for attempt, delay in enumerate(self.RETRY_DELAYS, start=1):
            try:
                result = await self.claude_client.call(
                    prompt=prompt, task_type=task_type, **kwargs
                )
                self.record_call()

                usage_pct = self.get_usage_pct()
                if usage_pct >= 75.0:
                    logger.warning(
                        "Quota 사용률 경고 | usage=%.1f%% | remaining=%d",
                        usage_pct,
                        self.get_remaining(),
                    )

                return result

            except Exception as e:
                # anthropic이 설치된 경우 RateLimitError 여부 확인
                is_rate_limit = (
                    _anthropic is not None
                    and isinstance(e, _anthropic.RateLimitError)
                )
                if not is_rate_limit:
                    raise

                last_error = e
                logger.warning(
                    "429 Rate Limit 에러 | attempt=%d/%d | retry_in=%ds",
                    attempt,
                    len(self.RETRY_DELAYS),
                    delay,
                )
                if attempt < len(self.RETRY_DELAYS):
                    await asyncio.sleep(delay)
                else:
                    # 마지막 재시도에서도 실패하면 대기 후 에러 전파
                    await asyncio.sleep(delay)
                    try:
                        result = await self.claude_client.call(
                            prompt=prompt, task_type=task_type, **kwargs
                        )
                        self.record_call()
                        return result
                    except Exception as retry_exc:
                        is_rate_limit_retry = (
                            _anthropic is not None
                            and isinstance(retry_exc, _anthropic.RateLimitError)
                        )
                        if is_rate_limit_retry:
                            logger.error(
                                "429 재시도 모두 실패 | attempts=%d | Fallback 전환 필요",
                                len(self.RETRY_DELAYS),
                            )
                            raise QuotaExhaustedError(
                                f"Claude API 429 에러 {len(self.RETRY_DELAYS)}회 재시도 실패. "
                                "Fallback 전환 필요."
                            ) from e
                        raise

        # 이론적으로 도달하지 않지만, 타입 안전성을 위해 유지
        if last_error is not None:
            raise QuotaExhaustedError(
                "Claude API 호출 실패"
            ) from last_error

        raise QuotaExhaustedError("Claude API 호출 실패: 알 수 없는 오류")

    def cleanup(self) -> None:
        """슬라이딩 윈도우 밖의 오래된 호출 기록을 제거하는 공개 인터페이스이다."""
        self._cleanup_old_calls()

    def _cleanup_old_calls(self) -> None:
        """슬라이딩 윈도우 밖의 오래된 호출 기록을 제거한다."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=self.window_hours)
        before_count = len(self.call_history)
        self.call_history = [t for t in self.call_history if t > cutoff]
        removed = before_count - len(self.call_history)
        if removed > 0:
            logger.debug(
                "오래된 호출 기록 %d건 제거 | remaining_in_window=%d",
                removed,
                len(self.call_history),
            )

    def get_status(self) -> dict:
        """현재 Quota 상태를 딕셔너리로 반환한다.

        Returns:
            Quota 상태 정보를 담은 딕셔너리.
        """
        self._cleanup_old_calls()
        return {
            "mode": "local (unlimited)" if self._local_mode else "api",
            "remaining": self.get_remaining(),
            "usage_pct": round(self.get_usage_pct(), 1),
            "calls_in_window": len(self.call_history),
            "max_calls": self.max_calls,
            "window_hours": self.window_hours,
            "can_call": self.can_call(),
        }
