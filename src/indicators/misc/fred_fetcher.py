"""F3.8 FredFetcher -- FRED 거시지표를 일괄 조회하여 캐시에 저장한다.

EOD 시퀀스, 준비 단계, 수동 크롤링 등에서 공통으로 사용하는
FRED API 호출 로직을 단일 모듈로 추출한 것이다.
"""
from __future__ import annotations

from src.common.logger import get_logger

logger = get_logger(__name__)

# 주요 FRED 시리즈 ID 목록이다
FRED_SERIES: list[str] = [
    "VIXCLS", "DGS10", "DGS2", "DFF",
    "CPIAUCSL", "UNRATE", "DEXKOUS",
    "WALCL", "WTREGEN", "RRPONTSYD",
]

_FRED_URL: str = "https://api.stlouisfed.org/fred/series/observations"
_CACHE_TTL: int = 86400  # 24시간


async def populate_fred_cache(
    http: object,
    vault: object,
    cache: object,
    *,
    ttl: int = _CACHE_TTL,
) -> int:
    """FRED 시리즈를 일괄 조회하여 macro:{시리즈} 캐시에 저장한다.

    Args:
        http: AsyncHttpClient 인스턴스이다.
        vault: SecretProvider 인스턴스이다.
        cache: CacheClient 인스턴스이다.
        ttl: 캐시 TTL(초)이다. 기본값 86400(24시간).

    Returns:
        성공적으로 저장한 시리즈 수이다.
    """
    fred_key: str = vault.get_secret_or_none("FRED_API_KEY") or ""  # type: ignore[union-attr]
    if not fred_key:
        logger.info("[FRED] FRED_API_KEY 미설정 -- 건너뜀")
        return 0

    count = 0
    for sid in FRED_SERIES:
        try:
            params = {
                "series_id": sid,
                "api_key": fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "30",
            }
            resp = await http.get(_FRED_URL, params=params)  # type: ignore[union-attr]
            if not resp.ok:
                logger.warning("[FRED] %s 조회 실패: HTTP %d", sid, resp.status)
                continue
            data = resp.json()
            observations = data.get("observations", [])
            clean: list[dict] = []
            for o in observations:
                raw_val = o.get("value", ".")
                if raw_val == ".":
                    continue
                try:
                    clean.append({"date": o.get("date", ""), "value": float(raw_val)})
                except (ValueError, TypeError):
                    continue
            if clean:
                await cache.write_json(f"macro:{sid}", clean, ttl=ttl)  # type: ignore[union-attr]
                count += 1
        except Exception as exc:
            logger.warning("[FRED] %s 개별 조회 실패: %s", sid, exc)

    logger.info("[FRED] 거시지표 크롤링 완료: %d/%d 시리즈", count, len(FRED_SERIES))
    return count


async def is_fred_cache_populated(cache: object) -> bool:
    """FRED 캐시가 이미 채워져 있는지 확인한다.

    macro:DFF 키가 존재하면 채워진 것으로 판단한다.
    """
    try:
        cached = await cache.read_json("macro:DFF")  # type: ignore[union-attr]
        return cached is not None and isinstance(cached, list) and len(cached) > 0
    except Exception:
        return False
