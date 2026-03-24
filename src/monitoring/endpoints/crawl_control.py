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

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

crawl_control_router = APIRouter(prefix="/api/crawl", tags=["crawl-control"])

_system: InjectedSystem | None = None

# 크롤 태스크 상태 캐시 TTL (초) -- 완료/실패 후 1시간 뒤 자동 만료한다
_CRAWL_TASK_TTL: int = 3600

# 동시 크롤링 방지 락 — 중복 수동 크롤이 crawl_engine을 동시 호출하는 것을 방지한다
_crawl_lock = asyncio.Lock()

# 백그라운드 태스크 참조 — GC에 의한 조기 수거를 방지한다
_background_tasks: set[asyncio.Task] = set()


def _on_bg_task_done(task: asyncio.Task, label: str) -> None:
    """백그라운드 태스크 완료 콜백 — 참조를 제거하고 예외를 로깅한다."""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error("백그라운드 태스크 예외 (%s): %s", label, exc)


# ── 응답 모델 ──────────────────────────────────────────────────────────────

class CrawlStartResponse(BaseModel):
    """크롤링 시작 응답 모델이다."""

    task_id: str
    status: str
    started_at: str


class CrawlerStatusItem(BaseModel):
    """개별 크롤러 상태 항목이다. Flutter CrawlProgress.fromJson 호환."""

    name: str
    status: str
    articles_count: int = 0
    time_elapsed: float | None = None


class CrawlStatusResponse(BaseModel):
    """크롤링 진행 상태 응답 모델이다.

    Flutter CrawlStatus.fromJson이 기대하는 필드를 모두 포함한다:
    task_id, status, total_crawlers, completed_crawlers, progress_pct,
    crawler_statuses, data.
    """

    task_id: str
    status: str                    # pending | running | completed | failed
    crawled: int
    new_articles: int
    errors: list[str] = Field(default_factory=list)
    completed_at: str | None = None
    # Flutter CrawlStatus.fromJson 호환 필드
    total_crawlers: int = 0
    completed_crawlers: int = 0
    progress_pct: float = 0.0
    crawler_statuses: list[CrawlerStatusItem] = Field(default_factory=list)
    data: dict | None = None


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
            await cache.write_json(cache_key, status, ttl=_CRAWL_TASK_TTL)

            # crawl_engine 피처 획득 (없으면 스킵)
            crawl_engine = _system.features.get("crawl_engine")  # type: ignore[union-attr]
            if crawl_engine is None:
                status["status"] = "failed"
                status["errors"].append("크롤 엔진이 등록되지 않았다")
                status["completed_at"] = _now_iso()
                await cache.write_json(cache_key, status, ttl=_CRAWL_TASK_TTL)
                return

            # crawl_scheduler 피처에서 스케줄을 생성한다
            crawl_scheduler = _system.features.get("crawl_scheduler")  # type: ignore[union-attr]
            if crawl_scheduler is None:
                status["status"] = "failed"
                status["errors"].append("크롤 스케줄러가 등록되지 않았다")
                status["completed_at"] = _now_iso()
                await cache.write_json(cache_key, status, ttl=_CRAWL_TASK_TTL)
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
            # 결과를 캐시에 최종 기록한다. 1시간 후 자동 만료한다.
            await cache.write_json(cache_key, status, ttl=_CRAWL_TASK_TTL)


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
        await cache.write_json(f"crawl:task:{task_id}", _default_status(task_id), ttl=_CRAWL_TASK_TTL)

        # 백그라운드 태스크 시작 — 참조를 저장하여 GC에 의한 소멸을 방지한다
        task = asyncio.create_task(_run_crawl_task(task_id))
        _background_tasks.add(task)
        task.add_done_callback(lambda t: _on_bg_task_done(t, "crawl"))

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
async def get_crawl_status(
    task_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    _auth: str = Depends(verify_api_key),
) -> CrawlStatusResponse:
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

        # Flutter CrawlStatus.fromJson 호환 필드를 캐시 데이터에서 추출한다
        crawler_statuses_raw = raw.get("crawler_statuses", [])
        crawler_items = [
            CrawlerStatusItem(
                name=str(cs.get("name", "")),
                status=str(cs.get("status", "pending")),
                articles_count=int(cs.get("articles_count", 0)),
                time_elapsed=cs.get("time_elapsed"),
            )
            for cs in crawler_statuses_raw
            if isinstance(cs, dict)
        ]
        total_crawlers = int(raw.get("total_crawlers", len(crawler_items)))
        completed_crawlers = int(raw.get("completed_crawlers", 0))
        # progress_pct: 캐시에 저장된 값 우선, 없으면 완료 크롤러 비율로 계산한다
        progress_pct = float(raw.get("progress_pct", 0.0))
        if progress_pct == 0.0 and total_crawlers > 0:
            progress_pct = round(completed_crawlers / total_crawlers * 100, 1)
        # completed 상태이면 100%로 보정한다
        task_status = str(raw.get("status", "unknown"))
        if task_status == "completed":
            progress_pct = 100.0

        # 완료 시 data 필드에 요약 정보를 구성한다 (Flutter CrawlSummary 호환)
        data_field = raw.get("data")
        if data_field is None and task_status == "completed":
            crawled_count = int(raw.get("crawled", 0))
            new_count = int(raw.get("new_articles", 0))
            data_field = {
                "total_articles": crawled_count,
                "unique_articles": crawled_count,
                "saved_articles": new_count,
                "duplicates": crawled_count - new_count,
            }

        return CrawlStatusResponse(
            task_id=str(raw.get("task_id", task_id)),
            status=task_status,
            crawled=int(raw.get("crawled", 0)),
            new_articles=int(raw.get("new_articles", 0)),
            errors=list(raw.get("errors", [])),
            completed_at=raw.get("completed_at"),
            total_crawlers=total_crawlers,
            completed_crawlers=completed_crawlers,
            progress_pct=progress_pct,
            crawler_statuses=crawler_items,
            data=data_field,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("크롤링 상태 조회 실패: %s", task_id)
        raise HTTPException(status_code=500, detail="크롤링 상태 조회 실패") from None
