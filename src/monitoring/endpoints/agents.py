"""F7.16 AgentEndpoints -- AI 에이전트 정보 조회 API이다.

시스템에 등록된 AI 에이전트 목록, 상세, 이력을 제공한다.

라우터 구조:
  - agents_router: /api/agents/* (ApiConstants.agents 상수 경로)
  - agents_compat_router: /agents/* (Flutter getAgentList/getAgentMd 하드코딩 경로)
두 라우터를 api_server.py에 모두 등록한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# /api/agents 접두어 — ApiConstants.agents = '/api/agents' 와 일치
agents_router = APIRouter(prefix="/api/agents", tags=["agents"])

# /agents 접두어 — Flutter가 하드코딩한 '/agents/list', '/agents/{id}' 와 일치
agents_compat_router = APIRouter(prefix="/agents", tags=["agents"])

_system: InjectedSystem | None = None

# 시스템 프롬프트별 에이전트 정의 (AI 에이전트)
_AI_AGENTS: list[dict[str, str]] = [
    {"id": "master_analyst", "name": "Master Analyst", "role": "종합 분석/매매 판단"},
    {"id": "news_analyst", "name": "News Analyst", "role": "뉴스 분석/영향도 평가"},
    {"id": "risk_manager", "name": "Risk Manager", "role": "리스크 관리/안전장치"},
    {"id": "macro_strategist", "name": "Macro Strategist", "role": "거시 경제 분석"},
    {"id": "short_term_trader", "name": "Short Term Trader", "role": "단기 매매 전략"},
]

# 시스템 모듈 에이전트 정의 (docs/agents/ 기반)
_MODULE_AGENTS: dict[str, dict[str, str]] = {
    "alert_manager": {"name": "Alert Manager", "role": "알림 관리"},
    "benchmark": {"name": "Benchmark", "role": "벤치마크 비교 분석"},
    "capital_guard": {"name": "Capital Guard", "role": "자본 보호/손실 한도"},
    "claude_client": {"name": "Claude Client", "role": "Claude AI 통신"},
    "crawl_engine": {"name": "Crawl Engine", "role": "뉴스 크롤링 엔진"},
    "crawl_scheduler": {"name": "Crawl Scheduler", "role": "크롤링 스케줄러"},
    "crawl_verifier": {"name": "Crawl Verifier", "role": "크롤링 검증"},
    "daily_feedback": {"name": "Daily Feedback", "role": "일일 피드백 생성"},
    "decision_maker": {"name": "Decision Maker", "role": "매매 의사결정"},
    "emergency_protocol": {"name": "Emergency Protocol", "role": "비상 프로토콜"},
    "entry_strategy": {"name": "Entry Strategy", "role": "진입 전략"},
    "exit_strategy": {"name": "Exit Strategy", "role": "청산 전략"},
    "hard_safety": {"name": "Hard Safety", "role": "하드 안전장치"},
    "kis_client": {"name": "KIS Client", "role": "KIS API 클라이언트"},
    "knowledge_manager": {"name": "Knowledge Manager", "role": "지식 관리(RAG)"},
    "mlx_classifier": {"name": "MLX Classifier", "role": "로컬 ML 분류기"},
    "news_classifier": {"name": "News Classifier", "role": "뉴스 분류"},
    "order_manager": {"name": "Order Manager", "role": "주문 관리"},
    "position_monitor": {"name": "Position Monitor", "role": "포지션 모니터링"},
    "regime_detector": {"name": "Regime Detector", "role": "시장 레짐 탐지"},
    "safety_checker": {"name": "Safety Checker", "role": "안전 검사"},
    "telegram_notifier": {"name": "Telegram Notifier", "role": "텔레그램 알림"},
    "weekly_analysis": {"name": "Weekly Analysis", "role": "주간 분석"},
}


def _get_all_agents() -> list[dict[str, str]]:
    """AI 에이전트 + 시스템 모듈 에이전트 전체 목록을 반환한다."""
    all_agents = list(_AI_AGENTS)
    for agent_id, meta in _MODULE_AGENTS.items():
        all_agents.append({"id": agent_id, "name": meta["name"], "role": meta["role"]})
    return all_agents


def _find_agent(agent_id: str) -> dict[str, str] | None:
    """에이전트 ID로 메타데이터를 조회한다."""
    for a in _AI_AGENTS:
        if a["id"] == agent_id:
            return a
    if agent_id in _MODULE_AGENTS:
        meta = _MODULE_AGENTS[agent_id]
        return {"id": agent_id, "name": meta["name"], "role": meta["role"]}
    return None


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


# 팀 ID → 팀에 속하는 에이전트 ID 매핑이다.
# Flutter AgentTeamType enum: crawling, analysis, decision, execution, safety, monitoring
_TEAM_MEMBERS: dict[str, list[str]] = {
    "crawling": [
        "crawl_engine", "crawl_scheduler", "crawl_verifier",
    ],
    "analysis": [
        "news_analyst", "news_classifier", "mlx_classifier",
        "regime_detector", "claude_client", "knowledge_manager",
    ],
    "decision": [
        "master_analyst", "decision_maker", "entry_strategy", "exit_strategy",
        "macro_strategist", "short_term_trader",
    ],
    "execution": [
        "order_manager", "kis_client", "position_monitor",
    ],
    "safety": [
        "hard_safety", "safety_checker", "emergency_protocol", "capital_guard",
    ],
    "monitoring": [
        "alert_manager", "telegram_notifier", "benchmark",
        "daily_feedback", "weekly_analysis",
    ],
}


def _build_teams_list() -> list[AgentTeamItem]:
    """에이전트 목록을 Flutter AgentTeam 호환 6팀 구조로 변환한다.

    각 팀의 id는 crawling/analysis/decision/execution/safety/monitoring 이며
    agents에 AgentInfoItem 리스트를 포함한다.
    """
    all_agent_map: dict[str, dict[str, str]] = {}
    for a in _get_all_agents():
        all_agent_map[a["id"]] = a

    teams: list[AgentTeamItem] = []
    for team_id, member_ids in _TEAM_MEMBERS.items():
        agents: list[AgentInfoItem] = []
        for mid in member_ids:
            meta = all_agent_map.get(mid)
            if meta:
                agents.append(AgentInfoItem(
                    id=mid,
                    name=meta["name"],
                    description=meta["role"],
                    team_id=team_id,
                    is_active=True,
                ))
        teams.append(AgentTeamItem(id=team_id, agents=agents))
    return teams


def _build_teams_response() -> AgentTeamsResponse:
    """에이전트 목록을 Flutter AgentTeam 호환 teams 구조로 변환한다."""
    teams = _build_teams_list()
    return AgentTeamsResponse(teams=teams, count=len(teams))


# docs/agents/ 디렉터리 경로 (프로젝트 루트 기준)
_DOCS_AGENTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "agents"

# 시딩 중복 실행 방지 플래그
_seeded = False


async def _seed_agents_from_docs() -> None:
    """docs/agents/ 디렉터리의 마크다운 파일을 Redis에 시딩한다.

    Redis에 agent:md:{agent_id} 키가 존재하지 않는 경우에만 저장하여
    사용자가 직접 저장한 콘텐츠를 덮어쓰지 않는다.
    최초 1회만 실행된다.
    """
    global _seeded
    if _seeded or _system is None:
        return
    _seeded = True

    if not _DOCS_AGENTS_DIR.is_dir():
        _logger.debug("docs/agents/ 디렉터리 없음: %s", _DOCS_AGENTS_DIR)
        return

    cache = _system.components.cache
    count = 0
    for md_path in sorted(_DOCS_AGENTS_DIR.glob("*.md")):
        if md_path.name == "_index.md":
            continue
        agent_id = md_path.stem  # 확장자 제거한 파일명
        redis_key = f"agent:md:{agent_id}"
        try:
            existing = await cache.read_json(redis_key)
            if existing is not None:
                continue
            content = md_path.read_text(encoding="utf-8")
            await cache.write_json(redis_key, {"content": content})
            count += 1
            _logger.debug("에이전트 문서 시딩: %s (%d bytes)", agent_id, len(content))
        except Exception:
            _logger.warning("에이전트 문서 시딩 실패: %s", agent_id, exc_info=True)

    if count > 0:
        _logger.info("에이전트 문서 시딩 완료: %d건", count)


# ── /api/agents/* 라우터 ──

@agents_router.get("", response_model=AgentsListResponse)
async def get_agents() -> AgentsListResponse:
    """AI 에이전트 목록을 반환한다.

    agents(원본 dict 리스트)와 teams(AgentTeamItem 리스트)를
    모두 포함하여 Flutter getAgentList() 호환성을 보장한다.
    최초 호출 시 docs/agents/ 마크다운 파일을 Redis에 시딩한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    await _seed_agents_from_docs()
    teams = _build_teams_list()
    all_agents = _get_all_agents()
    return AgentsListResponse(agents=all_agents, teams=teams, count=len(all_agents))


@agents_router.get("/list", response_model=AgentTeamsResponse)
async def get_agents_list_v2() -> AgentTeamsResponse:
    """에이전트 팀 목록을 반환한다. /api/agents/list 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    await _seed_agents_from_docs()
    return _build_teams_response()


@agents_router.get("/{agent_id}/history", response_model=AgentHistoryResponse)
async def get_agent_history(
    agent_id: str,
    limit: int = 20,
) -> AgentHistoryResponse:
    """에이전트 활동 이력을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        agent = _find_agent(agent_id)
        if agent is None:
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
async def get_agent_detail(agent_id: str) -> AgentDetailResponse:
    """에이전트 상세 정보를 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        agent = _find_agent(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=f"에이전트를 찾을 수 없다: {agent_id}",
            )
        # Redis에서 저장된 MD 콘텐츠 및 상태를 조회한다
        cache = _system.components.cache
        md_cached = await cache.read_json(f"agent:md:{agent_id}")
        status_cached = await cache.read_json(f"agent:status:{agent_id}")
        content = md_cached.get("content", "") if isinstance(md_cached, dict) else ""
        status_val = (
            status_cached.get("status", "idle")
            if isinstance(status_cached, dict)
            else "idle"
        )
        return AgentDetailResponse(
            id=agent["id"],
            name=agent["name"],
            role=agent["role"],
            status=status_val,
            content=content,
            md_content=content,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("에이전트 상세 조회 실패: %s", agent_id)
        raise HTTPException(status_code=500, detail="상세 조회 실패") from None


@agents_router.put("/{agent_id}", response_model=AgentSaveResponse)
async def save_agent_md_v2(
    agent_id: str,
    body: dict,
    _key: str = Depends(verify_api_key),
) -> AgentSaveResponse:
    """에이전트 MD 콘텐츠를 저장한다. 인증 필수.

    Flutter는 {"content": str} 형태로 전송한다.
    Redis에 agent:md:{agent_id} 키로 저장한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        content = body.get("content", "")
        if not isinstance(content, str):
            raise HTTPException(
                status_code=422,
                detail="content 필드는 문자열이어야 한다",
            )
        cache = _system.components.cache
        await cache.write_json(f"agent:md:{agent_id}", {"content": content})
        _logger.info("에이전트 MD 저장 완료 (v2): %s (%d bytes)", agent_id, len(content))
        return AgentSaveResponse(status="saved", agent_id=agent_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("에이전트 MD 저장 실패: %s", agent_id)
        raise HTTPException(status_code=500, detail="MD 저장 실패") from None


# ── /agents/* 호환 라우터 (Flutter 하드코딩 경로) ──

@agents_compat_router.get("/list", response_model=AgentTeamsResponse)
async def get_agents_list_compat() -> AgentTeamsResponse:
    """에이전트 팀 목록을 반환한다. Flutter /agents/list 호환 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    await _seed_agents_from_docs()
    return _build_teams_response()


@agents_compat_router.get("/{agent_id}", response_model=AgentDetailResponse)
async def get_agent_detail_compat(agent_id: str) -> AgentDetailResponse:
    """에이전트 상세 정보를 반환한다. Flutter /agents/{agentId} 호환 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        agent = _find_agent(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail=f"에이전트를 찾을 수 없다: {agent_id}",
            )
        cache = _system.components.cache
        md_cached = await cache.read_json(f"agent:md:{agent_id}")
        status_cached = await cache.read_json(f"agent:status:{agent_id}")
        content = md_cached.get("content", "") if isinstance(md_cached, dict) else ""
        status_val = (
            status_cached.get("status", "idle")
            if isinstance(status_cached, dict)
            else "idle"
        )
        return AgentDetailResponse(
            id=agent["id"],
            name=agent["name"],
            role=agent["role"],
            status=status_val,
            content=content,
            md_content=content,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("에이전트 상세 조회 실패 (compat): %s", agent_id)
        raise HTTPException(status_code=500, detail="상세 조회 실패") from None


@agents_compat_router.put("/{agent_id}", response_model=AgentSaveResponse)
async def save_agent_md_compat(
    agent_id: str,
    body: dict,
    _key: str = Depends(verify_api_key),
) -> AgentSaveResponse:
    """에이전트 MD 콘텐츠를 저장한다. Flutter /agents/{agentId} 호환 경로이다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        content = body.get("content", "")
        if not isinstance(content, str):
            raise HTTPException(
                status_code=422,
                detail="content 필드는 문자열이어야 한다",
            )
        cache = _system.components.cache
        await cache.write_json(f"agent:md:{agent_id}", {"content": content})
        _logger.info("에이전트 MD 저장 완료 (compat): %s (%d bytes)", agent_id, len(content))
        return AgentSaveResponse(status="saved", agent_id=agent_id)
    except HTTPException:
        raise
    except Exception:
        _logger.exception("에이전트 MD 저장 실패 (compat): %s", agent_id)
        raise HTTPException(status_code=500, detail="MD 저장 실패") from None
