"""F3 지표 -- Finnhub 5분봉 장중 데이터 조회이다."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.indicators.models import Candle5m

logger = get_logger(__name__)

_FINNHUB_BASE: str = "https://finnhub.io/api/v1"
_RESOLUTION: str = "5"  # 5분봉
_SECONDS_PER_DAY: int = 86400


def _parse_finnhub_candles(data: dict) -> list[Candle5m]:
    """Finnhub 응답을 Candle5m 리스트로 변환한다."""
    status = data.get("s", "")
    if status != "ok":
        return []
    timestamps = data.get("t", [])
    opens = data.get("o", [])
    highs = data.get("h", [])
    lows = data.get("l", [])
    closes = data.get("c", [])
    volumes = data.get("v", [])
    candles: list[Candle5m] = []
    for i in range(len(timestamps)):
        candles.append(Candle5m(
            timestamp=datetime.fromtimestamp(timestamps[i], tz=timezone.utc),
            open=float(opens[i]),
            high=float(highs[i]),
            low=float(lows[i]),
            close=float(closes[i]),
            volume=int(volumes[i]),
        ))
    return candles


class IntradayFetcher:
    """Finnhub API에서 5분봉 장중 데이터를 조회한다."""

    def __init__(self, http: AsyncHttpClient, finnhub_api_key: str) -> None:
        """HTTP 클라이언트와 API 키를 주입받는다."""
        self._http = http
        self._api_key = finnhub_api_key

    async def fetch(self, ticker: str) -> list[Candle5m]:
        """당일 5분봉 데이터를 조회하여 시간 오름차순으로 반환한다."""
        params = self._build_params(ticker)
        data = await self._request(ticker, params)
        if data is None:
            return []
        candles = _parse_finnhub_candles(data)
        logger.debug("%s 5분봉 %d개 조회 완료", ticker, len(candles))
        return candles

    def _build_params(self, ticker: str) -> dict[str, str]:
        """Finnhub API 요청 파라미터를 생성한다."""
        now = int(time.time())
        return {
            "symbol": ticker, "resolution": _RESOLUTION,
            "from": str(now - _SECONDS_PER_DAY), "to": str(now), "token": self._api_key,
        }

    async def _request(self, ticker: str, params: dict[str, str]) -> dict | None:
        """Finnhub API를 호출하고 JSON 응답을 반환한다. 실패 시 None이다."""
        try:
            resp = await self._http.get(f"{_FINNHUB_BASE}/stock/candle", params=params)
            if not resp.ok:
                logger.warning("Finnhub 5분봉 조회 실패: %s status=%d", ticker, resp.status)
                return None
            return resp.json()
        except Exception:
            logger.exception("Finnhub 5분봉 네트워크 오류: %s", ticker)
            return None
