"""VIX 지수 조회기이다. 캐시 -> FRED API -> 폴백 순서로 VIX를 조회한다.

ContangoDetector와 동일한 market:vix 키를 사용하므로 두 모듈이 공유 캐시를 참조한다.
"""
from __future__ import annotations

from src.common.cache_gateway import CacheClient
from src.common.http_client import AsyncHttpClient
from src.common.logger import get_logger
from src.common.secret_vault import SecretProvider
from src.indicators.misc.fred_fetcher import FRED_API_URL

logger = get_logger(__name__)

_VIX_CACHE_KEY: str = "market:vix"
_VIX3M_CACHE_KEY: str = "market:vix3m"
_VIX_TTL: int = 3600  # 1시간 캐시 TTL이다
_FALLBACK_VIX: float = 19.0  # 모든 소스 실패 시 mild_bull 레짐에 매핑되는 폴백 VIX이다

# FRED API 엔드포인트 — fred_fetcher에서 가져온다
_FRED_URL: str = FRED_API_URL
_FRED_SERIES_ID: str = "VIXCLS"
_FRED_VIX3M_SERIES_ID: str = "VXVCLS"  # CBOE VIX 3-Month (VIX3M)


def _parse_fred_response(body: dict) -> float | None:
    """FRED API 응답에서 최신 유효 VIX 값을 파싱한다.

    observations 리스트를 순회하여 첫 번째 유효 값을 반환한다.
    FRED는 주말/공휴일에 '.'을 반환하므로 해당 항목은 건너뛴다.
    """
    observations: list[dict] = body.get("observations", [])
    if not observations:
        logger.warning("FRED 응답에 observations가 없다")
        return None
    # 최신순 정렬된 observations에서 첫 번째 유효 숫자를 찾는다
    for obs in observations:
        raw_value: str = obs.get("value", "")
        if raw_value == "." or not raw_value:
            continue
        try:
            return float(raw_value)
        except (ValueError, TypeError):
            continue
    logger.warning("FRED 응답에서 유효한 VIX 값을 찾지 못했다 (전체 %d건)", len(observations))
    return None


class VixFetcher:
    """VIX 지수를 조회하는 모듈이다.

    조회 우선순위:
        1. 캐시 (market:vix 키)
        2. FRED VIXCLS API (FRED_API_KEY 또는 DEMO_KEY)
        3. 폴백 값 19.0
    """

    def __init__(
        self,
        cache: CacheClient,
        http: AsyncHttpClient,
        vault: SecretProvider,
    ) -> None:
        """의존성을 주입받는다.

        Args:
            cache: 캐시 클라이언트
            http: 비동기 HTTP 클라이언트
            vault: 시크릿 제공자 (FRED_API_KEY 조회용)
        """
        self._cache = cache
        self._http = http
        # FRED API 키가 없으면 DEMO_KEY를 사용한다 (일일 500회 제한)
        self._fred_api_key: str = (
            vault.get_secret_or_none("FRED_API_KEY") or "DEMO_KEY"
        )

    async def get_vix(self) -> float:
        """현재 VIX 값을 반환한다.

        캐시 히트 시 즉시 반환하고, 캐시 미스 시 FRED API를 호출한다.
        모든 소스 실패 시 폴백 값(19.0)을 반환한다.
        VIX3M은 VIX 캐시 히트 여부와 무관하게 매번 갱신을 시도한다 (콘탱고 정합성).

        Returns:
            VIX 지수 값 (실수)
        """
        # VIX3M도 매번 갱신 시도한다 — VIX가 캐시되어도 VIX3M이 stale하지 않도록 한다
        await self._refresh_vix3m()

        cached = await self._read_from_cache()
        if cached is not None:
            logger.debug("VIX 캐시 히트: %.2f", cached)
            return cached

        fetched = await self._fetch_from_fred()
        if fetched is not None:
            await self._write_to_cache(fetched)
            logger.info("FRED에서 VIX 조회 성공: %.2f", fetched)
            return fetched

        logger.warning("VIX 조회 실패 -- 폴백 값 사용: %.1f", _FALLBACK_VIX)
        return _FALLBACK_VIX

    async def _read_from_cache(self) -> float | None:
        """캐시에서 VIX 값을 읽는다. 없거나 파싱 실패 시 None을 반환한다."""
        try:
            raw = await self._cache.read(_VIX_CACHE_KEY)
            if raw is None:
                return None
            return float(raw)
        except (ValueError, TypeError, Exception) as exc:
            logger.debug("VIX 캐시 읽기 실패 (무시): %s", exc)
            return None

    async def _fetch_from_fred(self) -> float | None:
        """FRED API에서 최신 VIXCLS 값을 조회한다. 실패 시 None을 반환한다."""
        try:
            # limit=5로 최근 5일치를 조회하여 주말/공휴일 '.' 값을 건너뛸 수 있다
            params = {
                "series_id": _FRED_SERIES_ID,
                "api_key": self._fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "5",
            }
            response = await self._http.get(_FRED_URL, params=params)
            if not response.ok:
                logger.warning(
                    "FRED API 응답 오류: status=%d", response.status
                )
                return None
            body: dict = response.json()
            return _parse_fred_response(body)
        except Exception as exc:
            logger.warning("FRED API 호출 실패: %s", exc)
            return None

    async def _write_to_cache(self, vix: float) -> None:
        """VIX 값을 캐시에 TTL과 함께 저장한다. 실패 시 무시한다."""
        try:
            await self._cache.write(_VIX_CACHE_KEY, str(vix), ttl=_VIX_TTL)
            logger.debug("VIX 캐시 저장 완료: %.2f (TTL=%ds)", vix, _VIX_TTL)
        except Exception as exc:
            logger.warning("VIX 캐시 저장 실패 (무시): %s", exc)

    async def _refresh_vix3m(self) -> None:
        """FRED에서 VIX3M(VXVCLS)을 조회하여 캐시에 저장한다.

        ContangoDetector가 market:vix3m 키로 읽어 콘탱고/백워데이션을 판별한다.
        VIX와 동일한 TTL로 캐시하되, 캐시 유무와 무관하게 TTL 만료 시 갱신된다.
        실패해도 VIX 조회에는 영향을 주지 않는다.
        """
        try:
            # VIX3M도 VIX 캐시와 동일한 주기로 갱신한다 — 캐시 존재 시 건너뛴다
            cached = await self._cache.read(_VIX3M_CACHE_KEY)
            if cached is not None:
                return
            # limit=5로 최근 5일치를 조회하여 주말/공휴일 '.' 값을 건너뛸 수 있다
            params = {
                "series_id": _FRED_VIX3M_SERIES_ID,
                "api_key": self._fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "5",
            }
            response = await self._http.get(_FRED_URL, params=params)
            if not response.ok:
                logger.warning("FRED VIX3M 응답 오류: status=%d", response.status)
                return
            body: dict = response.json()
            value = _parse_fred_response(body)
            if value is not None:
                await self._cache.write(_VIX3M_CACHE_KEY, str(value), ttl=_VIX_TTL)
                logger.info("FRED VIX3M 조회 성공: %.2f", value)
        except Exception as exc:
            logger.warning("VIX3M 조회 실패 (무시): %s", exc)
