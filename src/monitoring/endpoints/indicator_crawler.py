"""F7.20 IndicatorCrawlerEndpoints -- FRED 거시지표 크롤링 API이다.

수동 크롤링 트리거와 크롤링 상태 조회를 제공한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.indicators.misc.fred_fetcher import FRED_API_URL, FRED_SERIES
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

indicator_crawler_router = APIRouter(
    prefix="/api/indicators/crawl",
    tags=["indicator-crawler"],
)

_system: InjectedSystem | None = None

# 백그라운드 태스크 참조 — GC에 의한 조기 수거를 방지한다
_background_tasks: set[asyncio.Task] = set()

# 크롤링 상태 추적
_crawl_status: dict = {
    "running": False,
    "last_run": None,
    "last_result": None,
}


class CrawlStatusResponse(BaseModel):
    """크롤링 상태 응답 모델이다."""

    running: bool
    last_run: str | None = None
    last_result: str | None = None


class CrawlTriggerResponse(BaseModel):
    """크롤링 트리거 응답 모델이다."""

    status: str
    message: str


def _on_crawl_done(task: asyncio.Task) -> None:
    """크롤링 태스크 완료 콜백 — 참조를 제거하고 예외를 로깅한다."""
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error("FRED 크롤링 백그라운드 태스크 예외: %s", exc)


def set_indicator_crawler_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("IndicatorCrawlerEndpoints 의존성 주입 완료")


@indicator_crawler_router.get("/status", response_model=CrawlStatusResponse)
async def get_crawl_status(
    _auth: str = Depends(verify_api_key),
) -> CrawlStatusResponse:
    """크롤링 상태를 반환한다."""
    return CrawlStatusResponse(
        running=_crawl_status["running"],
        last_run=_crawl_status.get("last_run"),
        last_result=_crawl_status.get("last_result"),
    )


@indicator_crawler_router.post("", response_model=CrawlTriggerResponse)
async def trigger_crawl(
    _key: str = Depends(verify_api_key),
) -> CrawlTriggerResponse:
    """FRED 거시지표 수동 크롤링을 트리거한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")

    if _crawl_status["running"]:
        raise HTTPException(status_code=409, detail="이미 크롤링이 진행 중이다")

    # 즉시 running=True를 설정하여 동시 요청의 TOCTOU 레이스를 방지한다
    _crawl_status["running"] = True
    try:
        async def _run_crawl() -> None:
            """비동기 크롤링 태스크를 실행한다."""
            try:
                # FRED 데이터 조회를 수행한다
                http = _system.components.http  # type: ignore[union-attr]
                vault = _system.components.vault  # type: ignore[union-attr]
                fred_key = vault.get_secret_or_none("FRED_API_KEY")

                if not fred_key:
                    _crawl_status["last_result"] = "FRED_API_KEY 미설정"
                    return

                series_ids = FRED_SERIES
                cache = _system.components.cache  # type: ignore[union-attr]
                count = 0
                for sid in series_ids:
                    try:
                        # API 키를 params에 전달하여 URL에 직접 노출하지 않는다
                        params = {
                            "series_id": sid,
                            "api_key": fred_key,
                            "file_type": "json",
                            "sort_order": "desc",
                            "limit": "30",
                        }
                        resp = await http.get(FRED_API_URL, params=params)
                        if not resp.ok:
                            _logger.warning("FRED %s 조회 실패: HTTP %d", sid, resp.status)
                            continue
                        data = resp.json()
                        observations = data.get("observations", [])
                        # observations에서 유효한 값만 추출하여 저장한다
                        clean = []
                        for o in observations:
                            raw_val = o.get("value", ".")
                            if raw_val == ".":
                                continue
                            try:
                                clean.append({
                                    "date": o.get("date", ""),
                                    "value": float(raw_val),
                                })
                            except (ValueError, TypeError):
                                continue
                        if clean:
                            await cache.write_json(f"macro:{sid}", clean, ttl=86400)
                            count += 1
                            _logger.info("FRED %s: %d건 캐시 저장", sid, len(clean))
                    except Exception as exc:
                        _logger.warning("FRED %s 개별 조회 실패: %s", sid, exc)

                _crawl_status["last_result"] = f"{count}/{len(series_ids)} 시리즈 수집"
            except Exception:
                _logger.exception("FRED 크롤링 오류")
                _crawl_status["last_result"] = "크롤링 오류 발생"
            finally:
                _crawl_status["running"] = False
                _crawl_status["last_run"] = datetime.now(tz=timezone.utc).isoformat()

        task = asyncio.create_task(_run_crawl())
        _background_tasks.add(task)
        task.add_done_callback(_on_crawl_done)
        return CrawlTriggerResponse(
            status="triggered", message="FRED 크롤링을 시작했다"
        )
    except HTTPException:
        _crawl_status["running"] = False
        raise
    except Exception:
        _crawl_status["running"] = False
        _logger.exception("크롤링 트리거 실패")
        raise HTTPException(status_code=500, detail="트리거 실패") from None
