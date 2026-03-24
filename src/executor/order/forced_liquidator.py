"""ForcedLiquidator (F5.5) -- EOD 또는 긴급 상황에서 전량 청산을 실행한다.

모든 보유 포지션을 순회하며 매도 주문을 제출하고,
성공/실패 결과를 LiquidationResult로 반환한다.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger
from src.common.ticker_registry import get_ticker_registry
from src.executor.order.order_manager import OrderManager
from src.executor.position.position_monitor import PositionMonitor

logger = get_logger(__name__)


class LiquidationResult(BaseModel):
    """청산 결과이다."""

    liquidated: list[str]
    failed: list[str]
    total_value: float = 0.0


async def force_liquidate_all(
    order_manager: OrderManager,
    position_monitor: PositionMonitor,
    reason: str = "EOD",
) -> LiquidationResult:
    """모든 보유 포지션을 강제 청산한다.

    1. 포지션 동기화로 최신 상태를 확보한다.
    2. 각 종목에 대해 전량 매도 주문을 제출한다.
    3. 성공/실패를 분류하여 결과를 반환한다.
    """
    logger.warning("강제 청산 시작: reason=%s", reason)
    await position_monitor.sync_positions()
    positions = position_monitor.get_all_positions()

    if not positions:
        logger.info("청산할 포지션 없음")
        return LiquidationResult(liquidated=[], failed=[])

    liquidated: list[str] = []
    failed: list[str] = []
    total_value = 0.0

    reg = get_ticker_registry()
    for ticker, pos in positions.items():
        exchange = reg.get_exchange_code(ticker) if reg.has_ticker(ticker) else "NAS"
        result = await order_manager.execute_sell(
            ticker=ticker, quantity=pos.quantity, exchange=exchange,
        )
        if result.status == "filled":
            liquidated.append(ticker)
            total_value += pos.current_price * pos.quantity
            logger.info("청산 성공: %s %d주", ticker, pos.quantity)
        else:
            failed.append(ticker)
            logger.error(
                "청산 실패: %s %d주 -> %s", ticker, pos.quantity, result.message,
            )

    # 청산 완료 후 이벤트 발행
    event_bus = get_event_bus()
    await event_bus.publish(
        EventType.EMERGENCY_LIQUIDATION,
        LiquidationResult(
            liquidated=liquidated, failed=failed, total_value=total_value,
        ),
    )

    logger.warning(
        "강제 청산 완료: 성공=%d, 실패=%d, 총액=$%.2f",
        len(liquidated), len(failed), total_value,
    )
    return LiquidationResult(
        liquidated=liquidated, failed=failed, total_value=total_value,
    )


async def force_liquidate_ticker(
    order_manager: OrderManager,
    position_monitor: PositionMonitor,
    ticker: str,
    reason: str = "manual",
) -> LiquidationResult:
    """특정 종목만 강제 청산한다."""
    logger.warning("단일 종목 청산: %s, reason=%s", ticker, reason)
    pos = await position_monitor.get_position(ticker)
    if pos is None:
        logger.info("청산할 포지션 없음: %s", ticker)
        return LiquidationResult(liquidated=[], failed=[])

    reg = get_ticker_registry()
    exchange = reg.get_exchange_code(ticker) if reg.has_ticker(ticker) else "NAS"
    result = await order_manager.execute_sell(
        ticker=ticker, quantity=pos.quantity, exchange=exchange,
    )
    value = pos.current_price * pos.quantity
    if result.status == "filled":
        logger.info("단일 종목 청산 성공: %s %d주 @$%.2f", ticker, pos.quantity, pos.current_price)
        return LiquidationResult(
            liquidated=[ticker], failed=[], total_value=value,
        )
    logger.error(
        "단일 종목 청산 실패: %s %d주 -> %s", ticker, pos.quantity, result.message,
    )
    return LiquidationResult(
        liquidated=[], failed=[ticker], total_value=0.0,
    )
