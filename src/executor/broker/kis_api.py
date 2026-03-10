"""KIS API (F5.1) -- KIS OpenAPI 실제 호출 함수를 제공한다.

BrokerClient 스텁 메서드의 실제 구현체이다.
시세는 real_auth, 거래는 virtual_auth를 사용한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from collections.abc import Awaitable, Callable

from src.common.broker_gateway import (
    BalanceData,
    KisAuth,
    OHLCV,
    OrderRequest,
    OrderResult,
    PositionData,
    PriceData,
)
from src.common.error_handler import BrokerError
from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.executor.broker.kis_response import (
    account_parts,
    build_url,
    check_response,
    safe_float,
    safe_int,
)
from src.executor.broker.kis_throttle import get_kis_throttle

logger = get_logger(__name__)

# KIS 토큰 만료 에러 코드이다
_TOKEN_EXPIRED_CODE = "EGW00123"


async def _with_token_retry(
    auth: KisAuth,
    fn: Callable[[], Awaitable[dict]],
    context: str,
) -> dict:
    """API 호출을 수행하고, 토큰 만료 시 재발급 후 1회 재시도한다."""
    try:
        return await fn()
    except BrokerError as exc:
        if _TOKEN_EXPIRED_CODE in (exc.detail or ""):
            logger.info("토큰 만료 감지 — 자동 재발급 후 재시도 (%s)", context)
            auth.invalidate_token()
            return await fn()
        raise

# -- API 경로 상수 --
_GET_PRICE = "/uapi/overseas-price/v1/quotations/price"
_GET_DAILY = "/uapi/overseas-price/v1/quotations/dailyprice"
_ORDER_PATH = "/uapi/overseas-stock/v1/trading/order"
_GET_BALANCE = "/uapi/overseas-stock/v1/trading/inquire-balance"
_GET_BUY_POWER = "/uapi/overseas-stock/v1/trading/inquire-psamount"
_GET_PRESENT_BALANCE = "/uapi/overseas-stock/v1/trading/inquire-present-balance"

# -- TR_ID 상수 --
# 시세 조회 (가상/실전 동일)
_TR_PRICE = "HHDFS00000300"
_TR_DAILY = "HHDFS76240000"

# 거래/잔고 TR_ID (가상 vs 실전 구분 필수)
_TR_ID_MAP: dict[str, dict[str, str]] = {
    "buy":       {"virtual": "VTTT1002U", "real": "TTTT1002U"},
    "sell":      {"virtual": "VTTT1001U", "real": "TTTT1001U"},
    "balance":   {"virtual": "VTTS3012R", "real": "TTTS3012R"},
    "buy_power": {"virtual": "VTTS3007R", "real": "TTTS3007R"},
    "present_balance": {"virtual": "VTRP6504R", "real": "CTRP6504R"},
}


def _get_tr_id(auth: KisAuth, operation: str) -> str:
    """auth 유형(가상/실전)에 따라 올바른 TR_ID를 반환한다.

    가상투자 TR_ID는 V 접두사, 실전투자 TR_ID는 T 접두사를 사용한다.
    KIS OpenAPI 규격 상 서버와 TR_ID가 일치하지 않으면 500 에러가 발생한다.
    """
    tr_map = _TR_ID_MAP.get(operation)
    if tr_map is None:
        raise ValueError(f"알 수 없는 TR_ID 오퍼레이션: {operation}")
    mode = "real" if auth._is_real else "virtual"
    tr_id = tr_map[mode]
    logger.debug("TR_ID 선택: %s → %s (%s)", operation, tr_id, mode)
    return tr_id

# 가상 거래에서 시장가 불가 -- 지정가 변환 시 슬리피지 비율
_MARKET_TO_LIMIT_SLIPPAGE = 0.005


async def fetch_price(
    auth: KisAuth, ticker: str, exchange: str, http: AsyncHttpClient,
) -> PriceData:
    """KIS 현재가 API를 호출하여 PriceData를 반환한다."""
    params = {"AUTH": "", "EXCD": exchange, "SYMB": ticker}
    url = build_url(auth, _GET_PRICE)

    async def _call() -> dict:
        await get_kis_throttle().before_query()
        headers = await auth.get_headers(_TR_PRICE)
        resp = await http.get(url, headers=headers, params=params)
        return check_response(resp, f"현재가 조회 {ticker}")

    data = await _with_token_retry(auth, _call, f"현재가 {ticker}")
    output = data.get("output", {})
    return PriceData(
        ticker=ticker,
        price=safe_float(output.get("last")),
        change_pct=safe_float(output.get("rate")),
        volume=safe_int(output.get("tvol")),
        timestamp=datetime.now(tz=timezone.utc),
    )


class _PresentBalanceResult:
    """inquire-present-balance API 결과를 담는다."""
    __slots__ = ("usd_cash", "total_equity_usd", "usd_rate")

    def __init__(self, usd_cash: float, total_equity_usd: float, usd_rate: float = 0.0) -> None:
        self.usd_cash = usd_cash
        self.total_equity_usd = total_equity_usd
        self.usd_rate = usd_rate


async def _fetch_present_balance(
    auth: KisAuth, http: AsyncHttpClient,
) -> _PresentBalanceResult:
    """inquire-present-balance API로 계좌 총자산과 USD 현금을 조회한다.

    output2: 통화별 잔고 → USD 현금 (frcr_dncl_amt_2)
    output3: 계좌 총자산 (tot_asst_amt, KRW) → 환율로 USD 환산
    모의투자: VTRP6504R, 실전: CTRP6504R.
    """
    tr_id = _get_tr_id(auth, "present_balance")
    cano, acnt_cd = account_parts(auth)
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
        "OVRS_EXCG_CD": "NASD", "WCRC_FRCR_DVSN_CD": "01",
        "NATN_CD": "840", "TR_MKET_CD": "00", "INQR_DVSN_CD": "00",
    }
    url = build_url(auth, _GET_PRESENT_BALANCE)

    async def _call() -> dict:
        await get_kis_throttle().before_query()
        headers = await auth.get_headers(tr_id)
        resp = await http.get(url, headers=headers, params=params)
        return check_response(resp, "체결기준잔고 조회")

    data = await _with_token_retry(auth, _call, "체결기준잔고")
    output2 = data.get("output2", [])
    output3 = data.get("output3", {})
    if isinstance(output2, dict):
        output2 = [output2]
    if isinstance(output3, list):
        output3 = output3[0] if output3 else {}

    # output2: USD 현금 + 환율 추출
    usd_cash = 0.0
    usd_rate = 0.0
    for crcy_item in output2:
        if crcy_item.get("crcy_cd") == "USD":
            usd_cash = safe_float(crcy_item.get("frcr_dncl_amt_2"))
            if usd_cash == 0.0:
                usd_cash = safe_float(crcy_item.get("frcr_drwg_psbl_amt_1"))
            usd_rate = safe_float(crcy_item.get("frst_bltn_exrt"))
            break

    # output3: 총자산 (KRW) → USD 환산
    tot_asst_krw = safe_float(output3.get("tot_asst_amt"))
    total_equity_usd = 0.0
    if tot_asst_krw > 0 and usd_rate > 0:
        total_equity_usd = round(tot_asst_krw / usd_rate, 2)

    logger.info(
        "체결기준잔고: usd_cash=%.2f, tot_asst_krw=%.0f, "
        "usd_rate=%.2f, total_equity_usd=%.2f",
        usd_cash, tot_asst_krw, usd_rate, total_equity_usd,
    )
    return _PresentBalanceResult(usd_cash=usd_cash, total_equity_usd=total_equity_usd, usd_rate=usd_rate)


async def fetch_balance(
    auth: KisAuth, http: AsyncHttpClient,
) -> BalanceData:
    """KIS 잔고 조회 API를 호출하여 BalanceData를 반환한다.

    1) inquire-balance로 포지션 + 기본 잔고 조회
    2) 현금이 0이면 inquire-present-balance로 USD 현금 보완
    3) 총자산: tot_asst_amt 우선 → 없으면 포지션 평가액 + 현금
    """
    tr_id = _get_tr_id(auth, "balance")
    cano, acnt_cd = account_parts(auth)
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
        "OVRS_EXCG_CD": "NASD", "TR_CRCY_CD": "USD",
        "CTX_AREA_FK200": "", "CTX_AREA_NK200": "",
    }
    url = build_url(auth, _GET_BALANCE)

    async def _call() -> dict:
        await get_kis_throttle().before_query()
        headers = await auth.get_headers(tr_id)
        resp = await http.get(url, headers=headers, params=params)
        return check_response(resp, "잔고 조회")

    data = await _with_token_retry(auth, _call, "잔고 조회")
    positions = _parse_positions(data.get("output1", []))
    output2 = data.get("output2", {})
    # 가상투자 API에서 output2가 리스트로 오는 경우 첫 번째 항목을 사용한다
    if isinstance(output2, list):
        output2 = output2[0] if output2 else {}
    if not isinstance(output2, dict):
        output2 = {}

    # -- inquire-present-balance로 계좌 총자산/현금 보완 --
    pb_result: _PresentBalanceResult | None = None
    try:
        pb_result = await _fetch_present_balance(auth, http)
    except Exception as exc:
        logger.warning("체결기준잔고 보완 실패 (건너뜀): %s", exc)

    # -- 현금 잔고 --
    # inquire-balance의 frcr_use_psbl_amt → frcr_evlu_amt → present-balance
    available_cash = safe_float(output2.get("frcr_use_psbl_amt"))
    if available_cash == 0.0:
        available_cash = safe_float(output2.get("frcr_evlu_amt"))
    if available_cash == 0.0 and pb_result is not None:
        available_cash = pb_result.usd_cash

    # -- 총자산 --
    # present-balance의 tot_asst_amt/환율 우선 (가장 정확)
    # → inquire-balance의 tot_asst_amt → 포지션 평가액 + 현금
    positions_value = sum(p.current_price * p.quantity for p in positions)
    total_equity = 0.0
    if pb_result is not None and pb_result.total_equity_usd > 0:
        total_equity = pb_result.total_equity_usd
    if total_equity == 0.0:
        total_equity = safe_float(output2.get("tot_asst_amt"))
    if total_equity == 0.0:
        total_equity = positions_value + available_cash

    logger.info(
        "잔고: positions_value=%.2f, cash=%.2f, total_equity=%.2f "
        "(present_balance=%s)",
        positions_value, available_cash, total_equity,
        f"{pb_result.total_equity_usd:.2f}" if pb_result else "N/A",
    )
    return BalanceData(
        total_equity=total_equity,
        available_cash=available_cash,
        positions=positions,
    )


def _parse_positions(items: list[dict]) -> list[PositionData]:
    """잔고 output1 배열을 PositionData 목록으로 변환한다."""
    positions: list[PositionData] = []
    for item in items:
        qty = safe_int(item.get("ovrs_cblc_qty"))
        if qty <= 0:
            continue
        positions.append(PositionData(
            ticker=item.get("ovrs_pdno", ""),
            quantity=qty,
            avg_price=safe_float(item.get("pchs_avg_pric")),
            current_price=safe_float(item.get("now_pric2")),
            pnl_pct=safe_float(item.get("evlu_pfls_rt")),
        ))
    return positions


async def fetch_buy_power(
    auth: KisAuth, http: AsyncHttpClient,
    ticker: str = "AAPL",
) -> float:
    """KIS 매수가능금액 API를 호출한다.

    auth 유형에 따라 가상(VTTS3007R) 또는 실전(TTTS3007R) TR_ID를 자동 선택한다.
    KIS 모의투자 서버는 ITEM_CD가 필수이므로 기본값으로 AAPL을 사용한다.
    """
    tr_id = _get_tr_id(auth, "buy_power")
    cano, acnt_cd = account_parts(auth)
    params = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
        "OVRS_EXCG_CD": "NASD", "OVRS_ORD_UNPR": "0",
        "ITEM_CD": ticker,
    }
    url = build_url(auth, _GET_BUY_POWER)

    async def _call() -> dict:
        await get_kis_throttle().before_query()
        headers = await auth.get_headers(tr_id)
        resp = await http.get(url, headers=headers, params=params)
        return check_response(resp, "매수가능금액 조회")

    data = await _with_token_retry(auth, _call, "매수가능금액")
    output = data.get("output", {})
    return safe_float(output.get("ord_psbl_frcr_amt"))


async def submit_order(
    auth: KisAuth, order: OrderRequest, http: AsyncHttpClient,
) -> OrderResult:
    """KIS 주문 API를 호출한다. 가상 거래에서 시장가는 지정가로 자동 변환한다."""
    tr_id = _get_tr_id(auth, "buy" if order.side == "buy" else "sell")
    cano, acnt_cd = account_parts(auth)
    ord_unpr = _resolve_order_price(order)
    body = {
        "CANO": cano, "ACNT_PRDT_CD": acnt_cd,
        "OVRS_EXCG_CD": order.exchange, "PDNO": order.ticker,
        "ORD_QTY": str(order.quantity), "OVRS_ORD_UNPR": ord_unpr,
        "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00",
    }
    url = build_url(auth, _ORDER_PATH)

    async def _call() -> dict:
        await get_kis_throttle().before_order()
        headers = await auth.get_headers(tr_id)
        resp = await http.post(url, json=body, headers=headers)
        return check_response(resp, f"주문 {order.side} {order.ticker}")

    data = await _with_token_retry(auth, _call, f"주문 {order.ticker}")
    output = data.get("output", {})
    odno = output.get("ODNO", "") or output.get("odno", "")
    return OrderResult(order_id=odno, status="filled", message="주문 접수 완료")


def _resolve_order_price(order: OrderRequest) -> str:
    """주문 유형에 따라 주문 단가 문자열을 결정한다."""
    if order.order_type == "market" and order.price is not None:
        sign = 1 if order.side == "buy" else -1
        limit = round(order.price * (1 + sign * _MARKET_TO_LIMIT_SLIPPAGE), 2)
        return str(limit)
    if order.order_type == "limit" and order.price is not None:
        return str(order.price)
    return "0"


async def fetch_daily_candles(
    auth: KisAuth, ticker: str, days: int,
    exchange: str, http: AsyncHttpClient,
) -> list[OHLCV]:
    """KIS 일봉 API를 호출한다. 최대 100개씩 조회한다."""
    params = {
        "AUTH": "", "EXCD": exchange, "SYMB": ticker,
        "GUBN": "0", "BYMD": "", "MODP": "1",
    }
    url = build_url(auth, _GET_DAILY)

    async def _call() -> dict:
        await get_kis_throttle().before_query()
        headers = await auth.get_headers(_TR_DAILY)
        resp = await http.get(url, headers=headers, params=params)
        return check_response(resp, f"일봉 조회 {ticker}")

    data = await _with_token_retry(auth, _call, f"일봉 {ticker}")
    return [
        OHLCV(
            date=item.get("xymd", ""),
            open=safe_float(item.get("open")),
            high=safe_float(item.get("high")),
            low=safe_float(item.get("low")),
            close=safe_float(item.get("clos")),
            volume=safe_int(item.get("tvol")),
        )
        for item in data.get("output2", [])[:days]
    ]


async def fetch_exchange_rate(
    auth: KisAuth, http: AsyncHttpClient,
) -> float:
    """체결기준잔고 API의 frst_bltn_exrt 필드에서 USD/KRW 환율을 추출한다.

    KIS OpenAPI에 독립 환율 조회 경로가 없으므로
    inquire-present-balance 응답에서 환율을 가져온다.
    범위 검증(900~2000)을 통과해야만 반환한다.
    """
    result = await _fetch_present_balance(auth, http)
    rate = result.usd_rate

    if not (900 < rate < 2000):
        raise BrokerError(
            message="KIS 환율 범위 이탈",
            detail=f"rate={rate} (from inquire-present-balance frst_bltn_exrt)",
        )

    logger.info("KIS 환율 조회: %.2f 원/달러 (체결기준잔고)", rate)
    return rate
