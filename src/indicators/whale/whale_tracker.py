"""F3 지표 -- 고래 활동 감지 (블록거래 + 아이스버그)이다."""
from __future__ import annotations

import json

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.indicators.models import WhaleSignal

logger = get_logger(__name__)

_BLOCK_THRESHOLD_USD: float = 200_000.0
_ICEBERG_MIN_TRADES: int = 5  # 1초 내 5회 이상 = 아이스버그 의심
_BLOCK_WEIGHT: float = 0.6
_ICEBERG_WEIGHT: float = 0.4
_CACHE_KEY: str = "whale:order_flow:{ticker}"


def _score_blocks(trades: list[dict], threshold: float) -> tuple[float, int, float]:
    """블록 거래($200k+)를 감지하고 점수/건수/순방향을 반환한다."""
    blocks: list[dict] = [t for t in trades if t.get("amount_usd", 0) >= threshold]
    if not blocks:
        return 0.0, 0, 0.0
    buy_vol = sum(t["amount_usd"] for t in blocks if t.get("side") == "buy")
    sell_vol = sum(t["amount_usd"] for t in blocks if t.get("side") == "sell")
    total = buy_vol + sell_vol
    if total == 0:
        return 0.0, len(blocks), 0.0
    # 점수: 블록 거래 금액 비율 (최대 1.0)
    score = min(1.0, total / 1_000_000.0)
    direction = (buy_vol - sell_vol) / total
    return score, len(blocks), direction


def _score_icebergs(trades: list[dict], min_trades: int) -> tuple[float, int, float]:
    """아이스버그 주문(1초 내 동일 가격 5+건)을 감지한다."""
    # 초 단위 타임스탬프 + 가격 조합으로 그룹핑한다
    groups: dict[str, list[dict]] = {}
    for t in trades:
        key = f"{int(t.get('timestamp', 0))}_{t.get('price', 0)}"
        groups.setdefault(key, []).append(t)
    icebergs = [g for g in groups.values() if len(g) >= min_trades]
    if not icebergs:
        return 0.0, 0, 0.0
    count = len(icebergs)
    buy_count = sum(
        1 for g in icebergs
        if sum(1 for t in g if t.get("side") == "buy") > len(g) // 2
    )
    sell_count = count - buy_count
    score = min(1.0, count / 10.0)
    direction = (buy_count - sell_count) / max(count, 1)
    return score, count, direction


class WhaleTracker:
    """블록 거래와 아이스버그 주문을 감지하여 고래 활동을 추적한다."""

    def __init__(self, cache: CacheClient) -> None:
        """CacheClient 의존성을 주입받는다."""
        self._cache = cache

    async def track(self, ticker: str) -> WhaleSignal | None:
        """고래 활동을 분석한다.

        Args:
            ticker: 종목 코드

        Returns:
            WhaleSignal 또는 None (Redis 데이터 미가용 시)
        """
        trades = await self._load_trades(ticker)
        if not trades:
            logger.debug("고래 추적 스킵: %s Redis 체결 데이터 없음", ticker)
            return None
        block_score, block_count, block_dir = _score_blocks(trades, _BLOCK_THRESHOLD_USD)
        ice_score, ice_count, ice_dir = _score_icebergs(trades, _ICEBERG_MIN_TRADES)

        total_score = block_score * _BLOCK_WEIGHT + ice_score * _ICEBERG_WEIGHT
        weighted_dir = block_dir * _BLOCK_WEIGHT + ice_dir * _ICEBERG_WEIGHT
        direction = "buy" if weighted_dir > 0.1 else ("sell" if weighted_dir < -0.1 else "neutral")

        logger.debug(
            "%s 고래: block=%.2f(%d), iceberg=%.2f(%d), dir=%s",
            ticker, block_score, block_count, ice_score, ice_count, direction,
        )
        return WhaleSignal(
            block_score=round(block_score, 4),
            iceberg_score=round(ice_score, 4),
            direction=direction,
            total_score=round(total_score, 4),
            block_count=block_count,
            iceberg_count=ice_count,
        )

    async def _load_trades(self, ticker: str) -> list[dict]:
        """Redis에서 최근 체결 데이터를 조회한다."""
        key = _CACHE_KEY.format(ticker=ticker)
        data = await self._cache.read_json(key)
        if data is None:
            return []
        return data.get("trades", [])
