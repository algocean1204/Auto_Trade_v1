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
        virtual_auth: KisAuth,
        real_auth: KisAuth,
        http: AsyncHttpClient,
    ) -> None:
        """듀얼 인증 + HTTP 클라이언트로 초기화한다."""
        super().__init__(virtual_auth=virtual_auth, real_auth=real_auth)
        self._http = http
        logger.info("BrokerClientImpl 초기화 완료 (KIS API 연결)")

    async def get_price(self, ticker: str, exchange: str = "NAS") -> PriceData:
        """real_auth로 현재가를 조회한다."""
        return await fetch_price(self.real_auth, ticker, exchange, self._http)

    async def get_balance(self) -> BalanceData:
        """virtual_auth로 잔고를 조회한다.

        가상 계좌에서 가용현금이 0이면 매수가능금액 API로 보완한다.
        """
        balance = await fetch_balance(self.virtual_auth, self._http)
        if balance.available_cash <= 0:
            cash = await fetch_buy_power(self.virtual_auth, self._http)
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
        effective_order = order
        if order.order_type == "market" and order.price is None:
            price_data = await self.get_price(order.ticker, order.exchange)
            effective_order = OrderRequest(
                ticker=order.ticker, side=order.side,
                quantity=order.quantity, order_type="market",
                price=price_data.price, exchange=order.exchange,
            )
        return await submit_order(self.virtual_auth, effective_order, self._http)

    async def get_exchange_rate(self) -> float:
        """virtual_auth의 체결기준잔고에서 USD/KRW 환율을 추출한다.

        실전 계좌에 잔고가 없으면 output2 USD 항목이 비어 환율 0이 된다.
        가상 계좌는 항상 잔고가 있으므로 안정적으로 환율을 조회할 수 있다.
        """
        return await fetch_exchange_rate(self.virtual_auth, self._http)

    async def get_daily_candles(
        self, ticker: str, days: int = 30, exchange: str = "NAS",
    ) -> list[OHLCV]:
        """real_auth로 일봉 캔들 데이터를 조회한다."""
        return await fetch_daily_candles(
            self.real_auth, ticker, days, exchange, self._http,
        )

    async def close(self) -> None:
        """클라이언트 종료 시 정리 작업을 수행한다."""
        logger.info("BrokerClientImpl 종료 완료")
