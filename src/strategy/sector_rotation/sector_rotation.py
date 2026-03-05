"""F4 섹터 로테이션 -- 7개 섹터 상대강도를 분석한다."""
from __future__ import annotations

from src.common.broker_gateway import BrokerClient
from src.common.logger import get_logger
from src.strategy.models import RotationSignal

logger = get_logger(__name__)

# 7개 섹터와 대표 ETF
_SECTOR_ETFS: dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Finance": "XLF",
    "Energy": "XLE",
    "Consumer": "XLY",
    "Industrial": "XLI",
    "Utilities": "XLU",
}

# 상대강도 가중치
_WEIGHT_PRICE_MOMENTUM = 0.4    # 가격 모멘텀 (변동률)
_WEIGHT_VOLUME_STRENGTH = 0.3   # 거래량 강도
_WEIGHT_RELATIVE_PERF = 0.3     # SPY 대비 상대 성과

# 벤치마크
_BENCHMARK = "SPY"


def _calculate_momentum(change_pct: float) -> float:
    """가격 모멘텀을 0~1 범위로 정규화한다."""
    # -5% ~ +5% 범위를 0 ~ 1로 매핑한다
    normalized = (change_pct + 5.0) / 10.0
    return round(max(0.0, min(1.0, normalized)), 4)


def _calculate_volume_strength(volume: int, avg_volume: int) -> float:
    """거래량 강도를 0~1 범위로 정규화한다."""
    if avg_volume <= 0:
        return 0.5
    ratio = volume / avg_volume
    # 0.5x ~ 2.0x 범위를 0 ~ 1로 매핑한다
    normalized = (ratio - 0.5) / 1.5
    return round(max(0.0, min(1.0, normalized)), 4)


def _calculate_relative_perf(sector_change: float, benchmark_change: float) -> float:
    """벤치마크 대비 상대 성과를 0~1 범위로 정규화한다."""
    diff = sector_change - benchmark_change
    # -3% ~ +3% 범위를 0 ~ 1로 매핑한다
    normalized = (diff + 3.0) / 6.0
    return round(max(0.0, min(1.0, normalized)), 4)


def _compute_sector_score(
    change_pct: float,
    volume: int,
    avg_volume: int,
    benchmark_change: float,
) -> float:
    """섹터 종합 점수를 계산한다."""
    momentum = _calculate_momentum(change_pct)
    vol_strength = _calculate_volume_strength(volume, avg_volume)
    relative = _calculate_relative_perf(change_pct, benchmark_change)

    score = (
        _WEIGHT_PRICE_MOMENTUM * momentum
        + _WEIGHT_VOLUME_STRENGTH * vol_strength
        + _WEIGHT_RELATIVE_PERF * relative
    )
    return round(score, 4)


def _select_top_bottom(scores: dict[str, float]) -> tuple[list[str], list[str]]:
    """점수순으로 상위 3개와 하위 2개를 선별한다."""
    sorted_sectors = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top3 = [s[0] for s in sorted_sectors[:3]]
    bottom2 = [s[0] for s in sorted_sectors[-2:]]
    return top3, bottom2


class SectorRotation:
    """7개 섹터 상대강도를 분석하여 선호/회피 섹터를 결정한다."""

    def __init__(self) -> None:
        self._cached_signal: RotationSignal | None = None

    @property
    def cached_signal(self) -> RotationSignal | None:
        """마지막 평가 결과를 반환한다."""
        return self._cached_signal

    async def evaluate(
        self,
        sector_data: dict,
        broker: BrokerClient,
    ) -> RotationSignal:
        """섹터별 상대강도를 분석한다.

        Args:
            sector_data: 섹터별 데이터 (change_pct, volume, avg_volume)
            broker: 브로커 클라이언트 (벤치마크 시세 조회용)
        """
        # 벤치마크 변동률 추출
        benchmark_change = sector_data.get(_BENCHMARK, {}).get("change_pct", 0.0)

        scores: dict[str, float] = {}
        for sector_name, etf_ticker in _SECTOR_ETFS.items():
            data = sector_data.get(etf_ticker, {})
            change = data.get("change_pct", 0.0)
            volume = data.get("volume", 0)
            avg_volume = data.get("avg_volume", 1)

            scores[sector_name] = _compute_sector_score(
                change, volume, avg_volume, benchmark_change,
            )

        top3, bottom2 = _select_top_bottom(scores)

        logger.info("섹터 로테이션: top3=%s bottom2=%s", top3, bottom2)

        signal = RotationSignal(
            top3_prefer=top3,
            bottom2_avoid=bottom2,
            scores=scores,
        )
        self._cached_signal = signal
        return signal
