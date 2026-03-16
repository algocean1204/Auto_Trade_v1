"""F3 지표 -- IndicatorBundle 조립기이다.

가용한 지표 모듈에서 데이터를 수집하여 IndicatorBundle 9개 필드를 모두 조립한다.
개별 지표 실패 시 해당 필드를 None으로 유지하고 나머지 지표는 계속 계산한다.

조립 대상 필드:
  technical      -- 일봉 기반 RSI/MACD/볼린저/ATR/EMA/SMA
  intraday       -- 5분봉 기반 VWAP/장중RSI/볼린저
  momentum       -- 캐시 기반 크로스 에셋 모멘텀
  volume_profile -- 일봉 기반 POC + Value Area 70%
  whale          -- 캐시 기반 블록/아이스버그 고래 감지
  order_flow     -- 캐시 기반 OBI/CVD/VPIN/체결강도
  contango       -- 캐시 VIX 기간구조 콘탱고 감지
  nav_premium    -- 브로커 실시간 NAV 프리미엄 추적
  decay          -- 일봉 기반 레버리지 변동성 드래그 정량화
"""
from __future__ import annotations

from src.common.broker_gateway import BrokerClient
from src.common.cache_gateway import CacheClient
from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.common.ticker_registry import TickerRegistry
from src.indicators.models import (
    ContangoState,
    DecayScore,
    IndicatorBundle,
    IntradayIndicators,
    MomentumScore,
    NAVPremiumState,
    OrderFlowSnapshot,
    TechnicalIndicators,
    VolumeProfileResult,
    WhaleSignal,
)

logger = get_logger(__name__)

_DEFAULT_CANDLE_DAYS: int = 100
_DEFAULT_EXCHANGE: str = "NAS"
# 5분봉 장중 지표에 필요한 최소 캔들 수이다
_MIN_INTRADAY_CANDLES: int = 5


async def _fetch_technical(
    broker: BrokerClient, ticker: str, exchange: str,
) -> TechnicalIndicators | None:
    """일봉 캔들을 조회하여 기술적 지표를 계산한다. 실패 시 None을 반환한다."""
    try:
        from src.indicators.price.price_data_fetcher import PriceDataFetcher
        from src.indicators.technical.technical_calculator import TechnicalCalculator

        candles = await PriceDataFetcher(broker).fetch(ticker, days=_DEFAULT_CANDLE_DAYS, exchange=exchange)
        if not candles:
            logger.warning("기술적 지표 계산 불가: %s 캔들 없음", ticker)
            return None
        return TechnicalCalculator().calculate(candles)
    except Exception as exc:
        logger.warning("기술적 지표 실패 (%s): %s", ticker, exc)
        return None


async def _fetch_intraday(
    http: AsyncHttpClient | None,
    finnhub_key: str | None,
    ticker: str,
) -> IntradayIndicators | None:
    """Finnhub 5분봉을 조회하여 장중 지표를 계산한다.

    http 클라이언트 또는 Finnhub API 키가 없으면 None을 반환한다.
    """
    try:
        # http 또는 API 키가 없으면 장중 지표를 계산할 수 없다
        if http is None or not finnhub_key:
            logger.debug("장중 지표 스킵 (%s): http=%s, key=%s", ticker, http, bool(finnhub_key))
            return None

        from src.indicators.price.intraday_fetcher import IntradayFetcher
        from src.indicators.technical.intraday_calculator import IntradayCalculator

        candles = await IntradayFetcher(http, finnhub_key).fetch(ticker)
        if len(candles) < _MIN_INTRADAY_CANDLES:
            logger.debug("장중 지표 계산 불가: %s 5분봉 부족 (%d개)", ticker, len(candles))
            return None
        return IntradayCalculator().calculate(candles)
    except Exception as exc:
        logger.warning("장중 지표 실패 (%s): %s", ticker, exc)
        return None


async def _fetch_order_flow(cache: CacheClient, ticker: str) -> OrderFlowSnapshot | None:
    """캐시에서 주문 흐름 스냅샷을 조회한다. 실패 시 None을 반환한다."""
    try:
        from src.indicators.misc.order_flow_aggregator import OrderFlowAggregator

        return await OrderFlowAggregator(cache).aggregate(ticker)
    except Exception as exc:
        logger.warning("주문 흐름 조회 실패 (%s): %s", ticker, exc)
        return None


async def _fetch_momentum(cache: CacheClient, ticker: str) -> MomentumScore | None:
    """캐시에서 크로스 에셋 모멘텀을 계산한다. 실패 시 None을 반환한다."""
    try:
        from src.indicators.cross_asset.cross_asset_momentum import CrossAssetMomentum

        return await CrossAssetMomentum(cache).calculate(ticker)
    except Exception as exc:
        logger.warning("크로스 에셋 모멘텀 실패 (%s): %s", ticker, exc)
        return None


async def _fetch_volume_profile(
    broker: BrokerClient, ticker: str, exchange: str,
) -> VolumeProfileResult | None:
    """일봉 캔들과 현재가로 볼륨 프로파일(POC + Value Area 70%)을 계산한다.

    현재가 조회 실패 시 최근 캔들 종가를 fallback으로 사용한다.
    """
    try:
        from src.indicators.price.price_data_fetcher import PriceDataFetcher
        from src.indicators.volume_profile.volume_profile import VolumeProfile

        candles = await PriceDataFetcher(broker).fetch(ticker, days=_DEFAULT_CANDLE_DAYS, exchange=exchange)
        if not candles:
            logger.debug("볼륨 프로파일 스킵: %s 캔들 없음", ticker)
            return None

        # 현재가를 브로커에서 조회한다. 실패 시 최근 캔들 종가를 사용한다
        try:
            price_data = await broker.get_price(ticker, exchange=exchange)
            current_price = price_data.price
        except Exception:
            current_price = candles[-1].close
            logger.debug("볼륨 프로파일 현재가 폴백: %s = %.4f (최근 종가)", ticker, current_price)

        return VolumeProfile().calculate(candles, current_price)
    except Exception as exc:
        logger.warning("볼륨 프로파일 실패 (%s): %s", ticker, exc)
        return None


async def _fetch_whale(cache: CacheClient, ticker: str) -> WhaleSignal | None:
    """캐시 체결 데이터에서 고래 활동(블록/아이스버그)을 감지한다. 실패 시 None을 반환한다."""
    try:
        from src.indicators.whale.whale_tracker import WhaleTracker

        return await WhaleTracker(cache).track(ticker)
    except Exception as exc:
        logger.warning("고래 감지 실패 (%s): %s", ticker, exc)
        return None


async def _fetch_contango(cache: CacheClient, broker: BrokerClient) -> ContangoState | None:
    """캐시 VIX 기간구조로 콘탱고/백워데이션 상태를 감지한다. 실패 시 None을 반환한다.

    종목별 계산이 아닌 시장 전체 상태를 반환하므로 ticker 인수가 없다.
    """
    try:
        from src.indicators.misc.contango_detector import ContangoDetector

        return await ContangoDetector(cache, broker).detect()
    except Exception as exc:
        logger.warning("콘탱고 감지 실패: %s", exc)
        return None


async def _fetch_nav_premium(broker: BrokerClient, ticker: str) -> NAVPremiumState | None:
    """ETF 현재가와 기초자산 가격으로 NAV 프리미엄을 추적한다.

    _ETF_NAV_MAP에 없는 티커(비레버리지 ETF 등)는 중립 상태를 반환한다.
    """
    try:
        from src.indicators.misc.nav_premium_tracker import NAVPremiumTracker

        return await NAVPremiumTracker(broker).track(ticker)
    except Exception as exc:
        logger.warning("NAV 프리미엄 실패 (%s): %s", ticker, exc)
        return None


async def _fetch_decay(
    broker: BrokerClient,
    ticker: str,
    exchange: str,
    registry: TickerRegistry,
) -> DecayScore | None:
    """일봉 캔들로 레버리지 ETF 변동성 드래그(디케이)를 정량화한다.

    레지스트리에서 레버리지 배수를 읽어 절댓값을 사용한다.
    레지스트리 미등록 티커는 기본 2.0배로 계산한다.
    """
    try:
        from src.indicators.misc.leverage_decay import LeverageDecay
        from src.indicators.price.price_data_fetcher import PriceDataFetcher

        candles = await PriceDataFetcher(broker).fetch(ticker, days=_DEFAULT_CANDLE_DAYS, exchange=exchange)
        if not candles:
            logger.debug("디케이 스킵: %s 캔들 없음", ticker)
            return None

        # 레지스트리에서 레버리지 배수를 조회한다. 미등록 시 기본 2.0이다
        leverage = 2.0
        if registry.has_ticker(ticker):
            # get_all()에서 해당 티커 메타를 찾아 레버리지 절댓값을 추출한다
            matched = next((m for m in registry.get_all() if m.ticker == ticker), None)
            if matched is not None:
                leverage = abs(matched.leverage)

        return LeverageDecay().calculate(candles, leverage)
    except Exception as exc:
        logger.warning("디케이 계산 실패 (%s): %s", ticker, exc)
        return None


class IndicatorBundleBuilder:
    """가용 데이터로 IndicatorBundle 9개 필드를 모두 조립한다.

    각 지표 계산은 독립 try/except로 격리되어 있으므로
    특정 지표 실패가 다른 지표 계산을 막지 않는다.
    """

    def __init__(
        self,
        broker: BrokerClient,
        cache: CacheClient,
        registry: TickerRegistry,
        http: AsyncHttpClient | None = None,
        finnhub_api_key: str | None = None,
    ) -> None:
        """의존성을 주입받는다.

        Args:
            broker: KIS 브로커 클라이언트 (일봉/현재가/NAV 조회용)
            cache: 캐시 클라이언트 (주문흐름/고래/모멘텀/VIX 조회용)
            registry: 티커 메타 레지스트리 (거래소 코드/레버리지 조회용)
            http: Finnhub HTTP 클라이언트 (5분봉 조회용, None이면 장중 지표 스킵)
            finnhub_api_key: Finnhub API 키 (None이면 장중 지표 스킵)
        """
        self._broker = broker
        self._cache = cache
        self._registry = registry
        self._http = http
        self._finnhub_key = finnhub_api_key

    async def build(self, ticker: str) -> IndicatorBundle:
        """종목에 대한 IndicatorBundle 9개 필드를 모두 조립한다.

        조립 순서:
          1. technical      -- 일봉 → RSI/MACD/볼린저/ATR/EMA/SMA
          2. intraday       -- 5분봉 → VWAP/장중RSI/볼린저
          3. momentum       -- 캐시 → 크로스 에셋 모멘텀
          4. volume_profile -- 일봉 → POC/Value Area
          5. whale          -- 캐시 → 블록/아이스버그 고래 감지
          6. order_flow     -- 캐시 → OBI/CVD/VPIN/체결강도
          7. contango       -- 캐시 VIX → 콘탱고/백워데이션
          8. nav_premium    -- 브로커 실시간가 → NAV 프리미엄
          9. decay          -- 일봉 → 레버리지 변동성 드래그

        개별 실패 시 해당 필드 None 유지, 나머지 계속 계산한다.
        """
        exchange = self._resolve_exchange(ticker)

        technical = await _fetch_technical(self._broker, ticker, exchange)
        intraday = await _fetch_intraday(self._http, self._finnhub_key, ticker)
        momentum = await _fetch_momentum(self._cache, ticker)
        volume_profile = await _fetch_volume_profile(self._broker, ticker, exchange)
        whale = await _fetch_whale(self._cache, ticker)
        order_flow = await _fetch_order_flow(self._cache, ticker)
        contango = await _fetch_contango(self._cache, self._broker)
        nav_premium = await _fetch_nav_premium(self._broker, ticker)
        decay = await _fetch_decay(self._broker, ticker, exchange, self._registry)

        _log_bundle_summary(ticker, technical, intraday, momentum, volume_profile,
                            whale, order_flow, contango, nav_premium, decay)

        return IndicatorBundle(
            technical=technical,
            intraday=intraday,
            momentum=momentum,
            volume_profile=volume_profile,
            whale=whale,
            order_flow=order_flow,
            contango=contango,
            nav_premium=nav_premium,
            decay=decay,
        )

    def _resolve_exchange(self, ticker: str) -> str:
        """티커의 거래소 코드를 반환한다. 미등록 시 기본값 NAS이다."""
        if self._registry.has_ticker(ticker):
            return self._registry.get_exchange_code(ticker)
        return _DEFAULT_EXCHANGE


def _log_bundle_summary(
    ticker: str,
    technical: TechnicalIndicators | None,
    intraday: IntradayIndicators | None,
    momentum: MomentumScore | None,
    volume_profile: VolumeProfileResult | None,
    whale: WhaleSignal | None,
    order_flow: OrderFlowSnapshot | None,
    contango: ContangoState | None,
    nav_premium: NAVPremiumState | None,
    decay: DecayScore | None,
) -> None:
    """각 필드의 None 여부를 DEBUG 로그로 출력한다.

    어떤 지표가 누락되었는지 운영 중 빠르게 파악하기 위한 목적이다.
    """
    fields = {
        "technical": technical,
        "intraday": intraday,
        "momentum": momentum,
        "volume_profile": volume_profile,
        "whale": whale,
        "order_flow": order_flow,
        "contango": contango,
        "nav_premium": nav_premium,
        "decay": decay,
    }
    # None인 필드만 추려서 로그에 표시한다
    missing = [name for name, val in fields.items() if val is None]
    built = len(fields) - len(missing)
    if missing:
        logger.debug(
            "%s IndicatorBundle 조립 완료: %d/9 성공, 누락=%s",
            ticker, built, missing,
        )
    else:
        logger.debug("%s IndicatorBundle 조립 완료: 9/9 전체 성공", ticker)
