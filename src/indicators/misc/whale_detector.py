"""F3 지표 -- 오더플로우 기반 고래 활동 탐지이다.

거래량 급등(2x 이상) 또는 CVD 절대 변동이 임계값을 초과하면
고래 이벤트로 기록하여 orderflow:whale 캐시에 누적한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger

logger = get_logger(__name__)

# 거래량 급등 배수 임계값 (평균 대비 2배 초과 시 탐지)
_VOLUME_SPIKE_MULTIPLIER: float = 2.0

# CVD 절대 변동 임계값 (직전 스냅샷 대비)
_CVD_SPIKE_THRESHOLD: float = 500.0

# 고래 이벤트 최대 보관 개수
_WHALE_MAX_SIZE: int = 100

# 고래 캐시 TTL (24시간)
_WHALE_TTL: int = 86400

# 히스토리에서 평균 계산 시 최소 데이터 수
_MIN_HISTORY_FOR_AVG: int = 3


def _calc_avg_volume(history: list[dict]) -> float:
    """히스토리에서 평균 거래량을 계산한다. 데이터 부족 시 0.0이다."""
    volumes = [h.get("volume", 0) for h in history if h.get("volume", 0) > 0]
    if len(volumes) < _MIN_HISTORY_FOR_AVG:
        return 0.0
    return sum(volumes) / len(volumes)


def _detect_volume_spike(
    ticker: str,
    current_volume: int,
    avg_volume: float,
) -> dict | None:
    """거래량이 평균의 2배를 초과하면 고래 이벤트를 반환한다."""
    if avg_volume <= 0 or current_volume <= 0:
        return None
    magnitude = round(current_volume / avg_volume, 2)
    if magnitude <= _VOLUME_SPIKE_MULTIPLIER:
        return None
    return {
        "ticker": ticker,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "type": "volume_spike",
        "magnitude": magnitude,
        "details": {
            "current_volume": current_volume,
            "avg_volume": round(avg_volume, 1),
            "multiplier": magnitude,
        },
    }


def _detect_cvd_spike(
    ticker: str,
    current_cvd: float,
    prev_cvd: float,
) -> dict | None:
    """CVD 절대 변동이 임계값을 초과하면 고래 이벤트를 반환한다."""
    delta = abs(current_cvd - prev_cvd)
    if delta <= _CVD_SPIKE_THRESHOLD:
        return None
    direction = "buy" if current_cvd > prev_cvd else "sell"
    return {
        "ticker": ticker,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "type": "cvd_spike",
        "magnitude": round(delta, 2),
        "details": {
            "current_cvd": round(current_cvd, 2),
            "prev_cvd": round(prev_cvd, 2),
            "delta": round(delta, 2),
            "direction": direction,
        },
    }


async def detect_whale_events(
    cache: CacheClient,
    snapshots: list[dict],
) -> None:
    """오더플로우 스냅샷에서 고래 활동을 탐지하여 캐시에 기록한다.

    각 티커의 히스토리를 조회하여 거래량 급등과 CVD 급변을 감지한다.
    탐지된 이벤트는 orderflow:whale 캐시 리스트에 원자적으로 추가한다.
    """
    whale_events: list[dict] = []
    for item in snapshots:
        ticker = item.get("ticker")
        if not ticker:
            continue
        events = await _detect_for_ticker(cache, ticker, item)
        whale_events.extend(events)

    if not whale_events:
        return

    await cache.atomic_list_append(
        "orderflow:whale",
        whale_events,
        max_size=_WHALE_MAX_SIZE,
        ttl=_WHALE_TTL,
    )
    logger.info("고래 이벤트 %d건 탐지: %s", len(whale_events),
                [e["ticker"] for e in whale_events])


async def _detect_for_ticker(
    cache: CacheClient,
    ticker: str,
    current: dict,
) -> list[dict]:
    """단일 티커에 대해 고래 이벤트를 탐지한다."""
    history = await cache.read_json(f"orderflow:history:{ticker}")
    if not isinstance(history, list) or len(history) < _MIN_HISTORY_FOR_AVG:
        return []

    current_volume = current.get("last_volume", 0)
    cvd_data = current.get("cvd", {})
    current_cvd = cvd_data.get("cumulative", 0.0) if isinstance(cvd_data, dict) else 0.0

    events: list[dict] = []

    # 거래량 급등 탐지
    avg_vol = _calc_avg_volume(history)
    vol_event = _detect_volume_spike(ticker, current_volume, avg_vol)
    if vol_event is not None:
        events.append(vol_event)

    # CVD 급변 탐지 (직전 스냅샷 대비)
    prev_cvd = history[-1].get("cvd", 0.0)
    cvd_event = _detect_cvd_spike(ticker, current_cvd, prev_cvd)
    if cvd_event is not None:
        events.append(cvd_event)

    return events
