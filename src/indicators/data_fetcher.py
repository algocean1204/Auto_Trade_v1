"""
KIS API를 통한 가격 데이터 수집 모듈

- 일일 OHLCV 데이터 (KIS 해외주식 일별시세)
- 장중 가격 데이터 (KIS 미지원 → 일봉으로 대체)
- VIX 지수 조회 (FRED VIXCLS API 활용)
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

import httpx
import pandas as pd

from src.utils.logger import get_logger
from src.utils.ticker_mapping import LEVERAGED_TO_UNDERLYING, UNDERLYING_TO_LEVERAGED

if TYPE_CHECKING:
    from src.executor.kis_client import KISClient

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 거래소 코드 상수
# ---------------------------------------------------------------------------

# 개별 나스닥 주식 (본주)
_NASDAQ_INDIVIDUAL_STOCKS: frozenset[str] = frozenset({
    "AAPL", "TSLA", "NVDA", "GOOGL", "GOOG", "AMZN", "META",
    "MSFT", "AMD", "COIN", "NFLX", "INTC", "QCOM", "MU",
    "AVGO", "ADBE", "PYPL", "SBUX", "COST", "CSCO",
})

# AMEX/NYSE Arca 거래 ETF (대부분의 ETF)
_AMEX_ETFS: frozenset[str] = frozenset({
    # 본주 (Index ETF)
    "SPY", "QQQ", "SOXX", "IWM", "DIA", "XLK", "XLF", "XLE",
    # 레버리지 ETF
    "SSO", "SDS", "QLD", "QID", "USD", "SSG", "UWM", "TWM",
    "DDM", "DXD", "ROM", "REW", "UYG", "SKF", "DIG", "DUG",
    "TSLL", "TSLS", "NVDL", "NVDS", "AAPB", "AAPD",
    "AMZU", "AMZD", "METU", "GGLL", "MSFL", "AMDU", "CONL",
    "SOXL", "SOXS", "TQQQ", "SQQQ", "SPXL", "SPXS",
    "LABU", "LABD", "FNGU", "FNGD", "WEBL", "WEBS",
    "TNA", "TZA", "UPRO", "SPXU", "UDOW", "SDOW",
})

# VIX 조회용 인메모리 캐시
_vix_cache: dict[str, tuple[float, Any]] = {}

# VIX 조회 실패 시 사용하는 기본 폴백값
_VIX_FALLBACK: float = 20.0


class PriceDataFetcher:
    """KIS API를 통한 가격 데이터 수집 클래스."""

    def __init__(self, kis_client: "KISClient") -> None:
        """PriceDataFetcher를 초기화한다.

        Args:
            kis_client: KIS API 클라이언트 인스턴스.
        """
        self._kis_client = kis_client

    # ------------------------------------------------------------------
    # 거래소 코드 감지
    # ------------------------------------------------------------------

    def _get_exchange(self, ticker: str) -> str:
        """티커에 대한 KIS 시세 조회용 거래소 코드를 반환한다.

        우선순위:
        1. 명시적으로 알려진 AMEX/NYSE Arca ETF → "AMS"
        2. 명시적으로 알려진 나스닥 개별주 → "NAS"
        3. 레버리지 ETF 역방향 매핑에 존재하는 티커 → "AMS"
        4. 본주 매핑에 존재하는 티커 (Index ETF 등) → "AMS"
        5. 나머지는 "NAS" 기본값 (개별 나스닥 주식 가정)

        Args:
            ticker: 종목 심볼 (예: "SPY", "SOXL", "AAPL").

        Returns:
            거래소 코드 ("NAS", "NYS", "AMS" 중 하나).
        """
        if ticker in _AMEX_ETFS:
            return "AMS"
        if ticker in _NASDAQ_INDIVIDUAL_STOCKS:
            return "NAS"
        # 레버리지 ETF 역방향 매핑 확인 (SOXL → SOXX 등)
        if ticker in LEVERAGED_TO_UNDERLYING:
            return "AMS"
        # 본주 매핑 확인 (SPY, QQQ, SOXX 등 Index ETF)
        if ticker in UNDERLYING_TO_LEVERAGED:
            return "AMS"
        # 기본값: 나스닥 개별주로 가정
        logger.debug("거래소 코드 불명확, NAS 기본값 사용: ticker=%s", ticker)
        return "NAS"

    # ------------------------------------------------------------------
    # 일일 가격 데이터
    # ------------------------------------------------------------------

    async def get_daily_prices(
        self, ticker: str, days: int = 252
    ) -> pd.DataFrame | None:
        """일일 가격 데이터(OHLCV)를 KIS API로 조회한다.

        KIS 해외주식 일별시세 API는 최대 100개 캔들을 반환하므로,
        100일을 초과하는 요청도 100개로 제한된다.

        Args:
            ticker: 종목 심볼 (예: "SPY", "SOXX").
            days: 조회할 과거 거래일 수. 기본값 252 (약 1년).
                  KIS 제한으로 실제 반환은 최대 100개이다.

        Returns:
            OHLCV 컬럼을 포함한 DataFrame (DatetimeIndex).
            컬럼: Open, High, Low, Close, Volume
            오류 발생 시 None을 반환한다 (빈 DataFrame이 아님 — 호출자가 에러/데이터 없음을 구분 가능).
        """
        logger.info("일일 가격 데이터 조회 시작: ticker=%s, days=%d", ticker, days)

        exchange = self._get_exchange(ticker)
        # KIS API 최대 100개 제한
        count = min(days, 100)

        try:
            raw_data = await self._kis_client.get_overseas_daily_price(
                ticker=ticker,
                exchange=exchange,
                period="D",
                count=count,
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "KIS 일별 시세 조회 타임아웃: ticker=%s, exchange=%s",
                ticker, exchange, exc_info=True,
            )
            return None
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KIS 일별 시세 HTTP 오류: ticker=%s, exchange=%s, status=%d",
                ticker, exchange, exc.response.status_code, exc_info=True,
            )
            return None
        except Exception as exc:
            logger.error(
                "KIS 일별 시세 조회 실패: ticker=%s, exchange=%s, error=%s",
                ticker, exchange, exc, exc_info=True,
            )
            return None

        if not raw_data:
            logger.warning("KIS 일별 시세 데이터 없음: ticker=%s", ticker)
            return None

        try:
            # KIS는 최신순 반환 → 오름차순으로 정렬
            records = []
            for item in reversed(raw_data):
                date_str = item.get("date", "")
                if not date_str:
                    continue
                records.append({
                    "Date": pd.to_datetime(date_str, format="%Y%m%d"),
                    "Open": float(item.get("open", 0.0)),
                    "High": float(item.get("high", 0.0)),
                    "Low": float(item.get("low", 0.0)),
                    "Close": float(item.get("close", 0.0)),
                    "Volume": int(item.get("volume", 0)),
                })

            if not records:
                logger.warning("파싱 가능한 데이터 없음: ticker=%s", ticker)
                return None

            df = pd.DataFrame(records)
            df = df.set_index("Date")
            df.index = pd.DatetimeIndex(df.index)
            df = df.sort_index()

        except Exception as exc:
            logger.error(
                "KIS 일별 시세 DataFrame 변환 실패: ticker=%s, error=%s",
                ticker, exc, exc_info=True,
            )
            return None

        logger.info(
            "일일 가격 데이터 조회 완료: ticker=%s, exchange=%s, rows=%d",
            ticker, exchange, len(df)
        )
        return df

    # ------------------------------------------------------------------
    # 장중 가격 데이터 (KIS 미지원 → 일봉 대체)
    # ------------------------------------------------------------------

    async def get_intraday_prices(
        self, ticker: str, interval: str = "15m"
    ) -> pd.DataFrame:
        """장중 가격 데이터를 조회한다.

        KIS API는 분봉 데이터를 지원하지 않으므로, 일봉 데이터로 대체한다.
        이 메서드는 현재 코드베이스에서 직접 호출되지 않으며,
        하위 호환성 유지 목적으로 보존된다.

        Args:
            ticker: 종목 심볼.
            interval: 봉 간격 (무시됨, 일봉으로 대체).

        Returns:
            일봉 OHLCV DataFrame (interval 파라미터 무시).
        """
        logger.warning(
            "get_intraday_prices() 호출: KIS는 분봉 미지원, 일봉으로 대체 (ticker=%s, interval=%s)",
            ticker, interval
        )
        return await self.get_daily_prices(ticker, days=30)

    # ------------------------------------------------------------------
    # VIX 조회 (FRED VIXCLS)
    # ------------------------------------------------------------------

    async def get_vix(self) -> float:
        """현재 VIX 지수를 FRED VIXCLS API로 조회한다.

        VIX (^VIX)는 CBOE 지수로 KIS API를 통해 조회할 수 없으므로
        FRED REST API의 VIXCLS 시계열을 사용한다.
        60초 인메모리 캐시를 적용한다.

        Returns:
            VIX 현재값. FRED 조회 실패 시 기본값 20.0을 반환한다.
        """
        logger.info("VIX 지수 조회 시작 (FRED VIXCLS)")

        cache_key = "vix_data_fetcher"
        now = time.time()
        if cache_key in _vix_cache:
            ts, cached_value = _vix_cache[cache_key]
            if now - ts < 60:
                logger.debug("VIX 캐시 히트: %.2f", cached_value)
                return float(cached_value)

        api_key = os.getenv("FRED_API_KEY", "")
        vix_value: float | None = None

        if api_key:
            try:
                url = "https://api.stlouisfed.org/fred/series/observations"
                params = {
                    "series_id": "VIXCLS",
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                }
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()

                observations = data.get("observations", [])
                if observations:
                    raw = observations[0].get("value", "").strip()
                    if raw and raw != ".":
                        parsed = float(raw)
                        if parsed > 0:
                            vix_value = parsed
            except httpx.TimeoutException as exc:
                logger.warning(
                    "FRED VIXCLS 조회 타임아웃, 기본값 %.1f 사용: %s",
                    _VIX_FALLBACK, exc,
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "FRED VIXCLS HTTP 오류 (status=%d), 기본값 %.1f 사용",
                    exc.response.status_code, _VIX_FALLBACK,
                )
            except Exception as exc:
                logger.warning(
                    "FRED VIXCLS 조회 실패, 기본값 %.1f 사용: %s",
                    _VIX_FALLBACK, exc,
                )
        else:
            logger.warning("FRED_API_KEY 미설정, VIX 기본값 %.1f 사용", _VIX_FALLBACK)

        if vix_value is None or vix_value <= 0:
            logger.warning("VIX 유효값 없음, 기본값 %.1f 적용", _VIX_FALLBACK)
            vix_value = _VIX_FALLBACK

        _vix_cache[cache_key] = (now, vix_value)
        logger.info("VIX 지수 조회 완료: %.2f", vix_value)
        return vix_value

    # ------------------------------------------------------------------
    # 현재가 조회
    # ------------------------------------------------------------------

    async def fetch_current_price(self, ticker: str) -> dict:
        """해외주식 현재가를 KIS API로 조회한다.

        main.py 트레이딩 루프에서 SPY 일중 변동률 조회 등에 사용한다.

        Args:
            ticker: 종목 심볼 (예: "SPY", "SOXL").

        Returns:
            KISClient.get_overseas_price() 반환 딕셔너리::

                {
                    "ticker": str,
                    "current_price": float,
                    "open_price": float,
                    "high_price": float,
                    "low_price": float,
                    "prev_close": float,
                    "volume": int,
                    "change_pct": float,
                    "trade_time": str,
                }

            오류 발생 시 빈 딕셔너리를 반환한다.

        Raises:
            Exception: KIS API 호출 오류는 로깅 후 빈 딕셔너리로 처리된다.
        """
        logger.info("현재가 조회 시작: ticker=%s", ticker)
        exchange = self._get_exchange(ticker)

        try:
            result = await self._kis_client.get_overseas_price(
                ticker=ticker,
                exchange=exchange,
            )
            logger.info(
                "현재가 조회 완료: ticker=%s, price=%.2f",
                ticker, result.get("current_price", 0.0)
            )
            return result
        except httpx.TimeoutException as exc:
            logger.error(
                "KIS 현재가 조회 타임아웃: ticker=%s, exchange=%s",
                ticker, exchange, exc_info=True,
            )
            return {}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "KIS 현재가 HTTP 오류: ticker=%s, exchange=%s, status=%d",
                ticker, exchange, exc.response.status_code, exc_info=True,
            )
            return {}
        except Exception as exc:
            logger.error(
                "KIS 현재가 조회 실패: ticker=%s, exchange=%s, error=%s",
                ticker, exchange, exc, exc_info=True,
            )
            return {}
