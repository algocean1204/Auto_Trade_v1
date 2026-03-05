"""F1 데이터 수집 -- API 기반 크롤러이다.

7개 API 소스(Finnhub, AlphaVantage, FRED, FearGreed, Finviz,
Stocktwits, DART)의 엔드포인트를 호출하고 응답을 RawArticle로 변환한다.
파싱 로직은 api_parsers 모듈에 분리되어 있다.
"""
from __future__ import annotations

from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.common.secret_vault import SecretProvider
from src.crawlers.engine.crawler_base import CrawlerBase
from src.crawlers.models import RawArticle, SourceConfig
from src.crawlers.sources.api_parsers import PARSERS

logger = get_logger(__name__)

# API 소스 이름 집합이다
_API_SOURCES: set[str] = {
    "finnhub", "alphavantage", "fred", "feargreed",
    "finviz", "stocktwits", "dart",
}

# 소스별 쿼리 파라미터이다 (API 키는 런타임에 주입한다)
_SOURCE_PARAMS: dict[str, dict[str, str]] = {
    "finnhub": {"category": "general"},
    "alphavantage": {"function": "NEWS_SENTIMENT", "limit": "50"},
    "fred": {"series_id": "VIXCLS", "sort_order": "desc", "limit": "1"},
    "feargreed": {},
    "finviz": {},
    "stocktwits": {},
    "dart": {"page_count": "10"},
}

# 소스별 시크릿 키 매핑이다
_SECRET_KEY_MAP: dict[str, str] = {
    "finnhub": "FINNHUB_API_KEY",
    "alphavantage": "ALPHAVANTAGE_API_KEY",
    "fred": "FRED_API_KEY",
    "dart": "DART_API_KEY",
}

# 소스별 API 키 파라미터 이름 매핑이다
_PARAM_NAME_MAP: dict[str, str] = {
    "finnhub": "token",
    "alphavantage": "apikey",
    "fred": "api_key",
    "dart": "apikey",
}


class ApiCrawler(CrawlerBase):
    """API 기반 크롤러이다. 7개 API 소스를 처리한다."""

    def __init__(
        self, http_client: AsyncHttpClient, vault: SecretProvider,
    ) -> None:
        """HTTP 클라이언트와 시크릿 제공자를 주입받는다."""
        super().__init__(http_client)
        self._vault = vault

    def can_handle(self, source: SourceConfig) -> bool:
        """이 크롤러가 해당 소스를 처리할 수 있는지 판별한다."""
        return source.name in _API_SOURCES

    async def crawl(self, source: SourceConfig) -> list[RawArticle]:
        """API 엔드포인트를 호출하고 응답을 RawArticle 목록으로 변환한다."""
        params = self._build_params(source)
        response = await self._http.get(source.url, params=params)

        if not response.ok:
            logger.warning(
                "API 응답 실패: %s status=%d", source.name, response.status,
            )
            return []

        return self._parse_response(source.name, response.json())

    def _build_params(self, source: SourceConfig) -> dict[str, str]:
        """소스별 쿼리 파라미터를 구성한다. API 키를 주입한다."""
        params = dict(_SOURCE_PARAMS.get(source.name, {}))
        secret_key = _SECRET_KEY_MAP.get(source.name)
        if secret_key:
            api_key = self._vault.get_secret_or_none(secret_key)
            if api_key:
                param_name = _PARAM_NAME_MAP.get(source.name, "apikey")
                params[param_name] = api_key
        return params

    def _parse_response(
        self, source_name: str, data: dict | list,
    ) -> list[RawArticle]:
        """소스별 파서를 호출하여 응답을 파싱한다."""
        parser = PARSERS.get(source_name)
        if parser is None:
            logger.warning("파서 미등록: %s", source_name)
            return []
        try:
            return parser(data)
        except Exception:
            logger.exception("API 파싱 실패: %s", source_name)
            return []
