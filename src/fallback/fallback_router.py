"""
Fallback 라우터

Claude API 호출을 래핑하여 장애 또는 Quota 초과 시 자동으로 로컬 Qwen3 모델로 전환한다.

라우팅 흐름:
  1. Claude 정상 & Quota 충분 -> Claude 사용
  2. 429 에러 -> 재시도 3회 (QuotaGuard.safe_call)
  3. 재시도 실패 or 장애 -> Qwen3 전환
  4. Qwen3 confidence < 0.90 -> 매매 스킵 (안전)
"""

from __future__ import annotations

import time
from typing import Any

from src.analysis.claude_client import ClaudeClient
from src.fallback.local_model import LocalModel
from src.safety.quota_guard import QuotaExhaustedError, QuotaGuard
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FallbackRouter:
    """Claude API와 로컬 Fallback 모델 간의 지능형 라우터.

    Claude API 호출 실패 시 로컬 Qwen3 모델로 자동 전환하며,
    Fallback 결과의 confidence가 기준 미달이면 매매를 스킵한다.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        quota_guard: QuotaGuard,
        local_model: LocalModel | None = None,
    ) -> None:
        """FallbackRouter 초기화.

        Args:
            claude_client: Claude API 클라이언트.
            quota_guard: Quota 관리자.
            local_model: 로컬 Fallback 모델. None이면 싱글톤 인스턴스 사용.
        """
        self.claude = claude_client
        self.quota = quota_guard
        self.local = local_model or LocalModel.get_instance()
        self.fallback_active: bool = False
        self.fallback_count: int = 0
        self._claude_status: str = "online"  # "online" | "degraded" | "offline"
        self._last_claude_success: float = time.monotonic()
        self._consecutive_failures: int = 0

        logger.info(
            "FallbackRouter 초기화 완료 | local_available=%s",
            self.local.is_available(),
        )

    async def call(
        self,
        prompt: str,
        task_type: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """지능형 라우팅으로 API를 호출한다.

        Claude -> Quota 체크 -> 재시도 -> Fallback 순으로 시도하며,
        Fallback의 confidence가 기준 미달이면 안전하게 스킵한다.

        Args:
            prompt: 프롬프트 텍스트.
            task_type: 태스크 유형 (모델 라우팅에 사용).
            **kwargs: ClaudeClient.call()에 전달할 추가 인자.

        Returns:
            라우팅 결과 딕셔너리:
                - content: str -- 응답 텍스트
                - model: str -- 사용된 모델 이름
                - source: "claude" | "fallback" -- 응답 출처
                - confidence: float -- 신뢰도
                - fallback_reason: str | None -- Fallback 전환 사유
                - should_skip: bool -- 매매 스킵 여부

        Raises:
            RuntimeError: Claude와 Fallback 모두 실패한 경우.
        """
        # 1. Claude 시도
        claude_result = await self._try_claude(prompt, task_type, **kwargs)
        if claude_result is not None:
            self._on_claude_success()
            return {
                "content": claude_result["content"],
                "model": claude_result["model"],
                "source": "claude",
                "confidence": 1.0,  # Claude 결과는 신뢰도 최대
                "fallback_reason": None,
                "should_skip": False,
            }

        # 2. Claude 실패 -> Fallback 시도
        fallback_reason = self._get_fallback_reason()
        logger.warning(
            "Claude 실패, Fallback 전환 | reason=%s | task=%s",
            fallback_reason,
            task_type,
        )

        fallback_result = await self._try_fallback(prompt, task_type)
        if fallback_result is not None:
            should_skip = self._should_skip_trade(fallback_result)
            if should_skip:
                logger.warning(
                    "Fallback confidence 부족, 매매 스킵 권고 | confidence=%.4f | min=%.2f",
                    fallback_result["confidence"],
                    LocalModel.MIN_CONFIDENCE,
                )

            return {
                "content": fallback_result["content"],
                "model": fallback_result["model"],
                "source": "fallback",
                "confidence": fallback_result["confidence"],
                "fallback_reason": fallback_reason,
                "should_skip": should_skip,
            }

        # 3. 둘 다 실패
        logger.error(
            "Claude + Fallback 모두 실패 | task=%s | reason=%s",
            task_type,
            fallback_reason,
        )
        raise RuntimeError(
            f"Claude API와 로컬 Fallback 모두 실패. "
            f"사유: {fallback_reason}. "
            f"task_type: {task_type}"
        )

    async def call_json(
        self,
        prompt: str,
        task_type: str,
        **kwargs: Any,
    ) -> dict | list | None:
        """JSON 응답을 기대하는 라우팅 호출.

        Claude의 call_json -> Fallback의 generate_json 순으로 시도한다.

        Args:
            prompt: 프롬프트 텍스트.
            task_type: 태스크 유형.
            **kwargs: 추가 인자.

        Returns:
            파싱된 JSON (dict 또는 list), 모두 실패 시 None.
        """
        # 1. Claude JSON 시도
        claude_json = await self._try_claude_json(prompt, task_type, **kwargs)
        if claude_json is not None:
            self._on_claude_success()
            return claude_json

        # 2. Fallback JSON 시도
        fallback_reason = self._get_fallback_reason()
        logger.warning(
            "Claude JSON 실패, Fallback 전환 | reason=%s | task=%s",
            fallback_reason,
            task_type,
        )

        fallback_json = await self._try_fallback_json(prompt, task_type)
        if fallback_json is not None:
            return fallback_json

        # 3. 둘 다 실패
        logger.error(
            "Claude + Fallback JSON 모두 실패 | task=%s",
            task_type,
        )
        return None

    def get_status(self) -> dict[str, Any]:
        """Fallback 시스템 상태를 반환한다.

        claude_client 모드(local/api)를 함께 보고한다.

        Returns:
            상태 정보 딕셔너리.
        """
        claude_mode = getattr(self.claude, "mode", "api")
        return {
            "claude_mode": claude_mode,
            "mode": "fallback" if self.fallback_active else "claude",
            "fallback_count": self.fallback_count,
            "local_model_available": self.local.is_available(),
            "local_model_loaded": self.local.is_loaded,
            "claude_status": self._claude_status,
            "consecutive_failures": self._consecutive_failures,
            "quota_remaining": self.quota.get_remaining(),
            "quota_usage_pct": round(self.quota.get_usage_pct(), 1),
            "quota_can_call": self.quota.can_call(),
        }

    async def _try_claude(
        self,
        prompt: str,
        task_type: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Claude 호출을 시도한다.

        QuotaGuard.safe_call()을 통해 Quota 체크와 429 재시도를 수행한다.
        실패 시 None을 반환한다.

        Args:
            prompt: 프롬프트 텍스트.
            task_type: 태스크 유형.
            **kwargs: 추가 인자.

        Returns:
            Claude 응답 딕셔너리 또는 None.
        """
        try:
            result = await self.quota.safe_call(
                prompt=prompt,
                task_type=task_type,
                **kwargs,
            )
            return result
        except QuotaExhaustedError as exc:
            self._on_claude_failure(f"quota_exhausted: {exc}")
            return None
        except Exception as exc:
            self._on_claude_failure(f"api_error: {type(exc).__name__}: {exc}")
            return None

    async def _try_claude_json(
        self,
        prompt: str,
        task_type: str,
        **kwargs: Any,
    ) -> dict | list | None:
        """Claude JSON 호출을 시도한다. 실패 시 None을 반환한다."""
        try:
            if not self.quota.can_call():
                self._on_claude_failure("quota_exhausted")
                return None

            result = await self.claude.call_json(
                prompt=prompt,
                task_type=task_type,
                **kwargs,
            )
            self.quota.record_call()
            return result
        except QuotaExhaustedError as exc:
            self._on_claude_failure(f"quota_exhausted: {exc}")
            return None
        except Exception as exc:
            self._on_claude_failure(f"api_error: {type(exc).__name__}: {exc}")
            return None

    async def _try_fallback(
        self,
        prompt: str,
        task_type: str,
    ) -> dict[str, Any] | None:
        """로컬 Fallback 모델 호출을 시도한다.

        모델이 사용 불가능하거나 생성에 실패하면 None을 반환한다.

        Args:
            prompt: 프롬프트 텍스트.
            task_type: 태스크 유형 (로깅용).

        Returns:
            생성 결과 딕셔너리 또는 None.
        """
        if not self.local.is_available():
            logger.error("로컬 Fallback 모델 사용 불가")
            return None

        try:
            result = await self.local.generate(prompt=prompt)
            self.fallback_active = True
            self.fallback_count += 1

            logger.info(
                "Fallback 생성 완료 | task=%s | confidence=%.4f | fallback_count=%d",
                task_type,
                result["confidence"],
                self.fallback_count,
            )
            return result
        except Exception as exc:
            logger.error(
                "Fallback 생성 실패 | task=%s | error=%s",
                task_type,
                exc,
            )
            return None

    async def _try_fallback_json(
        self,
        prompt: str,
        task_type: str,
    ) -> dict | list | None:
        """로컬 Fallback 모델의 JSON 생성을 시도한다. 실패 시 None을 반환한다."""
        if not self.local.is_available():
            logger.error("로컬 Fallback 모델 사용 불가 (JSON)")
            return None

        try:
            result = await self.local.generate_json(prompt=prompt)
            if result is not None:
                self.fallback_active = True
                self.fallback_count += 1
                logger.info(
                    "Fallback JSON 생성 완료 | task=%s | fallback_count=%d",
                    task_type,
                    self.fallback_count,
                )
            return result
        except Exception as exc:
            logger.error(
                "Fallback JSON 생성 실패 | task=%s | error=%s",
                task_type,
                exc,
            )
            return None

    def _should_skip_trade(self, result: dict[str, Any]) -> bool:
        """Fallback 결과의 confidence가 기준 미달이면 매매를 스킵한다.

        레버리지 ETF를 거래하므로 Fallback 모델의 결과는
        높은 신뢰도를 요구한다.

        Args:
            result: Fallback 생성 결과.

        Returns:
            True이면 매매를 스킵해야 한다.
        """
        confidence = result.get("confidence", 0.0)
        return confidence < LocalModel.MIN_CONFIDENCE

    def _on_claude_success(self) -> None:
        """Claude 호출 성공 시 상태를 업데이트한다."""
        self._last_claude_success = time.monotonic()
        self._consecutive_failures = 0

        if self.fallback_active:
            logger.info("Claude 복구 감지, Fallback 모드 해제")
            self.fallback_active = False

        self._claude_status = "online"

    def _on_claude_failure(self, reason: str) -> None:
        """Claude 호출 실패 시 상태를 업데이트한다.

        Args:
            reason: 실패 사유.
        """
        self._consecutive_failures += 1

        if self._consecutive_failures >= 3:
            self._claude_status = "offline"
        elif self._consecutive_failures >= 1:
            self._claude_status = "degraded"

        logger.warning(
            "Claude 호출 실패 | reason=%s | consecutive=%d | status=%s",
            reason,
            self._consecutive_failures,
            self._claude_status,
        )

    def _get_fallback_reason(self) -> str:
        """현재 상태에서 Fallback 전환 사유를 반환한다.

        local 모드에서는 Quota 소진이 발생하지 않으므로,
        연속 실패 횟수만 확인한다.
        """
        claude_mode = getattr(self.claude, "mode", "api")
        # api 모드에서만 Quota 소진 확인
        if claude_mode == "api" and not self.quota.can_call():
            return f"quota_exhausted (usage={self.quota.get_usage_pct():.1f}%)"
        if self._consecutive_failures >= 3:
            return f"claude_offline (consecutive_failures={self._consecutive_failures})"
        if self._consecutive_failures >= 1:
            return f"claude_degraded (consecutive_failures={self._consecutive_failures})"
        return "unknown"
