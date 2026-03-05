"""F3 지표 -- VIX 기간구조 + 레버리지 드래그 감지이다."""
from __future__ import annotations

from src.common.broker_gateway import BrokerClient
from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.indicators.models import ContangoState

logger = get_logger(__name__)

_VIX_CACHE_KEY: str = "market:vix"
_VIX9D_CACHE_KEY: str = "market:vix9d"
_VIX3M_CACHE_KEY: str = "market:vix3m"
_CONTANGO_THRESHOLD: float = 1.05  # VIX3M/VIX > 1.05 = 콘탱고
_BACKWARDATION_THRESHOLD: float = 0.95  # VIX3M/VIX < 0.95 = 백워데이션

# UVXY 대비 VIX 일일 드래그 측정용 티커
_DRAG_ETF: str = "UVXY"
_DRAG_BENCHMARK: str = "VIX"


async def _read_float(cache: CacheClient, key: str) -> float | None:
    """Redis에서 float 값을 읽는다."""
    raw = await cache.read(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _calc_contango_ratio(vix: float, vix3m: float) -> float:
    """VIX3M/VIX 비율로 콘탱고 비율을 계산한다."""
    if vix <= 0:
        return 1.0
    return vix3m / vix


def _classify_signal(ratio: float) -> str:
    """콘탱고/백워데이션/중립을 분류한다."""
    if ratio > _CONTANGO_THRESHOLD:
        return "contango"
    if ratio < _BACKWARDATION_THRESHOLD:
        return "backwardation"
    return "neutral"


def _estimate_drag(ratio: float) -> float:
    """콘탱고 비율로부터 일일 드래그를 추정한다.

    콘탱고가 클수록 레버리지 ETF 롤오버 비용이 증가한다.
    경험적 공식: drag = (ratio - 1.0) * 0.05 (연간 환산)
    """
    if ratio <= 1.0:
        return 0.0
    return round((ratio - 1.0) * 0.05, 6)


class ContangoDetector:
    """VIX 기간구조로 콘탱고/백워데이션 상태를 감지한다."""

    def __init__(self, cache: CacheClient, broker: BrokerClient) -> None:
        """CacheClient와 BrokerClient 의존성을 주입받는다."""
        self._cache = cache
        self._broker = broker

    async def detect(self) -> ContangoState:
        """콘탱고 상태를 분석한다.

        Returns:
            ContangoState (비율, 드래그 추정, 신호)
        """
        vix = await _read_float(self._cache, _VIX_CACHE_KEY)
        vix3m = await _read_float(self._cache, _VIX3M_CACHE_KEY)

        # VIX 데이터 없으면 중립 반환한다
        if vix is None or vix3m is None:
            logger.warning("VIX 데이터 미사용 가능: vix=%s, vix3m=%s", vix, vix3m)
            return ContangoState(contango_ratio=1.0, drag_estimate=0.0, signal="neutral")

        ratio = _calc_contango_ratio(vix, vix3m)
        signal = _classify_signal(ratio)
        drag = _estimate_drag(ratio)

        logger.debug(
            "콘탱고 감지: ratio=%.4f, signal=%s, drag=%.6f",
            ratio, signal, drag,
        )
        return ContangoState(
            contango_ratio=round(ratio, 4),
            drag_estimate=drag,
            signal=signal,
        )
