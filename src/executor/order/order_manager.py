"""OrderManager (F5.3) -- 주문 생성, 검증, 제출을 관리한다.

매수/매도 주문의 라이프사이클을 담당하며, 90000000 에러 방지를 위한
종목 블록 기능과 스나이퍼 엑스큐션(지정가→시장가 전환)을 제공한다.
슬리피지 측정: 체결 후 expected_price 대비 실제 주문가의 차이를 기록한다.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone

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
    if order.quantity <= 0 or order.quantity > _MAX_QUANTITY:
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
    KIS 모의투자 장종료(40580000) 감지 시 모든 주문을 차단한다.
    """

    def __init__(
        self,
        broker: BrokerClient,
        cache: object | None = None,
        slippage_tracker: object | None = None,
    ) -> None:
        """BrokerClient, CacheClient, SlippageTracker를 주입받아 초기화한다."""
        self._broker = broker
        self._cache = cache
        self._slippage_tracker = slippage_tracker
        self._sell_blocked_tickers: set[str] = set()
        self._market_closed: bool = False
        self._market_closed_at: datetime | None = None
        # 스나이퍼 엑스큐션에서 마지막 체결 주문 단가를 기록한다 (슬리피지 측정용)
        self._last_order_price: float = 0.0
        logger.info("OrderManager 초기화 완료")

    @property
    def is_market_closed(self) -> bool:
        """KIS 모의투자 장종료 상태인지 반환한다."""
        return self._market_closed

    def _check_market_closed(self, exc: BrokerError) -> None:
        """KIS 에러에서 모의투자 장종료(40580000)를 감지한다."""
        detail = str(exc.detail or "")
        if "40580000" in detail or "장종료" in detail:
            if not self._market_closed:
                self._market_closed = True
                self._market_closed_at = datetime.now(tz=timezone.utc)
                logger.warning("KIS 모의투자 장종료 감지 — 이후 모든 주문 차단")

    def _auto_reset_market_closed(self) -> None:
        """장종료 상태를 10분 후 자동 해제한다."""
        if self._market_closed and self._market_closed_at is not None:
            age = (datetime.now(tz=timezone.utc) - self._market_closed_at).total_seconds()
            if age > 600:  # 10분
                self._market_closed = False
                self._market_closed_at = None
                logger.info("장종료 상태 자동 해제 (%.0f초 경과)", age)

    async def _check_idempotency(self, ticker: str, side: str, quantity: int) -> OrderResult | None:
        """중복 주문을 방지하기 위해 멱등성 키를 검사한다.

        5초 윈도우 내 동일 종목/방향/수량 주문이 이미 접수되었으면
        중복으로 판단하여 OrderResult(rejected)를 반환한다.
        """
        if self._cache is None:
            return None
        try:
            from src.common.cache_gateway import CacheClient
            if not isinstance(self._cache, CacheClient):
                return None
            idem_key = f"idem:{ticker}:{side}:{quantity}:{int(time.time() // 5)}"
            existing = await self._cache.read(idem_key)
            if existing:
                logger.warning("중복 주문 감지 (스킵): %s", idem_key)
                return OrderResult(order_id="", status="rejected", message="중복 주문 방지")
        except Exception as exc:
            logger.debug("멱등성 검사 실패 (통과 처리): %s", exc)
        return None

    async def _mark_idempotency(self, ticker: str, side: str, quantity: int) -> None:
        """주문 체결 후 멱등성 키를 기록한다 (30초 TTL)."""
        if self._cache is None:
            return
        try:
            from src.common.cache_gateway import CacheClient
            if not isinstance(self._cache, CacheClient):
                return
            idem_key = f"idem:{ticker}:{side}:{quantity}:{int(time.time() // 5)}"
            await self._cache.write(idem_key, "1", ttl=30)
        except Exception as exc:
            logger.debug("멱등성 기록 실패 (무시): %s", exc)

    async def _record_slippage(
        self,
        ticker: str,
        side: str,
        expected_price: float,
        order_price: float,
        quantity: int,
    ) -> None:
        """체결 슬리피지를 캐시(slippage:raw)에 기록한다.

        expected_price: 매매 판단 시점의 현재가이다.
        order_price: 실제 브로커에 제출된 주문 단가이다.
        slippage_bps: (order_price - expected_price) / expected_price * 10000 이다.
        """
        if expected_price <= 0:
            return
        slippage_bps = round(
            (order_price - expected_price) / expected_price * 10000, 2,
        )
        now_iso = datetime.now(tz=timezone.utc).isoformat()
        record = {
            "ticker": ticker,
            "side": side,
            "expected_price": expected_price,
            "actual_price": order_price,
            "slippage_bps": slippage_bps,
            "quantity": quantity,
            "timestamp": now_iso,
        }
        # SlippageTracker 인메모리 기록 (슬리피지 엔드포인트 직접 조회용)
        if self._slippage_tracker is not None:
            try:
                self._slippage_tracker.measure(  # type: ignore[union-attr]
                    {"filled_price": order_price, "order_id": ""},
                    expected_price,
                    quantity,
                )
            except Exception as exc:
                logger.debug("SlippageTracker.measure 실패 (무시): %s", exc)
        # 캐시에 원시 슬리피지 데이터를 누적한다 (EOD 집계용)
        if self._cache is not None:
            try:
                from src.common.cache_gateway import CacheClient
                if isinstance(self._cache, CacheClient):
                    await self._cache.atomic_list_append(
                        "slippage:raw", [record], max_size=500, ttl=86400,
                    )
            except Exception as exc:
                logger.debug("슬리피지 캐시 기록 실패 (무시): %s", exc)
        logger.debug(
            "슬리피지 기록: %s %s %.2fbps (예상=$%.2f, 실제=$%.2f)",
            side, ticker, slippage_bps, expected_price, order_price,
        )

    async def _liquidity_truncate(self, ticker: str, quantity: int, side: str = "buy") -> int:
        """호가창 유동성을 확인하여 주문 수량을 잔량 이하로 조정한다.

        매수 시 매도호가(asks) 잔량, 매도 시 매수호가(bids) 잔량을 확인한다.
        주문 수량이 잔량의 80%를 초과하면 잔량의 80%로 절삭한다.
        데이터 부재 시 원래 수량을 그대로 반환한다.
        """
        if self._cache is None:
            return quantity
        try:
            from src.common.cache_gateway import CacheClient
            if not isinstance(self._cache, CacheClient):
                return quantity
            # 실제 호가 데이터는 order_flow:raw:{ticker} 키에 저장된다
            orderbook = await self._cache.read_json(f"order_flow:raw:{ticker}")
            if not orderbook:
                return quantity
            # 매수: 매도호가(asks) 잔량 확인, 매도: 매수호가(bids) 잔량 확인
            if side == "buy":
                entries = orderbook.get("asks", [])
            else:
                entries = orderbook.get("bids", [])
            available = sum(int(e.get("volume", 0)) for e in entries[:5])
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
        sniper: bool = True, expected_price: float = 0.0,
    ) -> OrderResult:
        """매수 주문을 실행한다. sniper=True면 스나이퍼 엑스큐션을 사용한다.

        expected_price: 매매 판단 시점의 현재가이다 (슬리피지 측정용).
        스나이퍼 엑스큐션: 최우선 호가에 지정가 매수 → 3초 미체결 시 시장가 전환.
        """
        self._auto_reset_market_closed()
        if self._market_closed:
            return OrderResult(
                order_id="", status="rejected",
                message="KIS 모의투자 장종료 — 매수 차단",
            )
        # M-8: 중복 주문 방지 — 5초 윈도우 내 동일 주문 차단
        dup = await self._check_idempotency(ticker, "buy", quantity)
        if dup is not None:
            return dup
        # 유동성 인지 사이징: 매수 시 매도호가(asks) 잔량 기준으로 수량 절삭한다
        quantity = await self._liquidity_truncate(ticker, quantity, side="buy")
        if sniper:
            result = await self._sniper_execute(ticker, "buy", quantity, exchange)
            if result.status == "filled":
                await self._mark_idempotency(ticker, "buy", quantity)
                if expected_price > 0:
                    await self._record_slippage(
                        ticker, "buy", expected_price,
                        self._last_order_price, quantity,
                    )
            return result
        order = build_order_params(ticker, "buy", quantity, exchange)
        if not validate_order(order):
            return OrderResult(
                order_id="", status="rejected", message="주문 검증 실패",
            )
        try:
            result = await self._broker.place_order(order)
            logger.info("매수 완료: %s %d주 -> %s", ticker, quantity, result.status)
            if result.status == "filled":
                await self._mark_idempotency(ticker, "buy", quantity)
                if expected_price > 0:
                    await self._record_slippage(
                        ticker, "buy", expected_price,
                        expected_price, quantity,
                    )
            return result
        except BrokerError as exc:
            self._check_market_closed(exc)
            logger.error("매수 실패: %s %d주 -> %s", ticker, quantity, exc.message)
            return OrderResult(
                order_id="", status="rejected", message=exc.message,
            )

    async def execute_sell(
        self, ticker: str, quantity: int, exchange: str = "NAS",
        expected_price: float = 0.0,
    ) -> OrderResult:
        """매도 주문을 실행한다.

        expected_price: 매매 판단 시점의 현재가이다 (슬리피지 측정용).
        블록된 종목은 스킵하여 90000000 에러 반복을 방지한다.
        KIS 장종료 감지 시 모든 매도를 차단한다.
        """
        self._auto_reset_market_closed()
        if self._market_closed:
            return OrderResult(
                order_id="", status="rejected",
                message="KIS 모의투자 장종료 — 매도 차단",
            )
        if ticker in self._sell_blocked_tickers:
            logger.warning("매도 블록된 종목 스킵: %s", ticker)
            return OrderResult(
                order_id="", status="rejected",
                message=f"{ticker} 매도 블록됨 (90000000 에러 방지)",
            )
        # M-8: 중복 주문 방지 — 5초 윈도우 내 동일 주문 차단
        dup = await self._check_idempotency(ticker, "sell", quantity)
        if dup is not None:
            return dup
        order = build_order_params(ticker, "sell", quantity, exchange)
        if not validate_order(order):
            return OrderResult(
                order_id="", status="rejected", message="주문 검증 실패",
            )
        try:
            result = await self._broker.place_order(order)
            logger.info("매도 완료: %s %d주 -> %s", ticker, quantity, result.status)
            if result.status == "filled":
                await self._mark_idempotency(ticker, "sell", quantity)
                if expected_price > 0:
                    await self._record_slippage(
                        ticker, "sell", expected_price,
                        expected_price, quantity,
                    )
            return result
        except BrokerError as exc:
            self._check_market_closed(exc)
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
        _last_order_price에 최종 체결 주문 단가를 기록한다 (슬리피지 측정용).
        """
        try:
            price_data = await self._broker.get_price(ticker, exchange=exchange)
            best_price = price_data.price
        except BrokerError as exc:
            self._check_market_closed(exc)
            logger.warning("스나이퍼 가격 조회 실패 → 시장가 폴백: %s", ticker)
            order = build_order_params(ticker, side, quantity, exchange)
            if not validate_order(order):
                return OrderResult(order_id="", status="rejected", message="주문 검증 실패")
            self._last_order_price = 0.0
            return await self._broker.place_order(order)

        # 1단계: 지정가 주문 (매수=현재가, 매도=현재가)
        limit_order = OrderRequest(
            ticker=ticker.upper(), side=side, quantity=quantity,
            order_type="limit", price=best_price, exchange=exchange,
        )
        if not validate_order(limit_order):
            return OrderResult(order_id="", status="rejected", message="주문 검증 실패")

        limit_result: OrderResult | None = None
        try:
            limit_result = await self._broker.place_order(limit_order)
            logger.info(
                "스나이퍼 1단계(지정가): %s %s %d주 @ $%.2f -> %s",
                side, ticker, quantity, best_price, limit_result.status,
            )
            if limit_result.status == "filled":
                self._last_order_price = best_price
                return limit_result
        except BrokerError as exc:
            self._check_market_closed(exc)
            logger.warning("스나이퍼 지정가 실패 → 시장가 전환: %s", exc.message)

        # 2단계: 3초 대기 후 미체결 지정가 취소 → 시장가 전환
        await asyncio.sleep(_SNIPER_TIMEOUT_SEC)

        # 지정가 주문이 아직 미체결일 수 있으므로 취소를 시도한다.
        # 취소하지 않으면 지정가+시장가 이중 체결(double-fill) 위험이 있다.
        limit_order_id = limit_result.order_id if limit_result else ""
        if limit_order_id:
            try:
                await self._broker.cancel_order(limit_order_id, exchange=exchange)
                logger.info("스나이퍼 지정가 취소 완료: %s", limit_order_id)
            except Exception as cancel_exc:
                # 취소 실패 시 시장가 전환을 건너뛰어 이중 체결을 방지한다
                logger.warning(
                    "지정가 취소 실패 — 시장가 전환 건너뜀 (이중체결 방지): %s",
                    cancel_exc,
                )
                return limit_result if limit_result else OrderResult(
                    order_id="", status="rejected", message="지정가 취소 실패",
                )

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
            if result.status == "filled":
                self._last_order_price = market_price
            return result
        except BrokerError as exc:
            self._check_market_closed(exc)
            logger.error("스나이퍼 시장가 실패: %s %d주 -> %s", ticker, quantity, exc.message)
            return OrderResult(order_id="", status="rejected", message=exc.message)

    def set_slippage_tracker(self, tracker: object) -> None:
        """슬리피지 트래커를 후속 주입한다. DI에서 호출된다."""
        self._slippage_tracker = tracker
        logger.info("OrderManager에 SlippageTracker 주입 완료")

    def block_ticker(self, ticker: str) -> None:
        """매도 실패 종목을 블록한다 (90000000 에러 방지)."""
        self._sell_blocked_tickers.add(ticker)
        logger.warning("매도 블록 등록: %s", ticker)

    def reset_blocked(self) -> None:
        """블록 목록을 초기화한다 (EOD 리셋)."""
        count = len(self._sell_blocked_tickers)
        self._sell_blocked_tickers.clear()
        logger.info("매도 블록 초기화: %d개 종목 해제", count)

    def reset_market_closed(self) -> None:
        """장종료 상태를 초기화한다 (EOD 리셋)."""
        if self._market_closed:
            self._market_closed = False
            self._market_closed_at = None
            logger.info("장종료 상태 초기화")

    def is_blocked(self, ticker: str) -> bool:
        """해당 종목이 매도 블록 상태인지 확인한다."""
        return ticker in self._sell_blocked_tickers

    def get_blocked_tickers(self) -> set[str]:
        """현재 블록된 종목 목록을 반환한다."""
        return set(self._sell_blocked_tickers)
