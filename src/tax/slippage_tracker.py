"""SlippageTracker -- 주문 슬리피지를 측정하고 기록한다.

체결 가격과 예상 가격의 차이를 백분율과 금액으로 추적한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.tax.models import SlippageRecord

logger = get_logger(__name__)


def _calc_slippage_pct(expected: float, filled: float) -> float:
    """슬리피지 비율(%)을 계산한다. 매수 시 양수=불리, 매도 시 양수=유리."""
    if expected <= 0:
        return 0.0
    return round(((filled - expected) / expected) * 100, 4)


def _calc_slippage_amount(expected: float, filled: float, qty: int) -> float:
    """슬리피지 금액(USD)을 계산한다."""
    return round((filled - expected) * qty, 4)


class SlippageTracker:
    """슬리피지 측정 관리자이다."""

    def __init__(self) -> None:
        """누적 통계를 초기화한다."""
        self._records: list[SlippageRecord] = []
        logger.info("SlippageTracker 초기화 완료")

    def measure(
        self,
        order_result: dict,
        expected_price: float,
        qty: int = 1,
    ) -> SlippageRecord:
        """체결 결과로부터 슬리피지를 계산한다.

        Args:
            order_result: 주문 체결 결과 (filled_price 키 필수)
            expected_price: 주문 시점 예상 가격
            qty: 주문 수량 (금액 계산용)

        Returns:
            슬리피지 측정 기록
        """
        filled = float(order_result.get("filled_price", expected_price))
        order_id = str(order_result.get("order_id", ""))

        pct = _calc_slippage_pct(expected_price, filled)
        amount = _calc_slippage_amount(expected_price, filled, qty)

        record = SlippageRecord(
            slippage_pct=pct,
            slippage_amount=amount,
            order_id=order_id,
        )
        self._records.append(record)

        if abs(pct) > 0.1:
            logger.warning("슬리피지 주의: %.4f%% ($%.4f) order=%s", pct, amount, order_id)
        else:
            logger.debug("슬리피지: %.4f%% ($%.4f)", pct, amount)

        return record

    def get_average_pct(self) -> float:
        """누적 평균 슬리피지(%)를 반환한다."""
        if not self._records:
            return 0.0
        total = sum(r.slippage_pct for r in self._records)
        return round(total / len(self._records), 4)

    def get_total_amount(self) -> float:
        """누적 슬리피지 금액(USD)을 반환한다."""
        return round(sum(r.slippage_amount for r in self._records), 4)

    def reset(self) -> None:
        """일일 통계를 초기화한다. EOD에서 호출한다."""
        self._records.clear()
        logger.info("SlippageTracker 일일 통계 초기화")
