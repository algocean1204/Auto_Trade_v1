"""외부 지표 -- Polymarket 예측시장 확률 데이터를 수집한다.

Polymarket Gamma API(공개)에서 FOMC, 경기침체, 관세 등
시장 이벤트 확률을 조회하여 캐시에 저장한다.
API 키 불필요. events 엔드포인트로 전체 조회 후 클라이언트 측 필터링한다.
캐시 키: prediction:polymarket (TTL 900초).
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient
    from src.common.http_client import AsyncHttpClient

logger = get_logger(__name__)

# Gamma API 엔드포인트이다
_EVENTS_URL: str = "https://gamma-api.polymarket.com/events"

# 캐시 설정이다
_CACHE_KEY: str = "prediction:polymarket"
_CACHE_TTL: int = 900  # 15분
_LAST_SUCCESS_KEY: str = "prediction:polymarket:last_success"
_LAST_SUCCESS_TTL: int = 86400  # 24시간 폴백 유지

# 매매에 영향을 주는 키워드이다 — title/slug에서 검색한다
_FINANCE_KEYWORDS: list[str] = [
    "fed", "fomc", "rate cut", "rate hike", "interest rate",
    "recession", "tariff", "trade war", "sanctions",
    "inflation", "cpi", "gdp", "employment", "unemployment",
    "stock", "market crash", "bear market", "bull market",
    "s&p", "nasdaq", "dow", "treasury", "debt ceiling",
    "government shutdown", "default", "economy",
]

# 페이지당 요청 수이다
_PAGE_SIZE: int = 50
_MAX_PAGES: int = 4  # 최대 200개 이벤트 스캔
_REQUEST_TIMEOUT: float = 12.0
_MAX_RETRIES: int = 2
_RETRY_DELAY: float = 2.0


def _parse_market(market: dict) -> dict[str, Any]:
    """개별 마켓에서 핵심 필드를 추출한다."""
    question = market.get("question", "")
    # 확률 추출 — outcomePrices가 JSON 문자열일 수 있다
    outcome_prices = market.get("outcomePrices", "")
    if isinstance(outcome_prices, str):
        try:
            outcome_prices = json.loads(outcome_prices)
        except (ValueError, TypeError):
            outcome_prices = []

    yes_price = 0.0
    if isinstance(outcome_prices, list) and len(outcome_prices) >= 1:
        try:
            yes_price = float(outcome_prices[0])
        except (ValueError, TypeError, IndexError):
            pass

    volume = 0.0
    try:
        volume = float(market.get("volume", 0) or 0)
    except (ValueError, TypeError):
        pass

    return {
        "question": question,
        "probability": round(yes_price * 100, 1),
        "volume": round(volume, 2),
    }


def _is_finance_related(title: str, slug: str) -> bool:
    """이벤트가 금융/경제 관련인지 판별한다."""
    combined = (title + " " + slug).lower()
    return any(kw in combined for kw in _FINANCE_KEYWORDS)


def _process_event(event: dict) -> dict[str, Any] | None:
    """이벤트에서 관련 마켓 데이터를 추출한다."""
    title = event.get("title", "")
    slug = event.get("slug", "")
    if not _is_finance_related(title, slug):
        return None

    markets = event.get("markets", [])
    if not markets:
        return None

    # 마켓별 데이터 추출
    parsed_markets: list[dict[str, Any]] = []
    total_volume = 0.0
    for m in markets:
        pm = _parse_market(m)
        if pm["question"]:
            parsed_markets.append(pm)
            total_volume += pm["volume"]

    if not parsed_markets:
        return None

    return {
        "event_title": title,
        "slug": slug,
        "total_volume": round(total_volume, 2),
        "markets": parsed_markets,
    }


class PolymarketFetcher:
    """Polymarket 예측시장 확률 수집기이다.

    Gamma API events 엔드포인트에서 전체 이벤트를 조회한 후
    금융/경제 키워드로 필터링한다.
    실패 시 마지막 성공 캐시를 폴백으로 사용한다.
    """

    def __init__(self, cache: CacheClient, http: AsyncHttpClient) -> None:
        """의존성을 주입받는다."""
        self._cache = cache
        self._http = http

    async def fetch(self) -> list[dict[str, Any]]:
        """관련 예측 데이터를 수집하여 캐시에 저장한다.

        Returns:
            관련 이벤트 리스트. 실패 시 폴백 캐시 또는 빈 리스트.
        """
        cached = await self._read_cache(_CACHE_KEY)
        if cached is not None:
            logger.debug("Polymarket 캐시 히트: %d건", len(cached))
            return cached

        events = await self._fetch_events()
        if events:
            await self._write_cache(events)
            logger.info("Polymarket 수집 완료: %d건", len(events))
            return events

        # 폴백: 마지막 성공 캐시
        fallback = await self._read_cache(_LAST_SUCCESS_KEY)
        if fallback:
            logger.warning("Polymarket API 실패 — 폴백 캐시 사용 (%d건)", len(fallback))
            return fallback

        logger.warning("Polymarket 수집 실패 — 데이터 없음")
        return []

    async def _fetch_events(self) -> list[dict[str, Any]]:
        """Gamma API events를 페이지네이션으로 조회하고 필터링한다."""
        results: list[dict[str, Any]] = []

        for page in range(_MAX_PAGES):
            offset = page * _PAGE_SIZE
            page_data = await self._fetch_page(offset)
            if page_data is None:
                break  # API 실패 — 수집된 것만 반환

            for event in page_data:
                processed = _process_event(event)
                if processed:
                    results.append(processed)

            # 마지막 페이지 감지
            if len(page_data) < _PAGE_SIZE:
                break
            # rate limit 방지
            await asyncio.sleep(0.3)

        # 거래량 높은 순 정렬
        results.sort(key=lambda x: x.get("total_volume", 0), reverse=True)
        return results[:20]

    async def _fetch_page(self, offset: int) -> list[dict] | None:
        """단일 페이지를 조회한다. 실패 시 None."""
        params = {
            "closed": "false",
            "limit": str(_PAGE_SIZE),
            "offset": str(offset),
        }
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await asyncio.wait_for(
                    self._http.get(_EVENTS_URL, params=params),
                    timeout=_REQUEST_TIMEOUT,
                )
                if resp.status == 429:
                    delay = _RETRY_DELAY * (attempt + 1)
                    logger.warning("Polymarket rate limit — %.0fs 대기", delay)
                    await asyncio.sleep(delay)
                    continue
                if not resp.ok:
                    logger.debug("Polymarket API 실패: offset=%d status=%d", offset, resp.status)
                    return None
                data = resp.json()
                return data if isinstance(data, list) else []
            except asyncio.TimeoutError:
                logger.debug("Polymarket 타임아웃: offset=%d (시도 %d/%d)", offset, attempt + 1, _MAX_RETRIES)
            except Exception as exc:
                logger.debug("Polymarket 조회 실패: offset=%d error=%s", offset, exc)
                return None
        return None

    async def _read_cache(self, key: str) -> list[dict[str, Any]] | None:
        """캐시에서 데이터를 읽는다."""
        try:
            cached = await self._cache.read_json(key)
            if cached and isinstance(cached, list):
                return cached
        except Exception as exc:
            logger.debug("Polymarket 캐시 읽기 실패 (%s): %s", key, exc)
        return None

    async def _write_cache(self, data: list[dict[str, Any]]) -> None:
        """정식 캐시 + 폴백 캐시에 저장한다."""
        try:
            await self._cache.write_json(_CACHE_KEY, data, ttl=_CACHE_TTL)
            await self._cache.write_json(_LAST_SUCCESS_KEY, data, ttl=_LAST_SUCCESS_TTL)
        except Exception as exc:
            logger.debug("Polymarket 캐시 저장 실패: %s", exc)
