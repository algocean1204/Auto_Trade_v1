"""F4 통계적 차익거래 -- Z-Score 기반 페어 스프레드 신호를 생성한다."""
from __future__ import annotations

import json
import math

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.strategy.models import StatArbSignal

logger = get_logger(__name__)

# 5개 페어 (기초자산/레버리지ETF)
_PAIRS: list[tuple[str, str]] = [
    ("QQQ", "QLD"),
    ("SPY", "SSO"),
    ("IWM", "UWM"),
    ("DIA", "DDM"),
    ("SOXX", "SOXL"),
]

# Z-Score 임계값
_Z_LONG_THRESHOLD = -2.0
_Z_SHORT_THRESHOLD = 2.0

# 스프레드 이력 캐시 키 접두사
_CACHE_PREFIX = "stat_arb:spread:"

# 이동 평균 윈도우
_WINDOW_SIZE = 20


def _calculate_spread(base_price: float, etf_price: float) -> float:
    """기초자산 대비 레버리지 ETF 로그 스프레드를 계산한다."""
    if base_price <= 0 or etf_price <= 0:
        return 0.0
    return math.log(etf_price) - math.log(base_price)


def _calculate_z_score(spread: float, mean: float, std: float) -> float:
    """스프레드의 Z-Score를 계산한다. 표준편차가 0이면 0을 반환한다."""
    if std == 0:
        return 0.0
    return round((spread - mean) / std, 4)


def _determine_signal(z_score: float) -> tuple[str, str]:
    """Z-Score로 방향과 신호 유형을 결정한다."""
    if z_score >= _Z_SHORT_THRESHOLD:
        return "short", "mean_reversion_short"
    if z_score <= _Z_LONG_THRESHOLD:
        return "long", "mean_reversion_long"
    return "neutral", "no_signal"


def _compute_stats(history: list[float]) -> tuple[float, float]:
    """이력의 평균과 표준편차를 계산한다."""
    n = len(history)
    if n < 2:
        return 0.0, 0.0
    mean = sum(history) / n
    variance = sum((x - mean) ** 2 for x in history) / (n - 1)
    return mean, math.sqrt(variance)


class StatArb:
    """Z-Score 기반 통계적 차익거래 신호를 생성한다."""

    async def evaluate(
        self,
        pair_prices: dict[str, float],
        cache: CacheClient,
    ) -> list[StatArbSignal]:
        """모든 페어의 스프레드를 계산하고 Z-Score 신호를 생성한다."""
        signals: list[StatArbSignal] = []

        for base_ticker, etf_ticker in _PAIRS:
            signal = await self._evaluate_pair(
                base_ticker, etf_ticker, pair_prices, cache,
            )
            if signal is not None:
                signals.append(signal)

        return signals

    async def _evaluate_pair(
        self,
        base_ticker: str,
        etf_ticker: str,
        pair_prices: dict[str, float],
        cache: CacheClient,
    ) -> StatArbSignal | None:
        """개별 페어의 Z-Score를 계산하고 신호를 반환한다."""
        base_price = pair_prices.get(base_ticker, 0.0)
        etf_price = pair_prices.get(etf_ticker, 0.0)
        if base_price <= 0 or etf_price <= 0:
            return None

        spread = _calculate_spread(base_price, etf_price)
        pair_key = f"{base_ticker}/{etf_ticker}"
        cache_key = f"{_CACHE_PREFIX}{pair_key}"

        # 캐시에서 이력을 읽는다
        history = await self._load_history(cache, cache_key)
        history.append(spread)

        # 윈도우 크기 유지
        if len(history) > _WINDOW_SIZE:
            history = history[-_WINDOW_SIZE:]

        # 이력 저장
        await cache.write(cache_key, json.dumps(history, default=str), ttl=86400)

        # 데이터 부족 시 신호 없음
        if len(history) < 5:
            return None

        mean, std = _compute_stats(history)
        z_score = _calculate_z_score(spread, mean, std)
        direction, signal_type = _determine_signal(z_score)

        if direction == "neutral":
            return None

        logger.info("StatArb 신호: %s z=%.2f dir=%s", pair_key, z_score, direction)
        return StatArbSignal(
            pair=pair_key, z_score=z_score, direction=direction, signal_type=signal_type,
        )

    async def _load_history(self, cache: CacheClient, key: str) -> list[float]:
        """캐시에서 스프레드 이력을 읽는다."""
        try:
            raw = await cache.read(key)
            if raw is not None:
                return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("StatArb 이력 파싱 실패: %s", key)
        return []
