"""
FRED (Federal Reserve Economic Data) 시계열 데이터 크롤러.

FRED REST API를 통해 주요 경제 지표의 최신 관측값을 수집한다.
기존 EconomicCalendarCrawler의 RSS 기반 캘린더와 달리,
특정 시계열(DFF, T10Y2Y, VIXCLS, CPIAUCSL, UNRATE)의
실제 데이터 값 변화를 추적하여 변동 알림을 생성한다.

Rate limit: FRED API는 분당 120회 호출을 허용한다.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from src.crawler.base_crawler import BaseCrawler
from src.utils.logger import get_logger

logger = get_logger(__name__)

# FRED API 기본 엔드포인트
_FRED_API_BASE = "https://api.stlouisfed.org/fred/series/observations"

# 추적 대상 FRED 시계열 정의
_DEFAULT_SERIES: dict[str, dict[str, str]] = {
    "DFF": {
        "name": "Federal Funds Rate",
        "description": "연방기금금리 (일일)",
        "frequency": "daily",
    },
    "T10Y2Y": {
        "name": "10Y-2Y Treasury Spread",
        "description": "10년-2년 국채 스프레드 (경기침체 신호)",
        "frequency": "daily",
    },
    "VIXCLS": {
        "name": "VIX Volatility Index",
        "description": "CBOE 변동성 지수 (일일 종가)",
        "frequency": "daily",
    },
    "CPIAUCSL": {
        "name": "CPI (Consumer Price Index)",
        "description": "소비자물가지수 (월간)",
        "frequency": "monthly",
    },
    "UNRATE": {
        "name": "Unemployment Rate",
        "description": "실업률 (월간)",
        "frequency": "monthly",
    },
}

# FRED 시계열 조회 URL 템플릿
_FRED_SERIES_URL = "https://fred.stlouisfed.org/series/{series_id}"


class FREDCrawler(BaseCrawler):
    """FRED REST API를 통해 주요 경제 지표 시계열 데이터를 수집하는 크롤러.

    각 시계열의 최신 관측값을 조회하고, 이전 값과 비교하여
    변화가 감지된 경우에만 알림 기사를 생성한다.
    변화가 없으면 노이즈를 줄이기 위해 기사를 생성하지 않는다.

    지원 시계열:
        - DFF: 연방기금금리
        - T10Y2Y: 10년-2년 국채 스프레드 (경기침체 신호)
        - VIXCLS: VIX 변동성 지수
        - CPIAUCSL: 소비자물가지수 (월간)
        - UNRATE: 실업률 (월간)
    """

    def __init__(self, source_key: str, source_config: dict[str, Any]) -> None:
        super().__init__(source_key, source_config)
        self._api_key = self._resolve_api_key()
        self._series_ids: list[str] = source_config.get(
            "series", list(_DEFAULT_SERIES.keys())
        )
        # 이전 관측값 저장소 (series_id -> value 문자열)
        self._previous_values: dict[str, str] = {}

    def _resolve_api_key(self) -> str:
        """FRED API 키를 설정 또는 환경 변수에서 가져온다.

        우선순위: config["api_key"] > config["api_key_env"] 환경 변수 > FRED_API_KEY 환경 변수
        """
        # 직접 지정된 키
        key = self.config.get("api_key", "")
        if key:
            return key

        # 환경 변수명이 config에 지정된 경우
        env_name = self.config.get("api_key_env", "FRED_API_KEY")
        key = os.environ.get(env_name, "")
        if key:
            return key

        # 기본 환경 변수
        key = os.environ.get("FRED_API_KEY", "")
        if not key:
            logger.warning(
                "[%s] FRED API 키가 설정되지 않았다. "
                "config['api_key'] 또는 환경 변수 FRED_API_KEY를 설정해야 한다.",
                self.name,
            )
        return key

    async def crawl(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """모든 추적 시계열의 최신 관측값을 조회하고 변화 알림을 생성한다.

        Args:
            since: 이 시점 이후 데이터만 반환 (FRED 조회 자체에는 사용하지 않으며,
                   반환된 기사의 published_at 필터에 활용한다).

        Returns:
            변화가 감지된 시계열에 대한 기사 딕셔너리 리스트.
        """
        if not self._api_key:
            logger.error("[%s] API 키가 없어 크롤링을 건너뛴다.", self.name)
            return []

        articles: list[dict[str, Any]] = []

        for series_id in self._series_ids:
            try:
                article = await self._fetch_series(series_id)
                if article is not None:
                    # since 필터 적용
                    if since and article["published_at"] < since:
                        continue
                    articles.append(article)
            except Exception as e:
                logger.error(
                    "[%s] 시계열 %s 조회 실패: %s",
                    self.name, series_id, e, exc_info=True,
                )

        return articles

    async def _fetch_series(self, series_id: str) -> dict[str, Any] | None:
        """단일 FRED 시계열의 최신 관측값을 조회하고, 변화 시 기사를 생성한다.

        Args:
            series_id: FRED 시계열 ID (예: "DFF", "T10Y2Y").

        Returns:
            값이 변경된 경우 기사 딕셔너리, 변화 없으면 None.
        """
        session = await self.get_session()

        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": "1",
        }

        try:
            async with session.get(_FRED_API_BASE, params=params) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[%s] FRED API HTTP %d (series=%s)",
                        self.name, resp.status, series_id,
                    )
                    return None

                data = await resp.json(content_type=None)

        except Exception as e:
            logger.error(
                "[%s] FRED API 요청 실패 (series=%s): %s",
                self.name, series_id, e,
            )
            return None

        return self._process_observation(series_id, data)

    def _process_observation(
        self, series_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """FRED API 응답을 파싱하고, 값 변화가 있으면 기사 딕셔너리를 생성한다.

        Args:
            series_id: FRED 시계열 ID.
            data: FRED API JSON 응답.

        Returns:
            값이 변경된 경우 기사 딕셔너리, 변화 없거나 파싱 실패 시 None.
        """
        observations = data.get("observations", [])
        if not observations:
            logger.debug("[%s] 시계열 %s: 관측값 없음", self.name, series_id)
            return None

        latest = observations[0]
        value_str = latest.get("value", "").strip()
        date_str = latest.get("date", "")

        # FRED에서 "."은 데이터 미가용을 의미한다
        if not value_str or value_str == ".":
            logger.debug(
                "[%s] 시계열 %s: 값이 미가용 ('%s')", self.name, series_id, value_str
            )
            return None

        # 이전 값과 비교하여 변화 여부 확인
        prev_value_str = self._previous_values.get(series_id)
        self._previous_values[series_id] = value_str

        if prev_value_str is not None and prev_value_str == value_str:
            # 변화 없음 - 노이즈 방지를 위해 기사 생성 안 함
            logger.debug(
                "[%s] 시계열 %s: 변화 없음 (값=%s)", self.name, series_id, value_str
            )
            return None

        # 시계열 메타데이터
        series_meta = _DEFAULT_SERIES.get(series_id, {})
        series_name = series_meta.get("name", series_id)

        # 변화량 계산
        diff_str = ""
        diff_value: float | None = None
        try:
            new_val = float(value_str)
            if prev_value_str is not None:
                prev_val = float(prev_value_str)
                diff_value = new_val - prev_val
                diff_str = f"{diff_value:+.4f}"
        except (ValueError, TypeError):
            pass

        # 관측 날짜 파싱 (YYYY-MM-DD 형식)
        try:
            obs_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            obs_date = datetime.now(tz=timezone.utc)

        # 헤드라인 구성
        if prev_value_str is not None and diff_str:
            headline = (
                f"[FRED] {series_name}: {prev_value_str} → {value_str} "
                f"(change: {diff_str})"
            )
        else:
            # 최초 조회 (이전 값 없음) - 현재 값만 보고
            headline = f"[FRED] {series_name}: {value_str} (initial reading)"

        # 본문 구성
        content = (
            f"FRED Series: {series_id} ({series_name})\n"
            f"Description: {series_meta.get('description', 'N/A')}\n"
            f"Observation Date: {date_str}\n"
            f"Value: {value_str}\n"
        )
        if prev_value_str is not None:
            content += f"Previous Value: {prev_value_str}\n"
        if diff_str:
            content += f"Change: {diff_str}\n"

        url = _FRED_SERIES_URL.format(series_id=series_id)

        article = {
            "headline": headline,
            "content": content,
            "url": url,
            "published_at": obs_date,
            "source": self.source_key,
            "language": self.language,
            "metadata": {
                "data_type": "fred_series",
                "series_id": series_id,
                "series_name": series_name,
                "frequency": series_meta.get("frequency", "unknown"),
                "observation_date": date_str,
                "value": value_str,
                "previous_value": prev_value_str,
                "change": diff_value,
                "is_initial": prev_value_str is None,
            },
        }

        logger.info(
            "[%s] 시계열 %s 변화 감지: %s → %s (변화: %s)",
            self.name,
            series_id,
            prev_value_str or "N/A",
            value_str,
            diff_str or "N/A",
        )

        return article
