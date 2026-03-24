"""외부 지표 -- 애널리스트 컨센서스 데이터를 수집한다.

2x ETF 기초자산의 애널리스트 투자의견(Buy/Hold/Sell)과
목표주가를 수집하여 AI 프롬프트 주입용 요약을 생성한다.
API 키 불필요. Nasdaq API(주) → TipRanks(폴백) 순서로 시도한다.
캐시 키: analyst:consensus:{ticker} (TTL 86400초).
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from src.common.logger import get_logger
from src.indicators.external._consensus_parsers import (
    determine_consensus,
    parse_nasdaq,
    parse_tipranks_forecast_html,
    parse_tipranks_overview,
    parse_tipranks_sentiment,
)

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient
    from src.common.http_client import AsyncHttpClient

logger = get_logger(__name__)

# -- 2x ETF → 기초자산 매핑이다 --
ETF_UNDERLYING_MAP: dict[str, list[str]] = {
    "SOXL": ["NVDA", "AMD", "AVGO", "QCOM", "INTC"],
    "SOXS": ["NVDA", "AMD", "AVGO", "QCOM", "INTC"],
    "QLD": ["AAPL", "MSFT", "AMZN", "GOOGL", "META"],
    "QID": ["AAPL", "MSFT", "AMZN", "GOOGL", "META"],
}

# 중복 제거한 전체 기초자산 목록이다
_ALL_TICKERS: list[str] = sorted({
    t for tickers in ETF_UNDERLYING_MAP.values() for t in tickers
})

# -- 엔드포인트 URL이다 --
_NASDAQ_URL: str = "https://api.nasdaq.com/api/analyst/{ticker}/targetprice"
_TR_SENTIMENT_URL: str = "https://www.tipranks.com/api/stocks/getNewsSentiments/"
_TR_OVERVIEW_URL: str = "https://www.tipranks.com/api/stocks/stockAnalysisOverview/"
_TR_FORECAST_URL: str = "https://www.tipranks.com/stocks/{ticker}/forecast"

# -- 캐시 설정이다 --
_CACHE_PREFIX: str = "analyst:consensus"
_CACHE_TTL: int = 86400  # 24시간
_LAST_SUCCESS_KEY: str = "analyst:consensus:last_success"
_LAST_SUCCESS_TTL: int = 86400 * 3  # 72시간 폴백

# -- 요청 설정이다 --
_TIMEOUT: float = 10.0
_MAX_RETRIES: int = 2
_RETRY_DELAY: float = 2.0
_TICKER_DELAY: float = 0.5  # 티커 간 딜레이(초)

# -- HTTP 헤더이다 --
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
}


def _cache_key(ticker: str) -> str:
    """티커별 캐시 키를 생성한다."""
    return f"{_CACHE_PREFIX}:{ticker}"


class TipRanksFetcher:
    """애널리스트 컨센서스 수집기이다.

    2x ETF 기초자산의 애널리스트 투자의견과 목표주가를 수집한다.
    데이터 소스 우선순위:
        1. Nasdaq targetprice API (공개, 안정적)
        2. TipRanks Sentiment API (Cloudflare 차단 가능)
        3. TipRanks Overview API (Cloudflare 차단 가능)
        4. TipRanks Forecast 페이지 스크래핑 (Cloudflare 차단 가능)
    실패 시 마지막 성공 캐시를 폴백으로 사용한다 (72시간 TTL).
    """

    def __init__(self, cache: CacheClient, http: AsyncHttpClient) -> None:
        """의존성을 주입받는다."""
        self._cache = cache
        self._http = http

    async def fetch(self) -> dict[str, dict[str, Any]]:
        """전체 기초자산의 컨센서스 데이터를 수집한다.

        Returns:
            {ticker: consensus_data} 딕셔너리. 실패한 티커는 제외된다.
        """
        results: dict[str, dict[str, Any]] = {}

        for ticker in _ALL_TICKERS:
            data = await self._fetch_ticker(ticker)
            if data:
                results[ticker] = data
            await asyncio.sleep(_TICKER_DELAY)

        if results:
            await self._write_last_success(results)
            logger.info(
                "애널리스트 컨센서스 수집 완료: %d/%d 티커",
                len(results), len(_ALL_TICKERS),
            )
            return results

        # 전부 실패 시 폴백 캐시이다
        fallback = await self._read_last_success()
        if fallback:
            logger.warning("컨센서스 전체 실패 — 폴백 사용 (%d건)", len(fallback))
            return fallback

        logger.warning("애널리스트 컨센서스 수집 실패 — 데이터 없음")
        return {}

    async def fetch_summary(self) -> str:
        """AI 프롬프트 주입용 요약 문자열을 생성한다."""
        data = await self.fetch()
        if not data:
            return "애널리스트 컨센서스: 데이터 없음"

        lines: list[str] = ["[애널리스트 컨센서스]"]

        for etf, tickers in ETF_UNDERLYING_MAP.items():
            # 중복 ETF는 건너뛴다 (SOXL/SOXS, QLD/QID 동일 기초자산)
            if etf in ("SOXS", "QID"):
                continue

            etf_label = "SOXL/SOXS" if etf == "SOXL" else "QLD/QID"
            ticker_lines: list[str] = []
            b_sum, h_sum, s_sum = 0, 0, 0

            for ticker in tickers:
                c = data.get(ticker)
                if not c:
                    ticker_lines.append(f"  {ticker}: N/A")
                    continue

                b, h, s = c.get("buy", 0), c.get("hold", 0), c.get("sell", 0)
                b_sum += b
                h_sum += h
                s_sum += s

                tgt = c.get("avg_target")
                tgt_str = f" 목표${tgt}" if tgt else ""
                ticker_lines.append(
                    f"  {ticker}: {c.get('consensus', 'N/A')} "
                    f"(B{b}/H{h}/S{s}){tgt_str}"
                )

            total = b_sum + h_sum + s_sum
            if total > 0:
                overall = determine_consensus(b_sum, h_sum, s_sum)
                lines.append(
                    f"{etf_label} 종합: {overall} "
                    f"(B{b_sum}/H{h_sum}/S{s_sum})"
                )
            else:
                lines.append(f"{etf_label} 종합: N/A")

            lines.extend(ticker_lines)

        return "\n".join(lines)

    # ── 티커별 수집이다 ──

    async def _fetch_ticker(self, ticker: str) -> dict[str, Any] | None:
        """단일 티커 컨센서스를 수집한다. 캐시 → Nasdaq → TipRanks 순서이다."""
        cached = await self._read_ticker_cache(ticker)
        if cached is not None:
            logger.debug("컨센서스 %s 캐시 히트", ticker)
            return cached

        # Nasdaq API (주 소스)이다
        data = await self._try_source(
            _NASDAQ_URL.format(ticker=ticker), parse_nasdaq, ticker,
        )
        if data:
            await self._write_ticker_cache(ticker, data)
            return data

        # TipRanks 폴백이다 — Cloudflare에 의해 대부분 차단된다
        for url, parser in [
            (_TR_SENTIMENT_URL, parse_tipranks_sentiment),
            (_TR_OVERVIEW_URL, parse_tipranks_overview),
        ]:
            data = await self._try_source(
                url, parser, ticker, params={"ticker": ticker},
                extra_headers={"Referer": "https://www.tipranks.com/"},
            )
            if data:
                await self._write_ticker_cache(ticker, data)
                return data

        # TipRanks forecast 스크래핑이다
        data = await self._try_forecast_scrape(ticker)
        if data:
            await self._write_ticker_cache(ticker, data)
            return data

        logger.warning("컨센서스 %s 모든 소스 실패", ticker)
        return None

    async def _try_source(
        self,
        url: str,
        parser: Any,
        ticker: str,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """단일 API 소스를 시도한다."""
        headers = {**_HEADERS, **(extra_headers or {})}
        body = await self._request(url, params=params, headers=headers)
        if body is None:
            return None
        try:
            return parser(json.loads(body))
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug("JSON 파싱 실패 (%s, %s): %s", ticker, url, exc)
            return None

    async def _try_forecast_scrape(
        self, ticker: str,
    ) -> dict[str, Any] | None:
        """TipRanks forecast 페이지를 스크래핑한다."""
        url = _TR_FORECAST_URL.format(ticker=ticker.lower())
        headers = {
            **_HEADERS,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Referer": "https://www.tipranks.com/",
        }
        body = await self._request(url, headers=headers)
        if body is None:
            return None
        return parse_tipranks_forecast_html(body)

    # ── HTTP 헬퍼이다 ──

    async def _request(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str | None:
        """재시도 + rate limit 대응 HTTP 요청이다. 성공 시 body, 실패 시 None."""
        hdrs = headers or dict(_HEADERS)

        for attempt in range(_MAX_RETRIES):
            try:
                resp = await asyncio.wait_for(
                    self._http.get(url, headers=hdrs, params=params),
                    timeout=_TIMEOUT,
                )
                if resp.status == 429:
                    delay = _RETRY_DELAY * (2 ** attempt)
                    logger.warning(
                        "Rate limit (429): %s — %.0fs 대기 (%d/%d)",
                        url, delay, attempt + 1, _MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue
                if resp.status == 403:
                    logger.debug("접근 차단 (403): %s", url)
                    return None
                if not resp.ok:
                    logger.debug("HTTP %d: %s", resp.status, url)
                    return None
                return resp.body
            except asyncio.TimeoutError:
                logger.debug("타임아웃: %s (%d/%d)", url, attempt + 1, _MAX_RETRIES)
            except Exception as exc:
                logger.debug("요청 실패: %s — %s", url, exc)
                return None
        return None

    # ── 캐시 헬퍼이다 ──

    async def _read_ticker_cache(self, ticker: str) -> dict[str, Any] | None:
        """개별 티커 캐시를 읽는다."""
        try:
            cached = await self._cache.read_json(_cache_key(ticker))
            if cached and isinstance(cached, dict):
                return cached
        except Exception as exc:
            logger.debug("캐시 읽기 실패 (%s): %s", ticker, exc)
        return None

    async def _write_ticker_cache(self, ticker: str, data: dict[str, Any]) -> None:
        """개별 티커 캐시에 저장한다."""
        try:
            await self._cache.write_json(_cache_key(ticker), data, ttl=_CACHE_TTL)
        except Exception as exc:
            logger.debug("캐시 저장 실패 (%s): %s", ticker, exc)

    async def _read_last_success(self) -> dict[str, dict[str, Any]] | None:
        """마지막 성공 폴백 캐시를 읽는다."""
        try:
            cached = await self._cache.read_json(_LAST_SUCCESS_KEY)
            if cached and isinstance(cached, dict):
                return cached
        except Exception as exc:
            logger.debug("폴백 캐시 읽기 실패: %s", exc)
        return None

    async def _write_last_success(self, data: dict[str, dict[str, Any]]) -> None:
        """전체 결과를 폴백 캐시에 저장한다."""
        try:
            await self._cache.write_json(_LAST_SUCCESS_KEY, data, ttl=_LAST_SUCCESS_TTL)
        except Exception as exc:
            logger.debug("폴백 캐시 저장 실패: %s", exc)
