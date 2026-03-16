"""슬리피지 집계 -- slippage:raw 데이터를 slippage:stats/hours로 집계한다.

EOD 시퀀스에서 호출되며, 캐시 slippage:raw 리스트를 읽어
종합 통계(slippage:stats)와 시간대별 통계(slippage:hours)를 산출한다.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient

logger = get_logger(__name__)

# 집계 결과 캐시 TTL: 7일 (초 단위)
_STATS_TTL: int = 86400 * 7


def _bps_to_pct(bps: float) -> float:
    """basis points를 퍼센트로 변환한다. 1bps = 0.01%."""
    return round(bps / 100, 6)


def _classify_recommendation(avg_pct: float) -> str:
    """평균 슬리피지(%)로 체결 추천 등급을 반환한다."""
    abs_pct = abs(avg_pct)
    if abs_pct < 0.02:
        return "EXCELLENT"
    if abs_pct < 0.05:
        return "GOOD"
    if abs_pct < 0.10:
        return "FAIR"
    return "AVOID"


def _total_slippage_cost(records: list[dict]) -> float:
    """금액 기반 슬리피지 합계(USD)를 계산한다."""
    return round(sum(
        abs(float(r.get("actual_price", 0)) - float(r.get("expected_price", 0)))
        * int(r.get("quantity", 1))
        for r in records
    ), 2)


def compute_slippage_stats(records: list[dict]) -> dict:
    """슬리피지 원시 기록 리스트에서 종합 통계를 산출한다."""
    if not records:
        return _empty_stats()

    all_bps = [float(r.get("slippage_bps", 0.0)) for r in records]
    by_hour = _aggregate_by_hour(records)

    return {
        "avg_slippage_pct": _bps_to_pct(statistics.mean(all_bps)),
        "median_slippage_pct": _bps_to_pct(statistics.median(all_bps)),
        "max_slippage_pct": _bps_to_pct(max(abs(b) for b in all_bps)),
        "total_slippage_cost": _total_slippage_cost(records),
        "total_trades": len(records),
        "best_execution_hour": _find_best_hour(by_hour),
        "by_side": _aggregate_by_side(records),
        "by_ticker": _aggregate_by_ticker(records),
        "by_hour": {str(h): v for h, v in by_hour.items()},
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def compute_slippage_hours(records: list[dict]) -> list[dict]:
    """시간대별 슬리피지 통계를 산출한다.

    Returns:
        slippage:hours 캐시에 기록할 리스트이다.
    """
    if not records:
        return []
    by_hour = _aggregate_by_hour(records)
    result: list[dict] = []
    for hour in sorted(by_hour.keys()):
        info = by_hour[hour]
        avg_pct = _bps_to_pct(info["avg_bps"])
        result.append({
            "hour": hour,
            "avg_slippage": avg_pct,
            "trade_count": info["count"],
            "recommendation": _classify_recommendation(avg_pct),
        })
    return result


def _aggregate_by_side(records: list[dict]) -> dict:
    """매수/매도 방향별 평균 슬리피지를 집계한다."""
    sides: dict[str, list[float]] = defaultdict(list)
    for r in records:
        side = r.get("side", "unknown")
        sides[side].append(float(r.get("slippage_bps", 0.0)))
    return {
        side: {
            "avg_bps": round(statistics.mean(vals), 2),
            "count": len(vals),
        }
        for side, vals in sides.items()
    }


def _aggregate_by_ticker(records: list[dict]) -> dict:
    """종목별 평균 슬리피지를 집계한다."""
    tickers: dict[str, list[float]] = defaultdict(list)
    for r in records:
        tk = r.get("ticker", "UNKNOWN")
        tickers[tk].append(float(r.get("slippage_bps", 0.0)))
    return {
        tk: {
            "avg_bps": round(statistics.mean(vals), 2),
            "count": len(vals),
        }
        for tk, vals in tickers.items()
    }


def _aggregate_by_hour(records: list[dict]) -> dict[int, dict]:
    """ET 시간대별 슬리피지를 집계한다."""
    hours: dict[int, list[float]] = defaultdict(list)
    for r in records:
        ts = r.get("timestamp", "")
        hour = _extract_hour(ts)
        hours[hour].append(float(r.get("slippage_bps", 0.0)))
    return {
        h: {
            "avg_bps": round(statistics.mean(vals), 2),
            "count": len(vals),
        }
        for h, vals in hours.items()
    }


def _extract_hour(ts_str: str) -> int:
    """ISO 타임스탬프에서 ET 시간(0-23)을 추출한다. 파싱 실패 시 0."""
    try:
        dt = datetime.fromisoformat(ts_str)
        # UTC → ET (대략 -5 또는 -4, 간이 -5h 적용)
        et_hour = (dt.hour - 5) % 24
        return et_hour
    except (ValueError, TypeError):
        return 0


def _find_best_hour(by_hour: dict[int, dict]) -> int:
    """슬리피지 절댓값이 가장 낮은 시간대를 반환한다."""
    if not by_hour:
        return 10  # 기본값: 오전 10시 ET
    return min(by_hour, key=lambda h: abs(by_hour[h]["avg_bps"]))


def _empty_stats() -> dict:
    """거래 없을 때 기본 통계를 반환한다."""
    return {
        "avg_slippage_pct": 0.0,
        "median_slippage_pct": 0.0,
        "max_slippage_pct": 0.0,
        "total_slippage_cost": 0.0,
        "total_trades": 0,
        "best_execution_hour": 10,
        "by_side": {},
        "by_ticker": {},
        "by_hour": {},
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


async def aggregate_and_write(cache: CacheClient) -> int:
    """slippage:raw를 읽어 stats/hours를 산출하고 캐시에 기록한다.

    Returns:
        집계에 사용된 원시 기록 수이다.
    """
    raw: list[dict] = await cache.read_json("slippage:raw") or []
    if not raw:
        logger.info("슬리피지 원시 데이터 없음 -- 집계 건너뜀")
        return 0

    stats = compute_slippage_stats(raw)
    hours = compute_slippage_hours(raw)

    await cache.write_json("slippage:stats", stats, ttl=_STATS_TTL)
    await cache.write_json("slippage:hours", hours, ttl=_STATS_TTL)

    logger.info(
        "슬리피지 집계 완료: %d건, 평균=%.4f%%, 최적시간=%dh ET",
        stats["total_trades"],
        stats["avg_slippage_pct"],
        stats["best_execution_hour"],
    )
    return len(raw)
