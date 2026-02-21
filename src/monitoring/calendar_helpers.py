"""
경제 캘린더 및 FOMC 일정 헬퍼 함수.

macro_endpoints.py에서 분리된 모듈로, 정기 경제 이벤트 생성,
FRED 릴리즈 캘린더 조회, FOMC 예정일 관리 기능을 제공한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx

from src.monitoring.fred_client import _FRED_BASE_URL, get_cached, set_cache
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_CALENDAR_API_TIMEOUT: float = 10.0

# FRED 릴리즈 일정 캐시 TTL (초)
_FRED_RELEASES_CACHE_TTL: int = 300

# 2025-2026 FOMC 예정일
FOMC_DATES_2025 = [
    date(2025, 12, 17),
]

FOMC_DATES_2026 = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 16),
]

ALL_FOMC_DATES = FOMC_DATES_2025 + FOMC_DATES_2026


def generate_upcoming_events(days_ahead: int = 45) -> list[dict[str, Any]]:
    """향후 정기 경제 이벤트 일정을 생성한다.

    FOMC(6주 주기), NFP(첫 번째 금요일), CPI(~13일), FOMC 의사록(3주 후),
    GDP(월말 전후) 등 반복 패턴 기반으로 이벤트 목록을 생성한다.

    Args:
        days_ahead: 오늘부터 몇 일 앞까지 이벤트를 생성할지.

    Returns:
        date, time, event, impact, previous, forecast, actual 키를 포함하는
        이벤트 딕셔너리 리스트 (날짜 오름차순).
    """
    today = date.today()
    end_date = today + timedelta(days=days_ahead)
    events: list[dict[str, Any]] = []

    for fomc_date in ALL_FOMC_DATES:
        if today <= fomc_date <= end_date:
            events.append({
                "date": fomc_date.isoformat(),
                "time": "14:00",
                "event": "FOMC Rate Decision",
                "impact": "high",
                "previous": None,
                "forecast": None,
                "actual": None,
            })
        # FOMC 의사록은 3주 후 수요일
        minutes_date = fomc_date + timedelta(weeks=3)
        # 해당 주의 수요일(weekday=2)로 맞춘다
        days_to_wed = (2 - minutes_date.weekday()) % 7
        minutes_date += timedelta(days=days_to_wed)
        if today <= minutes_date <= end_date:
            events.append({
                "date": minutes_date.isoformat(),
                "time": "14:00",
                "event": "FOMC Minutes",
                "impact": "medium",
                "previous": None,
                "forecast": None,
                "actual": None,
            })

    # NFP: 매월 첫 번째 금요일 (08:30 EST)
    # CPI: 매월 약 13일 전후 (08:30 EST)
    # PCE: 매월 마지막 금요일 (08:30 EST)
    current = today.replace(day=1)
    while current <= end_date:
        year = current.year
        month = current.month

        # 첫 번째 금요일 계산
        first_day = date(year, month, 1)
        days_to_fri = (4 - first_day.weekday()) % 7
        first_friday = first_day + timedelta(days=days_to_fri)
        if today <= first_friday <= end_date:
            events.append({
                "date": first_friday.isoformat(),
                "time": "08:30",
                "event": "Nonfarm Payrolls (NFP)",
                "impact": "high",
                "previous": None,
                "forecast": None,
                "actual": None,
            })

        # CPI: 해당 월 13일 (주말이면 인접 평일로 이동)
        cpi_target = date(year, month, 13)
        weekday = cpi_target.weekday()
        if weekday == 5:
            cpi_target += timedelta(days=2)
        elif weekday == 6:
            cpi_target += timedelta(days=1)
        if today <= cpi_target <= end_date:
            events.append({
                "date": cpi_target.isoformat(),
                "time": "08:30",
                "event": "CPI (Consumer Price Index)",
                "impact": "high",
                "previous": None,
                "forecast": None,
                "actual": None,
            })

        # PCE: 해당 월 마지막 금요일
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        days_from_fri = (last_day.weekday() - 4) % 7
        last_friday = last_day - timedelta(days=days_from_fri)
        if today <= last_friday <= end_date:
            events.append({
                "date": last_friday.isoformat(),
                "time": "08:30",
                "event": "PCE Price Index",
                "impact": "high",
                "previous": None,
                "forecast": None,
                "actual": None,
            })

        # 다음 달로 이동
        if month == 12:
            current = date(year + 1, 1, 1)
        else:
            current = date(year, month + 1, 1)

    # 중복 제거 및 날짜 오름차순 정렬
    seen: set[str] = set()
    unique_events: list[dict[str, Any]] = []
    for ev in sorted(events, key=lambda x: x["date"]):
        key = f"{ev['date']}_{ev['event']}"
        if key not in seen:
            seen.add(key)
            unique_events.append(ev)

    return unique_events


async def fetch_fred_release_dates(api_key: str, days_ahead: int = 45) -> list[dict[str, Any]]:
    """FRED 릴리즈 캘린더 API에서 예정된 경제 지표 발표일을 조회한다.

    API 호출 실패 시 빈 리스트를 반환하며, 결과는 5분 캐시를 적용한다.

    Args:
        api_key: FRED API 인증 키.
        days_ahead: 오늘부터 몇 일 앞까지 릴리즈 일정을 조회할지.

    Returns:
        date, event, impact 키를 포함하는 이벤트 딕셔너리 리스트.
    """
    cache_key = f"fred_releases_{days_ahead}"
    cached = get_cached(cache_key, ttl=_FRED_RELEASES_CACHE_TTL)
    if cached is not None:
        return cached

    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    url = f"{_FRED_BASE_URL}/releases/dates"
    params = {
        "api_key": api_key,
        "file_type": "json",
        "include_release_dates_with_no_data": "false",
        "realtime_start": today.isoformat(),
        "realtime_end": end_date.isoformat(),
        "limit": 100,
    }

    try:
        async with httpx.AsyncClient(timeout=_CALENDAR_API_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("FRED 릴리즈 캘린더 조회 실패: %s", exc)
        return []

    # 주요 릴리즈만 필터링 (impact 판단을 위한 키워드)
    high_impact_keywords = {
        "consumer price", "employment situation", "gdp",
        "federal open market", "nonfarm", "unemployment",
        "personal income", "retail sales",
    }
    medium_impact_keywords = {
        "industrial production", "housing", "durable goods",
        "trade balance", "producer price",
    }

    events: list[dict[str, Any]] = []
    for release in data.get("release_dates", []):
        release_name = release.get("release_name", "").lower()
        release_date = release.get("date", "")
        if not release_date:
            continue

        try:
            ev_date = date.fromisoformat(release_date)
        except ValueError:
            continue

        if ev_date < today or ev_date > end_date:
            continue

        # 중요도 분류
        if any(kw in release_name for kw in high_impact_keywords):
            impact = "high"
        elif any(kw in release_name for kw in medium_impact_keywords):
            impact = "medium"
        else:
            impact = "low"

        events.append({
            "date": release_date,
            "time": "08:30",
            "event": release.get("release_name", "Unknown"),
            "impact": impact,
            "previous": None,
            "forecast": None,
            "actual": None,
        })

    set_cache(cache_key, events)
    return events


def next_fomc_date() -> str:
    """다음 FOMC 회의 예정일을 반환한다.

    Returns:
        YYYY-MM-DD 형식의 다음 FOMC 예정일 문자열.
    """
    today = date.today()
    for d in ALL_FOMC_DATES:
        if d >= today:
            return d.isoformat()
    return "2027-01-01"
