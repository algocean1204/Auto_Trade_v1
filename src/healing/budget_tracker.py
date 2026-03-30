"""예산 추적기 -- Self-Healing AI 호출 비용을 추적하고 세션 예산을 관리한다.

Opus/Sonnet/Haiku 모델별 호출 횟수와 비용을 기록하여 예산 초과를 방지한다.
"""
from __future__ import annotations

import logging

from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 모델별 예상 호출 비용 (USD)
_COST_PER_CALL: dict[str, float] = {"opus": 0.15, "sonnet": 0.03, "haiku": 0.01}

# 세션당 기본 예산 상한 (USD)
_DEFAULT_BUDGET: float = 5.0

# 모델별 최대 호출 횟수 제한
_DEFAULT_MAX_CALLS: dict[str, int] = {"opus": 10, "sonnet": 20, "haiku": 50}


class BudgetTracker:
    """세션 내 AI 호출 비용을 추적하는 클래스이다."""

    def __init__(self, session_budget: float = _DEFAULT_BUDGET) -> None:
        self._budget = session_budget
        self._total_cost: float = 0.0
        self._calls: dict[str, int] = {"opus": 0, "sonnet": 0, "haiku": 0}
        logger.info("BudgetTracker 초기화 (예산=$%.2f)", session_budget)

    def can_call(self, model: str) -> bool:
        """예산 및 호출 횟수 한도 내에서 호출 가능 여부를 반환한다."""
        cost = _COST_PER_CALL.get(model, 0.15)
        # 예산 초과 여부 확인
        if self._total_cost + cost > self._budget:
            logger.warning("예산 초과로 %s 호출 불가 ($%.2f/$%.2f)", model, self._total_cost, self._budget)
            return False
        # 호출 횟수 한도 확인
        max_calls = _DEFAULT_MAX_CALLS.get(model, 10)
        if self._calls.get(model, 0) >= max_calls:
            logger.warning("%s 호출 횟수 한도 초과 (%d/%d)", model, self._calls.get(model, 0), max_calls)
            return False
        return True

    def record_call(self, model: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        """호출 결과를 기록한다. 토큰 수는 향후 정밀 비용 산정에 활용한다."""
        cost = _COST_PER_CALL.get(model, 0.15)
        self._total_cost += cost
        self._calls[model] = self._calls.get(model, 0) + 1
        logger.info(
            "%s 호출 기록 (누적=$%.2f, 횟수=%d, tokens=%d/%d)",
            model, self._total_cost, self._calls[model], input_tokens, output_tokens,
        )

    def get_summary(self) -> dict[str, object]:
        """현재 예산 사용 요약을 반환한다."""
        return {
            "total_cost": round(self._total_cost, 4),
            "calls": dict(self._calls),
            "budget_remaining": round(self._budget - self._total_cost, 4),
        }

    def reset(self) -> None:
        """새 세션을 위해 추적 상태를 초기화한다."""
        self._total_cost = 0.0
        self._calls = {"opus": 0, "sonnet": 0, "haiku": 0}
        logger.info("BudgetTracker 초기화 완료")
