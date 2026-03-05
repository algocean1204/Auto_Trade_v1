"""
MarketClock (C0.11) -- KST/ET 시각과 매매 윈도우, 시장 세션 유형을 제공한다.
서머타임(EDT/EST)은 ZoneInfo("US/Eastern")이 자동 처리한다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

_KST: ZoneInfo = ZoneInfo("Asia/Seoul")
_ET: ZoneInfo = ZoneInfo("US/Eastern")

_LOOP_INTERVALS: dict[str, int] = {
    "preparation": 60,
    "pre_market": 60,
    "power_open": 90,
    "mid_day": 180,
    "power_hour": 120,
    "final_monitoring": 60,
    "eod_sequence": 60,
    "closed": 60,
}

SessionType = Literal[
    "preparation",
    "pre_market",
    "power_open",
    "mid_day",
    "power_hour",
    "final_monitoring",
    "eod_sequence",
    "closed",
]

_instance: MarketClock | None = None


class TimeInfo(BaseModel):
    """시간 정보 종합 객체이다."""

    now_kst: datetime
    now_et: datetime
    is_trading_window: bool
    session_type: SessionType
    is_regular_session: bool
    is_danger_zone: bool
    loop_interval_seconds: int


def _default_clock() -> datetime:
    """기본 시스템 시계 -- KST 현재 시각을 반환한다."""
    return datetime.now(tz=_KST)


def _to_minutes(hour: int, minute: int) -> int:
    """시:분을 자정 기준 분 단위 정수로 변환한다."""
    return hour * 60 + minute


def _check_trading_window(now_kst: datetime) -> bool:
    """매매 가능 윈도우(20:00~다음날 06:30 KST)를 판별한다."""
    hour, minute = now_kst.hour, now_kst.minute
    if hour >= 20:          # 20:00~23:59 당일 저녁
        return True
    if hour < 6:            # 00:00~05:59 다음날 새벽
        return True
    if hour == 6 and minute < 30:  # 06:00~06:29
        return True
    return False


def _determine_session(now_kst: datetime) -> SessionType:
    """KST 시각 기준 세션 유형을 결정한다."""
    mins = _to_minutes(now_kst.hour, now_kst.minute)
    # 20:00~20:30 (1200~1230)
    if 1200 <= mins < 1230:
        return "preparation"
    # 20:30~23:30 (1230~1410)
    if 1230 <= mins < 1410:
        return "pre_market"
    # 23:30~24:00 (1410~1440)
    if mins >= 1410:
        return "power_open"
    # 00:00~05:30 (0~330)
    if mins < 330:
        return "mid_day"
    # 05:30~06:00 (330~360)
    if mins < 360:
        return "power_hour"
    # 06:00~06:30 (360~390)
    if mins < 390:
        return "final_monitoring"
    # 06:30~07:00 (390~420)
    if mins < 420:
        return "eod_sequence"
    # 07:00~20:00 (420~1200)
    return "closed"


def _check_regular_session(now_et: datetime) -> bool:
    """ET 기준 정규장(09:30~16:00)인지 판별한다."""
    mins = _to_minutes(now_et.hour, now_et.minute)
    # 09:30(570) ~ 16:00(960)
    return 570 <= mins < 960


def _check_danger_zone(now_et: datetime) -> bool:
    """ET 기준 위험 구간(09:30~10:00 또는 15:30~16:00)인지 판별한다."""
    mins = _to_minutes(now_et.hour, now_et.minute)
    # 09:30(570)~10:00(600) 또는 15:30(930)~16:00(960)
    return (570 <= mins < 600) or (930 <= mins < 960)


class MarketClock:
    """시장 시계 -- KST/ET 시각과 세션 상태를 제공한다."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        """시계 함수를 주입받아 초기화한다. None이면 시스템 시계를 사용한다."""
        self._clock = clock or _default_clock

    def _now_kst(self) -> datetime:
        """KST 현재 시각을 반환한다."""
        return self._clock()

    def _now_et(self, kst: datetime) -> datetime:
        """KST를 ET로 변환한다. 서머타임은 ZoneInfo가 자동 처리한다."""
        return kst.astimezone(_ET)

    def get_time_info(self) -> TimeInfo:
        """현재 시간 정보를 종합하여 반환한다."""
        kst = self._now_kst()
        et = self._now_et(kst)
        session = _determine_session(kst)

        return TimeInfo(
            now_kst=kst,
            now_et=et,
            is_trading_window=_check_trading_window(kst),
            session_type=session,
            is_regular_session=_check_regular_session(et),
            is_danger_zone=_check_danger_zone(et),
            loop_interval_seconds=_LOOP_INTERVALS[session],
        )

    def is_trading_window(self) -> bool:
        """매매 가능 윈도우(20:00~다음날 06:30 KST)를 판별한다."""
        return _check_trading_window(self._now_kst())

    def get_session_type(self) -> SessionType:
        """현재 KST 시각 기준 세션 유형을 반환한다."""
        return _determine_session(self._now_kst())

    def is_auto_stop_time(self) -> bool:
        """자동 종료 시각(06:30~20:00 KST)인지 판별한다."""
        kst = self._now_kst()
        hour, minute = kst.hour, kst.minute
        # 06:30 이상 ~ 20:00 미만
        if 7 <= hour < 20:
            return True
        if hour == 6 and minute >= 30:
            return True
        return False

    def get_operating_window_info(self) -> dict:
        """운영 윈도우 정보를 대시보드용 dict로 반환한다."""
        info = self.get_time_info()
        return {
            "now_kst": info.now_kst.isoformat(),
            "now_et": info.now_et.isoformat(),
            "session_type": info.session_type,
            "is_trading_window": info.is_trading_window,
            "is_regular_session": info.is_regular_session,
            "is_danger_zone": info.is_danger_zone,
            "loop_interval_seconds": info.loop_interval_seconds,
            "is_auto_stop": self.is_auto_stop_time(),
        }


def get_market_clock(
    clock: Callable[[], datetime] | None = None,
) -> MarketClock:
    """MarketClock 싱글톤을 반환한다. 최초 호출 시 clock을 주입할 수 있다."""
    global _instance
    if _instance is not None:
        return _instance

    _instance = MarketClock(clock=clock)
    return _instance


def reset_market_clock() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
