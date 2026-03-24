"""추가 환율 폴백 소스 -- FRED 캐시, 한국은행, ExchangeRate-API, Yahoo Finance이다.

FxScheduler의 6~9번째 폴백 소스로 사용된다.
각 함수는 순수 함수 형태로 의존성을 주입받는다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient
    from src.common.http_client import AsyncHttpClient

_logger = get_logger(__name__)

# 유효 환율 범위 (원/달러)이다
_MIN_RATE: float = 900.0
_MAX_RATE: float = 2000.0


def _validate_rate(rate: float, source: str) -> float | None:
    """환율 범위를 검증한다. 유효하면 반환, 아니면 None이다."""
    if _MIN_RATE < rate < _MAX_RATE:
        return rate
    _logger.warning("%s 환율 범위 이탈: %.2f", source, rate)
    return None


async def fetch_fred_cached_rate(cache: CacheClient) -> float | None:
    """FRED DEXKOUS 캐시에서 최신 USD/KRW 환율을 읽는다.

    macro:DEXKOUS 캐시 키에 저장된 시계열 데이터의
    첫 번째(최신) 값을 반환한다.
    """
    try:
        data = await cache.read_json("macro:DEXKOUS")
        if not data or not isinstance(data, list) or len(data) == 0:
            _logger.debug("FRED DEXKOUS 캐시 비어있음")
            return None

        first = data[0]
        if not isinstance(first, dict):
            return None

        raw = first.get("value")
        if raw is None:
            return None

        rate = float(raw)
        result = _validate_rate(rate, "FRED DEXKOUS")
        if result is not None:
            _logger.info("FRED DEXKOUS 캐시 환율: %.2f", result)
        return result
    except Exception:
        _logger.debug("FRED DEXKOUS 캐시 읽기 실패", exc_info=True)
        return None


async def fetch_bok_rate(http: AsyncHttpClient) -> float | None:
    """한국은행 ECOS API에서 USD/KRW 환율을 조회한다.

    공개 통계 API(인증키 불필요 경로)를 사용한다.
    실패 시 None을 반환한다.
    """
    # 한국은행 공개 환율 조회 URL이다
    url = (
        "https://ecos.bok.or.kr/api/StatisticSearch"
        "/sample/json/kr/1/1/731Y001/D"
    )
    try:
        resp = await http.get(url)
        if not resp.ok:
            _logger.debug("한국은행 API HTTP %d", resp.status)
            return None

        data = resp.json()
        # 응답 구조: {"StatisticSearch": {"row": [{"DATA_VALUE": "..."}]}}
        rows = (
            data.get("StatisticSearch", {})
            .get("row", [])
        )
        if not rows:
            _logger.debug("한국은행 API 데이터 없음")
            return None

        raw = rows[0].get("DATA_VALUE", "")
        if not raw or raw == ".":
            return None

        rate = float(str(raw).replace(",", ""))
        result = _validate_rate(rate, "한국은행")
        if result is not None:
            _logger.info("한국은행 API 환율: %.2f", result)
        return result
    except Exception:
        _logger.debug("한국은행 API 환율 조회 실패", exc_info=True)
        return None


async def fetch_exchangerate_api(
    http: AsyncHttpClient,
) -> float | None:
    """ExchangeRate-API(무료)에서 USD/KRW 환율을 조회한다.

    open.er-api.com은 API 키 없이 사용 가능하다.
    """
    url = "https://open.er-api.com/v6/latest/USD"
    try:
        resp = await http.get(url)
        if not resp.ok:
            _logger.debug("ExchangeRate-API HTTP %d", resp.status)
            return None

        data = resp.json()
        rates = data.get("rates", {})
        raw = rates.get("KRW")
        if raw is None:
            _logger.debug("ExchangeRate-API KRW 데이터 없음")
            return None

        rate = float(raw)
        result = _validate_rate(rate, "ExchangeRate-API")
        if result is not None:
            _logger.info("ExchangeRate-API 환율: %.2f", result)
        return result
    except Exception:
        _logger.debug("ExchangeRate-API 환율 조회 실패", exc_info=True)
        return None


async def fetch_yahoo_finance_rate(
    http: AsyncHttpClient,
) -> float | None:
    """Yahoo Finance API에서 USD/KRW 환율을 조회한다.

    query1.finance.yahoo.com의 JSON 응답을 파싱한다.
    """
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X"
        "?interval=1d&range=1d"
    )
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        resp = await http.get(url, headers=headers)
        if not resp.ok:
            _logger.debug("Yahoo Finance HTTP %d", resp.status)
            return None

        data = resp.json()
        # 응답: chart.result[0].meta.regularMarketPrice
        result_list = (
            data.get("chart", {}).get("result", [])
        )
        if not result_list:
            _logger.debug("Yahoo Finance 결과 없음")
            return None

        meta = result_list[0].get("meta", {})
        raw = meta.get("regularMarketPrice")
        if raw is None:
            # 대체: previousClose 사용
            raw = meta.get("previousClose")
        if raw is None:
            _logger.debug("Yahoo Finance 가격 데이터 없음")
            return None

        rate = float(raw)
        result = _validate_rate(rate, "Yahoo Finance")
        if result is not None:
            _logger.info("Yahoo Finance 환율: %.2f", result)
        return result
    except Exception:
        _logger.debug("Yahoo Finance 환율 조회 실패", exc_info=True)
        return None


async def fetch_last_success_rate(
    cache: CacheClient,
) -> float | None:
    """캐시된 최종 성공 환율을 읽는다.

    fx:last_success 키에 저장된 마지막 성공 환율을 반환한다.
    모든 실시간 소스 실패 시 최후의 보루로 사용한다.
    """
    try:
        data = await cache.read_json("fx:last_success")
        if not data or not isinstance(data, dict):
            _logger.debug("fx:last_success 캐시 없음")
            return None

        raw = data.get("rate")
        if raw is None:
            return None

        rate = float(raw)
        result = _validate_rate(rate, "last_success 캐시")
        if result is not None:
            _logger.info("최종 성공 캐시 환율: %.2f", result)
        return result
    except Exception:
        _logger.debug("최종 성공 캐시 읽기 실패", exc_info=True)
        return None
