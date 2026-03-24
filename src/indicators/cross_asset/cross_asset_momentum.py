"""F3 지표 -- 크로스 에셋 모멘텀 (리더맵 17쌍)이다."""
from __future__ import annotations

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.indicators.models import MomentumScore

logger = get_logger(__name__)

# 리더맵: ETF → 기초 주식 매핑 (17쌍)
_LEADER_MAP: dict[str, list[str]] = {
    "SOXL": ["NVDA", "AMD", "TSM"],
    "SOXS": ["NVDA", "AMD", "TSM"],
    "QLD": ["AAPL", "MSFT", "NVDA", "GOOG"],
    "QID": ["AAPL", "MSFT", "NVDA", "GOOG"],
    "SSO": ["AAPL", "MSFT", "AMZN"],
    "SDS": ["AAPL", "MSFT", "AMZN"],
    "NVDL": ["NVDA"],
    "NVDS": ["NVDA"],
    "UWM": ["IWM"],
    "DDM": ["DIA"],
}

_OBI_KEY_PREFIX: str = "order_flow:obi:"
_MOMENTUM_KEY_PREFIX: str = "momentum:score:"
_BULLISH_OBI_THRESHOLD: float = 0.5
_BEARISH_OBI_THRESHOLD: float = -0.5
_ETF_OBI_NEUTRAL: float = 0.1


async def _read_obi(cache: CacheClient, ticker: str) -> float | None:
    """캐시에서 종목의 OBI 값을 조회한다."""
    raw = await cache.read(f"{_OBI_KEY_PREFIX}{ticker}")
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


async def _read_momentum(cache: CacheClient, ticker: str) -> float | None:
    """캐시에서 종목의 모멘텀 점수를 조회한다."""
    raw = await cache.read(f"{_MOMENTUM_KEY_PREFIX}{ticker}")
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


class CrossAssetMomentum:
    """리더맵 기반 크로스 에셋 모멘텀 분석기이다."""

    def __init__(self, cache: CacheClient) -> None:
        """CacheClient 의존성을 주입받는다."""
        self._cache = cache

    async def calculate(self, ticker: str) -> MomentumScore | None:
        """ETF의 크로스 에셋 모멘텀을 분석한다.

        Args:
            ticker: ETF 종목 코드

        Returns:
            MomentumScore 또는 None (리더맵 미등록 / 데이터 미가용 시)
        """
        leaders = _LEADER_MAP.get(ticker, [])
        if not leaders:
            logger.debug("크로스에셋 스킵: %s 리더맵 미등록", ticker)
            return None

        leader_scores = await self._fetch_leader_scores(leaders)

        # 리더 점수가 모두 기본값(0.0)이면 실제 데이터가 없는 것이다
        if all(v == 0.0 for v in leader_scores.values()):
            logger.debug("크로스에셋 스킵: %s 리더 모멘텀 데이터 없음", ticker)
            return None

        etf_obi = await _read_obi(self._cache, ticker)

        alignment = self._calc_alignment(leader_scores)
        divergence = self._calc_divergence(leader_scores, etf_obi)
        bullish_div = self._check_bullish_divergence(leader_scores, etf_obi)
        bearish_div = self._check_bearish_divergence(leader_scores, etf_obi)

        return MomentumScore(
            alignment=round(alignment, 4),
            divergence=round(divergence, 4),
            leader_scores=leader_scores,
            has_bullish_divergence=bullish_div,
            has_bearish_divergence=bearish_div,
        )

    async def _fetch_leader_scores(self, leaders: list[str]) -> dict[str, float]:
        """리더 종목들의 모멘텀 점수를 캐시에서 조회한다."""
        scores: dict[str, float] = {}
        for leader in leaders:
            score = await _read_momentum(self._cache, leader)
            scores[leader] = score if score is not None else 0.0
        return scores

    def _calc_alignment(self, leader_scores: dict[str, float]) -> float:
        """리더 점수들의 방향 정렬도를 계산한다. 모두 같은 방향이면 1.0이다."""
        values = list(leader_scores.values())
        if not values:
            return 0.0
        positive = sum(1 for v in values if v > 0)
        return (positive / len(values)) * 2.0 - 1.0

    def _calc_divergence(
        self, leader_scores: dict[str, float], etf_obi: float | None,
    ) -> float:
        """리더와 ETF 간 괴리도를 계산한다."""
        if etf_obi is None:
            return 0.0
        values = list(leader_scores.values())
        if not values:
            return 0.0
        avg_leader = sum(values) / len(values)
        return avg_leader - etf_obi

    def _check_bullish_divergence(
        self, leader_scores: dict[str, float], etf_obi: float | None,
    ) -> bool:
        """강세 다이버전스를 판별한다. leader OBI > 0.5이고 ETF OBI < 0.1이면 참이다."""
        if etf_obi is None:
            return False
        avg = sum(leader_scores.values()) / max(len(leader_scores), 1)
        return avg > _BULLISH_OBI_THRESHOLD and etf_obi < _ETF_OBI_NEUTRAL

    def _check_bearish_divergence(
        self, leader_scores: dict[str, float], etf_obi: float | None,
    ) -> bool:
        """약세 다이버전스를 판별한다. leader OBI < -0.5이고 ETF OBI > -0.1이면 참이다."""
        if etf_obi is None:
            return False
        avg = sum(leader_scores.values()) / max(len(leader_scores), 1)
        return avg < _BEARISH_OBI_THRESHOLD and etf_obi > -_ETF_OBI_NEUTRAL

    def _neutral_score(self) -> MomentumScore:
        """리더맵이 없는 종목의 중립 점수를 반환한다."""
        return MomentumScore(
            alignment=0.0,
            divergence=0.0,
            leader_scores={},
            has_bullish_divergence=False,
            has_bearish_divergence=False,
        )
