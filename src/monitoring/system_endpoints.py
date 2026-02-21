"""
시스템 상태 및 API 사용량 API 엔드포인트.

dashboard_endpoints.py에서 분리된 모듈로, 시스템 전체 상태 확인과
API 사용량 통계 엔드포인트를 제공한다.

엔드포인트 목록:
  GET  /system/status  - 시스템 상태 (Claude, KIS, DB, Redis, Fallback, Safety)
  GET  /system/usage   - API 사용량 통계
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select, text

from src.db.connection import get_redis, get_session
from src.db.models import Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}
_startup_time_ref: dict[str, float] = {"value": 0.0}


def set_system_deps(
    safety_checker: Any = None,
    fallback_router: Any = None,
    kis_client: Any = None,
    startup_time: float = 0.0,
) -> None:
    """런타임 의존성을 주입한다.

    Args:
        safety_checker: 안전 체커 인스턴스.
        fallback_router: 폴백 라우터 인스턴스.
        kis_client: KIS API 클라이언트 인스턴스.
        startup_time: 서버 시작 시각 (monotonic).
    """
    _deps.update({
        "safety_checker": safety_checker,
        "fallback_router": fallback_router,
        "kis_client": kis_client,
    })
    _startup_time_ref["value"] = startup_time


def _try_get(name: str) -> Any | None:
    """의존성을 조회한다. 없으면 None을 반환한다."""
    return _deps.get(name)


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

system_router = APIRouter(tags=["system"])


@system_router.get("/system/status")
async def get_system_status() -> dict:
    """시스템 전체 상태를 반환한다: Claude, KIS, DB, Fallback, Quota, Safety."""
    status: dict[str, Any] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    # Database
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        status["database"] = {"ok": True}
    except Exception as exc:
        status["database"] = {"ok": False, "error": str(exc)}

    # Redis
    try:
        redis = get_redis()
        await redis.ping()
        status["redis"] = {"ok": True}
    except Exception as exc:
        status["redis"] = {"ok": False, "error": str(exc)}

    # KIS
    kis = _try_get("kis_client")
    if kis is not None:
        status["kis"] = {"ok": True, "connected": True}
    else:
        status["kis"] = {"ok": False, "connected": False}

    # Fallback
    fb = _try_get("fallback_router")
    if fb is not None:
        status["fallback"] = fb.get_status()
    else:
        status["fallback"] = {"mode": "unknown", "available": False}

    # Claude / Quota
    safety = _try_get("safety_checker")
    if safety is not None:
        safety_status = safety.get_safety_status()
        status["quota"] = safety_status.get("quota", {})
        status["safety"] = safety_status.get("hard_safety", {})
        status["claude"] = {"status": safety_status.get("grade", "UNKNOWN")}
    else:
        status["quota"] = {}
        status["safety"] = {}
        status["claude"] = {"status": "UNKNOWN"}

    return status


@system_router.get("/system/usage")
async def get_usage_stats() -> dict:
    """현재 세션의 API 사용량 통계를 반환한다."""
    trades_today = 0
    try:
        async with get_session() as session:
            today_start = datetime.now(tz=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            stmt = select(func.count(Trade.id)).where(Trade.created_at >= today_start)
            result = await session.execute(stmt)
            trades_today = int(result.scalar_one())
    except Exception as exc:
        logger.warning("Failed to count today's trades: %s", exc)

    fb = _try_get("fallback_router")
    fallback_count = fb.fallback_count if fb else 0

    safety = _try_get("safety_checker")
    claude_calls = 0
    if safety is not None:
        quota_status = safety.get_safety_status().get("quota", {})
        claude_calls = quota_status.get("total_calls", 0)

    return {
        "claude_calls_today": claude_calls,
        "kis_calls_today": 0,
        "trades_today": trades_today,
        "crawl_articles_today": 0,
        "fallback_count": fallback_count,
        "uptime_seconds": round(time.monotonic() - _startup_time_ref["value"], 1),
    }
