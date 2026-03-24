"""BrokerClientImpl (F5.2) -- BrokerClient 인터페이스의 KIS API 구현체이다.

KIS API 함수를 호출하여 시세/잔고/주문/환율/일봉 기능을 제공한다.
시세는 real_auth, 거래는 virtual_auth를 사용한다.
"""
from __future__ import annotations

from src.common.broker_gateway import (
    BalanceData,
    BrokerClient,
    KisAuth,
    OHLCV,
    OrderRequest,
    OrderResult,
    PriceData,
)
from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.executor.broker.kis_api import (
    CancelResult,
    cancel_order as kis_cancel_order,
    fetch_balance,
    fetch_buy_power,
    fetch_daily_candles,
    fetch_exchange_rate,
    fetch_price,
    submit_order,
)

logger = get_logger(__name__)


class BrokerClientImpl(BrokerClient):
    """KIS API 기반 BrokerClient 구현체이다.

    virtual_auth로 거래, real_auth로 시세를 조회한다.
    AsyncHttpClient를 주입받아 HTTP 통신을 수행한다.
    """

    def __init__(
        self,
        virtual_auth: KisAuth | None,
        real_auth: KisAuth | None,
        http: AsyncHttpClient,
    ) -> None:
        """듀얼 인증 + HTTP 클라이언트로 초기화한다.

        가상/실전 인증 중 하나만 있어도 동작한다.
        누락된 쪽의 기능 호출 시 BrokerError를 발생시킨다.
        """
        super().__init__(virtual_auth=virtual_auth, real_auth=real_auth)
        self._http = http
        logger.info("BrokerClientImpl 초기화 완료 (KIS API 연결)")

    def _require_real_auth(self) -> KisAuth:
        """실전 인증을 요구한다. 없으면 가상 인증으로 폴백한다."""
        if self.real_auth is not None:
            return self.real_auth
        if self.virtual_auth is not None:
            logger.debug("real_auth 미설정 — virtual_auth로 폴백")
            return self.virtual_auth
        from src.common.error_handler import BrokerError
        raise BrokerError(message="KIS 인증 없음", detail="real_auth와 virtual_auth 모두 미설정")

    def _require_virtual_auth(self) -> KisAuth:
        """가상 인증을 요구한다. 없으면 실전 인증으로 폴백한다."""
        if self.virtual_auth is not None:
            return self.virtual_auth
        if self.real_auth is not None:
            logger.debug("virtual_auth 미설정 — real_auth로 폴백")
            return self.real_auth
        from src.common.error_handler import BrokerError
        raise BrokerError(message="KIS 인증 없음", detail="virtual_auth와 real_auth 모두 미설정")

    async def get_price(self, ticker: str, exchange: str = "NAS") -> PriceData:
        """real_auth로 현재가를 조회한다. 없으면 virtual_auth로 폴백한다."""
        auth = self._require_real_auth()
        return await fetch_price(auth, ticker, exchange, self._http)

    async def get_balance(self) -> BalanceData:
        """virtual_auth로 잔고를 조회한다.

        가상 계좌에서 가용현금이 0이면 매수가능금액 API로 보완한다.
        """
        auth = self._require_virtual_auth()
        balance = await fetch_balance(auth, self._http)
        if balance.available_cash <= 0:
            cash = await fetch_buy_power(auth, self._http)
            balance = BalanceData(
                total_equity=balance.total_equity,
                available_cash=cash,
                positions=balance.positions,
            )
        return balance

    async def place_order(self, order: OrderRequest) -> OrderResult:
        """virtual_auth로 주문을 제출한다.

        시장가 주문 시 현재가를 먼저 조회하여 지정가로 자동 변환한다.
        """
        auth = self._require_virtual_auth()
        effective_order = order
        if order.order_type == "market" and order.price is None:
            price_data = await self.get_price(order.ticker, order.exchange)
            effective_order = OrderRequest(
                ticker=order.ticker, side=order.side,
                quantity=order.quantity, order_type="market",
                price=price_data.price, exchange=order.exchange,
            )
        return await submit_order(auth, effective_order, self._http)

    async def cancel_order(self, order_id: str, exchange: str = "NAS") -> CancelResult:
        """virtual_auth로 미체결 주문을 취소한다.

        CancelResult를 반환하여 부분 체결 정보를 확인할 수 있다.
        """
        auth = self._require_virtual_auth()
        return await kis_cancel_order(auth, order_id, exchange, self._http)

    async def get_exchange_rate(self) -> float:
        """virtual_auth의 체결기준잔고에서 USD/KRW 환율을 추출한다.

        실전 계좌에 잔고가 없으면 output2 USD 항목이 비어 환율 0이 된다.
        가상 계좌는 항상 잔고가 있으므로 안정적으로 환율을 조회할 수 있다.
        """
        auth = self._require_virtual_auth()
        return await fetch_exchange_rate(auth, self._http)

    async def get_daily_candles(
        self, ticker: str, days: int = 30, exchange: str = "NAS",
    ) -> list[OHLCV]:
        """real_auth로 일봉 캔들 데이터를 조회한다. 없으면 virtual_auth로 폴백한다."""
        auth = self._require_real_auth()
        return await fetch_daily_candles(
            auth, ticker, days, exchange, self._http,
        )

    async def close(self) -> None:
        """클라이언트 종료 시 정리 작업을 수행한다."""
        logger.info("BrokerClientImpl 종료 완료")
