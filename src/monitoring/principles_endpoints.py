"""
Flutter 대시보드용 매매 원칙(Principles) CRUD API 엔드포인트.

data/trading_principles.json 파일에 저장된 매매 원칙을 조회, 추가,
수정, 삭제하는 기능을 제공한다.

시스템 원칙(is_system=true)은 수정/삭제가 불가능하고,
사용자 정의 원칙(is_system=false)만 수정/삭제할 수 있다.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from src.monitoring.auth import verify_api_key
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수 정의
# ---------------------------------------------------------------------------

_PRINCIPLES_FILE = Path(__file__).resolve().parents[2] / "data" / "trading_principles.json"

# ---------------------------------------------------------------------------
# 라우터 정의
# ---------------------------------------------------------------------------

principles_router = APIRouter(prefix="/api/principles", tags=["Principles"])


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------


class PrincipleResponse(BaseModel):
    """매매 원칙 응답 스키마."""

    id: str
    category: str
    title: str
    content: str
    priority: int
    is_system: bool
    enabled: bool = True
    created_at: str


class PrinciplesListResponse(BaseModel):
    """매매 원칙 목록 응답 스키마 (core_principle 포함)."""

    core_principle: str
    principles: list[PrincipleResponse]


class PrincipleCreateRequest(BaseModel):
    """새 매매 원칙 생성 요청 스키마."""

    category: str = Field(..., min_length=1, max_length=50, description="원칙 카테고리 (예: risk, strategy, execution)")
    title: str = Field(..., min_length=1, max_length=100, description="원칙 제목")
    content: str = Field(..., min_length=1, max_length=1000, description="원칙 내용")
    priority: int = Field(default=99, ge=1, le=999, description="우선순위 (숫자가 낮을수록 높음)")


class PrincipleUpdateRequest(BaseModel):
    """매매 원칙 수정 요청 스키마."""

    category: str | None = Field(default=None, min_length=1, max_length=50, description="원칙 카테고리")
    title: str | None = Field(default=None, min_length=1, max_length=100, description="원칙 제목")
    content: str | None = Field(default=None, min_length=1, max_length=1000, description="원칙 내용")
    priority: int | None = Field(default=None, ge=1, le=999, description="우선순위")
    enabled: bool | None = Field(default=None, description="활성화 여부")


class CorePrincipleUpdateRequest(BaseModel):
    """핵심 원칙 수정 요청 모델이다."""

    core_principle: str = Field(..., min_length=1, max_length=500, description="핵심 원칙 텍스트")


# ---------------------------------------------------------------------------
# 내부 헬퍼: 파일 잠금 기반 읽기/쓰기 (async 래퍼)
# ---------------------------------------------------------------------------


async def _read_principles() -> dict[str, Any]:
    """trading_principles.json 파일을 읽고 전체 딕셔너리를 반환한다.

    파일이 없거나 파싱에 실패하면 빈 구조체를 반환한다.
    동기 I/O를 asyncio.to_thread()로 감싸 이벤트 루프 블로킹을 방지한다.

    Returns:
        {"core_principle": str, "principles": list[dict]} 형태의 딕셔너리.
    """
    def _sync_read() -> dict[str, Any]:
        try:
            with open(_PRINCIPLES_FILE, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    content = f.read()
                    return json.loads(content) if content.strip() else {"core_principle": "", "principles": []}
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except FileNotFoundError:
            logger.warning("trading_principles.json 파일이 없다: %s", _PRINCIPLES_FILE)
            return {"core_principle": "", "principles": []}
        except json.JSONDecodeError as exc:
            logger.error("trading_principles.json 파싱 실패: %s", exc)
            return {"core_principle": "", "principles": []}
        except OSError as exc:
            logger.error("trading_principles.json 읽기 실패: %s", exc)
            return {"core_principle": "", "principles": []}

    return await asyncio.to_thread(_sync_read)


async def _write_principles(data: dict[str, Any]) -> None:
    """전체 딕셔너리를 trading_principles.json 파일에 저장한다.

    파일 잠금을 사용하여 동시 쓰기 충돌을 방지한다.
    seek+truncate 방식으로 파일 잠금 후 안전하게 내용을 교체한다.
    동기 I/O를 asyncio.to_thread()로 감싸 이벤트 루프 블로킹을 방지한다.

    Args:
        data: 저장할 전체 딕셔너리 (core_principle + principles 포함).

    Raises:
        OSError: 파일 쓰기에 실패한 경우.
    """
    def _sync_write() -> None:
        _PRINCIPLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 파일이 없으면 "w" 모드로 새로 생성 (TOCTOU 없음: 존재 여부 확인 없이 직접 시도)
        try:
            f = open(_PRINCIPLES_FILE, "r+", encoding="utf-8")
        except FileNotFoundError:
            f = open(_PRINCIPLES_FILE, "w", encoding="utf-8")
        with f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                f.truncate()
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    await asyncio.to_thread(_sync_write)


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@principles_router.get("", response_model=PrinciplesListResponse)
async def list_principles() -> PrinciplesListResponse:
    """모든 매매 원칙을 우선순위(priority) 오름차순으로 반환한다.

    core_principle 필드와 함께 원칙 목록을 래핑하여 반환한다.

    Returns:
        core_principle과 우선순위 순으로 정렬된 매매 원칙 목록.
    """
    try:
        data = await _read_principles()
        principles = data.get("principles", [])
        principles.sort(key=lambda p: p.get("priority", 999))
        return PrinciplesListResponse(
            core_principle=data.get("core_principle", ""),
            principles=[PrincipleResponse(**p) for p in principles],
        )
    except Exception as exc:
        logger.error("매매 원칙 목록 조회 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="매매 원칙 목록 조회 중 오류가 발생했습니다.") from exc


@principles_router.post("", response_model=PrincipleResponse, status_code=201)
async def create_principle(
    request: PrincipleCreateRequest,
    _: None = Depends(verify_api_key),
) -> PrincipleResponse:
    """새 매매 원칙을 추가한다.

    id는 UUID로 자동 생성되며, is_system은 항상 false로 설정된다.

    Args:
        request: 생성할 원칙의 카테고리, 제목, 내용, 우선순위.

    Returns:
        생성된 매매 원칙.
    """
    try:
        data = await _read_principles()
        principles = data.get("principles", [])
        new_principle: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "category": request.category,
            "title": request.title,
            "content": request.content,
            "priority": request.priority,
            "is_system": False,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        principles.append(new_principle)
        data["principles"] = principles
        await _write_principles(data)
        logger.info("새 매매 원칙 추가: id=%s, title=%s", new_principle["id"], new_principle["title"])
        return PrincipleResponse(**new_principle)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("매매 원칙 추가 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="매매 원칙 추가 중 오류가 발생했습니다.") from exc


@principles_router.put("/core")
async def update_core_principle(
    request: CorePrincipleUpdateRequest,
    _: None = Depends(verify_api_key),
) -> dict[str, str]:
    """핵심 원칙을 수정한다."""
    try:
        data = await _read_principles()
        data["core_principle"] = request.core_principle
        await _write_principles(data)
        logger.info("핵심 원칙 수정 완료")
        return {"core_principle": data["core_principle"]}
    except Exception as e:
        logger.error("핵심 원칙 수정 실패: %s", e)
        raise HTTPException(status_code=500, detail="핵심 원칙 수정에 실패했다") from e


@principles_router.put("/{principle_id}", response_model=PrincipleResponse)
async def update_principle(
    principle_id: str,
    request: PrincipleUpdateRequest,
    _: None = Depends(verify_api_key),
) -> PrincipleResponse:
    """지정한 매매 원칙을 수정한다.

    시스템 원칙(is_system=true)은 수정할 수 없다.

    Args:
        principle_id: 수정할 원칙의 ID.
        request: 수정할 필드 (None인 필드는 변경하지 않음).

    Returns:
        수정된 매매 원칙.

    Raises:
        HTTPException 404: 해당 ID의 원칙이 존재하지 않는 경우.
        HTTPException 403: 시스템 원칙을 수정하려는 경우.
    """
    try:
        data = await _read_principles()
        principles = data.get("principles", [])
        target_idx: int | None = None
        for idx, p in enumerate(principles):
            if p.get("id") == principle_id:
                target_idx = idx
                break

        if target_idx is None:
            raise HTTPException(
                status_code=404,
                detail=f"원칙 ID '{principle_id}'를 찾을 수 없습니다.",
            )

        target = principles[target_idx]
        if target.get("is_system", False):
            raise HTTPException(
                status_code=403,
                detail="시스템 원칙(is_system=true)은 수정할 수 없습니다.",
            )

        if request.category is not None:
            target["category"] = request.category
        if request.title is not None:
            target["title"] = request.title
        if request.content is not None:
            target["content"] = request.content
        if request.priority is not None:
            target["priority"] = request.priority
        if request.enabled is not None:
            target["enabled"] = request.enabled

        principles[target_idx] = target
        data["principles"] = principles
        await _write_principles(data)
        logger.info("매매 원칙 수정 완료: id=%s", principle_id)
        return PrincipleResponse(**target)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("매매 원칙 수정 실패 (id=%s): %s", principle_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="매매 원칙 수정 중 오류가 발생했습니다.") from exc


@principles_router.delete("/{principle_id}", status_code=204, response_model=None)
async def delete_principle(
    principle_id: str,
    _: None = Depends(verify_api_key),
) -> Response:
    """지정한 매매 원칙을 삭제한다.

    시스템 원칙(is_system=true)은 삭제할 수 없다.

    Args:
        principle_id: 삭제할 원칙의 ID.

    Raises:
        HTTPException 404: 해당 ID의 원칙이 존재하지 않는 경우.
        HTTPException 403: 시스템 원칙을 삭제하려는 경우.
    """
    try:
        data = await _read_principles()
        principles = data.get("principles", [])
        target: dict[str, Any] | None = None
        for p in principles:
            if p.get("id") == principle_id:
                target = p
                break

        if target is None:
            raise HTTPException(
                status_code=404,
                detail=f"원칙 ID '{principle_id}'를 찾을 수 없습니다.",
            )

        if target.get("is_system", False):
            raise HTTPException(
                status_code=403,
                detail="시스템 원칙(is_system=true)은 삭제할 수 없습니다.",
            )

        data["principles"] = [p for p in principles if p.get("id") != principle_id]
        await _write_principles(data)
        logger.info("매매 원칙 삭제 완료: id=%s", principle_id)
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("매매 원칙 삭제 실패 (id=%s): %s", principle_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="매매 원칙 삭제 중 오류가 발생했습니다.") from exc
