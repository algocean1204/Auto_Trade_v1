"""F2 AI 분석 -- 반복 테마를 감지하고 캐시에서 추적한다."""
from __future__ import annotations

import json
import logging
from collections import Counter

from src.analysis.models import ClassifiedNews, ThemeSummary
from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 캐시 키 접두사이다
_KEY_PREFIX: str = "theme:"

# 테마 TTL이다 -- 7일간 유지한다
_THEME_TTL: int = 7 * 24 * 3600

# 최소 빈도 -- 이 이상 등장해야 테마로 인정한다
_MIN_FREQUENCY: int = 2


def _extract_themes(news_list: list[ClassifiedNews]) -> Counter:
    """뉴스 목록에서 카테고리+방향 조합으로 테마를 추출한다."""
    themes: Counter = Counter()
    for news in news_list:
        theme_key = f"{news.category}_{news.direction}"
        themes[theme_key] += 1
    return themes


def _determine_trend(current: int, previous: int) -> str:
    """이전 대비 현재 빈도로 추세를 판단한다."""
    if previous == 0:
        return "rising"
    ratio = current / previous
    if ratio > 1.2:
        return "rising"
    if ratio < 0.8:
        return "declining"
    return "stable"


def _cache_key(theme: str) -> str:
    """테마의 캐시 키를 생성한다."""
    return f"{_KEY_PREFIX}{theme}"


class NewsThemeTracker:
    """반복 테마를 감지하고 캐시에서 빈도/추세를 추적한다.

    카테고리+방향 조합(예: macro_bearish)을 테마 키로 사용한다.
    7일간 캐시에 빈도를 누적하며, rising/stable/declining 추세를 판단한다.
    """

    def __init__(self, cache_client: CacheClient) -> None:
        self._cache = cache_client
        logger.info("NewsThemeTracker 초기화 완료")

    async def track(
        self,
        news_list: list[ClassifiedNews],
    ) -> list[ThemeSummary]:
        """뉴스에서 테마를 추출하고 캐시와 대조하여 추세를 반환한다."""
        current_themes = _extract_themes(news_list)
        summaries: list[ThemeSummary] = []

        for theme, count in current_themes.items():
            if count < _MIN_FREQUENCY:
                continue
            summary = await self._process_theme(theme, count)
            summaries.append(summary)

        logger.info("테마 추적 완료: %d개 테마 감지", len(summaries))
        return summaries

    async def _process_theme(self, theme: str, count: int) -> ThemeSummary:
        """단일 테마의 추세를 캐시와 대조하여 계산한다."""
        prev_total, prev_batch = await self._get_previous(theme)
        trend = _determine_trend(count, prev_batch)
        new_total = prev_total + count
        await self._save_count(theme, new_total, count)

        return ThemeSummary(
            theme=theme,
            frequency=new_total,
            trend=trend,
        )

    async def _get_previous(self, theme: str) -> tuple[int, int]:
        """캐시에서 이전 누적 빈도와 직전 배치 빈도를 조회한다."""
        try:
            raw = await self._cache.read(_cache_key(theme))
            if raw is None:
                return 0, 0
            data = json.loads(raw)
            return int(data.get("count", 0)), int(data.get("last_batch", 0))
        except (json.JSONDecodeError, ValueError):
            return 0, 0

    async def _save_count(self, theme: str, total: int, batch: int) -> None:
        """캐시에 테마 누적 빈도와 현재 배치 빈도를 저장한다."""
        try:
            data = json.dumps({"count": total, "last_batch": batch})
            await self._cache.write(_cache_key(theme), data, ttl=_THEME_TTL)
        except Exception:
            logger.exception("테마 빈도 저장 실패: %s", theme)
