"""Tier1 운영 복구 -- 코드/설정 변경 없이 프로세스 레벨에서 복구를 시도한다.

토큰 갱신, 캐시 정리, 네트워크 대기 등 즉각적 운영 조치를 수행한다.
"""
from __future__ import annotations

import asyncio
import logging

from src.common.logger import get_logger
from src.healing.error_classifier import ErrorEvent, RepairResult, RepairTier

logger: logging.Logger = get_logger(__name__)

# 네트워크 확인 시 최대 대기 시간(초)과 재시도 간격(초)
_NETWORK_TIMEOUT: int = 60
_NETWORK_RETRY_INTERVAL: int = 5

# 캐시 정리 대상 키 접두어 — trades:today는 절대 삭제하지 않는다
_STALE_CACHE_PREFIXES: tuple[str, ...] = (
    "indicator:", "analysis:", "charts:", "regime:",
)


async def attempt_tier1(system: object, event: ErrorEvent) -> RepairResult:
    """Tier1 운영 복구를 시도한다. 에러 유형에 따라 적절한 복구 함수로 라우팅한다."""
    combined = f"{event.message} {event.detail or ''}".lower()

    # 토큰/인증 관련 에러 → 브로커 토큰 갱신
    if any(k in combined for k in ("token", "인증", "만료")):
        return await _refresh_broker_token(system)

    # 캐시 관련 에러 → 오래된 캐시 정리
    if any(k in combined for k in ("cache", "캐시", "stale")):
        return await _clear_stale_cache(system)

    # 네트워크/연결 관련 에러 → 네트워크 대기
    return await _wait_for_network()


async def _refresh_broker_token(system: object) -> RepairResult:
    """브로커 토큰을 갱신한다. system.components.broker에 접근하여 토큰을 재발급한다."""
    try:
        components = getattr(system, "components", None)
        broker = getattr(components, "broker", None) if components else None
        if broker is None:
            return RepairResult(success=False, tier=RepairTier.TIER1, action="토큰 갱신", detail="broker 접근 불가")

        # 브로커 클라이언트의 토큰 갱신 메서드를 호출한다
        refresh_fn = getattr(broker, "refresh_token", None)
        if refresh_fn is None:
            return RepairResult(success=False, tier=RepairTier.TIER1, action="토큰 갱신", detail="refresh_token 메서드 없음")

        await refresh_fn()
        logger.info("브로커 토큰 갱신 성공")
        return RepairResult(success=True, tier=RepairTier.TIER1, action="토큰 갱신")
    except Exception as exc:
        logger.error("브로커 토큰 갱신 실패: %s", exc)
        return RepairResult(success=False, tier=RepairTier.TIER1, action="토큰 갱신", detail=str(exc))


async def _clear_stale_cache(system: object) -> RepairResult:
    """오래된 분석/지표 캐시를 정리한다. trades:today 등 핵심 키는 보존한다."""
    try:
        components = getattr(system, "components", None)
        cache = getattr(components, "cache", None) if components else None
        if cache is None:
            return RepairResult(success=False, tier=RepairTier.TIER1, action="캐시 정리", detail="cache 접근 불가")

        # 인메모리 캐시의 내부 저장소에서 대상 키를 식별한다
        store: dict[str, str] = getattr(cache, "_store", {})
        keys_to_delete = [k for k in store if any(k.startswith(p) for p in _STALE_CACHE_PREFIXES)]
        for key in keys_to_delete:
            store.pop(key, None)
        logger.info("캐시 정리 완료: %d개 키 삭제", len(keys_to_delete))
        return RepairResult(success=True, tier=RepairTier.TIER1, action="캐시 정리", detail=f"{len(keys_to_delete)}개 키 삭제")
    except Exception as exc:
        logger.error("캐시 정리 실패: %s", exc)
        return RepairResult(success=False, tier=RepairTier.TIER1, action="캐시 정리", detail=str(exc))


async def _wait_for_network() -> RepairResult:
    """네트워크 연결을 확인하고 복구될 때까지 대기한다. 최대 60초간 재시도한다."""
    import httpx

    elapsed = 0
    while elapsed < _NETWORK_TIMEOUT:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("https://httpbin.org/status/200")
                if resp.status_code == 200:
                    logger.info("네트워크 연결 확인 완료 (%d초 소요)", elapsed)
                    return RepairResult(success=True, tier=RepairTier.TIER1, action="네트워크 대기")
        except Exception:
            pass
        await asyncio.sleep(_NETWORK_RETRY_INTERVAL)
        elapsed += _NETWORK_RETRY_INTERVAL

    logger.error("네트워크 복구 실패: %d초 타임아웃", _NETWORK_TIMEOUT)
    return RepairResult(success=False, tier=RepairTier.TIER1, action="네트워크 대기", detail=f"{_NETWORK_TIMEOUT}초 타임아웃")
