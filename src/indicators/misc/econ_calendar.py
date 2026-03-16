"""경제 캘린더 생성기이다. 정적 스케줄 기반으로 향후 30일 주요 경제 이벤트를 생성한다.

FOMC, CPI, NFP, GDP, PCE, PPI, Retail Sales, ISM Manufacturing 등
반복 이벤트를 패턴 기반으로 계산하여 macro:calendar 캐시에 기록한다.
외부 API 의존성 없이 공개된 일정 정보만 사용한다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger

logger = get_logger(__name__)

# 캐시 키 및 TTL이다
_CACHE_KEY: str = "macro:calendar"
_CACHE_TTL: int = 86400  # 24시간

# 2026년 FOMC 회의 날짜이다 (공개 일정)
_FOMC_2026: list[tuple[int, int, int, int]] = [
    (1, 27, 1, 28), (3, 17, 3, 18), (4, 28, 4, 29),
    (6, 16, 6, 17), (7, 28, 7, 29), (9, 15, 9, 16),
    (10, 27, 10, 28), (12, 8, 12, 9),
]


def _fomc_events(year: int, start: date, end: date) -> list[dict]:
    """FOMC 회의 이벤트를 생성한다. 2026년은 하드코딩, 그 외는 빈 리스트이다."""
    if year != 2026:
        return []
    events: list[dict] = []
    for m1, d1, m2, d2 in _FOMC_2026:
        meeting_start = date(year, m1, d1)
        meeting_end = date(year, m2, d2)
        if start <= meeting_end and meeting_start <= end:
            events.append({
                "date": meeting_end.isoformat(),
                "name": "FOMC 금리 결정",
                "importance": "high",
                "description": f"FOMC {m1}/{d1}-{m2}/{d2} 회의 결과 발표",
            })
    return events


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """해당 월의 n번째 특정 요일 날짜를 반환한다. weekday: 0=월 ~ 6=일이다."""
    first = date(year, month, 1)
    # 첫 번째 해당 요일까지의 오프셋을 계산한다
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _nfp_events(start: date, end: date) -> list[dict]:
    """비농업 고용지표(NFP) 이벤트를 생성한다. 매월 첫째 금요일이다."""
    events: list[dict] = []
    current = date(start.year, start.month, 1)
    limit = end + timedelta(days=31)
    while current <= limit:
        first_friday = _nth_weekday(current.year, current.month, 4, 1)
        if start <= first_friday <= end:
            events.append({
                "date": first_friday.isoformat(),
                "name": "비농업 고용지표 (NFP)",
                "importance": "high",
                "description": f"{current.year}년 {current.month}월 고용 보고서",
            })
        # 다음 달로 이동한다
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return events


def _monthly_date_events(
    start: date, end: date, day: int, name: str,
    importance: str, desc_template: str,
) -> list[dict]:
    """매월 특정일 기준 이벤트를 생성한다. 주말이면 다음 영업일로 조정한다."""
    events: list[dict] = []
    current = date(start.year, start.month, 1)
    limit = end + timedelta(days=31)
    while current <= limit:
        try:
            target = date(current.year, current.month, min(day, 28))
        except ValueError:
            target = date(current.year, current.month, 28)
        # 주말이면 다음 영업일(월요일)로 조정한다
        while target.weekday() >= 5:
            target += timedelta(days=1)
        if start <= target <= end:
            events.append({
                "date": target.isoformat(),
                "name": name,
                "importance": importance,
                "description": desc_template.format(
                    year=current.year, month=current.month,
                ),
            })
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return events


def _quarterly_gdp_events(start: date, end: date) -> list[dict]:
    """GDP 발표 이벤트를 생성한다. 분기 종료 후 약 28일째 발표된다."""
    events: list[dict] = []
    # 분기별 GDP 속보치 발표 예상월: 1, 4, 7, 10이다
    for year in (start.year, start.year + 1):
        for month in (1, 4, 7, 10):
            try:
                target = date(year, month, 28)
            except ValueError:
                continue
            while target.weekday() >= 5:
                target += timedelta(days=1)
            if start <= target <= end:
                q_label = {1: "Q4", 4: "Q1", 7: "Q2", 10: "Q3"}[month]
                events.append({
                    "date": target.isoformat(),
                    "name": "GDP 속보치",
                    "importance": "high",
                    "description": f"{q_label} GDP 성장률 속보치 발표",
                })
    return events


def generate_calendar(today: date | None = None) -> list[dict]:
    """향후 30일간 경제 캘린더 이벤트를 생성한다.

    Returns:
        이벤트 리스트 (date, name, importance, description 필드)
    """
    if today is None:
        today = datetime.now(tz=timezone.utc).date()
    end = today + timedelta(days=30)

    events: list[dict] = []
    events.extend(_fomc_events(today.year, today, end))
    events.extend(_nfp_events(today, end))
    events.extend(_monthly_date_events(
        today, end, 13, "소비자물가지수 (CPI)", "high",
        "{year}년 {month}월 CPI 발표",
    ))
    events.extend(_monthly_date_events(
        today, end, 28, "개인소비지출 (PCE)", "high",
        "{year}년 {month}월 PCE 물가 지수 발표",
    ))
    events.extend(_monthly_date_events(
        today, end, 14, "생산자물가지수 (PPI)", "medium",
        "{year}년 {month}월 PPI 발표",
    ))
    events.extend(_monthly_date_events(
        today, end, 16, "소매판매 (Retail Sales)", "medium",
        "{year}년 {month}월 소매판매 보고서",
    ))
    events.extend(_monthly_date_events(
        today, end, 1, "ISM 제조업 PMI", "medium",
        "{year}년 {month}월 ISM 제조업 지수 발표",
    ))
    events.extend(_quarterly_gdp_events(today, end))

    # 날짜순 정렬한다
    events.sort(key=lambda e: e["date"])
    return events


async def fetch_economic_calendar(cache: CacheClient) -> list[dict]:
    """경제 캘린더를 생성하여 캐시에 저장한다.

    Returns:
        생성된 이벤트 리스트
    """
    events = generate_calendar()
    await cache.write_json(_CACHE_KEY, events, ttl=_CACHE_TTL)
    logger.info("경제 캘린더 캐시 갱신: %d건 (TTL=%ds)", len(events), _CACHE_TTL)
    return events
