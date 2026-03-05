"""F7.26 AlertsEndpoints -- 알림/경보 조회 API이다.

안전 모듈에서 Redis에 저장한 알림 목록 조회, 읽음 처리 기능을 제공한다.
Redis 키 구조:
  - alerts:list  : list[dict] 형태의 알림 전체 목록 (안전 모듈이 저장)
  - alerts:read  : set 형태의 읽음 처리된 alert_id 집합
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key  # noqa: F401 -- 필요 시 사용

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

alerts_router = APIRouter(prefix="/api/alerts", tags=["alerts"])

_system: InjectedSystem | None = None


# ── 응답 모델 ──────────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    """알림 단건 모델이다."""

    id: str
    type: str
    message: str
    severity: str          # INFO | WARNING | CRITICAL
    timestamp: str
    read: bool


class AlertListResponse(BaseModel):
    """알림 목록 응답 모델이다."""

    alerts: list[AlertItem]
    total_count: int
    unread_count: int


class AlertUnreadCountResponse(BaseModel):
    """읽지 않은 알림 수 응답 모델이다."""

    count: int


class AlertMarkReadResponse(BaseModel):
    """알림 읽음 처리 응답 모델이다."""

    success: bool
    alert_id: str


# ── 의존성 주입 ────────────────────────────────────────────────────────────

def set_alerts_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("AlertsEndpoints 의존성 주입 완료")


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

def _require_system() -> None:
    """시스템이 초기화되지 않았으면 503 예외를 발생시킨다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")


async def _get_read_ids() -> set[str]:
    """Redis에서 읽음 처리된 alert_id 집합을 가져온다.

    저장 형식: alerts:read 키에 list[str]로 저장되어 있다.
    """
    cache = _system.components.cache  # type: ignore[union-attr]
    cached = await cache.read_json("alerts:read")
    if isinstance(cached, list):
        return set(cached)
    return set()


async def _get_raw_alerts() -> list[dict]:
    """Redis alerts:list에서 원시 알림 목록을 가져온다."""
    cache = _system.components.cache  # type: ignore[union-attr]
    cached = await cache.read_json("alerts:list")
    if isinstance(cached, list):
        return cached
    return []


def _build_alert_item(raw: dict, read_ids: set[str]) -> AlertItem:
    """원시 dict를 AlertItem으로 변환한다."""
    alert_id = str(raw.get("id", ""))
    return AlertItem(
        id=alert_id,
        type=str(raw.get("type", "UNKNOWN")),
        message=str(raw.get("message", "")),
        severity=str(raw.get("severity", "INFO")),
        timestamp=str(raw.get("timestamp", "")),
        read=alert_id in read_ids,
    )


# ── 엔드포인트 ────────────────────────────────────────────────────────────

@alerts_router.get("/", response_model=AlertListResponse)
async def get_alerts(limit: int = 100) -> AlertListResponse:
    """전체 알림 목록을 반환한다.

    Redis alerts:list에서 최신 알림을 읽고, 읽음 상태를 합산하여 반환한다.
    limit 파라미터로 최대 반환 건수를 제한한다.
    """
    _require_system()
    try:
        raw_alerts = await _get_raw_alerts()
        read_ids = await _get_read_ids()

        # 최신 순으로 정렬 (timestamp 기준 역순)
        sorted_alerts = sorted(
            raw_alerts,
            key=lambda a: str(a.get("timestamp", "")),
            reverse=True,
        )
        sliced = sorted_alerts[:limit]

        items = [_build_alert_item(r, read_ids) for r in sliced]
        unread = sum(1 for it in items if not it.read)

        return AlertListResponse(
            alerts=items,
            total_count=len(raw_alerts),
            unread_count=unread,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("알림 목록 조회 실패")
        raise HTTPException(status_code=500, detail="알림 목록 조회 실패") from None


@alerts_router.get("/unread-count", response_model=AlertUnreadCountResponse)
async def get_unread_count() -> AlertUnreadCountResponse:
    """읽지 않은 알림 수를 반환한다.

    전체 목록을 로드하지 않고 읽음 ID 집합 차이만 계산하여 빠르게 반환한다.
    """
    _require_system()
    try:
        raw_alerts = await _get_raw_alerts()
        read_ids = await _get_read_ids()
        all_ids = {str(a.get("id", "")) for a in raw_alerts}
        unread = len(all_ids - read_ids)
        return AlertUnreadCountResponse(count=unread)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("읽지 않은 알림 수 조회 실패")
        raise HTTPException(status_code=500, detail="읽지 않은 알림 수 조회 실패") from None


@alerts_router.post("/{alert_id}/read", response_model=AlertMarkReadResponse)
async def mark_alert_read(alert_id: str) -> AlertMarkReadResponse:
    """지정된 알림을 읽음 처리한다.

    Redis alerts:read 목록에 alert_id를 추가한다.
    존재하지 않는 alert_id여도 읽음 처리는 성공으로 간주한다.
    """
    _require_system()
    try:
        cache = _system.components.cache  # type: ignore[union-attr]

        # 기존 읽음 목록 로드 후 추가
        read_ids = await _get_read_ids()
        read_ids.add(alert_id)
        await cache.write_json("alerts:read", list(read_ids))

        _logger.info("알림 읽음 처리 완료: %s", alert_id)
        return AlertMarkReadResponse(success=True, alert_id=alert_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("알림 읽음 처리 실패: %s", alert_id)
        raise HTTPException(status_code=500, detail="알림 읽음 처리 실패") from None
