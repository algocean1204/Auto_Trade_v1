"""NetLiquidityTracker (F6.20) -- FRED 데이터 기반 순유동성 추적기이다.

TGA(재무부일반계정), WALCL(연준자산), RRPONTSYD(역레포) 데이터로
순유동성을 계산하고 시장 바이어스를 결정한다.
"""

from __future__ import annotations

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.risk.models import LiquidityBias

_logger = get_logger(__name__)

# -- FRED 시리즈 ID --
_SERIES_TGA: str = "WTREGEN"
_SERIES_WALCL: str = "WALCL"
_SERIES_RRPO: str = "RRPONTSYD"

# -- 바이어스 임계값 (10억 USD) --
_INJECT_THRESHOLD: float = 50.0
_DRAIN_THRESHOLD: float = -50.0

# -- 바이어스별 배수 --
_MULTIPLIERS: dict[str, float] = {
    "INJECT": 1.1,
    "DRAIN": 0.8,
    "NEUTRAL": 1.0,
}

# -- Redis 캐시 키 --
_CACHE_KEY: str = "macro:net_liquidity"
_CACHE_TTL: int = 3600  # 1시간


class NetLiquidityTracker:
    """FRED 기반 순유동성 추적기이다.

    Net Liquidity = WALCL - TGA - RRPONTSYD (billions USD)
    직전 값 대비 변화량으로 INJECT/DRAIN/NEUTRAL을 판별한다.
    """

    def __init__(
        self,
        cache: CacheClient,
        fred_api_key: str,
    ) -> None:
        """초기화한다.

        Args:
            cache: Redis 캐시 클라이언트.
            fred_api_key: FRED API 키.
        """
        self._cache = cache
        self._api_key = fred_api_key
        self._prev_nl: float | None = None

    async def update(self) -> LiquidityBias:
        """FRED에서 최신 데이터를 가져와 바이어스를 계산한다."""
        try:
            tga = await self._fetch_latest(_SERIES_TGA)
            walcl = await self._fetch_latest(_SERIES_WALCL)
            rrpo = await self._fetch_latest(_SERIES_RRPO)
        except Exception:
            _logger.exception("FRED 데이터 조회 실패")
            return self._fallback_bias()

        nl_bn = _compute_net_liquidity(walcl, tga, rrpo)
        bias, multiplier = _determine_bias(nl_bn, self._prev_nl)
        self._prev_nl = nl_bn

        await self._cache_result(nl_bn, bias, multiplier)

        _logger.info(
            "NetLiquidity: $%.1fB (%s, %.1fx)",
            nl_bn, bias, multiplier,
        )
        return LiquidityBias(
            net_liquidity_bn=round(nl_bn, 2),
            bias=bias,
            multiplier=multiplier,
        )

    async def get_cached(self) -> LiquidityBias:
        """캐시된 바이어스를 반환한다. 없으면 NEUTRAL이다."""
        data = await self._cache.read_json(_CACHE_KEY)
        if data is None:
            return self._fallback_bias()
        return LiquidityBias(**data)

    def reset(self) -> None:
        """일일 리셋한다."""
        self._prev_nl = None
        _logger.info("NetLiquidityTracker 리셋 완료")

    async def _fetch_latest(self, series_id: str) -> float:
        """FRED API에서 최신 관측값을 가져온다."""
        import httpx

        url = (
            "https://api.stlouisfed.org/fred/series/"
            "observations"
        )
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": "1",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()

        data = resp.json()
        observations = data.get("observations", [])
        if not observations:
            raise ValueError(
                f"FRED {series_id}: 관측값 없음",
            )
        value_str = observations[0].get("value", "0")
        return float(value_str)

    async def _cache_result(
        self, nl_bn: float, bias: str, multiplier: float,
    ) -> None:
        """결과를 Redis에 캐시한다."""
        await self._cache.write_json(
            _CACHE_KEY,
            {
                "net_liquidity_bn": round(nl_bn, 2),
                "bias": bias,
                "multiplier": multiplier,
            },
            ttl=_CACHE_TTL,
        )

    @staticmethod
    def _fallback_bias() -> LiquidityBias:
        """조회 실패 시 NEUTRAL 폴백을 반환한다."""
        return LiquidityBias(
            net_liquidity_bn=0.0,
            bias="NEUTRAL",
            multiplier=1.0,
        )


def _compute_net_liquidity(
    walcl: float, tga: float, rrpo: float,
) -> float:
    """순유동성을 계산한다 (단위: billions USD).

    FRED 데이터는 millions 단위이므로 1000으로 나눈다.
    """
    return (walcl - tga - rrpo) / 1000


def _determine_bias(
    current_nl: float, prev_nl: float | None,
) -> tuple[str, float]:
    """직전 값 대비 변화량으로 바이어스를 결정한다."""
    if prev_nl is None:
        return "NEUTRAL", _MULTIPLIERS["NEUTRAL"]

    delta = current_nl - prev_nl

    if delta >= _INJECT_THRESHOLD:
        return "INJECT", _MULTIPLIERS["INJECT"]
    if delta <= _DRAIN_THRESHOLD:
        return "DRAIN", _MULTIPLIERS["DRAIN"]
    return "NEUTRAL", _MULTIPLIERS["NEUTRAL"]
