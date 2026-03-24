"""
MarketClock (C0.11) -- KST/ET 시각과 매매 윈도우, 시장 세션 유형을 제공한다.
서머타임(EDT/EST)은 ZoneInfo("US/Eastern")이 자동 처리한다.
미국 시장 공휴일(NYSE 비거래일)을 인지하여 공휴일 매매를 방지한다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

_KST: ZoneInfo = ZoneInfo("Asia/Seoul")
_ET: ZoneInfo = ZoneInfo("US/Eastern")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """해당 월의 n번째 특정 요일 날짜를 반환한다.

    Args:
        year: 연도
        month: 월
        weekday: 요일 (0=월, ..., 6=일)
        n: 몇 번째 (1-based)
    """
    first = date(year, month, 1)
    # 첫 번째 해당 요일까지의 차이를 계산한다
    diff = (weekday - first.weekday()) % 7
    first_occurrence = first + timedelta(days=diff)
    return first_occurrence + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """해당 월의 마지막 특정 요일 날짜를 반환한다."""
    # 다음 달 1일에서 거꾸로 찾는다
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    last_day = next_first - timedelta(days=1)
    diff = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=diff)


def _get_us_market_holidays(year: int) -> set[date]:
    """해당 연도의 NYSE 비거래 공휴일 목록을 반환한다.

    NYSE 기준 9개 공휴일을 포함한다.
    공휴일이 토요일이면 금요일로, 일요일이면 월요일로 대체한다.
    """
    holidays: list[date] = []

    # 1. 새해 (1/1)
    new_year = date(year, 1, 1)
    holidays.append(new_year)

    # 2. 마틴 루터 킹 주니어 데이 (1월 셋째 월요일)
    holidays.append(_nth_weekday(year, 1, 0, 3))

    # 3. 대통령의 날 (2월 셋째 월요일)
    holidays.append(_nth_weekday(year, 2, 0, 3))

    # 4. 굿 프라이데이 -- 부활절 전 금요일
    # 부활절 날짜 계산 (Anonymous Gregorian Algorithm)
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l_val = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_val) // 451
    month = (h + l_val - 7 * m + 114) // 31
    day = ((h + l_val - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    good_friday = easter - timedelta(days=2)
    holidays.append(good_friday)

    # 5. 메모리얼 데이 (5월 마지막 월요일)
    holidays.append(_last_weekday(year, 5, 0))

    # 6. Juneteenth (6/19) -- 2021년부터 연방 공휴일
    holidays.append(date(year, 6, 19))

    # 7. 독립기념일 (7/4)
    holidays.append(date(year, 7, 4))

    # 8. 노동절 (9월 첫째 월요일)
    holidays.append(_nth_weekday(year, 9, 0, 1))

    # 9. 추수감사절 (11월 넷째 목요일)
    holidays.append(_nth_weekday(year, 11, 3, 4))

    # 10. 크리스마스 (12/25)
    holidays.append(date(year, 12, 25))

    # 주말 대체 규칙: 토요일→금요일, 일요일→월요일
    adjusted: set[date] = set()
    for h in holidays:
        if h.weekday() == 5:  # 토요일 → 금요일
            adjusted.add(h - timedelta(days=1))
        elif h.weekday() == 6:  # 일요일 → 월요일
            adjusted.add(h + timedelta(days=1))
        else:
            adjusted.add(h)
    return adjusted


# 연도별 공휴일 캐시 — 매번 재계산하지 않는다
_holiday_cache: dict[int, set[date]] = {}


def is_us_market_holiday(et_date: date) -> bool:
    """해당 날짜(ET 기준)가 미국 시장 공휴일인지 판별한다."""
    year = et_date.year
    if year not in _holiday_cache:
        _holiday_cache[year] = _get_us_market_holidays(year)
    return et_date in _holiday_cache[year]


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
    is_near_close: bool
    is_market_holiday: bool
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


def _check_near_close(now_et: datetime) -> bool:
    """ET 기준 장 마감 직전 구간(15:30~16:00)인지 판별한다.

    유동성이 급감하는 마감 30분 동안 신규 진입을 차단하기 위한 판별이다.
    """
    mins = _to_minutes(now_et.hour, now_et.minute)
    return 930 <= mins < 960


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
        holiday = is_us_market_holiday(et.date())

        # 공휴일이면 매매 윈도우를 비활성화한다
        trading_window = _check_trading_window(kst) and not holiday

        return TimeInfo(
            now_kst=kst,
            now_et=et,
            is_trading_window=trading_window,
            session_type=session,
            is_regular_session=_check_regular_session(et) and not holiday,
            is_danger_zone=_check_danger_zone(et),
            is_near_close=_check_near_close(et),
            is_market_holiday=holiday,
            loop_interval_seconds=_LOOP_INTERVALS[session],
        )

    def is_trading_window(self) -> bool:
        """매매 가능 윈도우(20:00~다음날 06:30 KST)를 판별한다.

        미국 시장 공휴일이면 매매 윈도우를 비활성화한다.
        """
        kst = self._now_kst()
        et = self._now_et(kst)
        if is_us_market_holiday(et.date()):
            return False
        return _check_trading_window(kst)

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
            "is_near_close": info.is_near_close,
            "is_market_holiday": info.is_market_holiday,
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
