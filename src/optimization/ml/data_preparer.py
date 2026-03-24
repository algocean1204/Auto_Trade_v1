"""F8 ML -- DB에서 학습 데이터를 조회하고 정제한다."""

from __future__ import annotations

import json

from sqlalchemy import text

from src.common.cache_gateway import CacheClient
from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger
from src.optimization.models import DateRange, PreparedData

logger = get_logger(__name__)

# 캐시 키 접두사이다
_CACHE_PREFIX: str = "ml:prepared_data"
_CACHE_TTL: int = 3600


async def _fetch_trades(
    session_factory: SessionFactory, date_range: DateRange,
) -> list[dict]:
    """거래 기록을 DB에서 조회한다."""
    async with session_factory.get_session() as session:
        # 명시적 컬럼 나열 — 스키마 변경에 안전하다 (Trade 모델 기준)
        query = (
            "SELECT id, ticker, side, quantity, price, "
            "order_id, reason, created_at "
            "FROM trades "
            "WHERE created_at BETWEEN :start AND :end "
            "ORDER BY created_at"
        )
        result = await session.execute(
            text(query),
            {"start": date_range.start, "end": date_range.end},
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]


async def _fetch_indicators(
    session_factory: SessionFactory, date_range: DateRange,
) -> list[dict]:
    """기술 지표 데이터를 indicator_history 테이블에서 조회한다."""
    async with session_factory.get_session() as session:
        query = (
            "SELECT id, ticker, indicator_name, value, "
            "metadata, recorded_at "
            "FROM indicator_history "
            "WHERE recorded_at BETWEEN :start AND :end "
            "ORDER BY recorded_at"
        )
        result = await session.execute(
            text(query),
            {"start": date_range.start, "end": date_range.end},
        )
        rows = result.mappings().all()
        return [dict(r) for r in rows]


def _merge_and_clean(
    trades: list[dict], indicators: list[dict],
) -> list[dict]:
    """거래와 지표 데이터를 병합하고 결측치를 제거한다.

    indicator_history는 지표별로 별도 행에 저장되므로
    (ticker, 시간) 기준으로 피벗하여 하나의 dict로 합친다.
    indicator_name을 키로, value를 값으로 사용한다.
    """
    merged: list[dict] = []

    # 지표를 (ticker, 시간) 기준으로 피벗한다
    # 각 행은 {indicator_name: value, ...} 구조로 변환된다
    ind_map: dict[str, dict[str, float]] = {}
    for ind in indicators:
        ticker = str(ind.get("ticker", ""))
        time_key = str(ind.get("recorded_at", ""))[:16]
        composite_key = f"{ticker}:{time_key}"
        if composite_key not in ind_map:
            ind_map[composite_key] = {}
        name = str(ind.get("indicator_name", ""))
        value = ind.get("value")
        if name and value is not None:
            ind_map[composite_key][name] = float(value)

    for trade in trades:
        ticker = str(trade.get("ticker", ""))
        trade_time = str(trade.get("created_at", ""))[:16]
        composite_key = f"{ticker}:{trade_time}"
        row = {**trade}
        if composite_key in ind_map:
            row.update(ind_map[composite_key])
        merged.append(row)

    # None 값이 절반 이상인 행을 제거한다
    cleaned: list[dict] = []
    for row in merged:
        none_count = sum(1 for v in row.values() if v is None)
        if none_count < len(row) / 2:
            cleaned.append(row)

    return cleaned


async def _try_cache(
    cache: CacheClient | None, key: str,
) -> PreparedData | None:
    """캐시에서 이전 결과를 조회한다."""
    if cache is None:
        return None
    raw = await cache.read_json(key)
    if raw is None:
        return None
    logger.info("캐시 히트: %s", key)
    return PreparedData(**raw)


async def _save_cache(
    cache: CacheClient | None, key: str, result: PreparedData,
) -> None:
    """결과를 캐시에 저장한다."""
    if cache is None:
        return
    await cache.write_json(
        key, json.loads(result.model_dump_json()), ttl=_CACHE_TTL,
    )


async def prepare_data(
    date_range: DateRange,
    session_factory: SessionFactory,
    cache: CacheClient | None = None,
) -> PreparedData:
    """학습 데이터를 조회하고 정제하여 반환한다.

    거래 기록과 기술 지표를 DB에서 조회한 뒤 병합/정제한다.
    캐시가 있으면 우선 조회하여 중복 쿼리를 방지한다.
    """
    cache_key = f"{_CACHE_PREFIX}:{date_range.start}:{date_range.end}"

    # 캐시 확인이다
    cached = await _try_cache(cache, cache_key)
    if cached is not None:
        return cached

    # DB 조회이다
    trades = await _fetch_trades(session_factory, date_range)
    indicators = await _fetch_indicators(session_factory, date_range)

    logger.info(
        "조회 완료: trades=%d, indicators=%d", len(trades), len(indicators),
    )

    # 병합/정제이다
    merged = _merge_and_clean(trades, indicators)
    date_str = f"{date_range.start:%Y-%m-%d} ~ {date_range.end:%Y-%m-%d}"

    result = PreparedData(
        data=merged, row_count=len(merged), date_range=date_str,
    )

    # 캐시 저장이다
    await _save_cache(cache, cache_key, result)

    logger.info("데이터 정제 완료: %d행", result.row_count)
    return result
