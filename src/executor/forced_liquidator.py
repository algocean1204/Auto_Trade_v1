"""
강제 청산기

보유 기간 초과 포지션을 단계적으로 청산한다.
HOLDING_RULES에 따라:
    - day 0~2: 유지 (0%)
    - day 3  : 50% 부분 청산
    - day 4  : 75% 부분 청산
    - day 5+ : 100% 강제 청산

ForcedLiquidator는 ExitStrategy의 보유기간 규칙과 별도로,
메인 루프에서 독립적으로 호출되어 강제 청산을 보장한다.
ExitStrategy가 놓칠 수 있는 엣지 케이스를 최종 안전망으로 잡아낸다.
"""

from datetime import datetime, timezone
from typing import Any

from src.executor.order_manager import OrderManager
from src.strategy.params import HOLDING_RULES
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 보유일수별 누적 청산 비율 (원래 수량 대비)
_LIQUIDATION_PCT: dict[int, float] = {
    3: 0.50,   # day 3: 50%
    4: 0.75,   # day 4: 75%
    5: 1.00,   # day 5+: 100%
}


class ForcedLiquidator:
    """보유 기간 초과 포지션을 단계적으로 강제 청산한다.

    HOLDING_RULES에 정의된 규칙에 따라 보유 3일차부터
    부분/전량 청산을 실행한다.

    Attributes:
        order_manager: 주문 관리자 인스턴스.
    """

    def __init__(self, order_manager: OrderManager) -> None:
        """ForcedLiquidator를 초기화한다.

        Args:
            order_manager: 주문 관리자 인스턴스.
        """
        self.order_manager = order_manager
        logger.info("ForcedLiquidator 초기화 완료")

    async def check_and_liquidate(
        self, positions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """모든 포지션의 보유 기간을 체크하고 강제 청산을 실행한다.

        각 포지션에 대해:
        1. hold_days 계산 (entry_at 기준)
        2. _LIQUIDATION_PCT에 따라 청산 비율 결정
        3. 이미 부분 청산된 수량 고려하여 실제 청산 수량 계산
        4. OrderManager를 통해 청산 실행

        Args:
            positions: 보유 포지션 리스트.
                각 항목에는 "ticker", "quantity", "entry_at", "trade_id",
                "entry_price", "already_liquidated" 키가 필요하다.
                "already_liquidated": 이미 강제 청산된 누적 수량 (기본 0).

        Returns:
            청산 결과 리스트::

                [
                    {
                        "ticker": str,
                        "hold_days": int,
                        "liquidation_pct": float,
                        "quantity_sold": int,
                        "reason": str,
                        "order_result": dict | None,
                    },
                    ...
                ]
        """
        results: list[dict[str, Any]] = []

        logger.info("강제 청산 체크 시작 | 포지션=%d건", len(positions))

        for position in positions:
            ticker = position.get("ticker", "UNKNOWN")
            quantity = position.get("quantity", 0)
            entry_at = position.get("entry_at")
            trade_id = position.get("trade_id", "")

            if quantity <= 0:
                continue

            # 보유일수 계산
            hold_days = self._calculate_hold_days(entry_at)
            if hold_days < 3:
                logger.debug(
                    "강제 청산 미해당 | ticker=%s | hold_days=%d",
                    ticker, hold_days,
                )
                continue

            # 청산 비율 결정
            liquidation_pct = self._get_liquidation_pct(hold_days)
            if liquidation_pct <= 0:
                continue

            # 실제 청산 수량 계산
            already_sold = position.get("already_liquidated", 0)
            # original_quantity: 진입 시 원래 수량.
            # 현재 quantity + already_sold 가 원래 수량.
            original_quantity = quantity + already_sold
            sell_quantity = self._calculate_liquidation_quantity(
                total_qty=original_quantity,
                pct=liquidation_pct,
                already_sold=already_sold,
            )

            if sell_quantity <= 0:
                logger.debug(
                    "이미 충분히 청산됨 | ticker=%s | hold_days=%d | "
                    "already_sold=%d | target_pct=%.0f%%",
                    ticker, hold_days, already_sold, liquidation_pct * 100,
                )
                continue

            # 현재 보유량을 초과하지 않도록 클램프
            sell_quantity = min(sell_quantity, quantity)

            reason = (
                f"강제 청산: 보유 {hold_days}일차 "
                f"({HOLDING_RULES.get(min(hold_days, 5), HOLDING_RULES[5])}), "
                f"청산 {liquidation_pct:.0%}"
            )

            logger.warning(
                "강제 청산 실행 | ticker=%s | hold_days=%d | "
                "pct=%.0f%% | qty=%d/%d | reason=%s",
                ticker, hold_days, liquidation_pct * 100,
                sell_quantity, quantity, reason,
            )

            # 청산 주문 실행
            exit_signal: dict[str, Any] = {
                "action": "sell",
                "reason": reason,
                "quantity": sell_quantity,
                "urgency": "immediate" if hold_days >= 5 else "normal",
                "trigger": "forced_liquidation",
                "hold_days": hold_days,
                "liquidation_ratio": liquidation_pct,
            }

            order_result = await self.order_manager.execute_exit(
                exit_signal=exit_signal,
                position=position,
            )

            results.append({
                "ticker": ticker,
                "hold_days": hold_days,
                "liquidation_pct": liquidation_pct,
                "quantity_sold": sell_quantity,
                "reason": reason,
                "order_result": order_result,
            })

        logger.info(
            "강제 청산 체크 완료 | 청산 실행=%d건",
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # 보유일수 계산
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_hold_days(entry_at: datetime | str | None) -> int:
        """거래일 기준 보유일수를 계산한다.

        단순 캘린더 일수를 사용한다 (주말/공휴일 미구분).
        정확한 거래일 기준 계산은 MarketHours와 통합하여 확장 가능하다.

        Args:
            entry_at: 진입 시각. None이면 0 반환.

        Returns:
            보유 일수 (정수).
        """
        if entry_at is None:
            return 0

        if isinstance(entry_at, str):
            try:
                entry_at = datetime.fromisoformat(entry_at)
            except (ValueError, TypeError):
                return 0

        now = datetime.now(tz=timezone.utc)

        # naive datetime 처리
        if entry_at.tzinfo is None:
            entry_at = entry_at.replace(tzinfo=timezone.utc)

        delta = now - entry_at
        return max(0, delta.days)

    @staticmethod
    def _get_liquidation_pct(hold_days: int) -> float:
        """보유일수에 따른 누적 청산 비율을 반환한다.

        Args:
            hold_days: 보유 일수.

        Returns:
            누적 청산 비율 (0.0 ~ 1.0).
            - 0~2일: 0.0 (유지)
            - 3일: 0.50 (50%)
            - 4일: 0.75 (75%)
            - 5일+: 1.00 (100%)
        """
        if hold_days < 3:
            return 0.0
        if hold_days >= 5:
            return 1.0
        return _LIQUIDATION_PCT.get(hold_days, 0.0)

    @staticmethod
    def _calculate_liquidation_quantity(
        total_qty: int,
        pct: float,
        already_sold: int,
    ) -> int:
        """실제 청산 수량을 계산한다.

        원래 수량 기준으로 목표 청산 수량을 계산하고,
        이미 부분 청산된 수량을 차감하여 추가 매도 수량을 반환한다.

        예시 (원래 100주):
        - day 3: 목표 50주 - 이미 0주 = 50주 매도
        - day 4: 목표 75주 - 이미 50주 = 25주 매도
        - day 5: 목표 100주 - 이미 75주 = 25주 매도

        Args:
            total_qty: 원래 총 수량 (진입 시 수량).
            pct: 누적 청산 비율 (0.0 ~ 1.0).
            already_sold: 이미 부분 청산된 누적 수량.

        Returns:
            추가 매도 수량 (0 이상 정수).
        """
        if total_qty <= 0 or pct <= 0:
            return 0

        # 100% 청산 시 정확히 전량
        if pct >= 1.0:
            target_sold = total_qty
        else:
            target_sold = int(total_qty * pct)
            # 최소 1주는 매도
            target_sold = max(1, target_sold)

        additional = target_sold - already_sold
        return max(0, additional)
