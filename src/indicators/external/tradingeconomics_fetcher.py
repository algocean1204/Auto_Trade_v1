"""외부 지표 -- Trading Economics 경제 캘린더 데이터를 수집한다.

TE 캘린더 페이지를 스크래핑하여 미국 주요 경제 지표 발표 일정을 추적한다.
API 키 불필요 (HTML 스크래핑). 캐시 키: macro:te:calendar (TTL 3600초).
기존 econ_calendar.py의 정적 캘린더를 실시간 데이터로 보강한다.
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

# Trading Economics 캘린더 URL이다
_CALENDAR_URL: str = "https://tradingeconomics.com/calendar"

# 캐시 설정이다
_CACHE_KEY: str = "macro:te:calendar"
_CACHE_TTL: int = 3600  # 1시간
_LAST_SUCCESS_KEY: str = "macro:te:calendar:last_success"
_LAST_SUCCESS_TTL: int = 86400  # 24시간 폴백

# 매매에 영향을 주는 고영향 이벤트 키워드이다
_HIGH_IMPACT_EVENTS: set[str] = {
    "nonfarm payrolls", "unemployment rate", "cpi", "core cpi",
    "gdp", "pce", "core pce", "fomc", "interest rate decision",
    "retail sales", "ism manufacturing", "ism services",
    "initial jobless claims", "consumer confidence",
    "ppi", "core ppi", "adp employment change",
    "existing home sales", "new home sales", "durable goods",
    "trade balance", "industrial production",
}

_MEDIUM_IMPACT_EVENTS: set[str] = {
    "construction spending", "factory orders", "housing starts",
    "building permits", "michigan consumer sentiment",
    "chicago pmi", "philly fed", "empire state",
    "jolts job openings", "productivity", "unit labour costs",
    "wholesale inventories", "personal income", "personal spending",
    "s&p global", "richmond fed", "dallas fed", "kansas city fed",
}

_REQUEST_TIMEOUT: float = 15.0
_MAX_RETRIES: int = 2
_RETRY_DELAY: float = 3.0

# HTML 파서용 정규식이다
_ROW_PATTERN = re.compile(
    r'<tr[^>]*'
    r'data-url="([^"]*)"[^>]*'
    r'data-country="([^"]*)"[^>]*'
    r'data-category="([^"]*)"[^>]*'
    r'data-event="([^"]*)"[^>]*'
    r"data-symbol='([^']*)'[^>]*>"
    r"(.*?)</tr>",
    re.DOTALL,
)
_DATE_PATTERN = re.compile(r"class='[^']*\s(\d{4}-\d{2}-\d{2})'")
_TIME_PATTERN = re.compile(r'calendar-date-\d+">\s*(\d+:\d+\s*[AP]M)')
_ACTUAL_PATTERN = re.compile(r'id=["\']actual["\'][^>]*>([^<]*)<')
_PREVIOUS_PATTERN = re.compile(r'id=["\']previous["\'][^>]*>([^<]*)<')
_FORECAST_PATTERN = re.compile(r'id=["\']forecast["\'][^>]*>([^<]*)<')

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


def _classify_importance(event_name: str) -> str:
    """이벤트 중요도를 분류한다."""
    lower = event_name.lower()
    for kw in _HIGH_IMPACT_EVENTS:
        if kw in lower:
            return "high"
    for kw in _MEDIUM_IMPACT_EVENTS:
        if kw in lower:
            return "medium"
    return "low"


def _parse_calendar_html(html: str) -> list[dict[str, Any]]:
    """Trading Economics 캘린더 HTML을 파싱한다."""
    events: list[dict[str, Any]] = []
    rows = _ROW_PATTERN.findall(html)

    for url, country, category, event_name, symbol, body in rows:
        if country != "united states":
            continue

        # 날짜/시간 추출
        date_m = _DATE_PATTERN.search(body)
        time_m = _TIME_PATTERN.search(body)
        actual_m = _ACTUAL_PATTERN.search(body)
        prev_m = _PREVIOUS_PATTERN.search(body)
        fcast_m = _FORECAST_PATTERN.search(body)

        event_date = date_m.group(1) if date_m else ""
        event_time = time_m.group(1).strip() if time_m else ""
        actual = actual_m.group(1).strip() if actual_m else ""
        previous = prev_m.group(1).strip() if prev_m else ""
        forecast = fcast_m.group(1).strip() if fcast_m else ""

        importance = _classify_importance(event_name)

        events.append({
            "date": event_date,
            "time_et": event_time,
            "event": event_name,
            "category": category,
            "importance": importance,
            "actual": actual,
            "forecast": forecast,
            "previous": previous,
            "symbol": symbol,
            "url": url,
        })

    return events


class TradingEconomicsFetcher:
    """Trading Economics 경제 캘린더 수집기이다.

    TE 웹사이트에서 미국 경제 지표 발표 일정을 스크래핑한다.
    고영향/중영향 이벤트를 자동 분류한다.
    실패 시 마지막 성공 캐시를 폴백으로 사용한다.
    """

    def __init__(self, cache: CacheClient, http: AsyncHttpClient) -> None:
        """의존성을 주입받는다."""
        self._cache = cache
        self._http = http

    async def fetch(self) -> list[dict[str, Any]]:
        """TE 캘린더 데이터를 수집하여 캐시에 저장한다.

        Returns:
            미국 경제 이벤트 리스트. 실패 시 폴백 또는 빈 리스트.
        """
        cached = await self._read_cache(_CACHE_KEY)
        if cached is not None:
            logger.debug("TE 캘린더 캐시 히트: %d건", len(cached))
            return cached

        events = await self._scrape_calendar()
        if events:
            await self._write_cache(events)
            high = sum(1 for e in events if e.get("importance") == "high")
            logger.info("TE 캘린더 수집 완료: %d건 (high=%d)", len(events), high)
            return events

        fallback = await self._read_cache(_LAST_SUCCESS_KEY)
        if fallback:
            logger.warning("TE 캘린더 스크래핑 실패 — 폴백 캐시 사용 (%d건)", len(fallback))
            return fallback

        logger.warning("TE 캘린더 수집 실패 — 데이터 없음")
        return []

    async def fetch_high_impact(self) -> list[dict[str, Any]]:
        """고영향 이벤트만 반환한다."""
        all_events = await self.fetch()
        return [e for e in all_events if e.get("importance") in ("high", "medium")]

    async def _scrape_calendar(self) -> list[dict[str, Any]]:
        """TE 캘린더 페이지를 스크래핑한다."""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await asyncio.wait_for(
                    self._http.get(_CALENDAR_URL, headers=_HEADERS),
                    timeout=_REQUEST_TIMEOUT,
                )

                if resp.status == 429:
                    delay = _RETRY_DELAY * (attempt + 1)
                    logger.warning("TE rate limit — %.0fs 대기", delay)
                    await asyncio.sleep(delay)
                    continue

                if resp.status == 403:
                    logger.warning("TE 접근 차단 (403) — 스크래핑 불가")
                    return []

                if not resp.ok:
                    logger.debug("TE 캘린더 응답 실패: status=%d", resp.status)
                    continue

                events = _parse_calendar_html(resp.body)
                if events:
                    return events

                logger.warning("TE 캘린더 파싱 결과 0건 — HTML 구조 변경 가능성")
                return []

            except asyncio.TimeoutError:
                logger.debug("TE 캘린더 타임아웃 (시도 %d/%d)", attempt + 1, _MAX_RETRIES)
            except Exception as exc:
                logger.debug("TE 캘린더 스크래핑 실패: %s", exc)
                return []

        return []

    async def _read_cache(self, key: str) -> list[dict[str, Any]] | None:
        """캐시에서 데이터를 읽는다."""
        try:
            cached = await self._cache.read_json(key)
            if cached and isinstance(cached, list):
                return cached
        except Exception as exc:
            logger.debug("TE 캐시 읽기 실패 (%s): %s", key, exc)
        return None

    async def _write_cache(self, data: list[dict[str, Any]]) -> None:
        """정식 캐시 + 폴백 캐시에 저장한다."""
        try:
            await self._cache.write_json(_CACHE_KEY, data, ttl=_CACHE_TTL)
            await self._cache.write_json(_LAST_SUCCESS_KEY, data, ttl=_LAST_SUCCESS_TTL)
        except Exception as exc:
            logger.debug("TE 캐시 저장 실패: %s", exc)
