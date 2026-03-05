"""네이버 환율 크롤러 -- USD/KRW 환율을 네이버 금융에서 크롤링한다.

FxScheduler의 2차 폴백 소스로 사용된다.
네이버 금융 환율 페이지에서 USD/KRW 매매기준율을 파싱한다.
"""
from __future__ import annotations

import re

import aiohttp

from src.common.logger import get_logger

_logger = get_logger(__name__)

# 네이버 금융 환율 상세 페이지 URL이다
_NAVER_FX_URL = "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW"

# 요청 타임아웃(초)이다
_REQUEST_TIMEOUT: int = 10

# 매매기준율을 추출하는 정규식 패턴이다
# 네이버 금융 페이지에서 "현재가" 영역의 숫자를 파싱한다
_RATE_PATTERN = re.compile(
    r'class="no_today"[^>]*>.*?<em[^>]*>\s*([\d,]+\.?\d*)',
    re.DOTALL,
)

# 대체 패턴: 네이버 모바일 API 응답용이다
_ALT_RATE_PATTERN = re.compile(r'"closePrice"\s*:\s*"?([\d,]+\.?\d*)"?')


async def fetch_naver_usd_krw() -> float | None:
    """네이버 금융에서 USD/KRW 환율을 크롤링한다.

    성공 시 float 환율, 실패 시 None을 반환한다.
    두 가지 소스를 순차적으로 시도한다:
      1. 네이버 금융 환율 상세 페이지 (PC 웹)
      2. 네이버 증권 모바일 API
    """
    # 1차: 네이버 증권 모바일 API (JSON 구조화 데이터, 더 안정적)
    rate = await _try_naver_mobile_api()
    if rate is not None:
        return rate

    # 2차: 네이버 금융 PC 웹 페이지 크롤링 (HTML 파싱, 폴백)
    rate = await _try_naver_web()
    if rate is not None:
        return rate

    _logger.warning("네이버 환율 크롤링 모두 실패")
    return None


async def _try_naver_web() -> float | None:
    """네이버 금융 PC 웹 페이지에서 환율을 파싱한다."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(_NAVER_FX_URL, headers=headers) as resp:
                if resp.status != 200:
                    _logger.debug("네이버 금융 페이지 HTTP %d", resp.status)
                    return None
                html = await resp.text()

        match = _RATE_PATTERN.search(html)
        if match:
            rate_str = match.group(1).replace(",", "")
            rate = float(rate_str)
            if 900 < rate < 2000:  # 합리적인 USD/KRW 범위 검증
                _logger.info("네이버 웹 환율 크롤링 성공: %.2f", rate)
                return rate
            _logger.warning("네이버 웹 환율 범위 이탈: %.2f", rate)

        _logger.debug("네이버 금융 페이지에서 환율 패턴을 찾지 못했다")
        return None
    except Exception:
        _logger.debug("네이버 웹 환율 크롤링 실패", exc_info=True)
        return None


async def _try_naver_mobile_api() -> float | None:
    """네이버 증권 모바일 API에서 환율을 조회한다."""
    url = (
        "https://m.stock.naver.com/front-api/marketIndex/productDetail"
        "?category=exchange&reutersCode=FX_USDKRW"
    )
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        }
        timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    _logger.debug("네이버 모바일 API HTTP %d", resp.status)
                    return None
                text = await resp.text()

        match = _ALT_RATE_PATTERN.search(text)
        if match:
            rate_str = match.group(1).replace(",", "")
            rate = float(rate_str)
            if 900 < rate < 2000:
                _logger.info("네이버 모바일 API 환율 조회 성공: %.2f", rate)
                return rate

        # JSON 파싱 시도
        try:
            import json
            data = json.loads(text)
            # 중첩 구조에서 closePrice를 탐색한다
            result = data.get("result", data)
            if isinstance(result, dict):
                close_price = result.get("closePrice") or result.get("nowVal")
                if close_price is not None:
                    rate = float(str(close_price).replace(",", ""))
                    if 900 < rate < 2000:
                        _logger.info("네이버 모바일 API JSON 환율: %.2f", rate)
                        return rate
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        _logger.debug("네이버 모바일 API에서 환율을 추출하지 못했다")
        return None
    except Exception:
        _logger.debug("네이버 모바일 API 환율 조회 실패", exc_info=True)
        return None
