"""
Finnhub 뉴스 API 크롤러.

Finnhub API를 사용하여 일반 시장 뉴스와 개별 종목 뉴스를 수집한다.
일반 뉴스는 매 호출마다 가져오고, 회사 뉴스는 추적 심볼 중 5개를
로테이션하며 수집하여 API 호출 횟수(60회/분)를 준수한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Finnhub 무료 플랜 rate limit: 60 calls/min
_RATE_LIMIT_CALLS = 60
_RATE_LIMIT_WINDOW = 60.0  # 초

# 한 번의 crawl() 호출에서 회사 뉴스를 가져올 심볼 수
_SYMBOLS_PER_ROTATION = 5


class FinnhubCrawler(BaseCrawler):
    """Finnhub API를 통해 일반 뉴스와 회사 뉴스를 수집하는 크롤러.

    rate limiting을 준수하며, 추적 심볼을 로테이션하여
    매 호출마다 일부 심볼의 뉴스만 가져온다.

    Attributes:
        _api_key: Finnhub API 인증 키.
        _tracked_symbols: 회사 뉴스를 추적할 심볼 목록.
        _rotation_index: 현재 로테이션 위치.
        _call_timestamps: rate limiting용 호출 타임스탬프 기록.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self._api_key: str = source_config.get("api_key", "")
        if not self._api_key:
            self._api_key = self._load_api_key_from_settings()
        self._tracked_symbols: list[str] = source_config.get(
            "tracked_symbols", []
        )
        self._rotation_index: int = 0
        self._call_timestamps: list[float] = []

    @staticmethod
    def _load_api_key_from_settings() -> str:
        """Settings에서 Finnhub API 키를 로드한다."""
        try:
            from src.utils.config import get_settings
            settings = get_settings()
            return getattr(settings, "finnhub_api_key", "")
        except Exception as exc:
            logger.debug("Finnhub API 키 로드 실패: %s", exc)
            return ""

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """일반 뉴스와 회사 뉴스를 수집한다.

        일반 뉴스는 매번 전체를 가져오고, 회사 뉴스는 추적 심볼 중
        최대 5개를 로테이션하며 수집한다.

        Args:
            since: 이 시점 이후의 뉴스만 필터링한다. None이면 전체.

        Returns:
            표준 article dict 형식의 리스트.
        """
        if not self._api_key:
            logger.warning("[%s] API 키가 설정되지 않아 크롤링을 건너뛴다", self.name)
            return []

        results: list[dict[str, Any]] = []

        # 일반 뉴스 수집
        general_articles = await self._fetch_general_news(since)
        results.extend(general_articles)

        # 회사 뉴스 수집 (로테이션)
        company_articles = await self._fetch_company_news_rotation(since)
        results.extend(company_articles)

        logger.info(
            "[%s] 총 %d건 수집 (일반: %d, 회사: %d)",
            self.name, len(results), len(general_articles), len(company_articles),
        )
        return results

    async def _fetch_general_news(
        self, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Finnhub 일반 뉴스를 수집한다.

        GET https://finnhub.io/api/v1/news?category=general&token={key}

        Args:
            since: 이 시점 이후의 뉴스만 필터링한다.

        Returns:
            표준 article dict 리스트.
        """
        try:
            await self._wait_for_rate_limit()
            session = await self.get_session()
            url = "https://finnhub.io/api/v1/news"
            params = {
                "category": "general",
                "token": self._api_key,
            }

            async with session.get(url, params=params) as resp:
                self._record_call()
                if resp.status != 200:
                    logger.warning(
                        "[%s] 일반 뉴스 API 응답 오류: status=%d",
                        self.name, resp.status,
                    )
                    return []

                data = await resp.json()

            if not isinstance(data, list):
                logger.warning("[%s] 일반 뉴스 응답이 리스트가 아니다: %s", self.name, type(data))
                return []

            articles = self._parse_articles(data, since)
            logger.info("[%s] 일반 뉴스 %d건 수집", self.name, len(articles))
            return articles

        except Exception as e:
            logger.error("[%s] 일반 뉴스 수집 실패: %s", self.name, e, exc_info=True)
            return []

    async def _fetch_company_news_rotation(
        self, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        """추적 심볼 중 일부를 로테이션하며 회사 뉴스를 수집한다.

        한 번의 호출에서 최대 _SYMBOLS_PER_ROTATION(5)개 심볼의
        뉴스를 가져온다. 다음 호출에서는 이어지는 심볼부터 시작한다.

        Args:
            since: 이 시점 이후의 뉴스만 필터링한다.

        Returns:
            표준 article dict 리스트.
        """
        if not self._tracked_symbols:
            logger.debug("[%s] 추적 심볼이 없어 회사 뉴스를 건너뛴다", self.name)
            return []

        # 로테이션할 심볼 선택
        symbols = self._get_rotation_symbols()
        all_articles: list[dict[str, Any]] = []

        for symbol in symbols:
            try:
                articles = await self._fetch_company_news(symbol, since)
                all_articles.extend(articles)
            except Exception as e:
                logger.warning(
                    "[%s] 회사 뉴스 수집 실패 (%s): %s", self.name, symbol, e
                )
                continue

        logger.info(
            "[%s] 회사 뉴스 %d건 수집 (심볼: %s)",
            self.name, len(all_articles), symbols,
        )
        return all_articles

    async def _fetch_company_news(
        self, symbol: str, since: datetime | None = None
    ) -> list[dict[str, Any]]:
        """특정 심볼의 회사 뉴스를 수집한다.

        GET https://finnhub.io/api/v1/company-news?symbol={sym}&from={date}&to={date}&token={key}

        Args:
            symbol: 조회할 티커 심볼.
            since: 이 시점 이후의 뉴스만 필터링한다.

        Returns:
            표준 article dict 리스트.
        """
        try:
            await self._wait_for_rate_limit()
            session = await self.get_session()

            # 날짜 범위 설정: since 또는 7일 전부터 오늘까지
            now = datetime.now(tz=timezone.utc)
            date_from = since if since else (now - timedelta(days=7))
            date_to = now

            url = "https://finnhub.io/api/v1/company-news"
            params = {
                "symbol": symbol,
                "from": date_from.strftime("%Y-%m-%d"),
                "to": date_to.strftime("%Y-%m-%d"),
                "token": self._api_key,
            }

            async with session.get(url, params=params) as resp:
                self._record_call()
                if resp.status != 200:
                    logger.warning(
                        "[%s] 회사 뉴스 API 응답 오류 (%s): status=%d",
                        self.name, symbol, resp.status,
                    )
                    return []

                data = await resp.json()

            if not isinstance(data, list):
                logger.warning(
                    "[%s] 회사 뉴스 응답이 리스트가 아니다 (%s): %s",
                    self.name, symbol, type(data),
                )
                return []

            articles = self._parse_articles(data, since, default_ticker=symbol)
            return articles

        except Exception as e:
            logger.error(
                "[%s] 회사 뉴스 수집 실패 (%s): %s",
                self.name, symbol, e, exc_info=True,
            )
            return []

    def _parse_articles(
        self,
        raw_items: list[dict[str, Any]],
        since: datetime | None = None,
        default_ticker: str | None = None,
    ) -> list[dict[str, Any]]:
        """Finnhub API 응답을 표준 article dict 형식으로 변환한다.

        Finnhub 응답 필드:
            - id: 기사 고유 ID
            - headline: 제목
            - summary: 요약
            - url: 원문 링크
            - datetime: Unix timestamp (초)
            - source: 출처명
            - category: 카테고리
            - related: 관련 티커 (쉼표 구분 문자열)
            - image: 이미지 URL

        Args:
            raw_items: Finnhub API 원시 응답 리스트.
            since: 이 시점 이후의 기사만 포함한다.
            default_ticker: 회사 뉴스 요청 시 기본 티커 심볼.

        Returns:
            표준 article dict 리스트.
        """
        articles: list[dict[str, Any]] = []

        for item in raw_items:
            try:
                # Unix timestamp를 UTC datetime으로 변환
                unix_ts = item.get("datetime", 0)
                if not unix_ts:
                    continue

                published_at = datetime.fromtimestamp(unix_ts, tz=timezone.utc)

                # since 필터링
                if since and published_at < since:
                    continue

                headline = item.get("headline", "").strip()
                if not headline:
                    continue

                summary = item.get("summary", "").strip()
                url = item.get("url", "").strip()
                source_name = item.get("source", "Finnhub")
                category = item.get("category", "")

                # 관련 티커 파싱
                related_raw = item.get("related", "")
                related_tickers: list[str] = []
                if related_raw and isinstance(related_raw, str):
                    related_tickers = [
                        t.strip()
                        for t in related_raw.split(",")
                        if t.strip()
                    ]

                # default_ticker가 있고 관련 티커에 포함되지 않으면 추가
                if default_ticker and default_ticker not in related_tickers:
                    related_tickers.insert(0, default_ticker)

                articles.append({
                    "headline": headline,
                    "content": summary,
                    "url": url,
                    "published_at": published_at,
                    "source": self.source_key,
                    "language": self.language,
                    "metadata": {
                        "data_type": "news",
                        "finnhub_id": item.get("id"),
                        "category": category,
                        "news_source": source_name,
                        "related_tickers": related_tickers,
                        "image_url": item.get("image", ""),
                    },
                })

            except Exception as e:
                logger.debug(
                    "[%s] 기사 파싱 실패: %s (item=%s)", self.name, e, item
                )
                continue

        return articles

    def _get_rotation_symbols(self) -> list[str]:
        """로테이션할 심볼 목록을 반환하고 인덱스를 전진시킨다.

        전체 추적 심볼 리스트에서 현재 인덱스 위치부터
        _SYMBOLS_PER_ROTATION개를 순환적으로 선택한다.

        Returns:
            이번 호출에서 처리할 심볼 리스트.
        """
        total = len(self._tracked_symbols)
        if total == 0:
            return []

        count = min(_SYMBOLS_PER_ROTATION, total)
        symbols: list[str] = []

        for i in range(count):
            idx = (self._rotation_index + i) % total
            symbols.append(self._tracked_symbols[idx])

        # 다음 호출을 위해 인덱스 전진
        self._rotation_index = (self._rotation_index + count) % total

        return symbols

    async def _wait_for_rate_limit(self) -> None:
        """rate limit을 초과하지 않도록 대기한다.

        최근 _RATE_LIMIT_WINDOW초 내에 _RATE_LIMIT_CALLS회 이상
        호출했으면 윈도우가 지날 때까지 대기한다.
        """
        now = asyncio.get_event_loop().time()

        # 윈도우 밖의 오래된 타임스탬프 제거
        self._call_timestamps = [
            ts for ts in self._call_timestamps
            if now - ts < _RATE_LIMIT_WINDOW
        ]

        if len(self._call_timestamps) >= _RATE_LIMIT_CALLS:
            oldest = self._call_timestamps[0]
            wait_time = _RATE_LIMIT_WINDOW - (now - oldest) + 0.1
            if wait_time > 0:
                logger.info(
                    "[%s] rate limit 대기: %.1f초", self.name, wait_time
                )
                await asyncio.sleep(wait_time)
                # 대기 후 타임스탬프 다시 정리
                now = asyncio.get_event_loop().time()
                self._call_timestamps = [
                    ts for ts in self._call_timestamps
                    if now - ts < _RATE_LIMIT_WINDOW
                ]

    def _record_call(self) -> None:
        """API 호출 타임스탬프를 기록한다."""
        self._call_timestamps.append(asyncio.get_event_loop().time())
