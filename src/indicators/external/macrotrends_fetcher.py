"""외부 지표 -- Macrotrends 밸류에이션 데이터를 수집한다.

Macrotrends 웹사이트에서 주요 기초 종목의 P/E 비율, 매출 성장률 등
밸류에이션 지표를 스크래핑하여 캐시에 저장한다.
API 키 불필요 (HTML 스크래핑). 캐시 키: macro:valuation:{ticker} (TTL 86400초).
반도체/기술 섹터의 핵심 종목을 대상으로 한다.
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

# 캐시 설정이다
_CACHE_KEY_PREFIX: str = "macro:valuation"
_CACHE_TTL: int = 86400  # 24시간
_LAST_SUCCESS_KEY: str = "macro:valuation:last_success"
_LAST_SUCCESS_TTL: int = 86400 * 7  # 7일 폴백 유지

# 요청 설정이다
_REQUEST_TIMEOUT: float = 15.0
_MAX_RETRIES: int = 2
_INTER_TICKER_DELAY: float = 1.0  # 티커 간 딜레이(초)

# 티커별 회사명 매핑이다 — Macrotrends URL 경로에 사용한다
_TICKER_COMPANY_MAP: dict[str, str] = {
    # 반도체
    "NVDA": "nvidia",
    "AMD": "advanced-micro-devices",
    "AVGO": "broadcom",
    "INTC": "intel",
    # 기술
    "AAPL": "apple",
    "MSFT": "microsoft",
    "AMZN": "amazon",
    "GOOGL": "alphabet",
}

# 섹터 그룹 정의이다
SECTOR_SEMICONDUCTORS: list[str] = ["NVDA", "AMD", "AVGO", "INTC"]
SECTOR_TECH: list[str] = ["AAPL", "MSFT", "AMZN", "GOOGL"]

# 스크래핑용 User-Agent이다
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Macrotrends URL 패턴이다
_BASE_URL: str = "https://www.macrotrends.net/stocks/charts"

# HTML 파싱용 정규식이다

# P/E ratio 테이블에서 날짜+주가+(EPS)+PE 4열 행을 추출한다
# EPS 열이 비어있을 수 있어 유연하게 매칭한다
_PE_TABLE_ROW_PATTERN = re.compile(
    r'<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*'
    r'<td[^>]*>[^<]*</td>\s*'
    r'<td[^>]*>[^<]*</td>\s*'
    r'<td[^>]*>([\d,.]+)</td>',
    re.DOTALL,
)

# meta description에서 현재 P/E를 추출한다
# 형식: "PE ratio as of March 20, 2026 is <strong>47.48</strong>"
# HTML 엔코딩된 형식도 처리한다
_META_PE_PATTERN = re.compile(
    r'PE ratio as of.*?'
    r'(?:&lt;strong&gt;|<strong>)([\d,.]+)(?:&lt;/strong&gt;|</strong>)',
    re.IGNORECASE,
)

# 시가총액 추출 패턴이다 — 회사 정보 테이블에서 $4442.283B 형식을 추출한다
_MARKET_CAP_TABLE_PATTERN = re.compile(
    r'\$([\d,.]+)(B|T|M)\b',
)

# 연간 매출 테이블에서 연도+매출 행을 추출한다
# 형식: <td>2026</td><td>$215,938</td>
_ANNUAL_REVENUE_PATTERN = re.compile(
    r'<td[^>]*>(\d{4})</td>\s*'
    r"<td[^>]*>\$?([\d,]+)</td>",
    re.DOTALL,
)


def _parse_number(raw: str) -> float | None:
    """문자열에서 숫자를 파싱한다. 쉼표/달러 기호를 제거한다."""
    try:
        cleaned = raw.replace(",", "").replace("$", "").strip()
        if not cleaned:
            return None
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _extract_market_cap(html: str) -> float | None:
    """회사 정보 테이블에서 시가총액을 추출한다. 십억 달러 단위로 반환한다.

    Macrotrends는 Market Cap 열에 $4442.283B 형식으로 표기한다.
    B=Billion, T=Trillion, M=Million으로 변환한다.
    """
    # Market Cap 헤더가 있는 테이블에서만 검색한다
    cap_section = re.search(
        r"Market Cap.*?<td[^>]*>(\$[\d,.]+[BTM])</td>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not cap_section:
        return None
    raw = cap_section.group(1)
    match = _MARKET_CAP_TABLE_PATTERN.search(raw)
    if not match:
        return None
    value = _parse_number(match.group(1))
    if value is None:
        return None
    unit = match.group(2)
    if unit == "T":
        return round(value * 1000, 2)
    if unit == "M":
        return round(value / 1000, 4)
    # B (Billion)
    return round(value, 2)


def _extract_pe_from_html(html: str) -> float | None:
    """P/E ratio 페이지 HTML에서 최신 P/E 값을 추출한다.

    방법 1: meta description에서 현재 P/E를 추출한다 (가장 정확).
    방법 2: P/E 데이터 테이블 행에서 최근 날짜의 값을 추출한다.
    """
    # 방법 1: meta description에서 추출한다 — "PE ratio as of ... is <strong>47.48</strong>"
    meta_match = _META_PE_PATTERN.search(html)
    if meta_match:
        value = _parse_number(meta_match.group(1))
        if value is not None and value > 0:
            return value

    # 방법 2: 테이블 행에서 추출한다
    matches = _PE_TABLE_ROW_PATTERN.findall(html)
    if matches:
        # 날짜 기준 최신 행의 P/E를 사용한다
        latest = sorted(matches, key=lambda x: x[0], reverse=True)[0]
        return _parse_number(latest[1])

    return None


def _compute_revenue_growth(html: str) -> float | None:
    """매출 페이지 HTML에서 YoY 매출 성장률을 계산한다.

    연간 매출 테이블에서 최근 2개 연도의 매출을 비교하여 성장률(%)을 반환한다.
    형식: <td>2026</td><td>$215,938</td>
    """
    matches = _ANNUAL_REVENUE_PATTERN.findall(html)
    if len(matches) < 2:
        return None

    # 연도 기준 정렬 후 최근 2개를 비교한다
    sorted_rows = sorted(matches, key=lambda x: x[0], reverse=True)
    latest_rev = _parse_number(sorted_rows[0][1])
    prev_rev = _parse_number(sorted_rows[1][1])

    if latest_rev is None or prev_rev is None or prev_rev == 0:
        return None

    growth = ((latest_rev - prev_rev) / prev_rev) * 100
    return round(growth, 2)


class MacrotrendsFetcher:
    """Macrotrends 밸류에이션 데이터 수집기이다.

    주요 기초 종목(반도체/기술)의 P/E 비율, 매출 성장률,
    시가총액 등을 스크래핑하여 캐시에 저장한다.
    Cloudflare가 요청을 차단하면 해당 티커를 건너뛰고 마지막 성공 캐시를 폴백으로 사용한다.
    """

    def __init__(self, cache: CacheClient, http: AsyncHttpClient) -> None:
        """의존성을 주입받는다."""
        self._cache = cache
        self._http = http

    async def fetch(self) -> dict[str, dict[str, Any]]:
        """전체 대상 종목의 밸류에이션 데이터를 수집한다.

        Returns:
            티커별 밸류에이션 데이터 dict. 실패 시 폴백 또는 빈 dict.
        """
        results: dict[str, dict[str, Any]] = {}

        for ticker in _TICKER_COMPANY_MAP:
            data = await self._fetch_ticker(ticker)
            if data:
                results[ticker] = data
            # 티커 간 딜레이로 rate limit을 방지한다
            await asyncio.sleep(_INTER_TICKER_DELAY)

        if results:
            # 폴백 캐시에도 전체 결과를 저장한다
            await self._write_last_success(results)
            logger.info(
                "Macrotrends 수집 완료: %d/%d 종목",
                len(results), len(_TICKER_COMPANY_MAP),
            )
            return results

        # 전체 실패 시 폴백 캐시를 사용한다
        fallback = await self._read_last_success()
        if fallback:
            logger.warning(
                "Macrotrends 전체 실패 — 폴백 캐시 사용 (%d종목)", len(fallback),
            )
            return fallback

        logger.warning("Macrotrends 수집 실패 — 데이터 없음")
        return {}

    def get_sector_average(
        self,
        data: dict[str, dict[str, Any]],
        tickers: list[str],
    ) -> dict[str, float | None]:
        """섹터 그룹의 평균 P/E를 계산한다.

        Args:
            data: fetch()에서 반환된 전체 밸류에이션 데이터
            tickers: 섹터에 속하는 티커 리스트

        Returns:
            avg_pe, avg_revenue_growth를 포함하는 dict.
            데이터 부족 시 해당 필드는 None이다.
        """
        pe_values: list[float] = []
        growth_values: list[float] = []

        for ticker in tickers:
            ticker_data = data.get(ticker)
            if not ticker_data:
                continue
            pe = ticker_data.get("pe_ratio")
            if pe is not None:
                pe_values.append(pe)
            growth = ticker_data.get("revenue_growth_yoy")
            if growth is not None:
                growth_values.append(growth)

        return {
            "avg_pe": round(sum(pe_values) / len(pe_values), 2) if pe_values else None,
            "avg_revenue_growth": (
                round(sum(growth_values) / len(growth_values), 2)
                if growth_values else None
            ),
            "ticker_count": len(tickers),
            "data_count": len(pe_values),
        }

    async def _fetch_ticker(self, ticker: str) -> dict[str, Any] | None:
        """개별 종목의 밸류에이션 데이터를 수집한다.

        캐시 히트 시 즉시 반환한다. 캐시 미스 시 P/E + 매출 페이지를 스크래핑한다.
        """
        cache_key = f"{_CACHE_KEY_PREFIX}:{ticker}"

        # 캐시 확인
        cached = await self._read_cache(cache_key)
        if cached is not None:
            logger.debug("Macrotrends %s 캐시 히트", ticker)
            return cached

        company = _TICKER_COMPANY_MAP.get(ticker)
        if not company:
            logger.debug("Macrotrends %s — 회사명 매핑 없음", ticker)
            return None

        # P/E ratio 페이지 스크래핑
        pe_data = await self._scrape_pe_page(ticker, company)

        # Revenue 페이지 스크래핑
        revenue_growth = await self._scrape_revenue_page(ticker, company)

        # 데이터가 하나라도 있으면 결과를 구성한다
        if pe_data is None and revenue_growth is None:
            logger.debug("Macrotrends %s — 데이터 추출 실패", ticker)
            return None

        result: dict[str, Any] = {
            "ticker": ticker,
            "pe_ratio": pe_data.get("pe_ratio") if pe_data else None,
            "market_cap_billion": pe_data.get("market_cap_billion") if pe_data else None,
            "revenue_growth_yoy": revenue_growth,
            "source": "macrotrends",
        }

        # 캐시에 저장한다
        await self._write_cache(cache_key, result)
        logger.info(
            "Macrotrends %s 수집 완료: PE=%.1f",
            ticker, result.get("pe_ratio") or 0,
        )
        return result

    async def _scrape_pe_page(
        self, ticker: str, company: str,
    ) -> dict[str, Any] | None:
        """P/E ratio 페이지를 스크래핑한다.

        단순 URL (/x/) 패턴을 먼저 시도하고, 실패 시 정규 URL을 시도한다.
        P/E 비율 + 시가총액을 동일 페이지에서 추출한다.
        """
        urls = [
            f"{_BASE_URL}/{ticker}/x/pe-ratio",
            f"{_BASE_URL}/{ticker}/{company}/pe-ratio",
        ]

        for url in urls:
            html = await self._fetch_page(url, ticker)
            if html is None:
                continue

            pe_ratio = _extract_pe_from_html(html)
            market_cap = _extract_market_cap(html)

            if pe_ratio is not None:
                return {
                    "pe_ratio": pe_ratio,
                    "market_cap_billion": market_cap,
                }

        return None

    async def _scrape_revenue_page(
        self, ticker: str, company: str,
    ) -> float | None:
        """Revenue 페이지를 스크래핑하여 YoY 성장률을 계산한다."""
        urls = [
            f"{_BASE_URL}/{ticker}/x/revenue",
            f"{_BASE_URL}/{ticker}/{company}/revenue",
        ]

        for url in urls:
            html = await self._fetch_page(url, ticker)
            if html is None:
                continue

            growth = _compute_revenue_growth(html)
            if growth is not None:
                return growth

        return None

    async def _fetch_page(self, url: str, ticker: str) -> str | None:
        """단일 페이지를 조회한다. 실패 시 None을 반환한다."""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await asyncio.wait_for(
                    self._http.get(url, headers=_HEADERS),
                    timeout=_REQUEST_TIMEOUT,
                )

                if resp.status == 403:
                    logger.debug(
                        "Macrotrends %s 접근 차단 (403) — 건너뜀", ticker,
                    )
                    return None

                if resp.status == 429:
                    delay = _INTER_TICKER_DELAY * (attempt + 1)
                    logger.warning(
                        "Macrotrends %s rate limit — %.0fs 대기", ticker, delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status in (301, 302, 308):
                    # 리다이렉트 — 다음 URL 패턴을 시도한다
                    logger.debug(
                        "Macrotrends %s 리다이렉트 (%d) — 다음 URL 시도",
                        ticker, resp.status,
                    )
                    return None

                if not resp.ok:
                    logger.debug(
                        "Macrotrends %s 응답 실패: url=%s status=%d",
                        ticker, url, resp.status,
                    )
                    return None

                # Cloudflare 챌린지 페이지 감지 — 200이지만 본문이 짧고 "Just a moment" 포함
                if len(resp.body) < 10000 and "Just a moment" in resp.body:
                    logger.debug(
                        "Macrotrends %s Cloudflare 챌린지 감지 — 건너뜀", ticker,
                    )
                    return None

                return resp.body

            except asyncio.TimeoutError:
                logger.debug(
                    "Macrotrends %s 타임아웃 (시도 %d/%d)",
                    ticker, attempt + 1, _MAX_RETRIES,
                )
            except Exception as exc:
                logger.debug(
                    "Macrotrends %s 스크래핑 실패: %s", ticker, exc,
                )
                return None

        return None

    async def _read_cache(self, key: str) -> dict[str, Any] | None:
        """캐시에서 데이터를 읽는다."""
        try:
            cached = await self._cache.read_json(key)
            if cached and isinstance(cached, dict):
                return cached
        except Exception as exc:
            logger.debug("Macrotrends 캐시 읽기 실패 (%s): %s", key, exc)
        return None

    async def _write_cache(self, key: str, data: dict[str, Any]) -> None:
        """개별 티커 캐시에 저장한다."""
        try:
            await self._cache.write_json(key, data, ttl=_CACHE_TTL)
        except Exception as exc:
            logger.debug("Macrotrends 캐시 저장 실패 (%s): %s", key, exc)

    async def _read_last_success(self) -> dict[str, dict[str, Any]] | None:
        """마지막 성공 폴백 캐시를 읽는다."""
        try:
            cached = await self._cache.read_json(_LAST_SUCCESS_KEY)
            if cached and isinstance(cached, dict):
                return cached
        except Exception as exc:
            logger.debug("Macrotrends 폴백 캐시 읽기 실패: %s", exc)
        return None

    async def _write_last_success(self, data: dict[str, dict[str, Any]]) -> None:
        """폴백 캐시에 전체 결과를 저장한다."""
        try:
            await self._cache.write_json(
                _LAST_SUCCESS_KEY, data, ttl=_LAST_SUCCESS_TTL,
            )
        except Exception as exc:
            logger.debug("Macrotrends 폴백 캐시 저장 실패: %s", exc)
