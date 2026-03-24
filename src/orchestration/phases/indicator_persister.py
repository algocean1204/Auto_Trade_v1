"""지표 DB 저장 -- 계산된 IndicatorBundle을 indicator_history 테이블에 기록한다.

data_preparer.py가 ML 학습 데이터를 조회할 때 indicator_history를 읽으므로
매매 루프에서 지표 계산 후 이 모듈을 호출하여 DB에 기록해야 한다.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger
from src.db.models import IndicatorHistory
from src.indicators.models import IndicatorBundle

logger = get_logger(__name__)


async def persist_indicator_bundle(
    db: SessionFactory,
    ticker: str,
    bundle: IndicatorBundle | None,
) -> int:
    """IndicatorBundle의 핵심 지표를 indicator_history 테이블에 저장한다.

    technical 필드의 주요 지표(rsi, macd, atr, ema_20 등)를 개별 행으로 기록한다.
    저장된 행 수를 반환한다. 실패 시 0을 반환하고 로그만 남긴다.
    """
    if bundle is None:
        return 0

    technical = getattr(bundle, "technical", None)
    if technical is None:
        return 0

    # 기록할 지표 매핑: (indicator_name, value, metadata)
    entries: list[tuple[str, float, dict]] = []

    # 핵심 기술 지표를 개별 행으로 분리한다
    _add_if_valid(entries, "rsi", getattr(technical, "rsi", None))
    _add_if_valid(entries, "macd", getattr(technical, "macd", None))
    _add_if_valid(entries, "macd_signal", getattr(technical, "macd_signal", None))
    _add_if_valid(entries, "macd_histogram", getattr(technical, "macd_histogram", None))
    _add_if_valid(entries, "atr", getattr(technical, "atr", None))
    _add_if_valid(entries, "ema_20", getattr(technical, "ema_20", None))
    _add_if_valid(entries, "ema_50", getattr(technical, "ema_50", None))
    _add_if_valid(entries, "sma_200", getattr(technical, "sma_200", None))
    _add_if_valid(entries, "bb_upper", getattr(technical, "bb_upper", None))
    _add_if_valid(entries, "bb_lower", getattr(technical, "bb_lower", None))

    # 추가 지표가 있으면 메타데이터와 함께 기록한다
    order_flow = getattr(bundle, "order_flow", None)
    if order_flow is not None:
        obi = getattr(order_flow, "obi", None)
        if obi is not None:
            entries.append(("obi", float(obi), {"source": "order_flow"}))

    momentum = getattr(bundle, "momentum", None)
    if momentum is not None:
        alignment = getattr(momentum, "alignment", None)
        if alignment is not None:
            entries.append(("momentum_alignment", float(alignment), {"source": "cross_asset"}))

    if not entries:
        return 0

    saved = 0
    try:
        async with db.get_session() as session:
            for name, value, meta in entries:
                record = IndicatorHistory(
                    ticker=ticker,
                    indicator_name=name,
                    value=value,
                    recorded_at=datetime.now(tz=timezone.utc),
                    metadata_=meta,
                )
                session.add(record)
            saved = len(entries)
        logger.debug("지표 DB 저장: %s %d건", ticker, saved)
    except Exception as exc:
        logger.warning("지표 DB 저장 실패 (%s): %s", ticker, exc)
        saved = 0

    return saved


def _add_if_valid(
    entries: list[tuple[str, float, dict]],
    name: str,
    value: float | None,
) -> None:
    """값이 유효한 숫자이면 entries 리스트에 추가한다."""
    if value is None:
        return
    try:
        float_val = float(value)
        # NaN/inf 값은 DB에 저장하지 않는다 (ML 학습 데이터 오염 방지)
        if math.isnan(float_val) or math.isinf(float_val):
            return
        entries.append((name, float_val, {}))
    except (TypeError, ValueError):
        pass
