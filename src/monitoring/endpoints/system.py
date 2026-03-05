"""F7.15 SystemEndpoints -- 시스템 상태, 헬스체크 엔드포인트이다.

운영 모니터링용 API를 제공한다. 헬스체크는 인증 없이 접근 가능하다.
시스템 정보는 버전, 가동 시간, 로드된 컴포넌트 수 등을 포함한다.
AI 모드 조회/전환 엔드포인트를 포함한다 (GET/POST /api/system/ai-mode).
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.common.market_clock import get_market_clock
from src.monitoring.schemas.response_models import (
    HealthResponse,
    ServiceHealthItem,
    SystemInfoResponse,
    SystemStatusResponse,
)
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

_VERSION: str = "2.0.0"
_COMPONENT_COUNT: int = 10  # SystemComponents 필드 수

# 서버 시작 시각 -- 모듈 로드 시점으로 기록한다
_start_time: float = time.monotonic()

system_router = APIRouter(prefix="/api/system", tags=["system"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None


class ClockInfoResponse(BaseModel):
    """MarketClock 시간 정보 응답 모델이다."""

    data: dict[str, Any]


class AiModeResponse(BaseModel):
    """AI 백엔드 모드 응답 모델이다."""

    mode: str  # "sdk", "api", "hybrid" 중 하나이다


class AiModeSwitchRequest(BaseModel):
    """AI 백엔드 모드 전환 요청 모델이다."""

    mode: str  # "sdk" 또는 "api"로 전환한다


def set_system_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system, _start_time
    _system = system
    _start_time = time.monotonic()
    _logger.info("SystemEndpoints 의존성 주입 완료")


@system_router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """헬스체크 응답을 반환한다. 로드밸런서/모니터링 도구용이다."""
    return HealthResponse(status="ok", version=_VERSION)


@system_router.get("/status", response_model=SystemStatusResponse)
async def system_status() -> SystemStatusResponse:
    """종합 시스템 상태를 반환한다.

    Claude AI, KIS API, Database(PostgreSQL), Redis의 연결 상태를 실시간 점검한다.
    Flutter SystemStatus.fromJson이 기대하는 형식으로 응답한다.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Claude AI 상태 점검
    claude_item = ServiceHealthItem(ok=False, status="OFFLINE", connected=False)
    try:
        from src.common.ai_gateway import get_ai_client

        client = get_ai_client()
        # ai 클라이언트가 존재하면 정상으로 판단한다
        claude_item = ServiceHealthItem(
            ok=True,
            status="NORMAL",
            connected=True,
        )
    except Exception as exc:
        _logger.debug("Claude AI 상태 점검 실패: %s", exc)

    # KIS API 상태 점검
    kis_item = ServiceHealthItem(ok=False, status="OFFLINE", connected=False)
    if _system is not None:
        try:
            broker = _system.components.broker
            # 브로커 객체가 존재하고 http 클라이언트가 초기화되었으면 정상이다
            has_http = getattr(broker, "_http", None) is not None
            kis_item = ServiceHealthItem(
                ok=has_http,
                status="NORMAL" if has_http else "OFFLINE",
                connected=has_http,
            )
        except Exception as exc:
            _logger.debug("KIS API 상태 점검 실패: %s", exc)

    # Database(PostgreSQL) 상태 점검
    db_item = ServiceHealthItem(ok=False, status="OFFLINE", connected=False)
    if _system is not None:
        try:
            db = _system.components.db
            # SessionFactory가 존재하면 DB 연결이 설정된 것으로 판단한다
            db_item = ServiceHealthItem(
                ok=True,
                status="NORMAL",
                connected=True,
            )
        except Exception as exc:
            _logger.debug("Database 상태 점검 실패: %s", exc)

    # Redis 상태 점검
    redis_item = ServiceHealthItem(ok=False, status="OFFLINE", connected=False)
    if _system is not None:
        try:
            cache = _system.components.cache
            # redis-py의 ping()으로 실제 연결을 확인한다
            redis_client = getattr(cache, "_client", None)
            if redis_client is not None:
                await redis_client.ping()
                redis_item = ServiceHealthItem(
                    ok=True,
                    status="NORMAL",
                    connected=True,
                )
            else:
                # _client가 없으면 cache 객체 존재만으로 판단한다
                redis_item = ServiceHealthItem(
                    ok=True,
                    status="DEGRADED",
                    connected=True,
                )
        except Exception as exc:
            _logger.debug("Redis 상태 점검 실패: %s", exc)

    return SystemStatusResponse(
        claude=claude_item,
        kis=kis_item,
        database=db_item,
        redis=redis_item,
        fallback=False,
        timestamp=now_iso,
    )


@system_router.get("/info", response_model=SystemInfoResponse)
async def system_info() -> SystemInfoResponse:
    """시스템 정보를 반환한다. 버전, Python 버전, 가동 시간 등이다."""
    uptime = time.monotonic() - _start_time
    features = len(_system.features) if _system else 0

    return SystemInfoResponse(
        version=_VERSION,
        python_version=sys.version.split()[0],
        uptime_seconds=round(uptime, 2),
        components_loaded=_COMPONENT_COUNT,
        features_registered=features,
    )


@system_router.get("/clock", response_model=ClockInfoResponse)
async def get_clock_info() -> ClockInfoResponse:
    """MarketClock 시간 정보를 반환한다. 디버깅/대시보드용이다."""
    clock = get_market_clock()
    return ClockInfoResponse(data=clock.get_operating_window_info())


@system_router.get("/ai-mode", response_model=AiModeResponse)
async def get_ai_mode() -> AiModeResponse:
    """현재 AI 백엔드 모드를 반환한다. 인증 불필요."""
    from src.common.ai_gateway import get_ai_client

    try:
        client = get_ai_client()
        return AiModeResponse(mode=client.mode)
    except Exception as exc:
        _logger.error("AI 모드 조회 실패: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"AI 클라이언트 조회 실패: {exc}",
        ) from exc


@system_router.post("/ai-mode", response_model=AiModeResponse)
async def switch_ai_mode(
    body: AiModeSwitchRequest,
    _key: str = Depends(verify_api_key),
) -> AiModeResponse:
    """AI 백엔드 모드를 전환한다. 인증 필수.

    허용 값: "sdk", "api", "hybrid"
    sdk 모드는 API 키 없이도 전환 가능하다.
    api/hybrid 모드 전환 시 API 키가 미설정이면 400을 반환한다.
    """
    from src.common.ai_gateway import get_ai_client
    from src.common.error_handler import AiError

    allowed_modes = {"sdk", "api", "hybrid"}
    if body.mode not in allowed_modes:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않은 모드이다: {body.mode!r}. 허용 값: {sorted(allowed_modes)}",
        )

    try:
        client = get_ai_client()
        client.switch_backend(body.mode)
        _logger.info("AI 백엔드 모드 전환 완료: %s", body.mode)
        return AiModeResponse(mode=client.mode)
    except AiError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:
        _logger.error("AI 모드 전환 실패: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"AI 모드 전환 실패: {exc}",
        ) from exc
