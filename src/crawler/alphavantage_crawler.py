"""
Alpha Vantage News Sentiment 크롤러.

Alpha Vantage NEWS_SENTIMENT API를 사용하여 추적 대상 티커의
뉴스 감성 데이터를 수집한다. 무료 티어는 일 25회 호출 제한이 있으므로
호출 횟수를 추적하여 초과 시 거부한다.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Alpha Vantage 무료 티어 일일 호출 제한
_FREE_TIER_DAILY_LIMIT = 25

# API 기본 URL
_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageCrawler(BaseCrawler):
    """Alpha Vantage News Sentiment API를 통해 뉴스 감성 데이터를 수집하는 크롤러.

    무료 티어는 일 25회 호출 제한이 있으므로, 날짜별 호출 횟수를
    추적하여 한도 초과 시 API 호출을 거부한다. API 응답에 포함된
    감성 점수(overall_sentiment_score, ticker_sentiment)는
    기사 메타데이터에 저장한다.
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self._api_key: str = self._resolve_api_key(source_config)
        self._tracked_symbols: list[str] = source_config.get(
            "tracked_symbols", ["SOXL", "QLD", "SSO", "NVDA", "AMD", "AAPL", "MSFT"]
        )
        # 일일 호출 횟수 추적: {날짜 문자열: 호출 수}
        self._daily_call_count: int = 0
        self._daily_call_date: date | None = None

    @staticmethod
    def _resolve_api_key(config: dict[str, Any]) -> str:
        """설정 또는 환경 변수에서 API 키를 가져온다."""
        key = config.get("api_key", "")
        if not key:
            key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
        return key

    def _check_rate_limit(self) -> bool:
        """일일 호출 한도를 확인한다.

        Returns:
            True이면 호출 가능, False이면 한도 초과.
        """
        today = date.today()

        # 날짜가 바뀌면 카운터 리셋
        if self._daily_call_date != today:
            self._daily_call_date = today
            self._daily_call_count = 0

        if self._daily_call_count >= _FREE_TIER_DAILY_LIMIT:
            logger.warning(
                "[%s] 일일 API 호출 한도 초과 (%d/%d). 내일까지 대기 필요",
                self.name,
                self._daily_call_count,
                _FREE_TIER_DAILY_LIMIT,
            )
            return False

        return True

    def _increment_call_count(self) -> None:
        """호출 횟수를 1 증가시킨다."""
        today = date.today()
        if self._daily_call_date != today:
            self._daily_call_date = today
            self._daily_call_count = 0
        self._daily_call_count += 1
        logger.debug(
            "[%s] API 호출 횟수: %d/%d",
            self.name,
            self._daily_call_count,
            _FREE_TIER_DAILY_LIMIT,
        )

    def get_remaining_calls(self) -> int:
        """오늘 남은 API 호출 횟수를 반환한다."""
        today = date.today()
        if self._daily_call_date != today:
            return _FREE_TIER_DAILY_LIMIT
        return max(0, _FREE_TIER_DAILY_LIMIT - self._daily_call_count)

    @staticmethod
    def _parse_alphavantage_time(time_str: str) -> datetime:
        """Alpha Vantage 시간 형식을 UTC datetime으로 변환한다.

        Alpha Vantage는 "20260217T120000" 형식을 사용한다.

        Args:
            time_str: "YYYYMMDDTHHmmss" 형식의 시간 문자열.

        Returns:
            UTC timezone-aware datetime 객체.
        """
        try:
            dt = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
            return dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as e:
            logger.warning("시간 파싱 실패 ('%s'): %s", time_str, e)
            return datetime.now(tz=timezone.utc)

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Alpha Vantage NEWS_SENTIMENT API를 호출하여 뉴스 감성 데이터를 수집한다.

        추적 대상 티커를 쉼표로 연결하여 한 번의 API 호출로 조회한다.
        일일 호출 한도(25회)를 초과하면 빈 리스트를 반환한다.

        Args:
            since: 이 시점 이후의 기사만 반환. None이면 전체.

        Returns:
            표준 기사 딕셔너리 리스트.
        """
        if not self._api_key:
            logger.error(
                "[%s] API 키 미설정. config['api_key'] 또는 "
                "환경 변수 ALPHAVANTAGE_API_KEY를 설정해야 한다",
                self.name,
            )
            return []

        if not self._check_rate_limit():
            return []

        try:
            tickers_param = ",".join(self._tracked_symbols)
            params = {
                "function": "NEWS_SENTIMENT",
                "tickers": tickers_param,
                "limit": "50",
                "apikey": self._api_key,
            }

            session = await self.get_session()
            async with session.get(_BASE_URL, params=params) as response:
                self._increment_call_count()

                if response.status != 200:
                    logger.error(
                        "[%s] API 응답 오류: HTTP %d",
                        self.name,
                        response.status,
                    )
                    return []

                data = await response.json(content_type=None)

            # API 에러 메시지 확인
            if "Error Message" in data:
                logger.error(
                    "[%s] API 에러: %s",
                    self.name,
                    data["Error Message"],
                )
                return []

            if "Note" in data:
                logger.warning(
                    "[%s] API 경고 (호출 빈도 초과 가능): %s",
                    self.name,
                    data["Note"],
                )
                return []

            if "Information" in data:
                logger.warning(
                    "[%s] API 정보: %s",
                    self.name,
                    data["Information"],
                )
                return []

            feed = data.get("feed", [])
            if not feed:
                logger.info("[%s] 뉴스 피드 없음", self.name)
                return []

            articles = self._parse_feed(feed, since)

            logger.info(
                "[%s] 뉴스 감성 데이터 %d건 수집 (남은 호출: %d/%d)",
                self.name,
                len(articles),
                self.get_remaining_calls(),
                _FREE_TIER_DAILY_LIMIT,
            )
            return articles

        except Exception as e:
            logger.error(
                "[%s] 크롤링 오류: %s", self.name, e, exc_info=True
            )
            return []

    def _parse_feed(
        self,
        feed: list[dict[str, Any]],
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """API 응답의 feed 배열을 표준 기사 딕셔너리로 변환한다.

        Args:
            feed: Alpha Vantage NEWS_SENTIMENT 응답의 feed 항목 리스트.
            since: 이 시점 이후의 기사만 포함.

        Returns:
            표준 기사 딕셔너리 리스트.
        """
        articles: list[dict[str, Any]] = []

        for item in feed:
            try:
                published_at = self._parse_alphavantage_time(
                    item.get("time_published", "")
                )

                # since 필터링
                if since and published_at < since:
                    continue

                title = item.get("title", "")
                url = item.get("url", "")
                summary = item.get("summary", "")
                source_name = item.get("source", "Alpha Vantage")

                # 감성 점수 추출
                overall_score = item.get("overall_sentiment_score", 0.0)
                overall_label = item.get("overall_sentiment_label", "Neutral")

                # 티커별 감성 배열 추출
                ticker_sentiments = []
                for ts in item.get("ticker_sentiment", []):
                    ticker_sentiments.append({
                        "ticker": ts.get("ticker", ""),
                        "relevance_score": ts.get("relevance_score", "0"),
                        "ticker_sentiment_score": ts.get(
                            "ticker_sentiment_score", "0"
                        ),
                        "ticker_sentiment_label": ts.get(
                            "ticker_sentiment_label", "Neutral"
                        ),
                    })

                # 관련 티커 목록 (추적 대상과 교집합)
                mentioned_tickers = [
                    ts["ticker"]
                    for ts in ticker_sentiments
                    if ts["ticker"] in self._tracked_symbols
                ]

                # 감성 라벨을 headline에 포함
                headline = (
                    f"[AlphaVantage] [{overall_label}] {title}"
                )
                content = summary if summary else title

                articles.append({
                    "headline": headline,
                    "content": content,
                    "url": url,
                    "published_at": published_at,
                    "source": self.source_key,
                    "language": self.language,
                    "metadata": {
                        "data_type": "news_sentiment",
                        "news_source": source_name,
                        "overall_sentiment_score": float(overall_score),
                        "overall_sentiment_label": overall_label,
                        "ticker_sentiments": ticker_sentiments,
                        "mentioned_tickers": mentioned_tickers,
                        "banner_image": item.get("banner_image", ""),
                        "topics": [
                            t.get("topic", "")
                            for t in item.get("topics", [])
                        ],
                    },
                })

            except Exception as e:
                logger.warning(
                    "[%s] 피드 항목 파싱 실패: %s", self.name, e
                )
                continue

        return articles
