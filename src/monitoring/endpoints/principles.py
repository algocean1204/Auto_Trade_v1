"""F7.14 PrinciplesEndpoints -- 매매 원칙 CRUD API이다.

매매 원칙을 조회/추가/수정/삭제할 수 있다.
원칙은 캐시에 저장한다.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

principles_router = APIRouter(prefix="/api/principles", tags=["principles"])

_system: InjectedSystem | None = None

_CACHE_KEY = "trading:principles"
_CORE_CACHE_KEY = "principles:core"


class PrincipleRequest(BaseModel):
    """매매 원칙 생성 요청 모델이다."""

    title: str
    content: str
    category: str = "general"  # general, entry, exit, risk


class PrincipleUpdateRequest(BaseModel):
    """매매 원칙 부분 수정 요청 모델이다. 제공된 필드만 업데이트한다."""

    title: str | None = None
    content: str | None = None
    category: str | None = None
    enabled: bool | None = None


class PrincipleItem(BaseModel):
    """매매 원칙 항목 모델이다."""

    id: str
    title: str
    content: str
    category: str


class CorePrincipleRequest(BaseModel):
    """핵심 원칙 저장/수정 요청 모델이다."""

    text: str


class CorePrincipleResponse(BaseModel):
    """핵심 원칙 저장/수정 응답 모델이다."""

    status: str
    core_principle: str = ""


class PrinciplesListResponse(BaseModel):
    """매매 원칙 목록 응답 모델이다."""

    principles: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    core_principle: str = ""


class PrincipleCreateResponse(BaseModel):
    """매매 원칙 생성 응답 모델이다."""

    status: str
    principle: dict[str, Any] = Field(default_factory=dict)


class PrincipleUpdateResponse(BaseModel):
    """매매 원칙 수정 응답 모델이다."""

    status: str
    principle: dict[str, Any] = Field(default_factory=dict)


class PrincipleDeleteResponse(BaseModel):
    """매매 원칙 삭제 응답 모델이다."""

    status: str
    id: str


def set_principles_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("PrinciplesEndpoints 의존성 주입 완료")


_SEED_FILE = Path(__file__).resolve().parents[3] / "data" / "trading_principles.json"


async def _ensure_seed_loaded() -> None:
    """캐시에 원칙 데이터가 없으면 시드 파일에서 자동 로드한다."""
    if _system is None:
        return
    cache = _system.components.cache  # type: ignore[union-attr]
    existing = await cache.read_json(_CACHE_KEY)
    if existing and isinstance(existing, list) and len(existing) > 0:
        return  # 이미 데이터가 있으면 건너뛴다

    if not _SEED_FILE.exists():
        _logger.warning("시드 파일 없음: %s", _SEED_FILE)
        return

    try:
        raw = json.loads(_SEED_FILE.read_text(encoding="utf-8"))
        principles = raw.get("principles", [])
        core = raw.get("core_principle", "")
        if principles:
            await cache.write_json(_CACHE_KEY, principles)
            _logger.info("매매 원칙 시드 로드 완료: %d건", len(principles))
        if core:
            await cache.write(_CORE_CACHE_KEY, core)
            _logger.info("핵심 원칙 시드 로드 완료")
    except Exception:
        _logger.exception("매매 원칙 시드 로드 실패")


async def _load_principles() -> list[dict]:
    """캐시에서 원칙 목록을 로드한다. 비어있으면 시드를 먼저 로드한다."""
    cache = _system.components.cache  # type: ignore[union-attr]
    cached = await cache.read_json(_CACHE_KEY)
    if cached and isinstance(cached, list):
        return cached
    # 시드 로드 시도 후 재조회한다
    await _ensure_seed_loaded()
    cached = await cache.read_json(_CACHE_KEY)
    if cached and isinstance(cached, list):
        return cached
    return []


async def _save_principles(principles: list[dict]) -> None:
    """원칙 목록을 캐시에 저장한다."""
    cache = _system.components.cache  # type: ignore[union-attr]
    await cache.write_json(_CACHE_KEY, principles)


@principles_router.get("", response_model=PrinciplesListResponse)
async def get_principles() -> PrinciplesListResponse:
    """매매 원칙 목록을 반환한다. 핵심 원칙(core_principle)도 포함한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        principles = await _load_principles()
        # 핵심 원칙을 캐시에서 읽는다
        cache = _system.components.cache
        core_text = await cache.read(_CORE_CACHE_KEY) or ""
        return PrinciplesListResponse(
            principles=principles,
            count=len(principles),
            core_principle=core_text,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 원칙 조회 실패")
        raise HTTPException(status_code=500, detail="원칙 조회 실패") from None


@principles_router.post("", response_model=PrincipleCreateResponse)
async def add_principle(
    req: PrincipleRequest,
    _key: str = Depends(verify_api_key),
) -> PrincipleCreateResponse:
    """매매 원칙을 추가한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        principles = await _load_principles()
        new_id = str(uuid.uuid4())[:8]
        principle: dict[str, Any] = {
            "id": new_id,
            "title": req.title,
            "content": req.content,
            "category": req.category,
            "priority": 0,
            "is_system": False,
            "enabled": True,
            "created_at": datetime.now().isoformat(),
        }
        principles.append(principle)
        await _save_principles(principles)
        _logger.info("매매 원칙 추가: %s", req.title)
        return PrincipleCreateResponse(status="created", principle=principle)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 원칙 추가 실패")
        raise HTTPException(status_code=500, detail="원칙 추가 실패") from None


@principles_router.put("/core", response_model=CorePrincipleResponse)
async def update_core_principle(
    req: CorePrincipleRequest,
    _key: str = Depends(verify_api_key),
) -> CorePrincipleResponse:
    """핵심 원칙 텍스트를 저장/수정한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        await cache.write(_CORE_CACHE_KEY, req.text)
        _logger.info("핵심 원칙 저장 완료")
        return CorePrincipleResponse(status="updated", core_principle=req.text)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("핵심 원칙 저장 실패")
        raise HTTPException(status_code=500, detail="핵심 원칙 저장 실패") from None


@principles_router.put("/{principle_id}", response_model=PrincipleUpdateResponse)
async def update_principle(
    principle_id: str,
    req: PrincipleUpdateRequest,
    _key: str = Depends(verify_api_key),
) -> PrincipleUpdateResponse:
    """매매 원칙을 수정한다. 제공된 필드만 업데이트한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        principles = await _load_principles()
        for p in principles:
            if p["id"] == principle_id:
                # 제공된 필드만 업데이트한다
                if req.title is not None:
                    p["title"] = req.title
                if req.content is not None:
                    p["content"] = req.content
                if req.category is not None:
                    p["category"] = req.category
                if req.enabled is not None:
                    p["enabled"] = req.enabled
                await _save_principles(principles)
                _logger.info("매매 원칙 수정: %s", principle_id)
                return PrincipleUpdateResponse(status="updated", principle=p)
        raise HTTPException(
            status_code=404,
            detail=f"원칙을 찾을 수 없다: {principle_id}",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 원칙 수정 실패: %s", principle_id)
        raise HTTPException(status_code=500, detail="원칙 수정 실패") from None


@principles_router.delete("/{principle_id}", response_model=PrincipleDeleteResponse)
async def delete_principle(
    principle_id: str,
    _key: str = Depends(verify_api_key),
) -> PrincipleDeleteResponse:
    """매매 원칙을 삭제한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        principles = await _load_principles()
        original_len = len(principles)
        principles = [p for p in principles if p["id"] != principle_id]
        if len(principles) == original_len:
            raise HTTPException(
                status_code=404,
                detail=f"원칙을 찾을 수 없다: {principle_id}",
            )
        await _save_principles(principles)
        _logger.info("매매 원칙 삭제: %s", principle_id)
        return PrincipleDeleteResponse(status="deleted", id=principle_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("매매 원칙 삭제 실패: %s", principle_id)
        raise HTTPException(status_code=500, detail="원칙 삭제 실패") from None
