"""
FRED REST API 클라이언트 및 관련 헬퍼 함수.

macro_endpoints.py에서 분리된 모듈로, FRED API 호출,
인메모리 TTL 캐시, VIX/Fear&Greed 계산 기능을 제공한다.
CNN Fear&Greed 실시간 조회(1분 캐시) 기능도 포함한다.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp
import httpx
from fastapi import HTTPException

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수 정의
# ---------------------------------------------------------------------------

_FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# CNN Fear & Greed API 엔드포인트
_FEAR_GREED_API_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# API 타임아웃 상수 (일관성을 위해 15초로 통일한다)
_FRED_API_TIMEOUT: float = 15.0

# CNN Fear & Greed API 타임아웃 (초)
_FEAR_GREED_TIMEOUT: float = 10.0

# VIX 현재값 캐시 TTL (초)
_VIX_CACHE_TTL: int = 60

# VIX 복합 캐시 TTL (초, 폴백 fear&greed 포함)
_VIX_COMPOSITE_CACHE_TTL: int = 300

FRED_SERIES_NAMES: dict[str, str] = {
    "DFF": "Federal Funds Rate",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "VIXCLS": "CBOE Volatility Index",
    "CPIAUCSL": "Consumer Price Index",
    "UNRATE": "Unemployment Rate",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
}

ALLOWED_SERIES: frozenset[str] = frozenset(FRED_SERIES_NAMES.keys())

# 레짐별 레이블
REGIME_LABELS: dict[str, str] = {
    "strong_bull": "Strong Bull",
    "mild_bull": "Mild Bull",
    "neutral": "Neutral",
    "mild_bear": "Mild Bear",
    "strong_bear": "Strong Bear",
    "crisis": "Crisis",
    "unknown": "Unknown",
}

# ---------------------------------------------------------------------------
# 인메모리 TTL 캐시
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, Any]] = {}


def get_cached(key: str, ttl: int = 300) -> Any | None:
    """TTL 캐시에서 데이터를 조회한다.

    Args:
        key: 캐시 키.
        ttl: 유효 시간(초). 기본 300초.

    Returns:
        캐시된 데이터 또는 None (캐시 미스 또는 만료).
    """
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < ttl:
            return data
    return None


def set_cache(key: str, data: Any) -> None:
    """TTL 캐시에 데이터를 저장한다.

    Args:
        key: 캐시 키.
        data: 저장할 데이터.
    """
    _cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# FRED API 헬퍼
# ---------------------------------------------------------------------------

def get_fred_api_key() -> str:
    """환경 변수에서 FRED API 키를 가져온다.

    Returns:
        FRED_API_KEY 환경 변수 값.

    Raises:
        HTTPException: API 키가 설정되지 않은 경우 503을 반환한다.
    """
    key = os.getenv("FRED_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=503,
            detail="FRED_API_KEY가 설정되지 않았습니다. 환경 변수를 확인하세요.",
        )
    return key


async def fetch_fred_latest(series_id: str, api_key: str) -> dict[str, Any]:
    """FRED API에서 최신 관측값을 조회한다.

    현재값과 이전값(변화 계산용)을 함께 조회한다.

    Args:
        series_id: FRED 시계열 ID (예: "DFF", "CPIAUCSL").
        api_key: FRED API 인증 키.

    Returns:
        current_value, previous_value, current_date, previous_date를 담은 딕셔너리.
        값을 파싱할 수 없는 경우 value는 None으로 반환된다.

    Raises:
        HTTPException: FRED API 호출 실패 시.
    """
    url = f"{_FRED_BASE_URL}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 2,
    }

    try:
        async with httpx.AsyncClient(timeout=_FRED_API_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("FRED API 타임아웃 (series=%s)", series_id)
        raise HTTPException(
            status_code=504,
            detail=f"FRED API 타임아웃 (series={series_id})",
        )
    except httpx.HTTPStatusError as exc:
        logger.error("FRED API HTTP 오류 (series=%s): %s", series_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"FRED API 오류 (series={series_id})",
        )
    except Exception as exc:
        logger.error("FRED API 예외 (series=%s): %s", series_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"FRED API 요청 실패 (series={series_id})",
        )

    observations = data.get("observations", [])

    result: dict[str, Any] = {
        "current_value": None,
        "previous_value": None,
        "current_date": None,
        "previous_date": None,
    }

    for i, obs in enumerate(observations):
        raw = obs.get("value", "").strip()
        obs_date = obs.get("date", "")
        # FRED에서 "."은 데이터 미가용을 의미한다
        if raw and raw != ".":
            try:
                parsed = float(raw)
            except ValueError:
                parsed = None
        else:
            parsed = None

        if i == 0:
            result["current_value"] = parsed
            result["current_date"] = obs_date
        elif i == 1:
            result["previous_value"] = parsed
            result["previous_date"] = obs_date

    return result


async def fetch_fred_history(
    series_id: str,
    api_key: str,
    observation_start: str,
) -> list[dict[str, Any]]:
    """FRED API에서 특정 시작일 이후의 모든 관측값을 조회한다.

    Args:
        series_id: FRED 시계열 ID.
        api_key: FRED API 인증 키.
        observation_start: 조회 시작일 (YYYY-MM-DD).

    Returns:
        date, value 키를 포함하는 딕셔너리 리스트 (오름차순).
    """
    url = f"{_FRED_BASE_URL}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "observation_start": observation_start,
    }

    try:
        async with httpx.AsyncClient(timeout=_FRED_API_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("FRED 이력 API 타임아웃 (series=%s)", series_id)
        raise HTTPException(
            status_code=504,
            detail=f"FRED API 타임아웃 (series={series_id})",
        )
    except httpx.HTTPStatusError as exc:
        logger.error("FRED 이력 API HTTP 오류 (series=%s): %s", series_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"FRED API 오류 (series={series_id})",
        )
    except Exception as exc:
        logger.error("FRED 이력 API 예외 (series=%s): %s", series_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"FRED API 요청 실패 (series={series_id})",
        )

    points: list[dict[str, Any]] = []
    for obs in data.get("observations", []):
        raw = obs.get("value", "").strip()
        obs_date = obs.get("date", "")
        if not raw or raw == ".":
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        points.append({"date": obs_date, "value": value})

    return points


# ---------------------------------------------------------------------------
# VIX 헬퍼
# ---------------------------------------------------------------------------

async def fetch_vix_value() -> float:
    """VIX 현재값을 FRED VIXCLS API로 조회한다.

    FRED 조회 실패 시 기본값 20.0을 반환한다.

    Returns:
        VIX 현재값 (float).
    """
    cache_key = "vix_current"
    cached = get_cached(cache_key, ttl=_VIX_CACHE_TTL)
    if cached is not None:
        return float(cached)

    vix_value: float | None = None

    # FRED VIXCLS 조회
    try:
        api_key = os.getenv("FRED_API_KEY", "")
        if api_key:
            fred_data = await fetch_fred_latest("VIXCLS", api_key)
            cv = fred_data.get("current_value")
            if cv is not None and cv > 0:
                vix_value = float(cv)
        else:
            logger.warning("FRED_API_KEY 미설정, VIX 기본값 사용")
    except Exception as exc:
        logger.warning("FRED VIXCLS 조회 실패: %s", exc)

    # 기본값
    if vix_value is None or vix_value <= 0:
        logger.warning("VIX 조회 실패, 기본값 20.0 사용")
        vix_value = 20.0

    set_cache(cache_key, vix_value)
    return vix_value


# ---------------------------------------------------------------------------
# CNN Fear & Greed 실시간 조회 (1분 캐시)
# ---------------------------------------------------------------------------

async def fetch_cnn_fear_greed() -> dict[str, Any]:
    """CNN 공포탐욕지수를 실시간으로 조회한다. 1분 캐시.

    CNN 내부 API(production.dataviz.cnn.io)에서 현재 Fear&Greed 점수,
    등급, 전일 대비 변동을 조회한다.
    조회 실패 시 VIX 기반 폴백 값을 반환한다.

    Returns:
        score, label, rating_en, previous_close, change,
        description, source, last_updated 키를 포함하는 딕셔너리.
    """
    cache_key = "cnn_fear_greed"
    cached = get_cached(cache_key, ttl=_VIX_CACHE_TTL)
    if cached is not None:
        return cached

    try:
        headers = {
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _FEAR_GREED_API_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=_FEAR_GREED_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    logger.warning("CNN F&G API 응답 오류: %d", resp.status)
                    return _fallback_fear_greed()
                data = await resp.json()

        fg = data.get("fear_and_greed", {})
        score = round(float(fg.get("score", 50)))
        rating = str(fg.get("rating", "Neutral"))
        previous = float(fg.get("previous_close", score))

        # 영문 등급을 한국어로 변환한다.
        rating_kr_map: dict[str, str] = {
            "Extreme Fear": "극도의 공포",
            "Fear": "공포",
            "Neutral": "중립",
            "Greed": "탐욕",
            "Extreme Greed": "극도의 탐욕",
        }
        rating_kr = rating_kr_map.get(rating, rating)

        result: dict[str, Any] = {
            "score": score,
            "label": rating_kr,
            "rating_en": rating,
            "previous_close": round(previous),
            "change": round(score - previous, 1),
            "description": _fg_description(score),
            "source": "cnn",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        set_cache(cache_key, result)
        return result

    except Exception as exc:
        logger.warning("CNN F&G 조회 실패: %s, VIX 기반 폴백 사용", exc)
        return _fallback_fear_greed()


def _fallback_fear_greed() -> dict[str, Any]:
    """VIX 기반 폴백 공포탐욕지수를 반환한다.

    CNN API 조회 실패 시 캐시된 VIX 값으로 Fear&Greed 를 추정한다.

    Returns:
        score, label, description, source, last_updated 키를 포함하는 딕셔너리.
    """
    cached_vix = get_cached("vix_current", ttl=_VIX_COMPOSITE_CACHE_TTL)
    vix = float(cached_vix) if cached_vix is not None else 20.0
    fg = calc_fear_greed(vix)
    return {
        "score": fg["score"],
        "label": fg["label"],
        "description": fg["description"],
        "source": "vix_estimate",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def _fg_description(score: int) -> str:
    """Fear&Greed 점수에 따른 시장 해석 문자열을 반환한다.

    Args:
        score: Fear&Greed 점수 (0~100).

    Returns:
        한국어 시장 해석 문자열.
    """
    if score <= 25:
        return "극도의 공포 - 역발상 매수 기회 가능성. 시장 패닉 상태."
    if score <= 40:
        return "공포 - 투자자 불안 심화. 선별적 매수 고려."
    if score <= 55:
        return "중립 - 시장 방향성 불분명. 관망 또는 포지션 유지."
    if score <= 75:
        return "탐욕 - 시장 낙관. 과매수 주의."
    return "극도의 탐욕 - 과열 경고. 차익 실현 또는 방어 전략 고려."


# ---------------------------------------------------------------------------
# Fear & Greed / VIX / 스프레드 계산
# ---------------------------------------------------------------------------

def calc_fear_greed(vix: float) -> dict[str, Any]:
    """VIX 값으로 Fear & Greed 지수를 계산한다.

    VIX 구간:
        - VIX < 12: Extreme Greed (85-100)
        - VIX 12-17: Greed (60-84)
        - VIX 17-22: Neutral (40-59)
        - VIX 22-30: Fear (15-39)
        - VIX > 30: Extreme Fear (0-14)

    공식: score = max(0, min(100, int(100 - (vix - 10) * 2.5)))

    Args:
        vix: VIX 현재값.

    Returns:
        score, label, description 키를 포함하는 딕셔너리.
    """
    score = max(0, min(100, int(100 - (vix - 10) * 2.5)))

    if vix < 12:
        label = "Extreme Greed"
        description = "극단적 탐욕 구간 - 과열 주의"
    elif vix < 17:
        label = "Greed"
        description = "시장 탐욕 구간"
    elif vix < 22:
        label = "Neutral"
        description = "중립 구간"
    elif vix < 30:
        label = "Fear"
        description = "시장 공포 구간"
    else:
        label = "Extreme Fear"
        description = "극단적 공포 구간 - 매수 기회 탐색"

    return {"score": score, "label": label, "description": description}


def vix_level(vix: float) -> str:
    """VIX 값에 따른 레벨 문자열을 반환한다.

    Args:
        vix: VIX 현재값.

    Returns:
        "low", "neutral", "elevated", "high", "extreme" 중 하나.
    """
    if vix < 15:
        return "low"
    elif vix < 20:
        return "neutral"
    elif vix < 25:
        return "elevated"
    elif vix < 35:
        return "high"
    else:
        return "extreme"


def treasury_spread_signal(spread: float) -> str:
    """국채 스프레드 값에 따른 신호를 반환한다.

    Args:
        spread: 10Y-2Y 국채 스프레드 값.

    Returns:
        "inverted", "flat", "normal", "steep" 중 하나.
    """
    if spread < -0.5:
        return "inverted"
    elif spread < 0.0:
        return "flat"
    elif spread < 1.5:
        return "normal"
    else:
        return "steep"


# ---------------------------------------------------------------------------
# 레짐 헬퍼
# ---------------------------------------------------------------------------

async def fetch_regime_from_db() -> dict[str, Any]:
    """DB에서 최신 레짐 정보를 조회한다.

    DB 조회 실패 시 기본값을 반환한다.

    Returns:
        current, confidence 키를 포함하는 딕셔너리.
    """
    try:
        from sqlalchemy import select

        from src.db.connection import get_session
        from src.db.models import IndicatorHistory

        async with get_session() as session:
            stmt = (
                select(IndicatorHistory)
                .where(IndicatorHistory.indicator_name == "regime")
                .order_by(IndicatorHistory.recorded_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is not None:
                metadata = row.metadata_ or {}
                return {
                    "current": metadata.get("regime", "unknown"),
                    "confidence": float(row.value) if row.value else 0.5,
                }
    except Exception as exc:
        logger.debug("레짐 DB 조회 실패 (정상 처리): %s", exc)

    return {"current": "unknown", "confidence": 0.5}


# ---------------------------------------------------------------------------
# 금리 전망 헬퍼
# ---------------------------------------------------------------------------

def estimate_rate_outlook(
    current_rate: float,
    vix: float,
    spread: float | None,
) -> dict[str, Any]:
    """VIX, 국채 스프레드 기반으로 금리 전망을 추정한다.

    시장 데이터(Polymarket/Kalshi)가 없을 때의 레짐 기반 추정치를 반환한다.

    Args:
        current_rate: 현재 연방기금금리 (%).
        vix: VIX 현재값.
        spread: 10Y-2Y 국채 스프레드. None이면 판단 제외.

    Returns:
        probabilities, year_end_estimate, source 키를 포함하는 딕셔너리.
    """
    # 수익률 곡선 역전 + VIX 고점 = 금리 인하 압력 증가
    if spread is not None and spread < -0.3 and vix > 25:
        return {
            "probabilities": {
                "cut_50bp": 15,
                "cut_25bp": 50,
                "hold": 30,
                "hike_25bp": 5,
            },
            "year_end_estimate": round(max(2.0, current_rate - 0.75), 2),
            "source": "regime_implied",
        }
    elif spread is not None and spread < 0.0:
        return {
            "probabilities": {
                "cut_50bp": 5,
                "cut_25bp": 35,
                "hold": 55,
                "hike_25bp": 5,
            },
            "year_end_estimate": round(max(2.5, current_rate - 0.50), 2),
            "source": "regime_implied",
        }
    elif vix > 30:
        return {
            "probabilities": {
                "cut_50bp": 25,
                "cut_25bp": 45,
                "hold": 25,
                "hike_25bp": 5,
            },
            "year_end_estimate": round(max(2.0, current_rate - 1.0), 2),
            "source": "regime_implied",
        }
    else:
        return {
            "probabilities": {
                "cut_50bp": 5,
                "cut_25bp": 25,
                "hold": 60,
                "hike_25bp": 10,
            },
            "year_end_estimate": round(current_rate - 0.25, 2),
            "source": "regime_implied",
        }


def format_rate_range(rate: float) -> str:
    """연방기금금리를 목표 범위 문자열로 포맷한다.

    예: 4.50 -> "4.25-4.50"

    Args:
        rate: 연방기금금리 (%).

    Returns:
        "하한-상한" 형식의 문자열.
    """
    lower = round(rate - 0.25, 2)
    return f"{lower:.2f}-{rate:.2f}"


async def fetch_market_rate_probs() -> dict[str, Any] | None:
    """DB에서 Polymarket/Kalshi 기반 금리 확률 데이터를 조회한다.

    DB에 관련 데이터가 없거나 조회 실패 시 None을 반환한다.

    Returns:
        probabilities, year_end_estimate 키를 담은 딕셔너리 또는 None.
    """
    try:
        from sqlalchemy import select

        from src.db.connection import get_session
        from src.db.models import IndicatorHistory

        async with get_session() as session:
            stmt = (
                select(IndicatorHistory)
                .where(
                    IndicatorHistory.indicator_name.in_([
                        "fed_rate_cut_prob",
                        "kalshi_rate_cut",
                        "polymarket_rate",
                    ])
                )
                .order_by(IndicatorHistory.recorded_at.desc())
                .limit(5)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            if not rows:
                return None

            # 가장 최근 행의 metadata에서 확률 추출
            for row in rows:
                meta = row.metadata_ or {}
                if "probabilities" in meta:
                    return {
                        "probabilities": meta["probabilities"],
                        "year_end_estimate": meta.get("year_end_estimate", 4.25),
                        "source": "market_implied",
                    }

    except Exception as exc:
        logger.debug("시장 금리 확률 DB 조회 예외: %s", exc)

    return None
