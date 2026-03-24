"""F7.16 AgentEndpoints -- AI 에이전트 정보 조회 API이다.

시스템에 등록된 AI 에이전트 목록, 상세, 이력을 제공한다.
에이전트 메타데이터는 src.agents.registry에서 관리한다.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from src.agents.registry import (
    get_agent,
    get_all_agents,
    get_all_teams,
    get_docs_dir,
)
from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.agents.agent_meta import AgentMeta
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# /api/agents 접두어 — ApiConstants.agents = '/api/agents' 와 일치
agents_router = APIRouter(prefix="/api/agents", tags=["agents"])

_system: InjectedSystem | None = None


# ── 레지스트리 → API dict 변환 ──

def _meta_to_dict(meta: AgentMeta) -> dict[str, str]:
    """AgentMeta를 API 응답용 dict로 변환한다."""
    return {"id": meta.id, "name": meta.name, "role": meta.role}


def _get_all_agents_dicts() -> list[dict[str, str]]:
    """전체 에이전트를 dict 리스트로 반환한다."""
    return [_meta_to_dict(a) for a in get_all_agents()]


def _find_agent_dict(agent_id: str) -> dict[str, str] | None:
    """에이전트 ID로 dict를 조회한다."""
    meta = get_agent(agent_id)
    return _meta_to_dict(meta) if meta else None


# ── Pydantic 응답 모델 (Flutter 호환, 변경 없음) ──

class AgentInfoItem(BaseModel):
    """개별 에이전트 정보 모델이다. Flutter AgentInfo.fromJson 호환."""

    id: str
    name: str
    description: str = ""
    team_id: str = ""
    is_active: bool = True
    md_content: str | None = None


class AgentTeamItem(BaseModel):
    """에이전트 팀 항목 모델이다. Flutter AgentTeam.fromJson 호환.

    id는 crawling/analysis/decision/execution/safety/monitoring 중 하나이다.
    agents는 AgentInfoItem 리스트이다.
    """

    id: str
    agents: list[AgentInfoItem] = Field(default_factory=list)


class AgentsListResponse(BaseModel):
    """에이전트 목록 응답 모델이다.

    Flutter getAgentList()는 'teams' 키를 우선 참조하므로
    agents와 teams를 모두 포함하여 호환성을 보장한다.
    """

    agents: list[dict[str, str]] = Field(default_factory=list)
    teams: list[AgentTeamItem] = Field(default_factory=list)
    count: int = 0


class AgentTeamsResponse(BaseModel):
    """에이전트 팀 목록 응답 모델이다."""

    teams: list[AgentTeamItem] = Field(default_factory=list)
    count: int = 0


class AgentDetailResponse(BaseModel):
    """에이전트 상세 응답 모델이다."""

    id: str
    name: str
    role: str
    status: str = "idle"
    content: str = ""
    md_content: str = ""


class AgentSaveRequest(BaseModel):
    """에이전트 MD 저장 요청 모델이다."""

    content: str = Field(default="", max_length=50000)


class AgentSaveResponse(BaseModel):
    """에이전트 저장 응답 모델이다."""

    status: str
    agent_id: str


class AgentHistoryResponse(BaseModel):
    """에이전트 이력 응답 모델이다."""

    agent_id: str
    history: list[dict[str, Any]] = Field(default_factory=list)


def set_agents_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("AgentEndpoints 의존성 주입 완료")


# ── 팀 목록 빌드 ──

def _build_teams_list() -> list[AgentTeamItem]:
    """에이전트를 Flutter AgentTeam 호환 6팀 구조로 변환한다."""
    teams: list[AgentTeamItem] = []
    for team_id, members in get_all_teams().items():
        agents = [
            AgentInfoItem(
                id=m.id, name=m.name, description=m.role,
                team_id=team_id, is_active=True,
            )
            for m in members
        ]
        teams.append(AgentTeamItem(id=team_id, agents=agents))
    return teams


def _build_teams_response() -> AgentTeamsResponse:
    """에이전트를 Flutter AgentTeam 호환 teams 구조로 변환한다."""
    teams = _build_teams_list()
    return AgentTeamsResponse(teams=teams, count=len(teams))


# ── 캐시 시딩 ──

_seeded = False
_seed_lock = asyncio.Lock()


async def _seed_agents_from_docs() -> None:
    """에이전트 문서를 캐시에 시딩한다.

    캐시에 agent:md:{agent_id} 키가 존재하지 않는 경우에만 저장하여
    사용자가 직접 저장한 콘텐츠를 덮어쓰지 않는다.
    최초 1회만 실행된다. asyncio.Lock으로 동시 시딩 레이스를 방지한다.
    """
    global _seeded
    if _seeded or _system is None:
        return
    async with _seed_lock:
        # Lock 획득 후 다시 확인한다 (다른 코루틴이 이미 완료했을 수 있다)
        if _seeded:
            return
        _seeded = True

    docs_dir = get_docs_dir()
    if not docs_dir.is_dir():
        _logger.debug("에이전트 문서 디렉터리 없음: %s", docs_dir)
        return

    cache = _system.components.cache
    count = 0
    for md_path in sorted(docs_dir.glob("*.md")):
        if md_path.name == "_index.md":
            continue
        agent_id = md_path.stem
        cache_key = f"agent:md:{agent_id}"
        try:
            existing = await cache.read_json(cache_key)
            if existing is not None:
                continue
            content = md_path.read_text(encoding="utf-8")
            await cache.write_json(cache_key, {"content": content})
            count += 1
            _logger.debug("에이전트 문서 시딩: %s (%d bytes)", agent_id, len(content))
        except Exception:
            _logger.warning("에이전트 문서 시딩 실패: %s", agent_id, exc_info=True)

    if count > 0:
        _logger.info("에이전트 문서 시딩 완료: %d건", count)


# ── 에이전트 상세 조회 공통 ──

async def _get_agent_detail_impl(agent_id: str) -> AgentDetailResponse:
    """에이전트 상세 정보를 조회하는 공통 구현이다."""
    agent = _find_agent_dict(agent_id)
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"에이전트를 찾을 수 없다: {agent_id}",
        )
    cache = _system.components.cache  # type: ignore[union-attr]
    md_cached = await cache.read_json(f"agent:md:{agent_id}")
    status_cached = await cache.read_json(f"agent:status:{agent_id}")
    content = md_cached.get("content", "") if isinstance(md_cached, dict) else ""
    status_val = (
        status_cached.get("status", "idle")
        if isinstance(status_cached, dict)
        else "idle"
    )
    return AgentDetailResponse(
        id=agent["id"], name=agent["name"], role=agent["role"],
        status=status_val, content=content, md_content=content,
    )


async def _save_agent_md_impl(agent_id: str, body: dict) -> AgentSaveResponse:
    """에이전트 MD 콘텐츠를 저장하는 공통 구현이다."""
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(
            status_code=422,
            detail="content 필드는 문자열이어야 한다",
        )
    cache = _system.components.cache  # type: ignore[union-attr]
    await cache.write_json(f"agent:md:{agent_id}", {"content": content})
    _logger.info("에이전트 MD 저장 완료: %s (%d bytes)", agent_id, len(content))
    return AgentSaveResponse(status="saved", agent_id=agent_id)


# ── /api/agents/* 라우터 ──

@agents_router.get("", response_model=AgentsListResponse)
async def get_agents(
    _auth: str = Depends(verify_api_key),
) -> AgentsListResponse:
    """AI 에이전트 목록을 반환한다.

    agents(원본 dict 리스트)와 teams(AgentTeamItem 리스트)를
    모두 포함하여 Flutter getAgentList() 호환성을 보장한다.
    최초 호출 시 에이전트 마크다운 파일을 캐시에 시딩한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    await _seed_agents_from_docs()
    teams = _build_teams_list()
    all_agents = _get_all_agents_dicts()
    return AgentsListResponse(agents=all_agents, teams=teams, count=len(all_agents))


@agents_router.get("/list", response_model=AgentTeamsResponse)
async def get_agents_list_v2(
    _auth: str = Depends(verify_api_key),
) -> AgentTeamsResponse:
    """에이전트 팀 목록을 반환한다. /api/agents/list 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    await _seed_agents_from_docs()
    return _build_teams_response()


@agents_router.get("/{agent_id}/history", response_model=AgentHistoryResponse)
async def get_agent_history(
    agent_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    limit: int = Query(default=20, ge=1, le=200),
    _auth: str = Depends(verify_api_key),
) -> AgentHistoryResponse:
    """에이전트 활동 이력을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        if _find_agent_dict(agent_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"에이전트를 찾을 수 없다: {agent_id}",
            )
        cache = _system.components.cache
        cached = await cache.read_json(f"agent:history:{agent_id}")
        history = cached if isinstance(cached, list) else []
        return AgentHistoryResponse(agent_id=agent_id, history=history[:limit])
    except HTTPException:
        raise
    except Exception:
        _logger.exception("에이전트 이력 조회 실패: %s", agent_id)
        raise HTTPException(status_code=500, detail="이력 조회 실패") from None


@agents_router.get("/{agent_id}", response_model=AgentDetailResponse)
async def get_agent_detail(
    agent_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    _auth: str = Depends(verify_api_key),
) -> AgentDetailResponse:
    """에이전트 상세 정보를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        return await _get_agent_detail_impl(agent_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("에이전트 상세 조회 실패: %s", agent_id)
        raise HTTPException(status_code=500, detail="상세 조회 실패") from None


@agents_router.put("/{agent_id}", response_model=AgentSaveResponse)
async def save_agent_md_v2(
    agent_id: str = Path(..., pattern=r"^[A-Za-z0-9_.-]+$"),
    body: AgentSaveRequest = ...,
    _key: str = Depends(verify_api_key),
) -> AgentSaveResponse:
    """에이전트 MD 콘텐츠를 저장한다. 인증 필수."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        return await _save_agent_md_impl(agent_id, body.model_dump())
    except HTTPException:
        raise
    except Exception:
        _logger.exception("에이전트 MD 저장 실패: %s", agent_id)
        raise HTTPException(status_code=500, detail="MD 저장 실패") from None
