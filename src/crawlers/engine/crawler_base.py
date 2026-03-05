"""F1 데이터 수집 -- 모든 크롤러의 추상 베이스 클래스이다.

공통 타임아웃 래핑과 에러 격리를 제공한다.
각 크롤러는 crawl() 메서드를 구현하여 RawArticle 목록을 반환한다.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.crawlers.models import RawArticle, SourceConfig

logger = get_logger(__name__)


class CrawlerBase(ABC):
    """크롤러 추상 베이스 클래스이다.

    타임아웃 래핑과 에러 격리를 자동으로 처리한다.
    하위 클래스는 crawl()만 구현하면 된다.
    """

    def __init__(self, http_client: AsyncHttpClient) -> None:
        """HTTP 클라이언트를 주입받아 초기화한다."""
        self._http = http_client

    @abstractmethod
    async def crawl(self, source: SourceConfig) -> list[RawArticle]:
        """소스에서 기사를 수집한다. 하위 클래스가 구현한다."""
        ...

    async def safe_crawl(self, source: SourceConfig) -> list[RawArticle]:
        """타임아웃과 에러를 격리하여 crawl()을 실행한다.

        타임아웃 초과나 예외 발생 시 빈 리스트를 반환하여
        다른 소스 크롤링에 영향을 주지 않는다.
        """
        try:
            articles = await asyncio.wait_for(
                self.crawl(source),
                timeout=source.timeout,
            )
            logger.info(
                "%s 크롤링 완료: %d건", source.name, len(articles),
            )
            return articles
        except asyncio.TimeoutError:
            logger.warning(
                "%s 크롤링 타임아웃: %d초 초과", source.name, source.timeout,
            )
            return []
        except Exception:
            logger.exception("%s 크롤링 실패", source.name)
            return []
