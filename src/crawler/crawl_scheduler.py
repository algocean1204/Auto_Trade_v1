"""
Night/Day 모드 기반 크롤링 스케줄러.

KST(한국 표준시) 기준으로 야간 모드(미국 장 시간)와 주간 모드를 자동 판별하여
소스별 크롤링 주기를 동적으로 조절한다.

- Night mode (23:00~06:30 KST): 미국 장 시간대, 공격적 폴링
- Day mode (06:30~23:00 KST): 한국 주간 시간대, 완화된 폴링
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.logger import get_logger

logger = get_logger(__name__)

_KST = ZoneInfo("Asia/Seoul")

# ── 크롤링 간격 설정 (초 단위) ──

# Night mode 전환 시각 (KST)
_NIGHT_MODE_START_HOUR: int = 23       # 23:00 KST 이후 night mode 진입
_NIGHT_MODE_END_HOUR: int = 6          # 06:xx KST까지 night mode 유지
_NIGHT_MODE_END_MINUTE: int = 30       # 06:30 KST에 day mode 전환

# 기본 폴백 간격 (소스 키가 아래 딕셔너리에 없을 때 사용)
_NIGHT_DEFAULT_INTERVAL: int = 900     # 15분
_DAY_DEFAULT_INTERVAL: int = 1800      # 30분

# RSS 피드 공통 간격
_NIGHT_RSS_INTERVAL: int = 600         # 10분
_DAY_RSS_INTERVAL: int = 1800          # 30분

# --- RSS 피드 소스 키 목록 ---
_RSS_FEED_KEYS: set[str] = {
    "reuters",
    "bloomberg_rss",
    "yahoo_finance",
    "cnbc",
    "marketwatch",
    "wsj_rss",
    "fed_announcements",
    "ft",
    "ecb_press",
    "bbc_business",
    "nikkei_asia",
    "scmp",
    "yonhap_en",
    "hankyung",
    "mk",
}

# --- Night mode 소스별 간격 (초) ---
_NIGHT_INTERVALS: dict[str, int] = {
    "finnhub": 300,
    "alphavantage": 1800,
    "naver_finance": 600,
    "fred_data": 3600,
    "finviz": 300,
    "investing_com": 1800,
    "cnn_fear_greed": 3600,
    "polymarket": 1800,
    "kalshi": 1800,
    "stocknow": 3600,
}

# --- Day mode 소스별 간격 (초) ---
_DAY_INTERVALS: dict[str, int] = {
    "finnhub": 900,
    "alphavantage": 0,      # 비활성
    "naver_finance": 1800,
    "fred_data": 3600,
    "finviz": 900,
    "investing_com": 3600,
    "cnn_fear_greed": 86400,  # 하루 1회
    "polymarket": 3600,
    "kalshi": 3600,
    "stocknow": 3600,
}


class CrawlScheduler:
    """Night/Day 모드 기반 크롤링 스케줄러이다.

    KST 기준으로 야간(미국 장 시간)과 주간을 판별하여
    소스별 크롤링 간격을 동적으로 조절한다.
    마지막 크롤링 시각을 기록하여 due 여부를 판단한다.
    """

    def __init__(self) -> None:
        """스케줄러를 초기화한다."""
        self._last_crawl_times: dict[str, datetime] = {}
        logger.info("CrawlScheduler 초기화 완료 (KST 기반 Night/Day 모드)")

    def get_mode(self) -> str:
        """현재 KST 시각 기준으로 모드를 판별한다.

        - Night mode: 23:00 ~ 06:30 KST (미국 장 시간)
        - Day mode: 06:30 ~ 23:00 KST

        Returns:
            "night" 또는 "day" 문자열.
        """
        now_kst = datetime.now(tz=_KST)
        hour = now_kst.hour
        minute = now_kst.minute

        # _NIGHT_MODE_START_HOUR 이후 또는 _NIGHT_MODE_END_HOUR:_NIGHT_MODE_END_MINUTE 이전이면 night
        if hour >= _NIGHT_MODE_START_HOUR:
            return "night"
        if hour < _NIGHT_MODE_END_HOUR:
            return "night"
        if hour == _NIGHT_MODE_END_HOUR and minute < _NIGHT_MODE_END_MINUTE:
            return "night"

        return "day"

    def get_interval(self, source_key: str) -> int:
        """소스 키에 대한 현재 모드의 크롤링 간격(초)을 반환한다.

        간격이 0이면 해당 소스는 비활성(disabled) 상태이다.

        Args:
            source_key: 크롤링 소스 식별 키.

        Returns:
            크롤링 간격 (초). 0이면 비활성.
        """
        mode = self.get_mode()

        if mode == "night":
            # 명시적 간격이 있으면 사용
            if source_key in _NIGHT_INTERVALS:
                return _NIGHT_INTERVALS[source_key]
            # RSS 피드 소스
            if source_key in _RSS_FEED_KEYS:
                return _NIGHT_RSS_INTERVAL
            # 기본값
            return _NIGHT_DEFAULT_INTERVAL
        else:
            # 명시적 간격이 있으면 사용
            if source_key in _DAY_INTERVALS:
                return _DAY_INTERVALS[source_key]
            # RSS 피드 소스
            if source_key in _RSS_FEED_KEYS:
                return _DAY_RSS_INTERVAL
            # 기본값
            return _DAY_DEFAULT_INTERVAL

    def should_crawl(self, source_key: str) -> bool:
        """마지막 크롤링 이후 충분한 시간이 경과했는지 판단한다.

        - 간격이 0이면 비활성이므로 False를 반환한다.
        - 마지막 크롤링 기록이 없으면 즉시 실행 대상이다.

        Args:
            source_key: 크롤링 소스 식별 키.

        Returns:
            크롤링을 실행해야 하면 True.
        """
        try:
            interval = self.get_interval(source_key)

            # 비활성 소스
            if interval == 0:
                return False

            # 최초 실행 (기록 없음)
            last_time = self._last_crawl_times.get(source_key)
            if last_time is None:
                return True

            # 경과 시간 확인
            now = datetime.now(tz=timezone.utc)
            elapsed = (now - last_time).total_seconds()
            return elapsed >= interval
        except Exception as e:
            logger.error(
                "should_crawl 판단 실패 (source=%s): %s", source_key, e
            )
            # 오류 시 안전하게 실행하지 않음
            return False

    def record_crawl(self, source_key: str) -> None:
        """크롤링 완료 시각을 기록한다.

        Args:
            source_key: 크롤링 소스 식별 키.
        """
        self._last_crawl_times[source_key] = datetime.now(tz=timezone.utc)
        logger.debug(
            "크롤링 기록 완료: %s (mode=%s)", source_key, self.get_mode()
        )

    def get_due_sources(self, available_sources: list[str] | None = None) -> list[str]:
        """크롤링이 필요한 소스 키 목록을 반환한다.

        Args:
            available_sources: 확인할 소스 키 목록. None이면 기록된 모든 소스와
                               available_sources 모두에서 확인하지 않고, 빈 리스트를
                               반환한다. CrawlEngine에서 등록된 소스 키를 전달해야 한다.

        Returns:
            크롤링이 필요한 소스 키 리스트.
        """
        if available_sources is None:
            return []

        due: list[str] = []
        for source_key in available_sources:
            try:
                if self.should_crawl(source_key):
                    due.append(source_key)
            except Exception as e:
                logger.error(
                    "get_due_sources 오류 (source=%s): %s", source_key, e
                )
        return due

    def get_schedule_info(self) -> dict[str, Any]:
        """현재 스케줄 상태 정보를 반환한다.

        디버깅 및 모니터링 API에서 사용한다.

        Returns:
            모드, 소스별 간격, 마지막 크롤링 시각 등의 정보 딕셔너리.
        """
        mode = self.get_mode()
        now_kst = datetime.now(tz=_KST)
        now_utc = datetime.now(tz=timezone.utc)

        last_crawl_info: dict[str, str | None] = {}
        for key, dt in self._last_crawl_times.items():
            elapsed = (now_utc - dt).total_seconds()
            last_crawl_info[key] = f"{elapsed:.0f}s ago"

        return {
            "mode": mode,
            "kst_time": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
            "utc_time": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "last_crawls": last_crawl_info,
        }
