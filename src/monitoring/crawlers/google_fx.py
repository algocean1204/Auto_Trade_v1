"""구글 환율 크롤러 -- USD/KRW 환율을 구글에서 크롤링한다.

FxScheduler의 3차 (최종) 폴백 소스로 사용된다.
구글 Finance 페이지에서 USD/KRW 환율을 파싱한다.
"""
from __future__ import annotations

import re

import aiohttp

from src.common.logger import get_logger

_logger = get_logger(__name__)

# 구글 Finance USD-KRW 페이지 URL이다
_GOOGLE_FINANCE_URL = "https://www.google.com/finance/quote/USD-KRW"

# 구글 검색 환율 URL이다
_GOOGLE_SEARCH_URL = "https://www.google.com/search?q=1+USD+to+KRW"

# 요청 타임아웃(초)이다
_REQUEST_TIMEOUT: int = 10

# 구글 Finance 페이지에서 환율을 추출하는 정규식 패턴이다
# data-last-price 속성에서 숫자를 추출한다
_FINANCE_RATE_PATTERN = re.compile(
    r'data-last-price="([\d.]+)"',
)

# 대체 패턴: 페이지 본문에서 큰 숫자를 찾는다
_ALT_RATE_PATTERN = re.compile(
    r'class="[^"]*YMlKec[^"]*"[^>]*>([\d,]+\.?\d*)',
)

# 구글 검색 결과에서 환율을 추출하는 패턴이다
_SEARCH_RATE_PATTERN = re.compile(
    r'([\d,]+\.?\d*)\s*(?:대한민국\s*원|South\s*Korean\s*Won|KRW)',
)


async def fetch_google_usd_krw() -> float | None:
    """구글에서 USD/KRW 환율을 크롤링한다.

    성공 시 float 환율, 실패 시 None을 반환한다.
    두 가지 소스를 순차적으로 시도한다:
      1. 구글 Finance 페이지
      2. 구글 검색 결과
    """
    # 1차: 구글 Finance 페이지
    rate = await _try_google_finance()
    if rate is not None:
        return rate

    # 2차: 구글 검색 결과
    rate = await _try_google_search()
    if rate is not None:
        return rate

    _logger.warning("구글 환율 크롤링 모두 실패")
    return None


async def _try_google_finance() -> float | None:
    """구글 Finance 페이지에서 환율을 파싱한다."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_GOOGLE_FINANCE_URL, headers=headers) as resp:
                if resp.status != 200:
                    _logger.debug("구글 Finance HTTP %d", resp.status)
                    return None
                html = await resp.text()

        # data-last-price 속성에서 추출을 시도한다
        match = _FINANCE_RATE_PATTERN.search(html)
        if match:
            rate = float(match.group(1))
            if 900 < rate < 2000:
                _logger.info("구글 Finance 환율 크롤링 성공: %.2f", rate)
                return rate

        # 대체 패턴으로 시도한다
        match = _ALT_RATE_PATTERN.search(html)
        if match:
            rate_str = match.group(1).replace(",", "")
            rate = float(rate_str)
            if 900 < rate < 2000:
                _logger.info("구글 Finance 대체 패턴 환율: %.2f", rate)
                return rate

        _logger.debug("구글 Finance 페이지에서 환율 패턴을 찾지 못했다")
        return None
    except Exception:
        _logger.debug("구글 Finance 환율 크롤링 실패", exc_info=True)
        return None


async def _try_google_search() -> float | None:
    """구글 검색 결과에서 환율을 파싱한다."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_GOOGLE_SEARCH_URL, headers=headers) as resp:
                if resp.status != 200:
                    _logger.debug("구글 검색 HTTP %d", resp.status)
                    return None
                html = await resp.text()

        match = _SEARCH_RATE_PATTERN.search(html)
        if match:
            rate_str = match.group(1).replace(",", "")
            rate = float(rate_str)
            if 900 < rate < 2000:
                _logger.info("구글 검색 환율 크롤링 성공: %.2f", rate)
                return rate

        # data-value 패턴으로 시도한다
        data_value_match = re.search(r'data-value="([\d.]+)"', html)
        if data_value_match:
            rate = float(data_value_match.group(1))
            if 900 < rate < 2000:
                _logger.info("구글 검색 data-value 환율: %.2f", rate)
                return rate

        _logger.debug("구글 검색 결과에서 환율을 추출하지 못했다")
        return None
    except Exception:
        _logger.debug("구글 검색 환율 크롤링 실패", exc_info=True)
        return None
