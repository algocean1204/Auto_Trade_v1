"""F8 RAG -- 분봉 리플레이 -> ChromaDB 임베딩이다."""

from __future__ import annotations

import json

from src.common.logger import get_logger
from src.optimization.models import TimeTravelResult

logger = get_logger(__name__)

# 패턴 감지 임계값이다
_SPIKE_THRESHOLD: float = 0.02
_VOLUME_SPIKE_MULT: float = 2.0
_MIN_PATTERN_LENGTH: int = 3


def _detect_price_spike(candles: list[dict], idx: int) -> bool:
    """급등/급락 패턴을 감지한다."""
    if idx < 1:
        return False
    prev_price = _safe_float(candles[idx - 1].get("close"))
    curr_price = _safe_float(candles[idx].get("close"))
    if prev_price <= 0:
        return False
    change = abs(curr_price - prev_price) / prev_price
    return change >= _SPIKE_THRESHOLD


def _detect_volume_spike(candles: list[dict], idx: int) -> bool:
    """거래량 급증 패턴을 감지한다."""
    if idx < 5:
        return False
    recent_vols = [
        _safe_float(candles[i].get("volume"))
        for i in range(idx - 5, idx)
    ]
    avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1.0
    curr_vol = _safe_float(candles[idx].get("volume"))
    return curr_vol >= avg_vol * _VOLUME_SPIKE_MULT


def _detect_trend_reversal(
    candles: list[dict], idx: int,
) -> bool:
    """추세 반전 패턴을 감지한다."""
    if idx < _MIN_PATTERN_LENGTH:
        return False
    prices = [
        _safe_float(candles[i].get("close"))
        for i in range(idx - _MIN_PATTERN_LENGTH, idx + 1)
    ]
    # 연속 상승 후 하락 또는 연속 하락 후 상승이다
    diffs = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    if len(diffs) < 2:
        return False
    prev_direction = diffs[-2] > 0
    curr_direction = diffs[-1] > 0
    return prev_direction != curr_direction


def _safe_float(val: object, default: float = 0.0) -> float:
    """안전하게 float 변환한다."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _extract_patterns(candles: list[dict]) -> list[dict]:
    """분봉 데이터에서 주요 패턴을 추출한다."""
    patterns: list[dict] = []

    for idx in range(len(candles)):
        pattern_types: list[str] = []

        if _detect_price_spike(candles, idx):
            pattern_types.append("price_spike")
        if _detect_volume_spike(candles, idx):
            pattern_types.append("volume_spike")
        if _detect_trend_reversal(candles, idx):
            pattern_types.append("trend_reversal")

        if pattern_types:
            patterns.append({
                "index": idx,
                "types": pattern_types,
                "candle": candles[idx],
            })

    return patterns


def _build_embedding_text(pattern: dict) -> str:
    """패턴을 임베딩용 텍스트로 변환한다."""
    candle = pattern.get("candle", {})
    types = ", ".join(pattern.get("types", []))
    return (
        f"패턴: {types} | "
        f"시간: {candle.get('timestamp', 'N/A')} | "
        f"가격: {candle.get('close', 0)} | "
        f"거래량: {candle.get('volume', 0)} | "
        f"틱커: {candle.get('ticker', 'N/A')}"
    )


def replay_and_embed(
    historical_data: list[dict],
    knowledge_manager: object | None = None,
) -> TimeTravelResult:
    """분봉 데이터를 리플레이하며 패턴을 ChromaDB에 임베딩한다.

    가격 급변, 거래량 급증, 추세 반전 패턴을 감지하여
    ChromaDB에 벡터로 저장한다.
    """
    logger.info("분봉 리플레이 시작: %d개 캔들", len(historical_data))

    patterns = _extract_patterns(historical_data)
    embedded_count = 0

    for pattern in patterns:
        text = _build_embedding_text(pattern)
        meta = {
            "pattern_types": json.dumps(pattern["types"]),
            "index": pattern["index"],
        }

        if knowledge_manager is not None:
            try:
                knowledge_manager.store_document(text, meta)
                embedded_count += 1
            except Exception as exc:
                logger.warning("임베딩 실패: %s", exc)
        else:
            embedded_count += 1

    logger.info(
        "리플레이 완료: 패턴=%d, 임베딩=%d",
        len(patterns), embedded_count,
    )

    return TimeTravelResult(
        embeddings_count=embedded_count,
        patterns_found=len(patterns),
    )
