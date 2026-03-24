"""외부 지표 -- ETF 펀드 플로우/AUM 데이터를 수집한다.

ETFdb.com에서 2X 레버리지 ETF의 AUM, 순유입/유출, 비용비율, 스프레드 등을
스크래핑하여 캐시에 저장한다. ETF.com은 Cloudflare 차단으로 ETFdb.com을 사용한다.
API 키 불필요 (HTML 스크래핑). 캐시 키: etf:flow:{ticker} (TTL 86400초).
"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient
    from src.common.http_client import AsyncHttpClient

logger = get_logger(__name__)

# ETFdb.com URL 패턴이다 — ETF.com은 Cloudflare 차단으로 사용 불가
_BASE_URL: str = "https://etfdb.com/etf/{ticker}/"

# 추적 대상 2X 레버리지 ETF 티커 목록이다
_TARGET_TICKERS: list[str] = [
    "SOXL", "SOXS", "QLD", "QID", "SSO", "SDS", "TQQQ", "SQQQ",
]

# 캐시 설정이다
_CACHE_KEY_PREFIX: str = "etf:flow"
_CACHE_TTL: int = 86400  # 24시간
_LAST_SUCCESS_KEY: str = "etf:flow:last_success"
_LAST_SUCCESS_TTL: int = 86400 * 3  # 72시간 폴백 유지

# 요청 설정이다
_REQUEST_TIMEOUT: float = 15.0
_MAX_RETRIES: int = 2
_RETRY_DELAY: float = 3.0
_INTER_REQUEST_DELAY: float = 1.5  # 티커 간 rate limit 방지 딜레이

# 스크래핑용 User-Agent이다
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
}

# -- HTML 파싱용 정규식 --

# AUM: <span>AUM</span> <span class='pull-right'>$11,805.0 M</span>
_AUM_PATTERN = re.compile(
    r"<span>AUM</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)

# Expense Ratio: <span>Expense Ratio</span> <span class='text-right'>0.75%</span>
_EXPENSE_RATIO_PATTERN = re.compile(
    r"<span>Expense Ratio</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)

# Average Spread (%): <span>Average Spread (%)</span> <span class='pull-right'>1.26</span>
_AVG_SPREAD_PCT_PATTERN = re.compile(
    r"<span>Average Spread \(%\)</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)

# Average Spread ($): <span>Average Spread ($)</span> <span class='pull-right'>1.26</span>
_AVG_SPREAD_USD_PATTERN = re.compile(
    r"<span>Average Spread \(\$\)</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)

# Net Fund Flows: <span class='net-fund-flow 5-day'><b>5 Day Net Flows:</b> -461.91 M</span>
_FLOW_5D_PATTERN = re.compile(
    r"class='net-fund-flow 5-day'>\s*<b>[^<]*</b>\s*([^<]+)</span>",
    re.IGNORECASE,
)
_FLOW_1M_PATTERN = re.compile(
    r"class='net-fund-flow 1-month'>\s*<b>[^<]*</b>\s*([^<]+)</span>",
    re.IGNORECASE,
)
_FLOW_3M_PATTERN = re.compile(
    r"class='net-fund-flow 3-month'>\s*<b>[^<]*</b>\s*([^<]+)</span>",
    re.IGNORECASE,
)

# Net AUM Change: <b>5 Day Net AUM Change:</b> -932.83 M
_AUM_CHANGE_5D_PATTERN = re.compile(
    r"class='5-day net-aum-change'>\s*<b>[^<]*</b>\s*([^<]+)<",
    re.IGNORECASE,
)
_AUM_CHANGE_1M_PATTERN = re.compile(
    r"class='1-month net-aum-change'>\s*<b>[^<]*</b>\s*([^<]+)<",
    re.IGNORECASE,
)
_AUM_CHANGE_3M_PATTERN = re.compile(
    r"class='3-month net-aum-change'>\s*<b>[^<]*</b>\s*([^<]+)<",
    re.IGNORECASE,
)

# 1 Month / 3 Month Avg Volume
_VOL_1M_PATTERN = re.compile(
    r"<span>1 Month Avg\. Volume</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)
_VOL_3M_PATTERN = re.compile(
    r"<span>3 Month Avg\. Volume</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)

# 52 Week Lo/Hi
_WEEK52_LO_PATTERN = re.compile(
    r"<span>52 Week Lo</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)
_WEEK52_HI_PATTERN = re.compile(
    r"<span>52 Week Hi</span>\s*<span[^>]*>([^<]+)</span>",
    re.IGNORECASE,
)


def _parse_money_value(raw: str) -> float | None:
    """금액 문자열을 숫자로 변환한다.

    '$11,805.0 M', '-461.91 M', '1.25 B', '-5.47 B' 등의 형식을 처리한다.
    단위(M=백만, B=십억, T=조)를 반영한다.
    """
    text = raw.strip().replace("$", "").replace(",", "").strip()
    if not text or text == "N/A" or text == "--":
        return None

    multiplier = 1.0
    # 단위 접미사를 확인한다
    if text.upper().endswith("T"):
        multiplier = 1_000_000_000_000
        text = text[:-1].strip()
    elif text.upper().endswith("B"):
        multiplier = 1_000_000_000
        text = text[:-1].strip()
    elif text.upper().endswith("M"):
        multiplier = 1_000_000
        text = text[:-1].strip()
    elif text.upper().endswith("K"):
        multiplier = 1_000
        text = text[:-1].strip()

    try:
        return float(text) * multiplier
    except (ValueError, TypeError):
        return None


def _parse_percentage(raw: str) -> float | None:
    """퍼센트 문자열을 숫자로 변환한다. '0.75%' → 0.75."""
    text = raw.strip().replace("%", "").replace(",", "").strip()
    if not text or text == "N/A" or text == "--":
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _parse_number(raw: str) -> float | None:
    """일반 숫자 문자열을 float로 변환한다. '87,188,552' → 87188552.0."""
    text = raw.strip().replace(",", "").replace("$", "").strip()
    if not text or text == "N/A" or text == "--":
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _extract_ticker_data(html: str, ticker: str) -> dict[str, Any]:
    """ETFdb.com HTML에서 단일 티커의 핵심 데이터를 추출한다."""
    result: dict[str, Any] = {"ticker": ticker}

    # AUM 추출
    m = _AUM_PATTERN.search(html)
    if m:
        result["aum"] = _parse_money_value(m.group(1))
        result["aum_raw"] = m.group(1).strip()

    # Expense Ratio 추출
    m = _EXPENSE_RATIO_PATTERN.search(html)
    if m:
        result["expense_ratio_pct"] = _parse_percentage(m.group(1))

    # Average Spread 추출
    m = _AVG_SPREAD_PCT_PATTERN.search(html)
    if m:
        result["avg_spread_pct"] = _parse_number(m.group(1))

    m = _AVG_SPREAD_USD_PATTERN.search(html)
    if m:
        result["avg_spread_usd"] = _parse_number(m.group(1))

    # Net Fund Flows (5일, 1개월, 3개월) 추출
    m = _FLOW_5D_PATTERN.search(html)
    if m:
        result["flow_5d"] = _parse_money_value(m.group(1))
        result["flow_5d_raw"] = m.group(1).strip()

    m = _FLOW_1M_PATTERN.search(html)
    if m:
        result["flow_1m"] = _parse_money_value(m.group(1))
        result["flow_1m_raw"] = m.group(1).strip()

    m = _FLOW_3M_PATTERN.search(html)
    if m:
        result["flow_3m"] = _parse_money_value(m.group(1))
        result["flow_3m_raw"] = m.group(1).strip()

    # Net AUM Change (5일, 1개월, 3개월) 추출
    m = _AUM_CHANGE_5D_PATTERN.search(html)
    if m:
        result["aum_change_5d"] = _parse_money_value(m.group(1))

    m = _AUM_CHANGE_1M_PATTERN.search(html)
    if m:
        result["aum_change_1m"] = _parse_money_value(m.group(1))

    m = _AUM_CHANGE_3M_PATTERN.search(html)
    if m:
        result["aum_change_3m"] = _parse_money_value(m.group(1))

    # 평균 거래량 추출
    m = _VOL_1M_PATTERN.search(html)
    if m:
        result["avg_volume_1m"] = _parse_number(m.group(1))

    m = _VOL_3M_PATTERN.search(html)
    if m:
        result["avg_volume_3m"] = _parse_number(m.group(1))

    # 52주 최저/최고 추출
    m = _WEEK52_LO_PATTERN.search(html)
    if m:
        result["week52_lo"] = _parse_number(m.group(1))

    m = _WEEK52_HI_PATTERN.search(html)
    if m:
        result["week52_hi"] = _parse_number(m.group(1))

    return result


class EtfFlowFetcher:
    """ETF 펀드 플로우/AUM 수집기이다.

    ETFdb.com에서 대상 티커별 AUM, 순유입/유출, 비용비율, 스프레드 등을
    스크래핑한다. 실패 시 마지막 성공 캐시를 폴백으로 사용한다.

    ETF.com은 Cloudflare 차단으로 접근 불가하여 ETFdb.com을 대안으로 사용한다.
    """

    def __init__(self, cache: CacheClient, http: AsyncHttpClient) -> None:
        """의존성을 주입받는다."""
        self._cache = cache
        self._http = http

    async def fetch(self) -> dict[str, dict[str, Any]]:
        """전체 대상 티커의 ETF 데이터를 수집한다.

        Returns:
            티커별 데이터 딕셔너리. 키=티커, 값=데이터 딕셔너리.
            실패 시 폴백 캐시 또는 빈 딕셔너리.
        """
        # 캐시 확인 — 첫 번째 티커 캐시가 있으면 전체 캐시 유효로 간주한다
        cached = await self._read_all_from_cache()
        if cached:
            logger.debug("ETF 플로우 캐시 히트: %d 티커", len(cached))
            return cached

        # 순차적으로 각 티커를 스크래핑한다 — rate limit 방지
        results: dict[str, dict[str, Any]] = {}
        for i, ticker in enumerate(_TARGET_TICKERS):
            data = await self._fetch_ticker(ticker)
            if data and len(data) > 1:  # ticker 필드 외에 데이터가 있어야 유효
                results[ticker] = data
            # 마지막 티커 이후에는 딜레이 불필요
            if i < len(_TARGET_TICKERS) - 1:
                await asyncio.sleep(_INTER_REQUEST_DELAY)

        if results:
            await self._write_all_to_cache(results)
            logger.info(
                "ETF 플로우 수집 완료: %d/%d 티커",
                len(results),
                len(_TARGET_TICKERS),
            )
            return results

        # 폴백: 마지막 성공 캐시
        fallback = await self._read_cache_json(_LAST_SUCCESS_KEY)
        if fallback and isinstance(fallback, dict):
            logger.warning(
                "ETF 플로우 스크래핑 실패 — 폴백 캐시 사용 (%d 티커)",
                len(fallback),
            )
            return fallback

        logger.warning("ETF 플로우 수집 실패 — 데이터 없음")
        return {}

    async def fetch_ticker(self, ticker: str) -> dict[str, Any]:
        """단일 티커의 ETF 데이터를 수집한다.

        Args:
            ticker: ETF 티커 심볼 (예: SOXL)

        Returns:
            티커 데이터 딕셔너리. 실패 시 빈 딕셔너리.
        """
        cache_key = f"{_CACHE_KEY_PREFIX}:{ticker}"
        cached = await self._read_cache_json(cache_key)
        if cached and isinstance(cached, dict):
            return cached

        data = await self._fetch_ticker(ticker)
        if data and len(data) > 1:
            await self._write_cache_json(cache_key, data, ttl=_CACHE_TTL)
            return data
        return {}

    async def _fetch_ticker(self, ticker: str) -> dict[str, Any]:
        """ETFdb.com에서 단일 티커 페이지를 스크래핑한다."""
        url = _BASE_URL.format(ticker=ticker)
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await asyncio.wait_for(
                    self._http.get(url, headers=_HEADERS),
                    timeout=_REQUEST_TIMEOUT,
                )

                if resp.status == 429:
                    delay = _RETRY_DELAY * (attempt + 1)
                    logger.warning(
                        "ETFdb rate limit (%s) — %.0fs 대기", ticker, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status == 403:
                    logger.warning(
                        "ETFdb 접근 차단 (%s, 403) — 스크래핑 불가", ticker,
                    )
                    return {}

                if not resp.ok:
                    logger.debug(
                        "ETFdb 응답 실패 (%s): status=%d", ticker, resp.status,
                    )
                    continue

                data = _extract_ticker_data(resp.body, ticker)

                # AUM이 없으면 파싱 실패로 간주한다
                if data.get("aum") is None and data.get("aum_raw") is None:
                    logger.warning(
                        "ETFdb %s 파싱 결과에 AUM 없음 — HTML 구조 변경 가능성",
                        ticker,
                    )
                    # 다른 데이터가 있으면 부분 결과라도 반환한다
                    if len(data) > 1:
                        return data
                    return {}

                return data

            except asyncio.TimeoutError:
                logger.debug(
                    "ETFdb 타임아웃 (%s, 시도 %d/%d)",
                    ticker,
                    attempt + 1,
                    _MAX_RETRIES,
                )
            except Exception as exc:
                logger.debug("ETFdb 스크래핑 실패 (%s): %s", ticker, exc)
                return {}

        return {}

    async def _read_all_from_cache(self) -> dict[str, dict[str, Any]]:
        """전체 티커 캐시를 읽는다. 하나라도 없으면 None을 반환한다."""
        results: dict[str, dict[str, Any]] = {}
        for ticker in _TARGET_TICKERS:
            cache_key = f"{_CACHE_KEY_PREFIX}:{ticker}"
            data = await self._read_cache_json(cache_key)
            if data is None or not isinstance(data, dict):
                return {}  # 하나라도 캐시 미스면 전체 재수집
            results[ticker] = data
        return results

    async def _write_all_to_cache(
        self, data: dict[str, dict[str, Any]],
    ) -> None:
        """전체 티커 데이터를 캐시에 저장한다."""
        for ticker, ticker_data in data.items():
            cache_key = f"{_CACHE_KEY_PREFIX}:{ticker}"
            await self._write_cache_json(cache_key, ticker_data, ttl=_CACHE_TTL)
        # 폴백 캐시에도 전체 데이터 저장
        await self._write_cache_json(
            _LAST_SUCCESS_KEY, data, ttl=_LAST_SUCCESS_TTL,
        )

    async def _read_cache_json(self, key: str) -> dict | list | None:
        """캐시에서 JSON 데이터를 읽는다."""
        try:
            return await self._cache.read_json(key)
        except Exception as exc:
            logger.debug("ETF 플로우 캐시 읽기 실패 (%s): %s", key, exc)
            return None

    async def _write_cache_json(
        self,
        key: str,
        data: dict | list,
        ttl: int | None = None,
    ) -> None:
        """캐시에 JSON 데이터를 저장한다."""
        try:
            await self._cache.write_json(key, data, ttl=ttl)
        except Exception as exc:
            logger.debug("ETF 플로우 캐시 저장 실패 (%s): %s", key, exc)
