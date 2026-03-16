"""F7.27 CrawlControlEndpoints -- 뉴스 크롤링 수동 제어 API이다.

수동 크롤링 시작과 진행 상태 조회를 제공한다.
크롤링 태스크는 즉시 반환하고 백그라운드에서 비동기 실행한다.

캐시 키 구조:
  - crawl:task:{task_id} : 크롤링 태스크 진행 상태 dict
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

crawl_control_router = APIRouter(prefix="/api/crawl", tags=["crawl-control"])

_system: InjectedSystem | None = None

# 동시 크롤링 방지 락 — 중복 수동 크롤이 crawl_engine을 동시 호출하는 것을 방지한다
_crawl_lock = asyncio.Lock()


# ── 응답 모델 ──────────────────────────────────────────────────────────────

class CrawlStartResponse(BaseModel):
    """크롤링 시작 응답 모델이다."""

    task_id: str
    status: str
    started_at: str


class CrawlStatusResponse(BaseModel):
    """크롤링 진행 상태 응답 모델이다."""

    task_id: str
    status: str                    # pending | running | completed | failed
    crawled: int
    new_articles: int
    errors: list[str]
    completed_at: str | None


# ── 의존성 주입 ────────────────────────────────────────────────────────────

def set_crawl_control_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("CrawlControlEndpoints 의존성 주입 완료")


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

def _require_system() -> None:
    """시스템이 초기화되지 않았으면 503 예외를 발생시킨다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")


def _now_iso() -> str:
    """현재 UTC 시각을 ISO 8601 문자열로 반환한다."""
    return datetime.now(tz=timezone.utc).isoformat()


def _default_status(task_id: str) -> dict:
    """기본 크롤링 상태 딕셔너리를 생성한다."""
    return {
        "task_id": task_id,
        "status": "pending",
        "crawled": 0,
        "new_articles": 0,
        "errors": [],
        "completed_at": None,
    }


async def _run_crawl_task(task_id: str) -> None:
    """백그라운드 크롤링 태스크 본체이다.

    crawl_scheduler에서 스케줄을 생성하고 crawl_engine.run(schedule)을 호출한다.
    진행 상태는 캐시 crawl:task:{task_id} 키에 실시간 기록한다.
    _crawl_lock으로 동시 실행을 방지한다.
    """
    cache = _system.components.cache  # type: ignore[union-attr]
    cache_key = f"crawl:task:{task_id}"
    status: dict = _default_status(task_id)
    status["status"] = "running"

    async with _crawl_lock:
        try:
            await cache.write_json(cache_key, status)

            # crawl_engine 피처 획득 (없으면 스킵)
            crawl_engine = _system.features.get("crawl_engine")  # type: ignore[union-attr]
            if crawl_engine is None:
                status["status"] = "failed"
                status["errors"].append("크롤 엔진이 등록되지 않았다")
                status["completed_at"] = _now_iso()
                await cache.write_json(cache_key, status)
                return

            # crawl_scheduler 피처에서 스케줄을 생성한다
            crawl_scheduler = _system.features.get("crawl_scheduler")  # type: ignore[union-attr]
            if crawl_scheduler is None:
                status["status"] = "failed"
                status["errors"].append("크롤 스케줄러가 등록되지 않았다")
                status["completed_at"] = _now_iso()
                await cache.write_json(cache_key, status)
                return

            schedule = crawl_scheduler.build_schedule()
            result = await crawl_engine.run(schedule)

            # CrawlResult 파싱 (total, new_count, failed_sources, duration_seconds)
            status["crawled"] = result.total
            status["new_articles"] = result.new_count
            status["errors"] = list(result.failed_sources)

            status["status"] = "completed"
            status["completed_at"] = _now_iso()
            _logger.info(
                "수동 크롤링 완료 [%s]: crawled=%d new=%d",
                task_id,
                status["crawled"],
                status["new_articles"],
            )

        except Exception as exc:
            _logger.exception("수동 크롤링 태스크 오류 [%s]", task_id)
            status["status"] = "failed"
            status["errors"].append(str(exc))
            status["completed_at"] = _now_iso()

        finally:
            # 결과를 캐시에 최종 기록한다. 1시간 후 자동 만료.
            await cache.write_json(cache_key, status)


# ── 엔드포인트 ────────────────────────────────────────────────────────────

@crawl_control_router.post("/manual", response_model=CrawlStartResponse)
async def start_manual_crawl(
    _key: str = Depends(verify_api_key),
) -> CrawlStartResponse:
    """수동 뉴스 크롤링을 시작한다. 인증 필수.

    백그라운드 asyncio 태스크로 즉시 실행하고 task_id를 반환한다.
    상태는 GET /api/crawl/status/{task_id} 로 조회한다.
    """
    _require_system()
    if _crawl_lock.locked():
        raise HTTPException(status_code=409, detail="수동 크롤링이 이미 실행 중이다")
    try:
        task_id = str(uuid.uuid4())
        started_at = _now_iso()

        # 초기 상태를 캐시에 미리 저장한다
        cache = _system.components.cache  # type: ignore[union-attr]
        await cache.write_json(f"crawl:task:{task_id}", _default_status(task_id))

        # 백그라운드 태스크 시작
        asyncio.create_task(_run_crawl_task(task_id))

        _logger.info("수동 크롤링 태스크 생성: %s", task_id)
        return CrawlStartResponse(
            task_id=task_id,
            status="pending",
            started_at=started_at,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("수동 크롤링 시작 실패")
        raise HTTPException(status_code=500, detail="크롤링 시작 실패") from None


@crawl_control_router.get("/status/{task_id}", response_model=CrawlStatusResponse)
async def get_crawl_status(task_id: str) -> CrawlStatusResponse:
    """크롤링 태스크의 진행 상태를 반환한다.

    캐시 crawl:task:{task_id} 키에서 상태를 읽는다.
    존재하지 않는 task_id이면 404를 반환한다.
    """
    _require_system()
    try:
        cache = _system.components.cache  # type: ignore[union-attr]
        raw = await cache.read_json(f"crawl:task:{task_id}")

        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=404,
                detail=f"크롤링 태스크를 찾을 수 없다: {task_id}",
            )

        return CrawlStatusResponse(
            task_id=str(raw.get("task_id", task_id)),
            status=str(raw.get("status", "unknown")),
            crawled=int(raw.get("crawled", 0)),
            new_articles=int(raw.get("new_articles", 0)),
            errors=list(raw.get("errors", [])),
            completed_at=raw.get("completed_at"),
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("크롤링 상태 조회 실패: %s", task_id)
        raise HTTPException(status_code=500, detail="크롤링 상태 조회 실패") from None
