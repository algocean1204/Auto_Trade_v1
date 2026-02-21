"""
리스크 게이트 파이프라인 (Addendum 26)

4개 리스크 게이트를 순차적으로 실행하여 매매 가능 여부를 판단한다.
하나라도 실패하면 매매를 차단한다.

게이트 순서:
    1. DailyLossLimiter: 일일 손실 한도
    2. ConcentrationLimiter: 집중도 한도
    3. LosingStreakDetector: 연패 감지
    4. SimpleVaR: Value at Risk
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GateResult:
    """리스크 게이트 실행 결과를 담는 데이터 클래스이다.

    Attributes:
        passed: 게이트 통과 여부.
        action: 권장 조치 ("allow", "reduce", "block", "halt").
        message: 설명 메시지.
        gate_name: 게이트 이름.
        details: 추가 정보.
    """

    passed: bool
    action: str
    message: str
    gate_name: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """전체 파이프라인 실행 결과이다.

    Attributes:
        can_trade: 매매 가능 여부.
        gate_results: 각 게이트별 결과.
        blocking_gates: 차단된 게이트 목록.
        overall_action: 전체 권장 조치.
    """

    can_trade: bool
    gate_results: list[GateResult]
    blocking_gates: list[str]
    overall_action: str


class RiskGatePipeline:
    """4개 리스크 게이트를 통합 관리하고 순차 실행한다.

    모든 게이트를 통과해야 매매가 허용된다.
    하나라도 실패하면 해당 게이트의 action에 따라 조치한다.
    """

    def __init__(
        self,
        daily_loss_limiter: Any = None,
        concentration_limiter: Any = None,
        losing_streak_detector: Any = None,
        simple_var: Any = None,
        risk_budget: Any = None,
        trailing_stop_loss: Any = None,
    ) -> None:
        """RiskGatePipeline을 초기화한다.

        Args:
            daily_loss_limiter: DailyLossLimiter 인스턴스.
            concentration_limiter: ConcentrationLimiter 인스턴스.
            losing_streak_detector: LosingStreakDetector 인스턴스.
            simple_var: SimpleVaR 인스턴스.
            risk_budget: RiskBudget 인스턴스.
            trailing_stop_loss: TrailingStopLoss 인스턴스.
        """
        self.daily_loss_limiter = daily_loss_limiter
        self.concentration_limiter = concentration_limiter
        self.losing_streak_detector = losing_streak_detector
        self.simple_var = simple_var
        self.risk_budget = risk_budget
        self.trailing_stop_loss = trailing_stop_loss

        self._last_result: PipelineResult | None = None

        logger.info("RiskGatePipeline 초기화 완료")

    async def check_all(
        self, portfolio: dict[str, Any], market_data: dict[str, Any] | None = None
    ) -> PipelineResult:
        """모든 리스크 게이트를 순차 실행한다.

        Args:
            portfolio: 현재 포트폴리오 상태.
            market_data: 시장 데이터 (가격 이력 등).

        Returns:
            전체 파이프라인 실행 결과.
        """
        gate_results: list[GateResult] = []
        blocking_gates: list[str] = []

        # Gate 1: 일일 손실 한도
        if self.daily_loss_limiter is not None:
            try:
                result = await self.daily_loss_limiter.check(portfolio)
                gate_results.append(result)
                if not result.passed:
                    blocking_gates.append(result.gate_name)
            except Exception as e:
                logger.error("Gate 1 (DailyLossLimiter) 실행 실패: %s", e)
                gate_results.append(GateResult(
                    passed=False,
                    action="block",
                    message=f"게이트 오류: {e}",
                    gate_name="daily_loss_limiter",
                ))
                blocking_gates.append("daily_loss_limiter")

        # Gate 2: 집중도 한도
        if self.concentration_limiter is not None:
            try:
                result = await self.concentration_limiter.check(portfolio)
                gate_results.append(result)
                if not result.passed:
                    blocking_gates.append(result.gate_name)
            except Exception as e:
                logger.error("Gate 2 (ConcentrationLimiter) 실행 실패: %s", e)
                gate_results.append(GateResult(
                    passed=False,
                    action="block",
                    message=f"게이트 오류: {e}",
                    gate_name="concentration_limiter",
                ))
                blocking_gates.append("concentration_limiter")

        # Gate 3: 연패 감지
        if self.losing_streak_detector is not None:
            try:
                result = await self.losing_streak_detector.check()
                gate_results.append(result)
                if not result.passed:
                    blocking_gates.append(result.gate_name)
            except Exception as e:
                logger.error("Gate 3 (LosingStreakDetector) 실행 실패: %s", e)
                gate_results.append(GateResult(
                    passed=False,
                    action="block",
                    message=f"게이트 오류: {e}",
                    gate_name="losing_streak_detector",
                ))
                blocking_gates.append("losing_streak_detector")

        # Gate 4: VaR 체크
        if self.simple_var is not None and market_data is not None:
            try:
                result = await self.simple_var.check(portfolio, market_data)
                gate_results.append(result)
                if not result.passed:
                    blocking_gates.append(result.gate_name)
            except Exception as e:
                logger.error("Gate 4 (SimpleVaR) 실행 실패: %s", e)
                gate_results.append(GateResult(
                    passed=False,
                    action="block",
                    message=f"게이트 오류: {e}",
                    gate_name="simple_var",
                ))
                blocking_gates.append("simple_var")

        can_trade = len(blocking_gates) == 0

        # 전체 권장 조치 결정 (가장 심각한 action 사용)
        action_priority = {"allow": 0, "reduce": 1, "block": 2, "halt": 3}
        overall_action = "allow"
        for gr in gate_results:
            if action_priority.get(gr.action, 0) > action_priority.get(overall_action, 0):
                overall_action = gr.action

        pipeline_result = PipelineResult(
            can_trade=can_trade,
            gate_results=gate_results,
            blocking_gates=blocking_gates,
            overall_action=overall_action,
        )
        self._last_result = pipeline_result

        if not can_trade:
            logger.warning(
                "리스크 게이트 차단 | blocking=%s | action=%s",
                blocking_gates,
                overall_action,
            )
        else:
            logger.debug("리스크 게이트 모두 통과")

        return pipeline_result

    async def check_order(
        self, order: dict[str, Any], portfolio: dict[str, Any]
    ) -> GateResult:
        """개별 주문에 대한 리스크 검증을 수행한다 (2차 체크).

        Args:
            order: 주문 정보.
            portfolio: 현재 포트폴리오 상태.

        Returns:
            주문 검증 결과.
        """
        try:
            # 집중도 한도 체크 (주문 포함)
            if self.concentration_limiter is not None:
                conc_result = await self.concentration_limiter.check_order(
                    order, portfolio
                )
                if not conc_result.passed:
                    logger.warning(
                        "주문 리스크 검증 실패 (집중도): %s", conc_result.message
                    )
                    return conc_result

            # 리스크 예산 체크
            if self.risk_budget is not None:
                budget_result = await self.risk_budget.check_order(order)
                if not budget_result.passed:
                    logger.warning(
                        "주문 리스크 검증 실패 (예산): %s", budget_result.message
                    )
                    return budget_result

            return GateResult(
                passed=True,
                action="allow",
                message="주문 리스크 검증 통과",
                gate_name="order_check",
            )
        except Exception as e:
            logger.error("주문 리스크 검증 실패: %s", e)
            return GateResult(
                passed=False,
                action="block",
                message=f"검증 오류: {e}",
                gate_name="order_check",
            )

    def get_status(self) -> dict[str, Any]:
        """현재 파이프라인 상태를 반환한다.

        Returns:
            파이프라인 상태 딕셔너리.
        """
        status: dict[str, Any] = {
            "gates": {
                "daily_loss_limiter": self.daily_loss_limiter is not None,
                "concentration_limiter": self.concentration_limiter is not None,
                "losing_streak_detector": self.losing_streak_detector is not None,
                "simple_var": self.simple_var is not None,
            },
            "risk_budget": self.risk_budget is not None,
            "trailing_stop_loss": self.trailing_stop_loss is not None,
        }

        if self._last_result is not None:
            status["last_check"] = {
                "can_trade": self._last_result.can_trade,
                "blocking_gates": self._last_result.blocking_gates,
                "overall_action": self._last_result.overall_action,
                "gate_count": len(self._last_result.gate_results),
            }

        return status

    def get_context(self) -> dict[str, Any]:
        """Claude AI 프롬프트에 주입할 리스크 컨텍스트를 반환한다.

        Returns:
            리스크 컨텍스트 딕셔너리.
        """
        context: dict[str, Any] = {"risk_gates_status": self.get_status()}

        if self._last_result is not None:
            context["can_trade"] = self._last_result.can_trade
            context["blocking_gates"] = self._last_result.blocking_gates
            context["overall_action"] = self._last_result.overall_action
            context["gate_details"] = [
                {
                    "gate": gr.gate_name,
                    "passed": gr.passed,
                    "action": gr.action,
                    "message": gr.message,
                }
                for gr in self._last_result.gate_results
            ]

        return context
