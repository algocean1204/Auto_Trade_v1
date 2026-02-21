"""
Flutter 대시보드용 거시경제 지표 API 엔드포인트.

FRED REST API를 활용하여 주요 거시경제 지표의
현재값, 이력 데이터, 경제 캘린더, 금리 전망 데이터를 제공한다.

핵심 로직은 fred_client.py와 calendar_helpers.py에 분리되어 있으며,
이 모듈은 FastAPI 라우터 엔드포인트만 정의한다.

캐싱: FRED 응답 5분(300s), VIX 1분(60s) 인메모리 TTL 캐시 적용.
자동 크롤링: IndicatorCrawler를 통해 1시간마다 백그라운드 갱신된다.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.monitoring.calendar_helpers import (
    fetch_fred_release_dates,
    generate_upcoming_events,
    next_fomc_date,
)
from src.monitoring.fred_client import (
    ALLOWED_SERIES,
    FRED_SERIES_NAMES,
    calc_fear_greed,
    estimate_rate_outlook,
    fetch_cnn_fear_greed,
    fetch_fred_history,
    fetch_fred_latest,
    fetch_market_rate_probs,
    fetch_regime_from_db,
    fetch_vix_value,
    format_rate_range,
    get_cached,
    get_fred_api_key,
    set_cache,
    treasury_spread_signal,
    vix_level,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 IndicatorCrawler 참조
# api_server.py 가 startup 시 set_macro_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_indicator_crawler: Any = None


def set_macro_deps(indicator_crawler: Any = None) -> None:
    """런타임 의존성을 주입한다.

    api_server.py의 set_dependencies()가 호출될 때 함께 호출된다.

    Args:
        indicator_crawler: IndicatorCrawler 인스턴스. None이면 캐시 엔드포인트가 비활성화된다.
    """
    global _indicator_crawler
    _indicator_crawler = indicator_crawler

# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/macro", tags=["macro"])


@router.get("/indicators")
async def get_macro_indicators() -> dict[str, Any]:
    """주요 거시경제 지표의 현재 스냅샷을 반환한다.

    VIX, Fear & Greed 지수, 연방기금금리, CPI, 실업률,
    국채 스프레드, 시장 레짐을 단일 응답으로 제공한다.

    캐싱: FRED 응답 5분, VIX 1분 인메모리 TTL 적용.

    Returns:
        vix, fear_greed, fed_rate, cpi, unemployment,
        treasury_spread, regime, updated_at 키를 포함하는 딕셔너리.
    """
    cache_key = "macro_indicators"
    cached = get_cached(cache_key, ttl=60)
    if cached is not None:
        return cached

    api_key = get_fred_api_key()

    # VIX 조회 (1분 TTL 캐시 적용)
    vix = await fetch_vix_value()

    # CNN Fear&Greed 실시간 조회 (1분 캐시, 실패 시 VIX 기반 폴백)
    fear_greed = await fetch_cnn_fear_greed()

    # FRED 시계열 병렬 조회
    dff_task = asyncio.create_task(fetch_fred_latest("DFF", api_key))
    cpi_task = asyncio.create_task(fetch_fred_latest("CPIAUCSL", api_key))
    unrate_task = asyncio.create_task(fetch_fred_latest("UNRATE", api_key))
    spread_task = asyncio.create_task(fetch_fred_latest("T10Y2Y", api_key))

    dff_result: dict[str, Any] = {}
    cpi_result: dict[str, Any] = {}
    unrate_result: dict[str, Any] = {}
    spread_result: dict[str, Any] = {}

    for task, name in [
        (dff_task, "DFF"),
        (cpi_task, "CPIAUCSL"),
        (unrate_task, "UNRATE"),
        (spread_task, "T10Y2Y"),
    ]:
        try:
            if task == dff_task:
                dff_result = await asyncio.shield(dff_task)
            elif task == cpi_task:
                cpi_result = await asyncio.shield(cpi_task)
            elif task == unrate_task:
                unrate_result = await asyncio.shield(unrate_task)
            elif task == spread_task:
                spread_result = await asyncio.shield(spread_task)
        except Exception as exc:
            logger.warning("FRED %s 조회 실패 (indicators): %s", name, exc)

    # DFF (연방기금금리) 처리
    fed_current = dff_result.get("current_value")
    fed_rate: dict[str, Any]
    if fed_current is not None:
        fed_rate = {
            "value": fed_current,
            "target_range": format_rate_range(fed_current),
            "last_change": dff_result.get("current_date"),
        }
    else:
        fed_rate = {"value": None, "target_range": None, "last_change": None}

    # CPI 처리
    cpi_current = cpi_result.get("current_value")
    cpi_previous = cpi_result.get("previous_value")
    cpi_data: dict[str, Any]
    if cpi_current is not None:
        cpi_change = (
            round(cpi_current - cpi_previous, 2)
            if cpi_previous is not None
            else None
        )
        cpi_data = {
            "value": cpi_current,
            "previous": cpi_previous,
            "change": cpi_change,
            "release_date": cpi_result.get("current_date"),
        }
    else:
        cpi_data = {"value": None, "previous": None, "change": None, "release_date": None}

    # UNRATE (실업률) 처리
    unrate_current = unrate_result.get("current_value")
    unrate_previous = unrate_result.get("previous_value")
    unemployment: dict[str, Any]
    if unrate_current is not None:
        unrate_change = (
            round(unrate_current - unrate_previous, 2)
            if unrate_previous is not None
            else None
        )
        unemployment = {
            "value": unrate_current,
            "previous": unrate_previous,
            "change": unrate_change,
        }
    else:
        unemployment = {"value": None, "previous": None, "change": None}

    # T10Y2Y (국채 스프레드) 처리
    spread_current = spread_result.get("current_value")
    treasury_spread: dict[str, Any]
    if spread_current is not None:
        treasury_spread = {
            "value": spread_current,
            "signal": treasury_spread_signal(spread_current),
        }
    else:
        treasury_spread = {"value": None, "signal": "unknown"}

    # VIX 응답 구성
    vix_1d_change = None
    try:
        vix_cache_key = "vix_prev_close"
        vix_prev = get_cached(vix_cache_key, ttl=86400)
        if vix_prev is not None:
            vix_1d_change = round(vix - float(vix_prev), 2)
    except Exception as exc:
        logger.debug("VIX 전일 대비 변동 계산 실패: %s", exc)

    vix_data: dict[str, Any] = {
        "value": round(vix, 2),
        "change_1d": vix_1d_change,
        "level": vix_level(vix),
    }

    # 레짐 조회
    regime = await fetch_regime_from_db()

    result: dict[str, Any] = {
        "vix": vix_data,
        "fear_greed": fear_greed,
        "fed_rate": fed_rate,
        "cpi": cpi_data,
        "unemployment": unemployment,
        "treasury_spread": treasury_spread,
        "regime": regime,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    set_cache(cache_key, result)
    return result


@router.get("/history/{series_id}")
async def get_macro_history(
    series_id: str,
    days: int = Query(default=90, ge=1, le=365),
) -> dict[str, Any]:
    """특정 FRED 시계열의 이력 데이터를 반환한다.

    Flutter 차트 렌더링에 사용할 date/value 페어 리스트를 제공한다.

    Args:
        series_id: FRED 시계열 ID (DFF, T10Y2Y, VIXCLS, CPIAUCSL, UNRATE, DGS10, DGS2).
        days: 조회할 일수 (1~365, 기본 90일).

    Returns:
        series_id, name, frequency, data 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 400: 허용되지 않은 시계열 ID.
        HTTPException 503: FRED_API_KEY 미설정.
    """
    series_id = series_id.upper()
    if series_id not in ALLOWED_SERIES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"허용되지 않은 시계열 ID입니다: {series_id}. "
                f"허용 목록: {sorted(ALLOWED_SERIES)}"
            ),
        )

    cache_key = f"fred_history_{series_id}_{days}"
    cached = get_cached(cache_key, ttl=300)
    if cached is not None:
        return cached

    api_key = get_fred_api_key()

    observation_start = (date.today() - timedelta(days=days)).isoformat()

    try:
        data_points = await fetch_fred_history(series_id, api_key, observation_start)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("FRED 이력 조회 예외 (series=%s): %s", series_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"이력 데이터 조회 실패 (series={series_id})",
        )

    # 시계열 주기 결정
    frequency = "daily"
    if series_id in ("CPIAUCSL", "UNRATE"):
        frequency = "monthly"

    result: dict[str, Any] = {
        "series_id": series_id,
        "name": FRED_SERIES_NAMES.get(series_id, series_id),
        "frequency": frequency,
        "data": data_points,
    }

    set_cache(cache_key, result)
    return result


@router.get("/calendar")
async def get_economic_calendar() -> dict[str, Any]:
    """향후 경제 이벤트 캘린더를 반환한다.

    정기 미국 거시경제 이벤트(FOMC, NFP, CPI, PCE)의 예정 일정과
    FRED 릴리즈 캘린더 데이터를 병합하여 반환한다.

    캐싱: 5분 인메모리 TTL 적용.

    Returns:
        events 키에 이벤트 리스트를 담은 딕셔너리.
        각 이벤트: date, time, event, impact, previous, forecast, actual.
    """
    cache_key = "economic_calendar"
    cached = get_cached(cache_key, ttl=300)
    if cached is not None:
        return cached

    # 정적 반복 이벤트 생성
    static_events = generate_upcoming_events(days_ahead=45)

    # FRED 릴리즈 캘린더 병합 (선택적)
    fred_events: list[dict[str, Any]] = []
    try:
        api_key = os.getenv("FRED_API_KEY", "")
        if api_key:
            fred_events = await fetch_fred_release_dates(api_key, days_ahead=45)
    except Exception as exc:
        logger.warning("FRED 캘린더 조회 실패 (무시됨): %s", exc)

    # 중복 제거 병합 (event 이름 + date 기준)
    all_events = list(static_events)
    existing_keys: set[str] = {f"{ev['date']}_{ev['event']}" for ev in static_events}

    for ev in fred_events:
        key = f"{ev['date']}_{ev['event']}"
        if key not in existing_keys:
            existing_keys.add(key)
            all_events.append(ev)

    # 날짜 오름차순 정렬
    all_events.sort(key=lambda x: x["date"])

    result: dict[str, Any] = {"events": all_events}
    set_cache(cache_key, result)
    return result


@router.get("/rate-outlook")
async def get_rate_outlook() -> dict[str, Any]:
    """연방기금금리 전망 및 금리 인하/인상 확률을 반환한다.

    Polymarket/Kalshi 데이터가 DB에 있으면 활용하고, 없으면
    현재 VIX와 국채 스프레드 기반의 레짐 추정치를 반환한다.

    캐싱: 5분 인메모리 TTL 적용.

    Returns:
        current_rate, next_meeting, probabilities,
        year_end_estimate, source 키를 포함하는 딕셔너리.
    """
    cache_key = "rate_outlook"
    cached = get_cached(cache_key, ttl=300)
    if cached is not None:
        return cached

    api_key = get_fred_api_key()

    # 현재 금리 조회
    current_rate: float = 4.50  # 기본값
    try:
        dff_data = await fetch_fred_latest("DFF", api_key)
        cv = dff_data.get("current_value")
        if cv is not None:
            current_rate = float(cv)
    except Exception as exc:
        logger.warning("DFF 조회 실패 (rate-outlook): %s", exc)

    # VIX 조회
    vix = await fetch_vix_value()

    # T10Y2Y 스프레드 조회
    spread: float | None = None
    try:
        spread_data = await fetch_fred_latest("T10Y2Y", api_key)
        sv = spread_data.get("current_value")
        if sv is not None:
            spread = float(sv)
    except Exception as exc:
        logger.warning("T10Y2Y 조회 실패 (rate-outlook): %s", exc)

    # DB에서 Polymarket/Kalshi 기반 데이터 조회 시도
    market_probs: dict[str, Any] | None = None
    try:
        market_probs = await fetch_market_rate_probs()
    except Exception as exc:
        logger.debug("시장 금리 확률 DB 조회 실패: %s", exc)

    if market_probs is not None:
        outlook = market_probs
        outlook["source"] = "market_implied"
    else:
        outlook = estimate_rate_outlook(current_rate, vix, spread)

    result: dict[str, Any] = {
        "current_rate": current_rate,
        "next_meeting": next_fomc_date(),
        "probabilities": outlook["probabilities"],
        "year_end_estimate": outlook["year_end_estimate"],
        "source": outlook["source"],
    }

    set_cache(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# GET /api/macro/cached-indicators
# ---------------------------------------------------------------------------


@router.get("/cached-indicators")
async def get_cached_indicators() -> dict[str, Any]:
    """자동 크롤러가 수집한 최신 매크로 지표를 인메모리 캐시에서 반환한다.

    DB 조회 없이 IndicatorCrawler의 인메모리 캐시를 직접 반환하므로
    응답이 빠르다. 1시간마다 백그라운드에서 자동 갱신된다.

    Returns:
        indicators (지표 딕셔너리), updated_at (마지막 갱신 시각) 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 503: IndicatorCrawler가 초기화되지 않은 경우.
    """
    if _indicator_crawler is None:
        raise HTTPException(
            status_code=503,
            detail="IndicatorCrawler가 초기화되지 않았습니다.",
        )

    return _indicator_crawler.get_latest()


# ---------------------------------------------------------------------------
# GET /api/macro/analysis
# ---------------------------------------------------------------------------


@router.get("/analysis")
async def get_macro_analysis() -> dict[str, Any]:
    """자동 크롤러가 생성한 최신 Sonnet 매크로 분석 결과를 반환한다.

    지표 변화 감지 시 Claude Sonnet이 생성한 한국어 시장 해석 텍스트를 반환한다.
    Claude 클라이언트가 미설정이거나 분석이 아직 수행되지 않은 경우 null을 반환한다.

    Returns:
        analysis (분석 텍스트 또는 null), updated_at 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 503: IndicatorCrawler가 초기화되지 않은 경우.
    """
    if _indicator_crawler is None:
        raise HTTPException(
            status_code=503,
            detail="IndicatorCrawler가 초기화되지 않았습니다.",
        )

    analysis = _indicator_crawler.get_last_analysis()
    latest = _indicator_crawler.get_latest()

    return {
        "analysis": analysis,
        "updated_at": latest.get("updated_at"),
        "has_analysis": analysis is not None,
    }


# ---------------------------------------------------------------------------
# POST /api/macro/refresh
# ---------------------------------------------------------------------------


@router.post("/refresh")
async def refresh_macro_indicators() -> dict[str, Any]:
    """지표 크롤링을 수동으로 즉시 트리거한다.

    IndicatorCrawler.crawl_once()를 호출하여 모든 지표를 즉시 재조회하고
    DB에 저장한다. 완료 후 갱신된 캐시를 반환한다.

    네트워크 연결이 없거나 조회 실패 시에도 503 대신 빈 결과와 함께
    오류 메시지를 반환한다 (graceful degradation).

    Returns:
        indicators, updated_at, refreshed 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 503: IndicatorCrawler가 초기화되지 않은 경우.
    """
    if _indicator_crawler is None:
        raise HTTPException(
            status_code=503,
            detail="IndicatorCrawler가 초기화되지 않았습니다.",
        )

    try:
        indicators = await _indicator_crawler.crawl_once()
    except Exception as exc:
        logger.error("수동 크롤링 실패: %s", exc, exc_info=True)
        return {
            "indicators": {},
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "refreshed": False,
            "error": str(exc),
        }

    latest = _indicator_crawler.get_latest()
    return {
        "indicators": indicators,
        "updated_at": latest.get("updated_at"),
        "refreshed": bool(indicators),
    }
