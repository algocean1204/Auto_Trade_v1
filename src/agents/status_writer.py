"""에이전트 상태 기록 — AI 에이전트 실행 상태를 캐시에 기록한다."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient

logger = get_logger(__name__)

# 상태 캐시 TTL (1시간) — 에이전트가 비정상 종료해도 자동 만료된다
_STATUS_TTL: int = 3600
# 이력 캐시 TTL (24시간) — 하루치 활동 이력을 보관한다
_HISTORY_TTL: int = 86400
# 이력 최대 보관 건수이다
_HISTORY_MAX_SIZE: int = 100


async def record_agent_start(
    cache: CacheClient,
    agent_id: str,
    task: str,
) -> None:
    """에이전트 실행 시작을 캐시에 기록한다.

    agent:status:{agent_id} 키에 running 상태를 저장한다.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    status = {
        "agent_id": agent_id,
        "status": "running",
        "task": task,
        "started_at": now,
        "updated_at": now,
    }
    try:
        await cache.write_json(
            f"agent:status:{agent_id}", status, ttl=_STATUS_TTL,
        )
    except Exception:
        logger.warning("에이전트 시작 상태 기록 실패: %s", agent_id, exc_info=True)


async def record_agent_complete(
    cache: CacheClient,
    agent_id: str,
    result_summary: str,
    duration_sec: float,
) -> None:
    """에이전트 실행 완료를 캐시에 기록한다.

    status를 idle로 갱신하고 history에 결과를 추가한다.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    status = {
        "agent_id": agent_id,
        "status": "idle",
        "last_task": result_summary,
        "last_result": result_summary,
        "last_duration_sec": round(duration_sec, 2),
        "completed_at": now,
        "updated_at": now,
    }
    history_entry = {
        "task": result_summary,
        "result": result_summary,
        "duration_sec": round(duration_sec, 2),
        "completed_at": now,
    }
    try:
        await cache.write_json(
            f"agent:status:{agent_id}", status, ttl=_STATUS_TTL,
        )
        await cache.atomic_list_append(
            f"agent:history:{agent_id}",
            [history_entry],
            max_size=_HISTORY_MAX_SIZE,
            ttl=_HISTORY_TTL,
        )
    except Exception:
        logger.warning("에이전트 완료 상태 기록 실패: %s", agent_id, exc_info=True)


async def record_agent_error(
    cache: CacheClient,
    agent_id: str,
    error: str,
) -> None:
    """에이전트 실행 오류를 캐시에 기록한다.

    status를 error로 갱신하고 history에 오류를 추가한다.
    """
    now = datetime.now(tz=timezone.utc).isoformat()
    status = {
        "agent_id": agent_id,
        "status": "error",
        "error": error,
        "updated_at": now,
    }
    history_entry = {
        "task": "error",
        "result": error,
        "duration_sec": 0.0,
        "completed_at": now,
    }
    try:
        await cache.write_json(
            f"agent:status:{agent_id}", status, ttl=_STATUS_TTL,
        )
        await cache.atomic_list_append(
            f"agent:history:{agent_id}",
            [history_entry],
            max_size=_HISTORY_MAX_SIZE,
            ttl=_HISTORY_TTL,
        )
    except Exception:
        logger.warning("에이전트 오류 상태 기록 실패: %s", agent_id, exc_info=True)
