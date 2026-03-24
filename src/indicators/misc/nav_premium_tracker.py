"""F3 지표 -- 레버리지 ETF NAV 프리미엄 추적이다."""
from __future__ import annotations

from src.common.broker_gateway import BrokerClient
from src.common.logger import get_logger
from src.indicators.models import NAVPremiumState

logger = get_logger(__name__)

# 10종 레버리지 ETF와 기초 지수/ETF 매핑
_ETF_NAV_MAP: dict[str, str] = {
    "SOXL": "SOXX",
    "SOXS": "SOXX",
    "QLD": "QQQ",
    "QID": "QQQ",
    "SSO": "SPY",
    "SDS": "SPY",
    "UWM": "IWM",
    "DDM": "DIA",
    "NVDL": "NVDA",
    "NVDS": "NVDA",
}

# 레버리지 배율 (인버스는 -2x)
_LEVERAGE: dict[str, float] = {
    "SOXL": 3.0, "SOXS": -3.0,
    "QLD": 2.0, "QID": -2.0,
    "SSO": 2.0, "SDS": -2.0,
    "UWM": 2.0, "DDM": 2.0,
    "NVDL": 2.0, "NVDS": -2.0,
}

# 프리미엄 → 배수 조정 구간
_PREMIUM_HIGH: float = 2.0   # 2% 이상 프리미엄 → 축소
_PREMIUM_LOW: float = -2.0   # -2% 이상 디스카운트 → 확대
_MIN_MULTIPLIER: float = 0.5
_MAX_MULTIPLIER: float = 1.2


def _neutral() -> NAVPremiumState:
    """중립 NAV 프리미엄 상태를 반환한다."""
    return NAVPremiumState(premium_pct=0.0, multiplier_adjustment=1.0)


def _calc_premium_pct(etf_price: float, nav_price: float, leverage: float) -> float:
    """ETF 가격과 추정 NAV 간의 프리미엄 비율(%)을 계산한다.

    NOTE: 레버리지 ETF의 절대 가격은 기초자산 × 레버리지와 관계가 없다.
    (예: SOXL ~$28 vs SOXX*3 ~$660) 절대가 비교는 항상 -90%~-95% 디스카운트를
    반환하여 multiplier가 1.2x로 고정되므로, 정확한 일간 수익률 비교가
    구현될 때까지 중립(0.0)을 반환한다.
    """
    # TODO: 일간 수익률 비교 방식으로 재구현 필요
    # correct_formula: (etf_daily_return / (nav_daily_return * leverage) - 1) * 100
    return 0.0


def _calc_multiplier(premium_pct: float) -> float:
    """프리미엄에 따른 포지션 배수 조정을 계산한다.

    프리미엄 → 0.5x~0.85x 축소, 디스카운트 → 1.1x~1.2x 확대
    """
    if premium_pct >= _PREMIUM_HIGH:
        # 프리미엄 2%~5% → 0.85~0.5x 선형 보간
        ratio = min(1.0, (premium_pct - _PREMIUM_HIGH) / 3.0)
        return round(0.85 - ratio * 0.35, 4)
    if premium_pct <= _PREMIUM_LOW:
        # 디스카운트 -2%~-5% → 1.1~1.2x 선형 보간
        ratio = min(1.0, (abs(premium_pct) - abs(_PREMIUM_LOW)) / 3.0)
        return round(1.1 + ratio * 0.1, 4)
    return 1.0


class NAVPremiumTracker:
    """레버리지 ETF의 NAV 프리미엄을 추적한다."""

    def __init__(self, broker: BrokerClient) -> None:
        """BrokerClient 의존성을 주입받는다."""
        self._broker = broker

    async def track(self, ticker: str) -> NAVPremiumState:
        """ETF의 NAV 프리미엄을 분석한다."""
        nav_ticker = _ETF_NAV_MAP.get(ticker)
        leverage = _LEVERAGE.get(ticker, 2.0)
        if nav_ticker is None:
            return _neutral()
        prices = await self._fetch_prices(ticker, nav_ticker)
        if prices is None:
            return _neutral()
        premium = _calc_premium_pct(prices[0], prices[1], leverage)
        multiplier = _calc_multiplier(premium)
        logger.debug("%s NAV 프리미엄: %.2f%%, 배수: %.4f", ticker, premium, multiplier)
        return NAVPremiumState(premium_pct=round(premium, 4), multiplier_adjustment=multiplier)

    async def _fetch_prices(self, etf: str, nav: str) -> tuple[float, float] | None:
        """ETF와 기초자산 현재가를 조회한다. 실패 시 None이다."""
        try:
            etf_data = await self._broker.get_price(etf)
            nav_data = await self._broker.get_price(nav)
            return etf_data.price, nav_data.price
        except Exception:
            logger.exception("NAV 프리미엄 가격 조회 실패: %s/%s", etf, nav)
            return None
