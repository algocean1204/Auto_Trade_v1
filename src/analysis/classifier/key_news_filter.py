"""F2 AI 분석 -- 영향도 임계값 이상 핵심 뉴스를 필터링한다."""
from __future__ import annotations

import logging

from src.analysis.models import ClassifiedNews, KeyNews
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 기본 영향도 임계값이다
_DEFAULT_THRESHOLD: float = 0.7


def _to_key_news(news: ClassifiedNews) -> KeyNews:
    """ClassifiedNews를 KeyNews로 변환한다."""
    summary = news.reasoning if news.reasoning else news.content[:200]
    return KeyNews(
        title=news.title,
        impact_score=news.impact_score,
        direction=news.direction,
        category=news.category,
        tickers_affected=news.tickers_affected,
        summary=summary,
        source=news.source or "unknown",
    )


def _sort_by_impact(news_list: list[KeyNews]) -> list[KeyNews]:
    """영향도 내림차순으로 정렬한다."""
    return sorted(news_list, key=lambda n: n.impact_score, reverse=True)


class KeyNewsFilter:
    """영향도 임계값 이상의 핵심 뉴스만 필터링한다.

    기본 임계값 0.7이며, 결과는 영향도 내림차순으로 정렬한다.
    """

    def __init__(self) -> None:
        logger.info("KeyNewsFilter 초기화 완료")

    def filter(
        self,
        news_list: list[ClassifiedNews],
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> list[KeyNews]:
        """임계값 이상의 뉴스를 필터링하고 KeyNews로 변환한다."""
        filtered = [
            _to_key_news(n) for n in news_list
            if n.impact_score >= threshold
        ]
        result = _sort_by_impact(filtered)
        logger.info(
            "핵심 뉴스 필터링: %d/%d건 (threshold=%.2f)",
            len(result), len(news_list), threshold,
        )
        return result
