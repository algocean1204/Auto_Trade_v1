"""F4 통계적 차익거래 -- Z-Score 기반 페어 스프레드 신호를 생성한다.

M-7: 자동 청산 조건을 추가한다 (평균회귀 완료, 스톱로스, 시간 제한).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

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

# 청산 Z-Score 임계값 (M-7)
_Z_EXIT_MEAN_REVERSION = 0.5     # 평균회귀 완료 (|Z| <= 0.5)
_Z_EXIT_STOP_LOSS = 3.0          # 발산 심화 스톱로스 (|Z| >= 3.0)
_EXIT_MAX_HOLDING_DAYS = 5       # 최대 보유 기간 (일)

# 진입 시각 캐시 키 접두사
_ENTRY_TIME_PREFIX = "stat_arb:entry_time:"

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
    """Z-Score 기반 통계적 차익거래 신호를 생성한다.

    M-7: 자동 청산 조건을 추가하여 포지션 관리를 완성한다.
    - 평균회귀 완료: |Z| <= 0.5
    - 발산 스톱로스: |Z| >= 3.0
    - 시간 제한: 5일 초과 보유
    """

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

    async def should_exit_pair(
        self,
        pair_key: str,
        current_z_score: float,
        cache: CacheClient,
    ) -> tuple[bool, str]:
        """StatArb 포지션의 청산 조건을 검사한다.

        Args:
            pair_key: 페어 키 (예: "QQQ/QLD")
            current_z_score: 현재 Z-Score
            cache: 캐시 클라이언트

        Returns:
            (청산 여부, 사유)
        """
        # 조건 1: 평균회귀 완료 -- Z-Score가 ±0.5 이내로 수렴했다
        if abs(current_z_score) <= _Z_EXIT_MEAN_REVERSION:
            logger.info(
                "StatArb 청산(평균회귀 완료): %s Z=%.2f",
                pair_key, current_z_score,
            )
            return True, f"평균회귀 완료 (Z={current_z_score:.2f})"

        # 조건 2: 발산 스톱로스 -- Z-Score가 ±3.0을 초과하여 발산이 심화되었다
        if abs(current_z_score) >= _Z_EXIT_STOP_LOSS:
            logger.warning(
                "StatArb 청산(발산 스톱로스): %s Z=%.2f",
                pair_key, current_z_score,
            )
            return True, f"발산 스톱로스 (Z={current_z_score:.2f})"

        # 조건 3: 시간 제한 -- 5일 초과 보유 시 강제 청산한다
        try:
            entry_key = f"{_ENTRY_TIME_PREFIX}{pair_key}"
            raw = await cache.read(entry_key)
            if raw is not None:
                entry_time = datetime.fromisoformat(raw)
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                holding_days = (datetime.now(tz=timezone.utc) - entry_time).days
                if holding_days >= _EXIT_MAX_HOLDING_DAYS:
                    logger.info(
                        "StatArb 청산(시간 제한): %s %d일 보유",
                        pair_key, holding_days,
                    )
                    return True, f"시간 제한 ({holding_days}일 >= {_EXIT_MAX_HOLDING_DAYS}일)"
        except Exception as exc:
            logger.debug("StatArb 진입 시각 조회 실패 (무시): %s", exc)

        return False, ""

    async def record_entry_time(
        self, pair_key: str, cache: CacheClient,
    ) -> None:
        """StatArb 진입 시각을 캐시에 기록한다."""
        try:
            entry_key = f"{_ENTRY_TIME_PREFIX}{pair_key}"
            # 이미 기록된 진입 시각이 없을 때만 저장한다
            existing = await cache.read(entry_key)
            if existing is None:
                now_str = datetime.now(tz=timezone.utc).isoformat()
                await cache.write(
                    entry_key, now_str,
                    ttl=_EXIT_MAX_HOLDING_DAYS * 86400 + 86400,
                )
        except Exception as exc:
            logger.warning("StatArb 진입 시각 기록 실패 — 이 페어는 시간 제한 미적용: %s", exc)

    async def clear_entry_time(
        self, pair_key: str, cache: CacheClient,
    ) -> None:
        """StatArb 청산 후 진입 시각을 삭제한다."""
        try:
            await cache.delete(f"{_ENTRY_TIME_PREFIX}{pair_key}")
        except Exception:
            pass

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
