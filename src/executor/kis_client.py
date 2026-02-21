"""
KIS OpenAPI 클라이언트 (해외주식 전용)

한국투자증권 OpenAPI를 통해 해외주식 시세 조회, 주문 실행,
잔고 조회, 체결 내역 조회 등의 기능을 제공한다.

Exchange 코드:
- "NASD": 나스닥
- "NYSE": 뉴욕증권거래소
- "AMEX": 아멕스

시세 조회용 exchange 코드:
- "NAS": 나스닥
- "NYS": 뉴욕증권거래소
- "AMS": 아멕스
"""

import asyncio
import time
from datetime import datetime, timedelta

import httpx

from src.executor.kis_auth import KISAuth, KISAuthError
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------
# 모듈 수준 상수
# ------------------------------------------------------------------

# KIS API HTTP 요청 타임아웃 (초)
_KIS_API_TIMEOUT_SECONDS: float = 30.0

# 주문 exchange 코드 → 시세 조회 exchange 코드 변환 맵
# place_order의 exchange 파라미터는 거래소 전체 코드를 사용하지만,
# 시세 조회(get_overseas_price)는 단축 코드를 사용한다.
_EXCHANGE_CODE_MAP: dict[str, str] = {"NASD": "NAS", "NYSE": "NYS", "AMEX": "AMS"}

# 모의투자 지정가 전환 시 매수 마크업 배율 (+0.5%)
_VIRTUAL_BUY_MARKUP: float = 1.005

# 모의투자 지정가 전환 시 매도 할인 배율 (-0.5%)
_VIRTUAL_SELL_DISCOUNT: float = 0.995

# 잔고 조회 대상 해외 거래소 코드 목록
_OVERSEAS_EXCHANGES: list[str] = ["NASD", "NYSE", "AMEX"]


class KISAPIError(Exception):
    """KIS API 호출 실패 예외.

    Attributes:
        message: 에러 메시지.
        rt_cd: KIS 응답 코드 (성공="0").
        msg_cd: KIS 메시지 코드.
        msg: KIS 상세 메시지.
    """

    def __init__(
        self,
        message: str,
        rt_cd: str | None = None,
        msg_cd: str | None = None,
        msg: str | None = None,
    ) -> None:
        super().__init__(message)
        self.rt_cd = rt_cd
        self.msg_cd = msg_cd
        self.msg = msg


class KISOrderError(KISAPIError):
    """주문 관련 API 에러 (매수/매도/취소)."""


class KISClient:
    """한국투자증권 해외주식 API 클라이언트.

    KISAuth를 통해 인증을 처리하고, 해외주식 시세 조회/주문/잔고 조회 등
    주요 API를 래핑하여 제공한다. 모든 메서드는 async로 동작한다.

    재시도 로직: 일시적 오류(5xx, 네트워크 에러)에 대해 최대 3회,
    exponential backoff(1s, 2s, 4s)로 재시도한다.
    """

    # 재시도 설정
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0  # seconds

    # 잔고 캐시 TTL (초)
    _BALANCE_CACHE_TTL: float = 30.0

    # tr_id 매핑: (실전, 모의)
    # 시세 조회 API는 실전/모의 동일한 TR_ID를 사용한다 (V prefix 없음).
    # 거래 API만 모의투자용 V prefix TR_ID를 사용한다.
    _TR_IDS: dict[str, tuple[str, str]] = {
        # 시세 조회 (실전/모의 동일)
        "overseas_price": ("HHDFS00000300", "HHDFS00000300"),
        "overseas_daily_price": ("HHDFS76240000", "HHDFS76240000"),
        "overseas_stock_info": ("CTPF1702R", "CTPF1702R"),
        "exchange_rate": ("CTRP6504R", "CTRP6504R"),
        # 거래 (모의투자는 V prefix)
        "overseas_buy": ("JTTT1002U", "VTTT1002U"),
        "overseas_sell": ("JTTT1006U", "VTTT1006U"),
        "overseas_cancel": ("JTTT1004U", "VTTT1004U"),
        "overseas_balance": ("JTTT3012R", "VTTT3012R"),
        "overseas_order_history": ("JTTT3001R", "VTTT3001R"),
    }

    # 시세 조회는 항상 실전 URL을 사용해야 한다 (모의 서버에 시세 API가 없음).
    _PRICE_API_PATHS: frozenset[str] = frozenset({
        "/uapi/overseas-price/v1/quotations/price",
        "/uapi/overseas-price/v1/quotations/dailyprice",
        "/uapi/overseas-price/v1/quotations/search-info",
        "/uapi/overseas-stock/v1/trading/inquire-present-balance",  # 환율 조회 (real server only)
    })

    def __init__(self, auth: KISAuth, real_auth: KISAuth | None = None) -> None:
        """KISClient를 초기화한다.

        Args:
            auth: 인증 관리 인스턴스 (거래용, 모의/실전에 따라 다름).
            real_auth: 실전 인증 인스턴스 (시세 조회 전용). None이면 auth를 공용으로 사용.
                모의투자 모드에서는 시세 조회를 위해 별도 실전 인증이 필요하다.
        """
        self.auth = auth
        self._real_auth = real_auth
        self.client = httpx.AsyncClient(timeout=_KIS_API_TIMEOUT_SECONDS)
        # get_balance() 결과 캐시 (_BALANCE_CACHE_TTL 초 TTL, 동시 호출 방지 Lock 포함)
        self._balance_cache: dict | None = None
        self._balance_cache_ts: float = 0.0
        self._balance_lock = asyncio.Lock()
        logger.info("KISClient initialized (virtual=%s, separate_price_auth=%s)",
                     auth.virtual, real_auth is not None)

    async def close(self) -> None:
        """HTTP 클라이언트를 종료한다."""
        await self.client.aclose()
        logger.info("KISClient HTTP client closed")

    def clear_balance_cache(self) -> None:
        """잔고 캐시를 강제 무효화한다.

        배포 후 즉시 최신 잔고를 조회해야 할 때 사용한다.
        다음 get_balance() 호출 시 KIS API에서 새로 조회한다.
        """
        self._balance_cache = None
        self._balance_cache_ts = 0.0
        logger.info("Balance cache cleared (force refresh on next get_balance())")

    # ------------------------------------------------------------------
    # 시세 조회
    # ------------------------------------------------------------------

    async def get_overseas_price(
        self, ticker: str, exchange: str = "NAS"
    ) -> dict:
        """해외주식 현재가를 조회한다.

        Args:
            ticker: 종목 심볼 (예: "AAPL", "TSLA").
            exchange: 거래소 코드 ("NAS", "NYS", "AMS").

        Returns:
            현재가 정보 딕셔너리::

                {
                    "ticker": str,
                    "current_price": float,
                    "open_price": float,
                    "high_price": float,
                    "low_price": float,
                    "prev_close": float,
                    "volume": int,
                    "change_pct": float,
                    "trade_time": str,
                }

        Raises:
            KISAPIError: API 호출 실패.
        """
        tr_id = self._get_tr_id("overseas_price")
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": ticker,
        }

        data = await self._request(
            method="GET",
            path="/uapi/overseas-price/v1/quotations/price",
            tr_id=tr_id,
            params=params,
        )

        output = data.get("output", {})
        return {
            "ticker": ticker,
            "current_price": self._safe_float(output.get("last", "0")),
            "open_price": self._safe_float(output.get("open", "0")),
            "high_price": self._safe_float(output.get("high", "0")),
            "low_price": self._safe_float(output.get("low", "0")),
            "prev_close": self._safe_float(output.get("base", "0")),
            "volume": self._safe_int(output.get("tvol", "0")),
            "change_pct": self._safe_float(output.get("rate", "0")),
            "trade_time": output.get("ordy", ""),
        }

    async def get_overseas_daily_price(
        self,
        ticker: str,
        exchange: str = "NAS",
        period: str = "D",
        count: int = 30,
    ) -> list[dict]:
        """해외주식 일별 시세를 조회한다.

        기술적 지표 계산에 사용되는 일봉 데이터를 반환한다.

        Args:
            ticker: 종목 심볼.
            exchange: 거래소 코드.
            period: 기간 구분 ("D"=일, "W"=주, "M"=월).
            count: 조회 건수 (최대 100).

        Returns:
            일별 시세 리스트 (최신순)::

                [
                    {
                        "date": str,  # "YYYYMMDD"
                        "open": float,
                        "high": float,
                        "low": float,
                        "close": float,
                        "volume": int,
                    },
                    ...
                ]

        Raises:
            KISAPIError: API 호출 실패.
        """
        tr_id = self._get_tr_id("overseas_daily_price")
        today = datetime.now().strftime("%Y%m%d")
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": ticker,
            "GUBN": period,
            "BYMD": today,
            "MODP": "1",  # 수정주가 반영
        }

        data = await self._request(
            method="GET",
            path="/uapi/overseas-price/v1/quotations/dailyprice",
            tr_id=tr_id,
            params=params,
        )

        output2 = data.get("output2", [])
        results: list[dict] = []
        for item in output2[:count]:
            if not item.get("xymd"):
                continue
            results.append({
                "date": item["xymd"],
                "open": self._safe_float(item.get("open", "0")),
                "high": self._safe_float(item.get("high", "0")),
                "low": self._safe_float(item.get("low", "0")),
                "close": self._safe_float(item.get("clos", "0")),
                "volume": self._safe_int(item.get("tvol", "0")),
            })

        logger.info(
            "Daily price fetched: %s, %d candles", ticker, len(results)
        )
        return results

    # ------------------------------------------------------------------
    # 주문
    # ------------------------------------------------------------------

    async def place_order(
        self,
        ticker: str,
        order_type: str,
        side: str,
        quantity: int,
        price: float | None = None,
        exchange: str = "NASD",
    ) -> dict:
        """해외주식 주문을 실행한다.

        Args:
            ticker: 종목 심볼.
            order_type: "00"(지정가), "01"(시장가).
            side: "buy" 또는 "sell".
            quantity: 주문 수량.
            price: 주문 가격 (지정가 시 필수, 시장가 시 무시).
            exchange: 거래소 코드 ("NASD", "NYSE", "AMEX").

        Returns:
            주문 결과::

                {
                    "order_id": str,
                    "ticker": str,
                    "side": str,
                    "quantity": int,
                    "price": float | None,
                    "order_type": str,
                    "message": str,
                }

        Raises:
            KISOrderError: 주문 실패.
            ValueError: 잘못된 파라미터.
        """
        if side not in ("buy", "sell"):
            raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'.")
        if order_type not in ("00", "01"):
            raise ValueError(
                f"Invalid order_type: {order_type}. Must be '00'(limit) or '01'(market)."
            )
        if order_type == "00" and price is None:
            raise ValueError("price is required for limit orders (order_type='00').")
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}.")

        # 모의투자 서버는 시장가 주문(order_type="01")을 지원하지 않는다.
        # 가상 모드에서 시장가 주문이 들어오면 지정가로 자동 전환한다.
        if self.auth.virtual and order_type == "01":
            # 시세 조회용 exchange 코드로 변환 (NASD -> NAS, NYSE -> NYS, AMEX -> AMS)
            price_exchange = _EXCHANGE_CODE_MAP.get(exchange, "NAS")
            try:
                price_data = await self.get_overseas_price(ticker, exchange=price_exchange)
                current_price = price_data.get("current_price", 0.0)
            except httpx.TimeoutException:
                current_price = 0.0
                logger.warning(
                    "모의투자 지정가 전환 중 현재가 조회 타임아웃 | ticker=%s | exchange=%s",
                    ticker, price_exchange,
                )
            except httpx.HTTPStatusError as exc:
                current_price = 0.0
                logger.warning(
                    "모의투자 지정가 전환 중 현재가 HTTP 오류 | ticker=%s | exchange=%s | status=%d",
                    ticker, price_exchange, exc.response.status_code,
                )
            except ValueError as exc:
                current_price = 0.0
                logger.warning(
                    "모의투자 지정가 전환 중 현재가 파싱 오류 | ticker=%s | exchange=%s | error=%s",
                    ticker, price_exchange, exc,
                )
            except KISAPIError:
                current_price = 0.0
                logger.warning(
                    "모의투자 지정가 전환 중 현재가 조회 실패 | ticker=%s | exchange=%s",
                    ticker, price_exchange,
                )

            if current_price > 0:
                if side == "buy":
                    limit_price = round(current_price * _VIRTUAL_BUY_MARKUP, 2)
                else:
                    limit_price = round(current_price * _VIRTUAL_SELL_DISCOUNT, 2)
            else:
                # 현재가 조회 실패 시 price 파라미터 사용, 없으면 에러
                if price is not None and price > 0:
                    limit_price = price
                else:
                    raise KISOrderError(
                        f"모의투자 시장가 전환 실패: 현재가 조회 불가 | ticker={ticker}"
                    )

            logger.warning(
                "모의투자 시장가 불가, 지정가로 전환: ticker=%s, price=%s",
                ticker, limit_price,
            )
            order_type = "00"
            price = limit_price

        tr_id_key = "overseas_buy" if side == "buy" else "overseas_sell"
        tr_id = self._get_tr_id(tr_id_key)

        order_price = f"{price:.2f}" if price is not None else "0"

        body = {
            "CANO": self.auth.account_number,
            "ACNT_PRDT_CD": self.auth.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": order_price,
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": order_type,
        }

        logger.info(
            "Placing %s order: ticker=%s, type=%s, qty=%d, price=%s, exchange=%s",
            side.upper(),
            ticker,
            "LIMIT" if order_type == "00" else "MARKET",
            quantity,
            order_price,
            exchange,
        )

        try:
            data = await self._request(
                method="POST",
                path="/uapi/overseas-stock/v1/trading/order",
                tr_id=tr_id,
                body=body,
            )
        except KISAPIError as exc:
            logger.error(
                "Order FAILED: ticker=%s, side=%s, qty=%d, error=%s",
                ticker,
                side,
                quantity,
                str(exc),
            )
            raise KISOrderError(
                f"Order failed for {ticker}: {exc}",
                rt_cd=exc.rt_cd,
                msg_cd=exc.msg_cd,
                msg=exc.msg,
            ) from exc

        output = data.get("output", {})
        order_id = output.get("ODNO", "")

        logger.info(
            "Order SUCCESS: order_id=%s, ticker=%s, side=%s, qty=%d, price=%s",
            order_id,
            ticker,
            side,
            quantity,
            order_price,
        )

        return {
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
            "order_type": "limit" if order_type == "00" else "market",
            "message": data.get("msg1", ""),
        }

    async def cancel_order(
        self,
        order_id: str,
        ticker: str,
        quantity: int,
        exchange: str = "NASD",
    ) -> dict:
        """해외주식 주문을 취소한다.

        Args:
            order_id: 원주문 번호.
            ticker: 종목 심볼.
            quantity: 취소 수량.
            exchange: 거래소 코드.

        Returns:
            취소 결과::

                {
                    "order_id": str,
                    "original_order_id": str,
                    "ticker": str,
                    "message": str,
                }

        Raises:
            KISOrderError: 취소 실패.
        """
        tr_id = self._get_tr_id("overseas_cancel")

        body = {
            "CANO": self.auth.account_number,
            "ACNT_PRDT_CD": self.auth.account_product_code,
            "OVRS_EXCG_CD": exchange,
            "PDNO": ticker,
            "ORGN_ODNO": order_id,
            "RVSE_CNCL_DVSN_CD": "02",  # 02=취소
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": "0",
            "ORD_SVR_DVSN_CD": "0",
        }

        logger.info(
            "Cancelling order: order_id=%s, ticker=%s, qty=%d",
            order_id,
            ticker,
            quantity,
        )

        try:
            data = await self._request(
                method="POST",
                path="/uapi/overseas-stock/v1/trading/order-rvsecncl",
                tr_id=tr_id,
                body=body,
            )
        except KISAPIError as exc:
            logger.error(
                "Cancel FAILED: order_id=%s, ticker=%s, error=%s",
                order_id,
                ticker,
                str(exc),
            )
            raise KISOrderError(
                f"Cancel failed for order {order_id}: {exc}",
                rt_cd=exc.rt_cd,
                msg_cd=exc.msg_cd,
                msg=exc.msg,
            ) from exc

        output = data.get("output", {})
        cancel_order_id = output.get("ODNO", "")

        logger.info(
            "Cancel SUCCESS: cancel_order_id=%s, original_order_id=%s, ticker=%s",
            cancel_order_id,
            order_id,
            ticker,
        )

        return {
            "order_id": cancel_order_id,
            "original_order_id": order_id,
            "ticker": ticker,
            "message": data.get("msg1", ""),
        }

    # ------------------------------------------------------------------
    # 잔고 / 체결 내역
    # ------------------------------------------------------------------

    async def get_balance(self) -> dict:
        """해외주식 잔고를 조회한다.

        Returns:
            잔고 정보::

                {
                    "positions": [
                        {
                            "ticker": str,
                            "name": str,
                            "quantity": int,
                            "avg_price": float,
                            "current_price": float,
                            "pnl_pct": float,
                            "pnl_amount": float,
                            "exchange": str,
                        },
                        ...
                    ],
                    "total_evaluation": float,
                    "total_pnl": float,
                    "cash_balance": float,
                    "currency": str,
                }

        Raises:
            KISAPIError: API 호출 실패.
        """
        # 캐시가 유효하면 즉시 반환한다 (Lock 획득 없이).
        now = time.monotonic()
        if self._balance_cache is not None and (now - self._balance_cache_ts) < self._BALANCE_CACHE_TTL:
            logger.debug(
                "get_balance 캐시 반환 (age=%.1fs)", now - self._balance_cache_ts
            )
            return self._balance_cache

        async with self._balance_lock:
            # Lock 획득 후 다시 캐시 확인한다.
            # 다른 코루틴이 Lock을 먼저 획득하여 이미 갱신했을 수 있다.
            now = time.monotonic()
            if self._balance_cache is not None and (now - self._balance_cache_ts) < self._BALANCE_CACHE_TTL:
                logger.debug(
                    "get_balance 캐시 반환 (Lock 후 재확인, age=%.1fs)",
                    now - self._balance_cache_ts,
                )
                return self._balance_cache

            tr_id = self._get_tr_id("overseas_balance")

            # KIS 해외잔고 조회는 거래소별로 분리 조회한다.
            # NASD만 조회하면 다른 거래소 포지션/현금이 누락될 수 있으므로
            # NASD, NYSE, AMEX 세 거래소를 순차적으로 조회하여 결과를 합산한다.
            exchange_codes = _OVERSEAS_EXCHANGES

            all_positions: list[dict] = []
            # 현금잔고·총자산·총손익은 계좌 전체 기준이므로 최댓값을 사용한다.
            # (거래소별 응답에서 동일 계좌 전체 현금이 반복 반환되므로 MAX가 안전하다.)
            best_cash_balance = 0.0
            best_total_pnl = 0.0
            best_total_evaluation = 0.0
            seen_tickers: set[str] = set()

            for excg_cd in exchange_codes:
                params = {
                    "CANO": self.auth.account_number,
                    "ACNT_PRDT_CD": self.auth.account_product_code,
                    "OVRS_EXCG_CD": excg_cd,
                    "TR_CRCY_CD": "USD",
                    "CTX_AREA_FK200": "",
                    "CTX_AREA_NK200": "",
                }

                try:
                    data = await self._request(
                        method="GET",
                        path="/uapi/overseas-stock/v1/trading/inquire-balance",
                        tr_id=tr_id,
                        params=params,
                    )
                except KISAPIError as exc:
                    # 해당 거래소에 잔고가 없으면 KIOK0560 등의 에러가 반환될 수 있다.
                    # 에러를 무시하고 다음 거래소로 진행한다.
                    logger.debug(
                        "거래소 %s 잔고 조회 실패 (건너뜀): %s", excg_cd, exc
                    )
                    continue

                output1 = data.get("output1", [])
                output2 = data.get("output2", {})

                # output2가 리스트인 경우 첫 번째 항목 사용
                if isinstance(output2, list):
                    output2 = output2[0] if output2 else {}

                # 계좌 전체 현금·총자산·총손익: 각 거래소 응답의 최댓값 보관
                # frcr_use_psbl_amt (외화 사용가능금액): 실전/모의 공통 필드.
                # 일부 모의 응답에서 이 필드가 없거나 0인 경우
                # frcr_evlu_amt (외화 평가금액) 또는 evlu_amt_smtl_amt 필드를 사용한다.
                excg_cash = self._safe_float(output2.get("frcr_use_psbl_amt", "0"))
                if excg_cash == 0.0:
                    excg_cash = self._safe_float(output2.get("frcr_evlu_amt", "0"))
                excg_total_pnl = self._safe_float(output2.get("tot_evlu_pfls_amt", "0"))
                excg_total_eval = self._safe_float(output2.get("tot_asst_amt", "0"))

                if excg_cash > best_cash_balance:
                    best_cash_balance = excg_cash
                if abs(excg_total_pnl) > abs(best_total_pnl):
                    best_total_pnl = excg_total_pnl
                if excg_total_eval > best_total_evaluation:
                    best_total_evaluation = excg_total_eval

                logger.debug(
                    "거래소 %s 조회 완료: output1=%d건, cash=%.2f, total_eval=%.2f",
                    excg_cd,
                    len(output1),
                    excg_cash,
                    excg_total_eval,
                )

                for item in output1:
                    qty = self._safe_int(item.get("ovrs_cblc_qty", "0"))
                    if qty == 0:
                        continue

                    ticker = item.get("ovrs_pdno", "")
                    # 동일 티커가 여러 거래소에서 중복 반환되는 경우 첫 번째만 사용한다.
                    if ticker in seen_tickers:
                        continue
                    seen_tickers.add(ticker)

                    # 현재가: now_pric2 우선, 0이면 ovrs_now_pric1 시도, 그래도 0이면 평균단가 사용
                    current_price = self._safe_float(item.get("now_pric2", "0"))
                    if current_price == 0.0:
                        current_price = self._safe_float(item.get("ovrs_now_pric1", "0"))
                    avg_price = self._safe_float(item.get("pchs_avg_pric", "0"))
                    if current_price == 0.0:
                        current_price = avg_price
                        logger.debug(
                            "현재가 조회 불가, 평균단가로 대체 | ticker=%s | avg_price=%.4f",
                            ticker,
                            avg_price,
                        )

                    all_positions.append({
                        "ticker": ticker,
                        "name": item.get("ovrs_item_name", ""),
                        "quantity": qty,
                        "avg_price": avg_price,
                        "current_price": current_price,
                        "pnl_pct": self._safe_float(item.get("evlu_pfls_rt", "0")),
                        "pnl_amount": self._safe_float(item.get("frcr_evlu_pfls_amt", "0")),
                        "exchange": item.get("ovrs_excg_cd", excg_cd),
                    })

            # ----------------------------------------------------------------
            # inquire-present-balance (CTRP6504R) 로 USD 현금잔고를 보완한다.
            #
            # inquire-balance(JTTT3012R)의 output2에는 frcr_use_psbl_amt 필드가
            # 존재하지 않거나 0으로 반환된다. 실제 USD 현금은
            # inquire-present-balance의 output2 리스트에서 crcy_cd=="USD"인
            # 항목의 frcr_dncl_amt_2 필드를 읽어야 한다.
            #
            # 중요: 모의투자 클라이언트(self.auth.virtual==True)의 경우
            # inquire-present-balance를 모의 서버로 직접 호출해야 한다.
            # _PRICE_API_PATHS에 이 경로가 등록되어 있어 기본적으로 실전 서버로
            # 라우팅되지만, 실전 서버는 모의투자 계좌번호를 모르므로 현금 0이 반환된다.
            # force_trading_auth=True 를 사용해 모의 서버로 강제 라우팅한다.
            #
            # 실전 클라이언트는 기존대로 _PRICE_API_PATHS 경유(실전 서버)를 사용한다.
            # ----------------------------------------------------------------
            present_balance_tr_id = self._get_tr_id("exchange_rate")
            trading_auth = self.auth
            # 모의투자: force_trading_auth=True → 모의 서버로 직접 요청
            # 실전투자: force_trading_auth=False(기본) → _PRICE_API_PATHS 경유 실전 서버
            use_force_trading_auth = self.auth.virtual
            try:
                pb_data = await self._request(
                    method="GET",
                    path="/uapi/overseas-stock/v1/trading/inquire-present-balance",
                    tr_id=present_balance_tr_id,
                    params={
                        "CANO": trading_auth.account_number,
                        "ACNT_PRDT_CD": trading_auth.account_product_code,
                        "OVRS_EXCG_CD": "NASD",
                        "WCRC_FRCR_DVSN_CD": "01",  # 01=외화
                        "NATN_CD": "840",             # 840=미국
                        "TR_MKET_CD": "00",
                        "INQR_DVSN_CD": "00",
                    },
                    force_trading_auth=use_force_trading_auth,
                )
                # output2는 통화별 리스트다. USD 항목을 찾아 현금잔고를 읽는다.
                pb_output2 = pb_data.get("output2", [])
                if isinstance(pb_output2, dict):
                    pb_output2 = [pb_output2]
                for crcy_item in pb_output2:
                    if crcy_item.get("crcy_cd") == "USD":
                        usd_cash = self._safe_float(
                            crcy_item.get("frcr_dncl_amt_2", "0")
                        )
                        if usd_cash > best_cash_balance:
                            best_cash_balance = usd_cash
                            logger.debug(
                                "inquire-present-balance에서 USD 현금잔고 갱신: %.2f",
                                usd_cash,
                            )
                        break

                # output3은 KRW 기준 계좌 총자산이므로 여기서는 사용하지 않는다.

            except Exception as exc:
                logger.debug(
                    "inquire-present-balance 현금잔고 보완 실패 (건너뜀): %s", exc
                )

            # 총 자산 평가금액: 포지션 평가금액 합산 + 현금으로 계산한다.
            if best_total_evaluation == 0.0:
                positions_value = sum(
                    p["current_price"] * p["quantity"] for p in all_positions
                )
                best_total_evaluation = positions_value + best_cash_balance
                logger.debug(
                    "총자산 계산: positions=%.2f + cash=%.2f = %.2f",
                    positions_value,
                    best_cash_balance,
                    best_total_evaluation,
                )

            logger.info(
                "Balance fetched (all exchanges): %d positions, cash=%.2f USD, total_eval=%.2f USD",
                len(all_positions),
                best_cash_balance,
                best_total_evaluation,
            )

            result = {
                "positions": all_positions,
                "total_evaluation": best_total_evaluation,
                "total_pnl": best_total_pnl,
                "cash_balance": best_cash_balance,
                "currency": "USD",
            }
            # 성공 시 캐시 저장
            self._balance_cache = result
            self._balance_cache_ts = time.monotonic()

            return result

    async def get_order_history(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """체결 내역을 조회한다.

        Args:
            start_date: 조회 시작일 ("YYYYMMDD"). None이면 7일 전.
            end_date: 조회 종료일 ("YYYYMMDD"). None이면 오늘.

        Returns:
            체결 내역 리스트::

                [
                    {
                        "order_id": str,
                        "ticker": str,
                        "side": str,
                        "quantity": int,
                        "filled_quantity": int,
                        "price": float,
                        "filled_price": float,
                        "order_time": str,
                        "status": str,
                    },
                    ...
                ]

        Raises:
            KISAPIError: API 호출 실패.
        """
        now = datetime.now()
        if end_date is None:
            end_date = now.strftime("%Y%m%d")
        if start_date is None:
            start_date = (now - timedelta(days=7)).strftime("%Y%m%d")

        tr_id = self._get_tr_id("overseas_order_history")
        params = {
            "CANO": self.auth.account_number,
            "ACNT_PRDT_CD": self.auth.account_product_code,
            "PDNO": "",
            "ORD_STRT_DT": start_date,
            "ORD_END_DT": end_date,
            "SLL_BUY_DVSN": "00",  # 00=전체
            "CCLD_NCCS_DVSN": "00",  # 00=전체
            "OVRS_EXCG_CD": "NASD",
            "SORT_SQN": "DS",  # DS=역순
            "ORD_GNO_BRNO": "",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        }

        data = await self._request(
            method="GET",
            path="/uapi/overseas-stock/v1/trading/inquire-ccnl",
            tr_id=tr_id,
            params=params,
        )

        output = data.get("output", [])
        results = []
        for item in output:
            order_id = item.get("odno", "")
            if not order_id:
                continue
            results.append({
                "order_id": order_id,
                "ticker": item.get("pdno", ""),
                "side": "buy" if item.get("sll_buy_dvsn_cd", "") == "02" else "sell",
                "quantity": self._safe_int(item.get("ft_ord_qty", "0")),
                "filled_quantity": self._safe_int(item.get("ft_ccld_qty", "0")),
                "price": self._safe_float(item.get("ft_ord_unpr3", "0")),
                "filled_price": self._safe_float(item.get("ft_ccld_unpr3", "0")),
                "order_time": item.get("ord_dt", "") + item.get("ord_tmd", ""),
                "status": self._parse_order_status(
                    item.get("ccld_yn", ""), item.get("cncl_yn", "")
                ),
            })

        logger.info(
            "Order history fetched: %d records (%s ~ %s)",
            len(results),
            start_date,
            end_date,
        )
        return results

    # ------------------------------------------------------------------
    # 종목 정보 / 환율
    # ------------------------------------------------------------------

    async def get_stock_info(
        self, ticker: str, exchange: str = "NAS"
    ) -> dict:
        """해외주식 종목 정보를 조회한다.

        Args:
            ticker: 종목 심볼.
            exchange: 거래소 코드.

        Returns:
            종목 정보::

                {
                    "ticker": str,
                    "name": str,
                    "exchange": str,
                    "currency": str,
                    "lot_size": int,
                }

        Raises:
            KISAPIError: API 호출 실패.
        """
        tr_id = self._get_tr_id("overseas_stock_info")
        params = {
            "AUTH": "",
            "EXCD": exchange,
            "SYMB": ticker,
        }

        data = await self._request(
            method="GET",
            path="/uapi/overseas-price/v1/quotations/search-info",
            tr_id=tr_id,
            params=params,
        )

        output = data.get("output", {})
        return {
            "ticker": ticker,
            "name": output.get("prdt_eng_name", ""),
            "exchange": exchange,
            "currency": output.get("tr_crcy_cd", "USD"),
            "lot_size": self._safe_int(output.get("buy_unit_qty", "1")),
        }

    async def get_exchange_rate(self) -> float:
        """USD/KRW 환율을 조회한다.

        환율 조회는 _PRICE_API_PATHS에 등록되어 실전 서버(real_auth)를 통해 요청된다.
        따라서 CANO/ACNT_PRDT_CD 파라미터도 real_auth의 계좌번호를 사용해야 한다.
        real_auth가 없으면 auth(거래용)의 계좌번호를 사용한다.

        Returns:
            현재 USD/KRW 환율.

        Raises:
            KISAPIError: API 호출 실패.
        """
        tr_id = self._get_tr_id("exchange_rate")
        # 환율 조회는 실전 API 서버를 사용하므로 real_auth의 계좌번호를 사용한다.
        active_auth = self._real_auth or self.auth
        params = {
            "CANO": active_auth.account_number,
            "ACNT_PRDT_CD": active_auth.account_product_code,
            "OVRS_EXCG_CD": "NASD",
            "TR_CRCY_CD": "USD",
        }

        data = await self._request(
            method="GET",
            path="/uapi/overseas-stock/v1/trading/inquire-present-balance",
            tr_id=tr_id,
            params=params,
        )

        output2 = data.get("output2", {})
        if isinstance(output2, list):
            output2 = output2[0] if output2 else {}

        rate = self._safe_float(output2.get("frst_bltn_exrt", "0"))
        if rate == 0.0:
            # fallback: output1에서 환율 추출 시도
            output1 = data.get("output1", [])
            if output1 and isinstance(output1, list):
                rate = self._safe_float(
                    output1[0].get("bass_exrt", "0")
                )

        logger.info("Exchange rate USD/KRW: %.2f", rate)
        return rate

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        tr_id: str,
        params: dict | None = None,
        body: dict | None = None,
        force_trading_auth: bool = False,
    ) -> dict:
        """KIS API에 요청을 보내고 응답을 반환한다.

        자동으로 토큰을 갱신하고, 일시적 오류에 대해 재시도한다.
        KIS API 응답에서 rt_cd가 "0"이 아닌 경우 KISAPIError를 발생시킨다.

        Args:
            method: HTTP 메서드 ("GET" 또는 "POST").
            path: API 경로 (예: "/uapi/overseas-price/v1/quotations/price").
            tr_id: 거래 ID.
            params: GET 쿼리 파라미터.
            body: POST 요청 바디.
            force_trading_auth: True이면 _PRICE_API_PATHS 라우팅을 무시하고
                self.auth(거래 계좌 인증)를 강제 사용한다. 모의투자 클라이언트가
                inquire-present-balance를 모의 서버로 직접 호출할 때 사용한다.

        Returns:
            API 응답 JSON 딕셔너리.

        Raises:
            KISAPIError: API 응답 에러 또는 재시도 실패.
        """
        # force_trading_auth=True 이면 항상 self.auth를 사용한다.
        # 그 외에는 시세 조회 API(_PRICE_API_PATHS)에 한해 real_auth(실전 서버)를 사용한다.
        if force_trading_auth:
            active_auth = self.auth
        else:
            is_price_api = path in self._PRICE_API_PATHS
            active_auth = (self._real_auth or self.auth) if is_price_api else self.auth

        # 토큰 갱신
        await active_auth.get_token()

        url = f"{active_auth.base_url}{path}"
        headers = active_auth.get_headers(tr_id=tr_id)

        # POST 요청 시 hashkey 추가
        if method == "POST" and body is not None:
            try:
                hashkey = await active_auth.get_hashkey(body)
                headers["hashkey"] = hashkey
            except KISAuthError:
                logger.warning("Hashkey generation failed, proceeding without it")

        last_exception: Exception | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                if method == "GET":
                    resp = await self.client.get(
                        url, headers=headers, params=params
                    )
                elif method == "POST":
                    resp = await self.client.post(
                        url, headers=headers, json=body
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                resp.raise_for_status()
                data = resp.json()

                # KIS API 응답 코드 확인
                rt_cd = data.get("rt_cd", "")
                if rt_cd != "0":
                    msg_cd = data.get("msg_cd", "")
                    msg1 = data.get("msg1", "")
                    logger.error(
                        "KIS API error: path=%s, tr_id=%s, rt_cd=%s, msg_cd=%s, msg=%s",
                        path,
                        tr_id,
                        rt_cd,
                        msg_cd,
                        msg1,
                    )
                    # OPSQ2000 (INVALID_CHECK_ACNO) 은 간헐적으로 발생할 수 있음
                    # 초당 거래건수 초과도 재시도 대상
                    _retryable_msg_cds = {"OPSQ2000", "OPSQ0001"}
                    if msg_cd in _retryable_msg_cds and attempt < self.MAX_RETRIES:
                        delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "KIS API retryable error: %s %s, msg_cd=%s, retry %d/%d in %.1fs",
                            method, path, msg_cd, attempt, self.MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue

                    raise KISAPIError(
                        f"KIS API error [{msg_cd}]: {msg1}",
                        rt_cd=rt_cd,
                        msg_cd=msg_cd,
                        msg=msg1,
                    )

                logger.debug(
                    "KIS API success: %s %s (tr_id=%s)", method, path, tr_id
                )
                return data

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_exception = exc

                # 5xx 에러만 재시도
                if status >= 500 and attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "Server error %d on %s %s, retry %d/%d in %.1fs",
                        status,
                        method,
                        path,
                        attempt,
                        self.MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error(
                    "HTTP error %d on %s %s: %s",
                    status,
                    method,
                    path,
                    exc.response.text[:500],
                )
                raise KISAPIError(
                    f"HTTP {status} on {method} {path}",
                    rt_cd=str(status),
                ) from exc

            except httpx.RequestError as exc:
                last_exception = exc

                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "Network error on %s %s: %s, retry %d/%d in %.1fs",
                        method,
                        path,
                        str(exc),
                        attempt,
                        self.MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.error(
                    "Network error on %s %s after %d retries: %s",
                    method,
                    path,
                    self.MAX_RETRIES,
                    str(exc),
                )
                raise KISAPIError(
                    f"Network error on {method} {path}: {exc}"
                ) from exc

            except KISAPIError:
                # 비즈니스 에러는 재시도하지 않음
                raise

        # 재시도 모두 실패
        raise KISAPIError(
            f"All {self.MAX_RETRIES} retries failed for {method} {path}"
        ) from last_exception

    def _get_tr_id(self, key: str) -> str:
        """모의/실전 모드에 따라 올바른 tr_id를 반환한다.

        Args:
            key: _TR_IDS 딕셔너리의 키.

        Returns:
            해당 모드의 tr_id.
        """
        real_id, virtual_id = self._TR_IDS[key]
        return virtual_id if self.auth.virtual else real_id

    @staticmethod
    def _parse_order_status(ccld_yn: str, cncl_yn: str) -> str:
        """체결/취소 여부로부터 주문 상태를 파싱한다."""
        if cncl_yn == "Y":
            return "cancelled"
        if ccld_yn == "Y":
            return "filled"
        return "pending"

    @staticmethod
    def _safe_float(value: str | float | None) -> float:
        """문자열을 안전하게 float로 변환한다."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _safe_int(value: str | int | None) -> int:
        """문자열을 안전하게 int로 변환한다."""
        if value is None:
            return 0
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return 0
