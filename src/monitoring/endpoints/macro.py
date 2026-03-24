"""F7.6 MacroEndpoints -- 거시 경제 지표 API이다.

FRED 거시 지표, 시리즈 이력, 경제 캘린더, Net Liquidity,
Flutter 대시보드용 Rich 지표, 금리 전망, 캐시 지표를 제공한다.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.monitoring.server.auth import verify_api_key
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

macro_router = APIRouter(prefix="/api/macro", tags=["macro"])

_system: InjectedSystem | None = None

# 주요 FRED 시리즈 ID 목록
_MACRO_SERIES: list[dict[str, str]] = [
    {"id": "VIXCLS", "name": "VIX 변동성 지수", "category": "volatility"},
    {"id": "DGS10", "name": "미국 10년물 국채 수익률", "category": "rates"},
    {"id": "DGS2", "name": "미국 2년물 국채 수익률", "category": "rates"},
    {"id": "DEXKOUS", "name": "USD/KRW 환율", "category": "fx"},
    {"id": "WALCL", "name": "Fed 총자산", "category": "liquidity"},
    {"id": "WTREGEN", "name": "재무부 일반 계좌 (TGA)", "category": "liquidity"},
    {"id": "RRPONTSYD", "name": "역레포 잔액", "category": "liquidity"},
]


class MacroIndicatorsResponse(BaseModel):
    """거시 지표 목록 응답 모델이다."""

    indicators: list[dict[str, str]] = Field(default_factory=list)
    count: int = 0


class MacroHistoryResponse(BaseModel):
    """FRED 시리즈 이력 응답 모델이다."""

    series_id: str
    name: str = ""
    frequency: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)


class EconomicCalendarResponse(BaseModel):
    """경제 캘린더 응답 모델이다."""

    events: list[dict[str, Any]] = Field(default_factory=list)


class NetLiquidityResponse(BaseModel):
    """Net Liquidity 응답 모델이다."""

    net_liquidity: float | None = None
    walcl: float | None = None
    tga: float | None = None
    rrp: float | None = None
    bias: str = "NEUTRAL"
    message: str = ""


class RichMacroResponse(BaseModel):
    """Flutter 대시보드용 거시경제 지표 풍부한 응답이다."""

    vix: dict[str, Any] = Field(default_factory=dict)
    fear_greed: dict[str, Any] = Field(default_factory=dict)
    fed_rate: dict[str, Any] = Field(default_factory=dict)
    cpi: dict[str, Any] = Field(default_factory=dict)
    unemployment: dict[str, Any] = Field(default_factory=dict)
    treasury_spread: dict[str, Any] = Field(default_factory=dict)
    regime: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = ""


class RateOutlookResponse(BaseModel):
    """금리 전망 응답 모델이다."""

    current_rate: float = 0.0
    next_meeting: str | None = None
    probabilities: dict[str, int] = Field(default_factory=dict)
    year_end_estimate: float | None = None
    source: str = "estimated"


class CachedIndicatorsResponse(BaseModel):
    """캐시에 저장된 거시 지표 원시 데이터 응답이다."""

    data: dict[str, Any] = Field(default_factory=dict)
    cached_keys: list[str] = Field(default_factory=list)


# Fear & Greed 캐시 키 및 TTL이다
_FG_CACHE_KEY: str = "macro:fear_greed"
_FG_CACHE_TTL: int = 3600  # 1시간


def _vix_to_level(vix: float) -> str:
    """VIX 값을 공포/탐욕 레벨 문자열로 변환한다."""
    if vix < 15:
        return "extreme_greed"
    if vix < 20:
        return "greed"
    if vix < 25:
        return "neutral"
    if vix < 35:
        return "fear"
    return "extreme_fear"


def _rate_to_target_range(rate: float) -> str:
    """금리 값을 0.25% 단위 타겟 범위 문자열로 변환한다."""
    lower = math.floor(rate * 4) / 4  # 0.25 단위로 내림 (실효금리가 범위 내에 위치하도록)
    upper = lower + 0.25
    return f"{lower:.2f}-{upper:.2f}"


def _treasury_spread_signal(spread: float) -> str:
    """국채 스프레드 값을 시그널 문자열로 변환한다."""
    if spread > 0.5:
        return "normal"
    if spread >= 0:
        return "flattening"
    return "inverted"


async def _extract_latest_value(cache: Any, key: str) -> float | None:
    """캐시에서 FRED 시리즈의 최신 값을 추출한다.

    캐시 데이터가 리스트 형태([{"date": ..., "value": ...}])이면
    첫 번째 항목의 value를, 문자열이면 float로 파싱한다.
    """
    try:
        cached = await cache.read_json(key)
        if cached is None:
            # JSON이 아닌 단순 문자열일 수 있다
            raw = await cache.read(key)
            if raw is not None:
                return float(raw)
            return None
        if isinstance(cached, list) and len(cached) > 0:
            # 리스트의 첫 번째(최신) 항목에서 value를 추출한다
            first = cached[0]
            if isinstance(first, dict):
                val = first.get("value")
                if val is not None:
                    return float(val)
        if isinstance(cached, dict):
            val = cached.get("value")
            if val is not None:
                return float(val)
        return None
    except Exception as exc:
        _logger.debug("캐시 값 추출 실패 (%s): %s", key, exc)
        return None


async def _extract_series_values(cache: Any, key: str) -> list[dict]:
    """캐시에서 FRED 시리즈 전체 데이터를 리스트로 반환한다.

    sort_order=desc로 저장되어 있으므로 index 0이 최신이다.
    """
    try:
        cached = await cache.read_json(key)
        if isinstance(cached, list):
            return cached
        return []
    except Exception:
        return []


def _compute_yoy_change(series: list[dict]) -> float | None:
    """월간 시리즈에서 전년 동기 대비 변화율(%)을 계산한다.

    index 0이 최신, index 12가 12개월 전이다.
    YoY = ((현재 / 12개월전) - 1) * 100
    """
    if len(series) < 13:
        return None
    try:
        current = float(series[0].get("value", 0))
        year_ago = float(series[12].get("value", 0))
        if year_ago == 0:
            return None
        return round((current / year_ago - 1) * 100, 1)
    except (ValueError, TypeError, AttributeError):
        return None


def _compute_mom_change(series: list[dict]) -> float | None:
    """월간 시리즈에서 전월 대비 변화를 계산한다 (절대값 차이)."""
    if len(series) < 2:
        return None
    try:
        current = float(series[0].get("value", 0))
        previous = float(series[1].get("value", 0))
        return round(current - previous, 2)
    except (ValueError, TypeError, AttributeError):
        return None


def _get_series_name(series_id: str) -> str:
    """FRED 시리즈 ID에 대한 한국어 이름을 반환한다."""
    for entry in _MACRO_SERIES:
        if entry["id"] == series_id:
            return entry["name"]
    return series_id


def set_macro_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("MacroEndpoints 의존성 주입 완료")


@macro_router.get("/indicators", response_model=MacroIndicatorsResponse)
async def get_macro_indicators(_auth: str = Depends(verify_api_key)) -> MacroIndicatorsResponse:
    """사용 가능한 거시 지표 목록을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    return MacroIndicatorsResponse(
        indicators=_MACRO_SERIES, count=len(_MACRO_SERIES)
    )


@macro_router.get("/history/{series_id}", response_model=MacroHistoryResponse)
async def get_macro_history(
    series_id: str = Path(..., pattern=r"^[A-Za-z0-9_]+$"),
    limit: int = Query(default=30, ge=1, le=365),
    _auth: str = Depends(verify_api_key),
) -> MacroHistoryResponse:
    """FRED 시리즈 이력 데이터를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json(f"macro:{series_id}")
        data = cached if isinstance(cached, list) else []
        # FRED API가 sort_order=desc로 반환하므로 시간순(오래된→최신)으로 정렬한다.
        # Flutter 차트가 index 0을 가장 오래된 데이터로 가정하기 때문이다.
        data = sorted(data, key=lambda x: x.get("date", ""))
        # 최신 limit건만 반환한다 (정렬 후 뒤쪽이 최신이므로 뒤에서 자른다)
        data = data[-limit:] if len(data) > limit else data
        # Flutter FredHistoryData.fromJson이 name/frequency도 기대하므로 포함한다
        series_name = _get_series_name(series_id)
        return MacroHistoryResponse(
            series_id=series_id, name=series_name, data=data,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("거시지표 이력 조회 실패: %s", series_id)
        raise HTTPException(status_code=500, detail="이력 조회 실패") from None


@macro_router.get("/calendar", response_model=EconomicCalendarResponse)
async def get_economic_calendar(_auth: str = Depends(verify_api_key)) -> EconomicCalendarResponse:
    """경제 캘린더 이벤트를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("macro:calendar")
        events = cached if isinstance(cached, list) else []
        return EconomicCalendarResponse(events=events)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("경제 캘린더 조회 실패")
        raise HTTPException(status_code=500, detail="캘린더 조회 실패") from None


@macro_router.get("/net-liquidity", response_model=NetLiquidityResponse)
async def get_net_liquidity(_auth: str = Depends(verify_api_key)) -> NetLiquidityResponse:
    """Net Liquidity 현황을 반환한다. WALCL - TGA - RRP 수식이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("macro:net_liquidity")
        if cached and isinstance(cached, dict):
            return NetLiquidityResponse(
                net_liquidity=cached.get("net_liquidity"),
                walcl=cached.get("walcl"),
                tga=cached.get("tga"),
                rrp=cached.get("rrp"),
                bias=cached.get("bias", "NEUTRAL"),
                message=cached.get("message", ""),
            )
        return NetLiquidityResponse(message="캐시된 데이터가 없다")
    except HTTPException:
        raise
    except Exception:
        _logger.exception("Net Liquidity 조회 실패")
        raise HTTPException(status_code=500, detail="조회 실패") from None


# ── Rich Macro Indicators (Flutter 대시보드용) ──


@macro_router.get("/indicators/rich", response_model=RichMacroResponse)
async def get_rich_macro_indicators(_auth: str = Depends(verify_api_key)) -> RichMacroResponse:
    """Flutter 대시보드용 거시경제 지표 종합 데이터를 반환한다.

    VIX, Fear & Greed, 금리, CPI, 실업률, 국채 스프레드, 시장 레짐을
    모두 수집하여 반환한다. 개별 지표 실패 시 빈 dict를 반환한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")

    cache = _system.components.cache
    features = _system.features

    # VIX 데이터 수집이다
    vix_data: dict[str, Any] = {}
    try:
        vix_value: float = 19.0
        vix_fetcher = features.get("vix_fetcher")
        if vix_fetcher is not None:
            vix_value = await vix_fetcher.get_vix()  # type: ignore[union-attr]

        # 전일 VIX를 캐시에서 조회하여 변동폭을 계산한다
        change_1d: float = 0.0
        try:
            history = await cache.read_json("macro:VIXCLS")
            if isinstance(history, list) and len(history) >= 2:
                prev_val = history[1].get("value") if isinstance(history[1], dict) else None
                if prev_val is not None:
                    change_1d = round(vix_value - float(prev_val), 2)
        except Exception as exc:
            _logger.debug("VIX 이전 값 캐시 조회 실패 (무시): %s", exc)

        vix_data = {
            "value": round(vix_value, 2),
            "change_1d": change_1d,
            "level": _vix_to_level(vix_value),
        }
    except Exception as exc:
        _logger.warning("VIX 데이터 수집 실패: %s", exc)

    # Fear & Greed 데이터 수집이다 (캐시 우선, 미스 시 직접 조회)
    fg_data: dict[str, Any] = {}
    try:
        # 캐시에서 먼저 조회한다
        cached_fg = await cache.read_json(_FG_CACHE_KEY)
        if cached_fg and isinstance(cached_fg, dict):
            fg_data = cached_fg
        else:
            # 캐시 미스 -- 직접 크롤링한다
            from src.monitoring.crawlers.fear_greed_fetcher import fetch_fear_greed

            fg_data = await fetch_fear_greed()
            # 결과를 캐시에 저장한다
            try:
                await cache.write_json(_FG_CACHE_KEY, fg_data, ttl=_FG_CACHE_TTL)
            except Exception as exc:
                _logger.debug("Fear & Greed 캐시 저장 실패 (무시): %s", exc)
    except Exception as exc:
        _logger.warning("Fear & Greed 데이터 수집 실패: %s", exc)

    # Fed Rate 데이터 수집이다
    fed_rate_data: dict[str, Any] = {}
    try:
        rate = await _extract_latest_value(cache, "macro:DFF")
        if rate is not None:
            fed_rate_data = {
                "value": round(rate, 2),
                "target_range": _rate_to_target_range(rate),
            }
    except Exception as exc:
        _logger.warning("Fed Rate 데이터 수집 실패: %s", exc)

    # CPI 데이터 수집이다 -- CPIAUCSL은 원시 지수이므로 YoY 변화율로 변환한다
    cpi_data: dict[str, Any] = {}
    try:
        cpi_series = await _extract_series_values(cache, "macro:CPIAUCSL")
        if cpi_series:
            yoy = _compute_yoy_change(cpi_series)
            if yoy is not None:
                # 전월 대비 변화도 계산한다
                mom = _compute_mom_change(cpi_series)
                cpi_data = {
                    "value": yoy,
                    "change": mom,
                    "release_date": cpi_series[0].get("date", ""),
                }
            else:
                # YoY 계산 불가 시 원시 지수를 반환한다 (12개월 이력 부족)
                raw_val = await _extract_latest_value(cache, "macro:CPIAUCSL")
                if raw_val is not None:
                    cpi_data = {"value": round(raw_val, 1)}
    except Exception as exc:
        _logger.warning("CPI 데이터 수집 실패: %s", exc)

    # 실업률 데이터 수집이다
    unemp_data: dict[str, Any] = {}
    try:
        unemp_series = await _extract_series_values(cache, "macro:UNRATE")
        if unemp_series:
            unemp_val = float(unemp_series[0].get("value", 0))
            mom = _compute_mom_change(unemp_series)
            prev_val = float(unemp_series[1].get("value", 0)) if len(unemp_series) >= 2 else None
            unemp_data = {
                "value": round(unemp_val, 1),
                "previous": round(prev_val, 1) if prev_val else None,
                "change": mom,
            }
        else:
            unemp_val = await _extract_latest_value(cache, "macro:UNRATE")
            if unemp_val is not None:
                unemp_data = {"value": round(unemp_val, 1)}
    except Exception as exc:
        _logger.warning("실업률 데이터 수집 실패: %s", exc)

    # 국채 스프레드 데이터 수집이다 (10Y - 2Y)
    spread_data: dict[str, Any] = {}
    try:
        dgs10 = await _extract_latest_value(cache, "macro:DGS10")
        dgs2 = await _extract_latest_value(cache, "macro:DGS2")
        if dgs10 is not None and dgs2 is not None:
            spread = round(dgs10 - dgs2, 2)
            spread_data = {
                "value": spread,
                "signal": _treasury_spread_signal(spread),
            }
    except Exception as exc:
        _logger.warning("국채 스프레드 데이터 수집 실패: %s", exc)

    # 시장 레짐 데이터 수집이다
    regime_data: dict[str, Any] = {}
    try:
        detector = features.get("regime_detector")
        if detector is not None:
            vix_for_regime = vix_data.get("value", 20.0)
            regime = detector.detect(float(vix_for_regime))  # type: ignore[union-attr]
            regime_data = {
                "current": regime.regime_type,
                "confidence": round(regime.params.position_multiplier, 2),
            }
    except Exception as exc:
        _logger.warning("레짐 데이터 수집 실패: %s", exc)

    now_str = datetime.now(timezone.utc).isoformat()

    # 데이터 수집 결과를 로그에 기록한다 (디버깅용)
    empty_fields = [
        name for name, data in [
            ("vix", vix_data), ("fed_rate", fed_rate_data),
            ("cpi", cpi_data), ("unemployment", unemp_data),
            ("treasury_spread", spread_data),
        ] if not data
    ]
    if empty_fields:
        _logger.warning("Rich 거시지표 빈 필드: %s (FRED 캐시 확인 필요)", empty_fields)

    return RichMacroResponse(
        vix=vix_data,
        fear_greed=fg_data,
        fed_rate=fed_rate_data,
        cpi=cpi_data,
        unemployment=unemp_data,
        treasury_spread=spread_data,
        regime=regime_data,
        updated_at=now_str,
    )


# ── Rate Outlook ──


@macro_router.get("/rate-outlook", response_model=RateOutlookResponse)
async def get_rate_outlook(_auth: str = Depends(verify_api_key)) -> RateOutlookResponse:
    """금리 전망 데이터를 반환한다.

    현재 금리를 캐시(macro:DFF)에서 조회하고,
    기본적인 금리 전망 추정치를 생성한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")

    try:
        cache = _system.components.cache
        current_rate = await _extract_latest_value(cache, "macro:DFF")

        if current_rate is None:
            return RateOutlookResponse(
                source="unavailable",
            )

        # 기본적인 금리 전망 추정이다 (실제 CME FedWatch 데이터가 없으므로)
        # 현재 금리 수준에 따라 확률을 추정한다
        probabilities: dict[str, int] = {}
        year_end: float | None = None

        if current_rate >= 5.0:
            # 고금리 구간 -- 인하 가능성이 높다
            probabilities = {"cut_25bp": 45, "hold": 40, "hike_25bp": 15}
            year_end = current_rate - 0.5
        elif current_rate >= 4.0:
            # 중상위 구간 -- 동결 또는 소폭 인하
            probabilities = {"cut_25bp": 35, "hold": 50, "hike_25bp": 15}
            year_end = current_rate - 0.25
        elif current_rate >= 2.0:
            # 중간 구간 -- 동결 위주
            probabilities = {"cut_25bp": 20, "hold": 60, "hike_25bp": 20}
            year_end = current_rate
        else:
            # 저금리 구간 -- 인상 가능성
            probabilities = {"cut_25bp": 10, "hold": 40, "hike_25bp": 50}
            year_end = current_rate + 0.25

        return RateOutlookResponse(
            current_rate=round(current_rate, 2),
            probabilities=probabilities,
            year_end_estimate=round(year_end, 2) if year_end is not None else None,
            source="estimated",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("금리 전망 조회 실패")
        raise HTTPException(status_code=500, detail="금리 전망 조회 실패") from None


# ── Cached Indicators ──


@macro_router.get("/cached-indicators", response_model=CachedIndicatorsResponse)
async def get_cached_indicators(_auth: str = Depends(verify_api_key)) -> CachedIndicatorsResponse:
    """캐시에 저장된 거시 지표 원시 데이터를 반환한다.

    macro:* 키에 저장된 모든 FRED 시리즈의 최신 데이터를 조회한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")

    try:
        cache = _system.components.cache
        result: dict[str, Any] = {}
        cached_keys: list[str] = []

        # 알려진 FRED 시리즈 키를 순회하며 캐시 데이터를 수집한다
        series_keys: list[str] = [
            "VIXCLS", "DGS10", "DGS2", "DFF", "CPIAUCSL",
            "UNRATE", "DEXKOUS", "WALCL", "WTREGEN", "RRPONTSYD",
        ]

        for series_id in series_keys:
            cache_key = f"macro:{series_id}"
            try:
                cached = await cache.read_json(cache_key)
                if cached is not None:
                    result[series_id] = cached
                    cached_keys.append(series_id)
                else:
                    # 단순 문자열 값도 시도한다
                    raw = await cache.read(cache_key)
                    if raw is not None:
                        result[series_id] = raw
                        cached_keys.append(series_id)
            except Exception:
                _logger.debug("캐시 키 조회 실패: %s", cache_key)

        # Fear & Greed 캐시도 포함한다
        try:
            fg_cached = await cache.read_json(_FG_CACHE_KEY)
            if fg_cached is not None:
                result["fear_greed"] = fg_cached
                cached_keys.append("fear_greed")
        except Exception as exc:
            _logger.debug("Fear & Greed 캐시 조회 실패 (무시): %s", exc)

        # 외부 데이터 소스 캐시도 포함한다
        external_keys = [
            ("prediction:polymarket", "polymarket"),
            ("macro:te:calendar", "te_calendar"),
            ("macro:superinvestor", "superinvestor"),
        ]
        for cache_key, label in external_keys:
            try:
                ext = await cache.read_json(cache_key)
                if ext is not None:
                    result[label] = ext
                    cached_keys.append(label)
            except Exception:
                _logger.debug("외부 캐시 조회 실패: %s", label)

        return CachedIndicatorsResponse(data=result, cached_keys=cached_keys)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("캐시 지표 조회 실패")
        raise HTTPException(status_code=500, detail="캐시 지표 조회 실패") from None
