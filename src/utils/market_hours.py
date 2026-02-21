"""
미국 주식 시장 시간 관리 (KST 기준)

모든 시간은 Asia/Seoul(KST) 기준 timezone-aware datetime으로 처리한다.
서머타임(DST) 전환은 US/Eastern 표준 규칙을 따른다.

미국 거래 시간 (KST):
| 구분        | 비서머타임 (11~3월)  | 서머타임 (3~11월)    |
|-------------|---------------------|---------------------|
| 프리마켓    | 18:00 ~ 23:30       | 17:00 ~ 22:30       |
| 정규장      | 23:30 ~ 06:00(+1)   | 22:30 ~ 05:00(+1)   |
| 애프터마켓  | 06:00 ~ 09:00       | 05:00 ~ 08:00       |
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
US_EASTERN = ZoneInfo("US/Eastern")

# 준비 단계 시작 시간 상수 (KST 기준)
# 서머타임(EDT) 적용 시: 22:00 KST / 비서머타임(EST) 시: 23:00 KST
_PREP_TIME_DST = time(22, 0)
_PREP_TIME_STANDARD = time(23, 0)

# 미국 공휴일 (NYSE 휴장일) -- 2025~2027 하드코딩
# 정확한 날짜는 NYSE 공식 캘린더 기반
_US_MARKET_HOLIDAYS: set[date] = {
    # 2025
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # MLK Day
    date(2025, 2, 17),   # Presidents Day
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed, 7/4 is Saturday)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
    # 2027
    date(2027, 1, 1),    # New Year's Day
    date(2027, 1, 18),   # MLK Day
    date(2027, 2, 15),   # Presidents Day
    date(2027, 3, 26),   # Good Friday
    date(2027, 5, 31),   # Memorial Day
    date(2027, 6, 18),   # Juneteenth (observed, 6/19 is Saturday)
    date(2027, 7, 5),    # Independence Day (observed, 7/4 is Sunday)
    date(2027, 9, 6),    # Labor Day
    date(2027, 11, 25),  # Thanksgiving
    date(2027, 12, 24),  # Christmas (observed, 12/25 is Saturday)
}


class MarketHours:
    """미국 주식 시장 시간을 KST 기준으로 관리한다.

    내부적으로 US/Eastern 타임존을 사용하여 서머타임을 자동 처리하고,
    사용자에게는 KST datetime을 반환한다.
    """

    # US Eastern 기준 시장 시간 (EST/EDT 자동 적용)
    _PRE_MARKET_START_ET = time(4, 0)    # 04:00 ET
    _REGULAR_OPEN_ET = time(9, 30)       # 09:30 ET
    _REGULAR_CLOSE_ET = time(16, 0)      # 16:00 ET
    _AFTER_MARKET_END_ET = time(19, 0)   # 19:00 ET

    def _now_kst(self) -> datetime:
        """현재 KST 시각을 반환한다."""
        return datetime.now(tz=KST)

    def _to_kst(self, dt: datetime) -> datetime:
        """timezone-aware datetime을 KST로 변환한다."""
        return dt.astimezone(KST)

    def _to_eastern(self, dt: datetime) -> datetime:
        """timezone-aware datetime을 US/Eastern으로 변환한다."""
        return dt.astimezone(US_EASTERN)

    def _ensure_aware(self, dt: datetime | None) -> datetime:
        """dt가 None이면 현재 KST를, naive이면 KST로 간주하여 반환한다."""
        if dt is None:
            return self._now_kst()
        if dt.tzinfo is None:
            return dt.replace(tzinfo=KST)
        return dt

    def is_dst(self, dt: datetime | None = None) -> bool:
        """현재(또는 지정) 시점이 미국 서머타임(EDT)인지 확인한다.

        Args:
            dt: 확인할 시점. None이면 현재 시각.

        Returns:
            서머타임 적용 중이면 True.
        """
        dt = self._ensure_aware(dt)
        dt_eastern = self._to_eastern(dt)
        # US/Eastern에서 DST 적용 중이면 utcoffset이 -4시간 (EDT)
        # 아니면 -5시간 (EST)
        return dt_eastern.utcoffset() == timedelta(hours=-4)

    def _get_market_times_et(self, target_date: date) -> dict[str, datetime]:
        """주어진 날짜의 미국 동부 기준 시장 시간을 반환한다.

        Args:
            target_date: 미국 동부 기준 거래일 날짜.

        Returns:
            ET 기준 시장 시간 dict.
        """
        return {
            "pre_market_start": datetime.combine(
                target_date, self._PRE_MARKET_START_ET, tzinfo=US_EASTERN
            ),
            "regular_open": datetime.combine(
                target_date, self._REGULAR_OPEN_ET, tzinfo=US_EASTERN
            ),
            "regular_close": datetime.combine(
                target_date, self._REGULAR_CLOSE_ET, tzinfo=US_EASTERN
            ),
            "after_market_end": datetime.combine(
                target_date, self._AFTER_MARKET_END_ET, tzinfo=US_EASTERN
            ),
        }

    def _get_us_trading_date(self, dt: datetime) -> date:
        """KST datetime에 대응하는 미국 거래일 날짜를 반환한다.

        KST를 US/Eastern으로 변환한 후, 만약 자정 이전 (04:00 이전)이면
        아직 전날의 애프터마켓일 수 있으므로 전날 날짜를 반환하지 않고,
        US/Eastern 날짜를 그대로 사용한다.
        """
        dt_et = self._to_eastern(dt)
        return dt_et.date()

    def get_session_type(self, dt: datetime | None = None) -> str:
        """현재 세션 타입을 반환한다.

        Args:
            dt: 확인할 시점. None이면 현재 시각.

        Returns:
            'pre_market', 'regular', 'after_market', 'closed' 중 하나.
        """
        dt = self._ensure_aware(dt)
        dt_et = self._to_eastern(dt)
        us_date = dt_et.date()

        # 주말 체크
        if us_date.weekday() >= 5:
            return "closed"

        # 공휴일 체크
        if us_date in _US_MARKET_HOLIDAYS:
            return "closed"

        times = self._get_market_times_et(us_date)

        if times["pre_market_start"] <= dt_et < times["regular_open"]:
            return "pre_market"
        elif times["regular_open"] <= dt_et < times["regular_close"]:
            return "regular"
        elif times["regular_close"] <= dt_et < times["after_market_end"]:
            return "after_market"
        else:
            return "closed"

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """정규장이 열려있는지 확인한다.

        Args:
            dt: 확인할 시점.

        Returns:
            정규장 거래 시간이면 True.
        """
        return self.get_session_type(dt) == "regular"

    def is_tradeable(self, dt: datetime | None = None) -> bool:
        """거래 가능 여부를 확인한다 (프리마켓 + 정규장 + 애프터마켓).

        Args:
            dt: 확인할 시점.

        Returns:
            거래 가능 시간이면 True.
        """
        return self.get_session_type(dt) in ("pre_market", "regular", "after_market")

    def _next_regular_open(self, dt: datetime) -> datetime:
        """dt 이후 가장 가까운 정규장 개장 시각(KST)을 반환한다."""
        dt_et = self._to_eastern(dt)
        candidate_date = dt_et.date()

        # 오늘 정규장 개장 시각이 아직 지나지 않았으면 오늘 사용
        today_open = datetime.combine(
            candidate_date, self._REGULAR_OPEN_ET, tzinfo=US_EASTERN
        )
        if dt_et < today_open and self._is_trading_day_us(candidate_date):
            return self._to_kst(today_open)

        # 다음 거래일 찾기
        candidate_date += timedelta(days=1)
        while not self._is_trading_day_us(candidate_date):
            candidate_date += timedelta(days=1)

        next_open = datetime.combine(
            candidate_date, self._REGULAR_OPEN_ET, tzinfo=US_EASTERN
        )
        return self._to_kst(next_open)

    def _next_regular_close(self, dt: datetime) -> datetime:
        """dt 이후 가장 가까운 정규장 마감 시각(KST)을 반환한다."""
        dt_et = self._to_eastern(dt)
        candidate_date = dt_et.date()

        today_close = datetime.combine(
            candidate_date, self._REGULAR_CLOSE_ET, tzinfo=US_EASTERN
        )
        if dt_et < today_close and self._is_trading_day_us(candidate_date):
            return self._to_kst(today_close)

        candidate_date += timedelta(days=1)
        while not self._is_trading_day_us(candidate_date):
            candidate_date += timedelta(days=1)

        next_close = datetime.combine(
            candidate_date, self._REGULAR_CLOSE_ET, tzinfo=US_EASTERN
        )
        return self._to_kst(next_close)

    def time_until_open(self, dt: datetime | None = None) -> timedelta:
        """정규장 개장까지 남은 시간을 반환한다.

        이미 정규장 시간이면 timedelta(0)을 반환한다.

        Args:
            dt: 기준 시점.

        Returns:
            개장까지 남은 시간.
        """
        dt = self._ensure_aware(dt)
        if self.is_market_open(dt):
            return timedelta(0)
        next_open = self._next_regular_open(dt)
        return next_open - dt

    def time_until_close(self, dt: datetime | None = None) -> timedelta:
        """정규장 마감까지 남은 시간을 반환한다.

        정규장이 아닌 시간이면 다음 정규장 마감까지의 시간을 반환한다.

        Args:
            dt: 기준 시점.

        Returns:
            마감까지 남은 시간.
        """
        dt = self._ensure_aware(dt)
        next_close = self._next_regular_close(dt)
        return next_close - dt

    def should_eod_close(
        self, dt: datetime | None = None, minutes_before: int = 30
    ) -> bool:
        """EOD(End of Day) 청산 시점인지 확인한다.

        정규장 마감 N분 전부터 마감까지를 EOD 청산 구간으로 판단한다.

        Args:
            dt: 기준 시점.
            minutes_before: 마감 몇 분 전부터 청산 구간인지.

        Returns:
            EOD 청산 시점이면 True.
        """
        dt = self._ensure_aware(dt)
        if not self.is_market_open(dt):
            return False

        remaining = self.time_until_close(dt)
        return timedelta(0) < remaining <= timedelta(minutes=minutes_before)

    def get_market_schedule(self, dt: datetime | None = None) -> dict[str, datetime]:
        """해당 날짜의 시장 스케줄을 KST 기준으로 반환한다.

        Args:
            dt: 기준 날짜가 포함된 시점. None이면 오늘(KST).

        Returns:
            KST 기준 시장 시간 딕셔너리::

                {
                    "pre_market_start": datetime,
                    "regular_open": datetime,
                    "regular_close": datetime,
                    "after_market_end": datetime,
                }
        """
        dt = self._ensure_aware(dt)
        dt_et = self._to_eastern(dt)
        us_date = dt_et.date()
        times_et = self._get_market_times_et(us_date)
        return {key: self._to_kst(val) for key, val in times_et.items()}

    def _is_trading_day_us(self, d: date) -> bool:
        """미국 동부 기준 날짜가 거래일인지 확인한다."""
        if d.weekday() >= 5:
            return False
        if d in _US_MARKET_HOLIDAYS:
            return False
        return True

    def is_trading_day(self, dt: datetime | None = None) -> bool:
        """거래일인지 확인한다 (주말, 미국 공휴일 제외).

        Args:
            dt: 기준 시점. None이면 현재 시각.

        Returns:
            거래일이면 True.
        """
        dt = self._ensure_aware(dt)
        dt_et = self._to_eastern(dt)
        return self._is_trading_day_us(dt_et.date())

    def get_next_trading_day(self, dt: datetime | None = None) -> date:
        """다음 거래일 날짜(US Eastern 기준)를 반환한다.

        Args:
            dt: 기준 시점. None이면 현재 시각.

        Returns:
            다음 거래일 date 객체.
        """
        dt = self._ensure_aware(dt)
        dt_et = self._to_eastern(dt)
        candidate = dt_et.date() + timedelta(days=1)
        while not self._is_trading_day_us(candidate):
            candidate += timedelta(days=1)
        return candidate

    def get_preparation_start_time(self, dt: datetime | None = None) -> datetime:
        """준비 단계 시작 시간을 KST로 반환한다.

        서머타임이면 22:00 KST, 비서머타임이면 23:00 KST.
        이 시간에 데이터 수집 및 분석 준비를 시작한다.

        Args:
            dt: 기준 시점. None이면 현재 시각.

        Returns:
            KST 기준 준비 시작 시각.
        """
        dt = self._ensure_aware(dt)
        kst_date = dt.astimezone(KST).date()

        if self.is_dst(dt):
            prep_time = _PREP_TIME_DST
        else:
            prep_time = _PREP_TIME_STANDARD

        return datetime.combine(kst_date, prep_time, tzinfo=KST)

    # -----------------------------------------------------------------------
    # 운영 윈도우 (Operating Window) 관련 메서드
    # -----------------------------------------------------------------------

    def _get_window_start_hour(self, dt: datetime) -> int:
        """DST 여부에 따라 운영 윈도우 시작 시각(KST 시)을 반환한다.

        서머타임(EDT)이면 22시, 비서머타임(EST)이면 23시.
        """
        return 22 if self.is_dst(dt) else 23

    def _get_window_start_for_date(self, kst_date: date, dt: datetime) -> datetime:
        """주어진 KST 날짜의 운영 윈도우 시작 datetime(KST)을 반환한다."""
        start_hour = self._get_window_start_hour(dt)
        return datetime.combine(kst_date, time(start_hour, 0), tzinfo=KST)

    def _get_window_end_for_date(self, kst_date: date) -> datetime:
        """주어진 KST 날짜 기준으로 운영 윈도우 종료 datetime(KST)을 반환한다.

        운영 윈도우 종료는 항상 다음날 07:00 KST이다.
        """
        next_date = kst_date + timedelta(days=1)
        return datetime.combine(next_date, time(7, 0), tzinfo=KST)

    def is_operating_window(self, dt: datetime | None = None) -> bool:
        """현재 시각이 자동매매 운영 윈도우 안인지 확인한다.

        운영 윈도우는 DST에 따라 달라진다:
        - 비서머타임(EST): 23:00 KST ~ 익일 07:00 KST
        - 서머타임(EDT):   22:00 KST ~ 익일 07:00 KST

        토요일 23:00 이후 시작하는 세션(일요일 새벽)은 미국 시장이 열리지 않으므로
        운영 윈도우에 포함하지 않는다.

        Args:
            dt: 확인할 시점. None이면 현재 시각.

        Returns:
            운영 윈도우 내이면 True.
        """
        dt = self._ensure_aware(dt)
        now_kst = dt.astimezone(KST)
        hour = now_kst.hour
        weekday = now_kst.weekday()  # 0=월, 5=토, 6=일

        start_hour = self._get_window_start_hour(dt)

        # 윈도우 시작 시각(22 또는 23)부터 자정 전
        if hour >= start_hour:
            # 토요일 22:00/23:00 이후 시작은 일요일 새벽으로 연결 → 미국 시장 미개장 제외
            if weekday == 5:  # 토요일
                return False
            return True

        # 자정 이후 ~ 07:00 KST
        if hour < 7:
            return True

        return False

    def get_next_operating_window_start(self, dt: datetime | None = None) -> datetime:
        """다음 운영 윈도우 시작 시각(KST)을 반환한다.

        현재 운영 윈도우 내에 있으면 이미 시작된 현재 윈도우의 시작 시각을 반환한다.
        운영 윈도우 밖이면 다음 유효한 윈도우의 시작 시각을 반환한다.

        Args:
            dt: 기준 시점. None이면 현재 시각.

        Returns:
            KST 기준 다음(또는 현재) 운영 윈도우 시작 datetime.
        """
        dt = self._ensure_aware(dt)
        now_kst = dt.astimezone(KST)

        if self.is_operating_window(dt):
            # 현재 윈도우 시작 시각을 역산한다.
            # 자정 이후(00:00~07:00)이면 전날이 윈도우 시작일이다.
            hour = now_kst.hour
            start_hour = self._get_window_start_hour(dt)
            if hour < start_hour:
                # 자정 이후이므로 시작 날짜는 전날
                start_date = now_kst.date() - timedelta(days=1)
            else:
                start_date = now_kst.date()
            return self._get_window_start_for_date(start_date, dt)

        # 윈도우 밖 → 오늘 또는 내일 윈도우 시작을 탐색
        candidate_date = now_kst.date()
        for _ in range(8):  # 최대 1주일 탐색
            candidate_start = self._get_window_start_for_date(candidate_date, dt)
            if candidate_start > now_kst:
                # 토요일 시작 윈도우 제외 (일요일 새벽으로 연결)
                if candidate_date.weekday() != 5:  # 5=토요일
                    return candidate_start
            candidate_date += timedelta(days=1)

        # fallback: 8일 후 (이론적으로 도달 불가)
        return self._get_window_start_for_date(candidate_date, dt)

    def get_operating_window_info(self, dt: datetime | None = None) -> dict:
        """운영 윈도우 상태 정보를 딕셔너리로 반환한다.

        Returns:
            dict with:
                is_active (bool): 현재 운영 윈도우 내인지 여부.
                is_trading_day (bool): 오늘이 거래일인지 여부.
                window_start_kst (str): 현재(또는 다음) 운영 윈도우 시작 시각 (ISO 형식, KST).
                window_end_kst (str): 현재(또는 다음) 운영 윈도우 종료 시각 (ISO 형식, KST).
                next_window_start_kst (str): 다음 운영 윈도우 시작 시각 (ISO 형식, KST).
                current_kst (str): 현재 KST 시각 (ISO 형식).
                is_dst (bool): 현재 미국 서머타임 적용 여부.
        """
        dt = self._ensure_aware(dt)
        now_kst = dt.astimezone(KST)
        is_active = self.is_operating_window(dt)
        trading_day = self.is_trading_day(dt)

        window_start = self.get_next_operating_window_start(dt)
        # 윈도우 종료는 시작 날짜 기준 다음날 07:00 KST
        window_end = self._get_window_end_for_date(window_start.date())

        # 다음 윈도우 시작: 현재 윈도우 안이면 그 다음 윈도우를 계산한다.
        if is_active:
            next_start_candidate = window_end + timedelta(hours=16)
            next_window_start = self.get_next_operating_window_start(
                self._ensure_aware(next_start_candidate)
            )
        else:
            next_window_start = window_start

        return {
            "is_active": is_active,
            "is_trading_day": trading_day,
            "window_start_kst": window_start.isoformat(),
            "window_end_kst": window_end.isoformat(),
            "next_window_start_kst": next_window_start.isoformat(),
            "current_kst": now_kst.isoformat(),
            "is_dst": self.is_dst(dt),
        }


# 모듈 레벨 싱글톤
_market_hours: MarketHours | None = None


def get_market_hours() -> MarketHours:
    """MarketHours 싱글톤 인스턴스를 반환한다."""
    global _market_hours
    if _market_hours is None:
        _market_hours = MarketHours()
    return _market_hours
