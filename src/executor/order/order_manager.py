"""OrderManager (F5.3) -- 주문 생성, 검증, 제출을 관리한다.

매수/매도 주문의 라이프사이클을 담당하며, 90000000 에러 방지를 위한
종목 블록 기능을 제공한다.
"""
from __future__ import annotations

from src.common.broker_gateway import (
    BrokerClient,
    OrderRequest,
    OrderResult,
)
from src.common.error_handler import BrokerError
from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger

logger = get_logger(__name__)

# 주문 수량 제한
_MAX_QUANTITY = 9999
_MIN_QUANTITY = 1

# 허용 거래소 코드
_VALID_EXCHANGES: set[str] = {"NAS", "AMS", "NYS"}


def build_order_params(
    ticker: str, side: str, quantity: int, exchange: str,
) -> OrderRequest:
    """원시 파라미터로부터 OrderRequest를 생성한다."""
    return OrderRequest(
        ticker=ticker.upper(),
        side=side,
        quantity=quantity,
        order_type="market",
        price=None,
        exchange=exchange,
    )


def validate_order(order: OrderRequest) -> bool:
    """주문 요청의 유효성을 검사한다. 유효하면 True를 반환한다."""
    if not order.ticker or len(order.ticker) > 10:
        logger.warning("유효하지 않은 티커: %s", order.ticker)
        return False
    if order.quantity < _MIN_QUANTITY or order.quantity > _MAX_QUANTITY:
        logger.warning("유효하지 않은 수량: %d", order.quantity)
        return False
    if order.exchange not in _VALID_EXCHANGES:
        logger.warning("유효하지 않은 거래소: %s", order.exchange)
        return False
    if order.side not in ("buy", "sell"):
        logger.warning("유효하지 않은 주문 방향: %s", order.side)
        return False
    return True


class OrderManager:
    """주문 관리자이다.

    매수/매도 주문의 생성, 검증, 제출을 통합 관리한다.
    90000000 에러가 발생한 종목은 블록하여 반복 실패를 방지한다.
    """

    def __init__(self, broker: BrokerClient) -> None:
        """BrokerClient를 주입받아 초기화한다."""
        self._broker = broker
        self._sell_blocked_tickers: set[str] = set()
        logger.info("OrderManager 초기화 완료")

    async def execute_buy(
        self, ticker: str, quantity: int, exchange: str = "NAS",
    ) -> OrderResult:
        """매수 주문을 실행한다.

        OrderRequest를 생성하고 검증한 뒤 브로커에 제출한다.
        """
        order = build_order_params(ticker, "buy", quantity, exchange)
        if not validate_order(order):
            return OrderResult(
                order_id="", status="rejected", message="주문 검증 실패",
            )
        try:
            result = await self._broker.place_order(order)
            logger.info("매수 완료: %s %d주 -> %s", ticker, quantity, result.status)
            return result
        except BrokerError as exc:
            logger.error("매수 실패: %s %d주 -> %s", ticker, quantity, exc.message)
            return OrderResult(
                order_id="", status="rejected", message=exc.message,
            )

    async def execute_sell(
        self, ticker: str, quantity: int, exchange: str = "NAS",
    ) -> OrderResult:
        """매도 주문을 실행한다.

        블록된 종목은 스킵하여 90000000 에러 반복을 방지한다.
        """
        if ticker in self._sell_blocked_tickers:
            logger.warning("매도 블록된 종목 스킵: %s", ticker)
            return OrderResult(
                order_id="", status="rejected",
                message=f"{ticker} 매도 블록됨 (90000000 에러 방지)",
            )
        order = build_order_params(ticker, "sell", quantity, exchange)
        if not validate_order(order):
            return OrderResult(
                order_id="", status="rejected", message="주문 검증 실패",
            )
        try:
            result = await self._broker.place_order(order)
            logger.info("매도 완료: %s %d주 -> %s", ticker, quantity, result.status)
            return result
        except BrokerError as exc:
            # 90000000 에러 시 종목을 블록한다
            if "90000000" in str(exc.detail or ""):
                self.block_ticker(ticker)
            logger.error("매도 실패: %s %d주 -> %s", ticker, quantity, exc.message)
            return OrderResult(
                order_id="", status="rejected", message=exc.message,
            )

    def block_ticker(self, ticker: str) -> None:
        """매도 실패 종목을 블록한다 (90000000 에러 방지)."""
        self._sell_blocked_tickers.add(ticker)
        logger.warning("매도 블록 등록: %s", ticker)

    def reset_blocked(self) -> None:
        """블록 목록을 초기화한다 (EOD 리셋)."""
        count = len(self._sell_blocked_tickers)
        self._sell_blocked_tickers.clear()
        logger.info("매도 블록 초기화: %d개 종목 해제", count)

    def is_blocked(self, ticker: str) -> bool:
        """해당 종목이 매도 블록 상태인지 확인한다."""
        return ticker in self._sell_blocked_tickers

    def get_blocked_tickers(self) -> set[str]:
        """현재 블록된 종목 목록을 반환한다."""
        return set(self._sell_blocked_tickers)
