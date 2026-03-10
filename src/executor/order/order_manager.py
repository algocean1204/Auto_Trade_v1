"""OrderManager (F5.3) -- 주문 생성, 검증, 제출을 관리한다.

매수/매도 주문의 라이프사이클을 담당하며, 90000000 에러 방지를 위한
종목 블록 기능과 스나이퍼 엑스큐션(지정가→시장가 전환)을 제공한다.
"""
from __future__ import annotations

import asyncio

from src.common.broker_gateway import (
    BrokerClient,
    OrderRequest,
    OrderResult,
)
from src.common.error_handler import BrokerError
from src.common.event_bus import EventType, get_event_bus
from src.common.logger import get_logger

logger = get_logger(__name__)

# 스나이퍼 엑스큐션: 지정가 미체결 시 시장가 전환 대기 시간(초)
_SNIPER_TIMEOUT_SEC = 3.0
# 시장가 슬리피지 허용 범위 (±0.5%)
_MARKET_SLIPPAGE_PCT = 0.005

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
    유동성 인지 사이징으로 호가 잔량 초과 주문을 방지한다.
    90000000 에러가 발생한 종목은 블록하여 반복 실패를 방지한다.
    """

    def __init__(self, broker: BrokerClient, cache: object | None = None) -> None:
        """BrokerClient와 CacheClient를 주입받아 초기화한다."""
        self._broker = broker
        self._cache = cache
        self._sell_blocked_tickers: set[str] = set()
        logger.info("OrderManager 초기화 완료")

    async def _liquidity_truncate(self, ticker: str, quantity: int) -> int:
        """호가창 유동성을 확인하여 주문 수량을 잔량 이하로 조정한다.

        캐시에서 호가 데이터를 읽어 최우선 5호가 잔량 합을 계산하고,
        주문 수량이 잔량의 80%를 초과하면 잔량의 80%로 절삭한다.
        데이터 부재 시 원래 수량을 그대로 반환한다.
        """
        if self._cache is None:
            return quantity
        try:
            from src.common.cache_gateway import CacheClient
            if not isinstance(self._cache, CacheClient):
                return quantity
            orderbook = await self._cache.read_json(f"ws:orderbook:{ticker}")
            if not orderbook:
                return quantity
            # 매수 시 매도 호가 잔량, 매도 시 매수 호가 잔량을 확인한다
            asks = orderbook.get("asks", [])
            available = sum(int(a.get("volume", 0)) for a in asks[:5])
            if available <= 0:
                return quantity
            max_qty = int(available * 0.8)
            if quantity > max_qty and max_qty >= _MIN_QUANTITY:
                logger.info(
                    "유동성 절삭: %s %d주 → %d주 (호가 잔량 %d)",
                    ticker, quantity, max_qty, available,
                )
                return max_qty
        except Exception as exc:
            logger.debug("유동성 체크 실패 (원래 수량 유지): %s", exc)
        return quantity

    async def execute_buy(
        self, ticker: str, quantity: int, exchange: str = "NAS",
        sniper: bool = True,
    ) -> OrderResult:
        """매수 주문을 실행한다. sniper=True면 스나이퍼 엑스큐션을 사용한다.

        스나이퍼 엑스큐션: 최우선 호가에 지정가 매수 → 3초 미체결 시 시장가 전환.
        """
        # 유동성 인지 사이징: 호가 잔량 초과 시 수량 절삭한다
        quantity = await self._liquidity_truncate(ticker, quantity)
        if sniper:
            return await self._sniper_execute(ticker, "buy", quantity, exchange)
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

    async def _sniper_execute(
        self, ticker: str, side: str, quantity: int, exchange: str,
    ) -> OrderResult:
        """스나이퍼 엑스큐션 -- 최우선 호가 지정가 → 3초 후 시장가 전환한다.

        1단계: 현재가를 조회하여 최우선 호가에 지정가 주문을 제출한다.
        2단계: 3초 대기 후 미체결이면 시장가(±0.5%)로 전환 주문을 제출한다.
        """
        try:
            price_data = await self._broker.get_price(ticker, exchange=exchange)
            best_price = price_data.price
        except BrokerError:
            logger.warning("스나이퍼 가격 조회 실패 → 시장가 폴백: %s", ticker)
            order = build_order_params(ticker, side, quantity, exchange)
            if not validate_order(order):
                return OrderResult(order_id="", status="rejected", message="주문 검증 실패")
            return await self._broker.place_order(order)

        # 1단계: 지정가 주문 (매수=현재가, 매도=현재가)
        limit_order = OrderRequest(
            ticker=ticker.upper(), side=side, quantity=quantity,
            order_type="limit", price=best_price, exchange=exchange,
        )
        if not validate_order(limit_order):
            return OrderResult(order_id="", status="rejected", message="주문 검증 실패")

        try:
            result = await self._broker.place_order(limit_order)
            logger.info(
                "스나이퍼 1단계(지정가): %s %s %d주 @ $%.2f -> %s",
                side, ticker, quantity, best_price, result.status,
            )
            if result.status == "filled":
                return result
        except BrokerError as exc:
            logger.warning("스나이퍼 지정가 실패 → 시장가 전환: %s", exc.message)

        # 2단계: 3초 대기 후 시장가 전환
        await asyncio.sleep(_SNIPER_TIMEOUT_SEC)
        sign = 1 if side == "buy" else -1
        market_price = round(best_price * (1 + sign * _MARKET_SLIPPAGE_PCT), 2)
        market_order = OrderRequest(
            ticker=ticker.upper(), side=side, quantity=quantity,
            order_type="market", price=market_price, exchange=exchange,
        )
        try:
            result = await self._broker.place_order(market_order)
            logger.info(
                "스나이퍼 2단계(시장가): %s %s %d주 @ $%.2f -> %s",
                side, ticker, quantity, market_price, result.status,
            )
            return result
        except BrokerError as exc:
            logger.error("스나이퍼 시장가 실패: %s %d주 -> %s", ticker, quantity, exc.message)
            return OrderResult(order_id="", status="rejected", message=exc.message)

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
