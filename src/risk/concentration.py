"""
집중도 한도 게이트 (Addendum 26 - Gate 2)

포트폴리오 집중도를 제한한다:
    - 단일 종목 최대 30%
    - 전체 포지션 합계 최대 60%
    - 현금 비율 최소 40%
    - 최대 동시 보유 종목 3개
"""

from __future__ import annotations

from typing import Any

from src.risk.risk_gate import GateResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 집중도 한도 기본값
DEFAULT_SINGLE_MAX_PCT: float = 30.0
DEFAULT_TOTAL_MAX_PCT: float = 60.0
DEFAULT_MIN_CASH_PCT: float = 40.0
DEFAULT_MAX_POSITIONS: int = 3


class ConcentrationLimiter:
    """포트폴리오 집중도를 제한한다.

    종목당/전체 포지션 비율과 현금 비율, 동시 보유 종목 수를 제한한다.

    Attributes:
        single_max_pct: 단일 종목 최대 비중 (%).
        total_max_pct: 전체 포지션 합계 최대 비중 (%).
        min_cash_pct: 최소 현금 비율 (%).
        max_positions: 최대 동시 보유 종목 수.
    """

    def __init__(
        self,
        single_max_pct: float = DEFAULT_SINGLE_MAX_PCT,
        total_max_pct: float = DEFAULT_TOTAL_MAX_PCT,
        min_cash_pct: float = DEFAULT_MIN_CASH_PCT,
        max_positions: int = DEFAULT_MAX_POSITIONS,
    ) -> None:
        """ConcentrationLimiter를 초기화한다.

        Args:
            single_max_pct: 단일 종목 최대 비중.
            total_max_pct: 전체 포지션 합계 최대 비중.
            min_cash_pct: 최소 현금 비율.
            max_positions: 최대 동시 보유 종목 수.
        """
        self.single_max_pct = single_max_pct
        self.total_max_pct = total_max_pct
        self.min_cash_pct = min_cash_pct
        self.max_positions = max_positions

        logger.info(
            "ConcentrationLimiter 초기화 | single=%.0f%% | total=%.0f%% | "
            "cash>=%.0f%% | max_pos=%d",
            single_max_pct,
            total_max_pct,
            min_cash_pct,
            max_positions,
        )

    async def check(self, portfolio: dict[str, Any]) -> GateResult:
        """포트폴리오 집중도를 점검한다.

        Args:
            portfolio: 현재 포트폴리오 상태.
                필수 키: "total_value", "cash", "positions".

        Returns:
            게이트 실행 결과.
        """
        try:
            total_value = portfolio.get("total_value", 0.0)
            cash = portfolio.get("cash", 0.0)
            positions = portfolio.get("positions", [])

            if total_value <= 0:
                return GateResult(
                    passed=True,
                    action="allow",
                    message="포트폴리오 가치 0, 체크 생략",
                    gate_name="concentration_limiter",
                )

            violations: list[str] = []
            details: dict[str, Any] = {}

            # 1. 동시 보유 종목 수 체크
            position_count = len(positions) if isinstance(positions, list) else len(positions.keys())
            details["position_count"] = position_count
            if position_count > self.max_positions:
                violations.append(
                    f"보유 종목 수 초과: {position_count} > {self.max_positions}"
                )

            # 2. 현금 비율 체크
            cash_pct = (cash / total_value) * 100.0
            details["cash_pct"] = round(cash_pct, 2)
            if cash_pct < self.min_cash_pct:
                violations.append(
                    f"현금 비율 부족: {cash_pct:.1f}% < {self.min_cash_pct:.0f}%"
                )

            # 3. 전체 포지션 비율 체크
            total_position_value = total_value - cash
            total_position_pct = (total_position_value / total_value) * 100.0
            details["total_position_pct"] = round(total_position_pct, 2)
            if total_position_pct > self.total_max_pct:
                violations.append(
                    f"전체 포지션 비율 초과: {total_position_pct:.1f}% > {self.total_max_pct:.0f}%"
                )

            # 4. 단일 종목 비율 체크
            if isinstance(positions, list):
                pos_items = positions
            else:
                pos_items = list(positions.values())

            for pos in pos_items:
                ticker = pos.get("ticker", "unknown")
                market_value = pos.get("market_value", 0.0)
                pos_pct = (market_value / total_value) * 100.0
                if pos_pct > self.single_max_pct:
                    violations.append(
                        f"종목 {ticker} 비중 초과: {pos_pct:.1f}% > {self.single_max_pct:.0f}%"
                    )

            if violations:
                logger.warning(
                    "집중도 한도 위반 %d건: %s",
                    len(violations),
                    "; ".join(violations),
                )
                return GateResult(
                    passed=False,
                    action="block",
                    message=f"집중도 한도 위반 {len(violations)}건: {'; '.join(violations)}",
                    gate_name="concentration_limiter",
                    details=details,
                )

            return GateResult(
                passed=True,
                action="allow",
                message="집중도 한도 정상",
                gate_name="concentration_limiter",
                details=details,
            )
        except Exception as e:
            logger.error("집중도 한도 체크 실패: %s", e)
            return GateResult(
                passed=False,
                action="block",
                message=f"체크 오류: {e}",
                gate_name="concentration_limiter",
            )

    async def check_order(
        self, order: dict[str, Any], portfolio: dict[str, Any]
    ) -> GateResult:
        """신규 주문이 집중도 한도를 위반하는지 사전 검증한다.

        Args:
            order: 주문 정보. 필수 키: "ticker", "quantity", "price".
            portfolio: 현재 포트폴리오 상태.

        Returns:
            주문 검증 결과.
        """
        try:
            total_value = portfolio.get("total_value", 0.0)
            cash = portfolio.get("cash", 0.0)
            positions = portfolio.get("positions", [])

            if total_value <= 0:
                return GateResult(
                    passed=True,
                    action="allow",
                    message="포트폴리오 가치 0, 체크 생략",
                    gate_name="concentration_order_check",
                )

            ticker = order.get("ticker", "")
            order_value = order.get("quantity", 0) * order.get("price", 0.0)

            # 매수 후 현금 비율 체크
            new_cash = cash - order_value
            new_cash_pct = (new_cash / total_value) * 100.0
            if new_cash_pct < self.min_cash_pct:
                return GateResult(
                    passed=False,
                    action="reduce",
                    message=f"주문 실행 시 현금 비율 부족: {new_cash_pct:.1f}% < {self.min_cash_pct:.0f}%",
                    gate_name="concentration_order_check",
                    details={"projected_cash_pct": round(new_cash_pct, 2)},
                )

            # 매수 후 종목 비중 체크
            existing_value = 0.0
            if isinstance(positions, list):
                for pos in positions:
                    if pos.get("ticker") == ticker:
                        existing_value = pos.get("market_value", 0.0)
                        break
            elif isinstance(positions, dict):
                pos = positions.get(ticker, {})
                existing_value = pos.get("market_value", 0.0)

            new_position_pct = ((existing_value + order_value) / total_value) * 100.0
            if new_position_pct > self.single_max_pct:
                return GateResult(
                    passed=False,
                    action="reduce",
                    message=(
                        f"주문 실행 시 종목 {ticker} 비중 초과: "
                        f"{new_position_pct:.1f}% > {self.single_max_pct:.0f}%"
                    ),
                    gate_name="concentration_order_check",
                    details={"projected_position_pct": round(new_position_pct, 2)},
                )

            # 신규 종목이면 보유 종목 수 체크
            position_count = len(positions) if isinstance(positions, list) else len(positions.keys())
            is_new_ticker = existing_value == 0.0
            if is_new_ticker and position_count >= self.max_positions:
                return GateResult(
                    passed=False,
                    action="block",
                    message=f"최대 보유 종목 수 도달: {position_count} >= {self.max_positions}",
                    gate_name="concentration_order_check",
                )

            return GateResult(
                passed=True,
                action="allow",
                message="주문 집중도 검증 통과",
                gate_name="concentration_order_check",
            )
        except Exception as e:
            logger.error("주문 집중도 검증 실패: %s", e)
            return GateResult(
                passed=False,
                action="block",
                message=f"검증 오류: {e}",
                gate_name="concentration_order_check",
            )

    def get_status(self) -> dict[str, Any]:
        """현재 설정을 반환한다."""
        return {
            "single_max_pct": self.single_max_pct,
            "total_max_pct": self.total_max_pct,
            "min_cash_pct": self.min_cash_pct,
            "max_positions": self.max_positions,
        }
