"""
에이전트 팀 관리 API 엔드포인트.

dashboard_endpoints.py에서 분리된 모듈로, 에이전트 목록/상세/수정
API를 제공한다. 에이전트 문서는 docs/agents/*.md 파일로 관리된다.

엔드포인트 목록:
  GET  /agents/list              - 에이전트 목록 (팀별)
  GET  /agents/{agent_id}        - 에이전트 상세 (마크다운 내용)
  PUT  /agents/{agent_id}        - 에이전트 마크다운 수정
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.monitoring.auth import verify_api_key
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 에이전트 데이터 (상수)
# ---------------------------------------------------------------------------

# 에이전트 문서 디렉토리 (프로젝트 루트 기준)
_AGENTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "agents"

# 허용된 에이전트 ID 목록 (경로 탐색 방지용 화이트리스트)
ALLOWED_AGENT_IDS: frozenset[str] = frozenset({
    "crawl_engine",
    "crawl_scheduler",
    "crawl_verifier",
    "news_classifier",
    "mlx_classifier",
    "regime_detector",
    "claude_client",
    "knowledge_manager",
    "decision_maker",
    "entry_strategy",
    "exit_strategy",
    "order_manager",
    "kis_client",
    "position_monitor",
    "hard_safety",
    "safety_checker",
    "emergency_protocol",
    "capital_guard",
    "alert_manager",
    "telegram_notifier",
    "benchmark",
    "daily_feedback",
    "weekly_analysis",
})

# 팀별 에이전트 구성
AGENT_TEAMS: list[dict[str, Any]] = [
    {
        "id": "crawling",
        "name": "크롤링팀",
        "agents": [
            {
                "id": "crawl_engine",
                "name": "CrawlEngine",
                "file": "crawl_engine.md",
                "description": "30개 뉴스 소스 대상 RSS/API/스크래핑 크롤링 엔진",
                "team_id": "crawling",
                "is_active": True,
            },
            {
                "id": "crawl_scheduler",
                "name": "CrawlScheduler",
                "file": "crawl_scheduler.md",
                "description": "야간/주간 모드 크롤링 스케줄 관리자",
                "team_id": "crawling",
                "is_active": True,
            },
            {
                "id": "crawl_verifier",
                "name": "CrawlVerifier",
                "file": "crawl_verifier.md",
                "description": "크롤링 결과 중복 제거 및 품질 검증기",
                "team_id": "crawling",
                "is_active": True,
            },
        ],
    },
    {
        "id": "analysis",
        "name": "분석팀",
        "agents": [
            {
                "id": "news_classifier",
                "name": "NewsClassifier",
                "file": "news_classifier.md",
                "description": "Claude API 기반 뉴스 감성·영향도 분류기",
                "team_id": "analysis",
                "is_active": True,
            },
            {
                "id": "mlx_classifier",
                "name": "MLXClassifier",
                "file": "mlx_classifier.md",
                "description": "MLX(Qwen3-30B) 로컬 AI 분류기 (Apple Silicon MPS)",
                "team_id": "analysis",
                "is_active": True,
            },
            {
                "id": "regime_detector",
                "name": "RegimeDetector",
                "file": "regime_detector.md",
                "description": "VIX·공포탐욕 지수 기반 시장 국면 감지기",
                "team_id": "analysis",
                "is_active": True,
            },
            {
                "id": "claude_client",
                "name": "ClaudeClient",
                "file": "claude_client.md",
                "description": "Claude Opus/Sonnet AI 클라이언트 래퍼",
                "team_id": "analysis",
                "is_active": True,
            },
            {
                "id": "knowledge_manager",
                "name": "KnowledgeManager",
                "file": "knowledge_manager.md",
                "description": "ChromaDB + bge-m3 기반 RAG 지식 관리자",
                "team_id": "analysis",
                "is_active": True,
            },
        ],
    },
    {
        "id": "decision",
        "name": "의사결정팀",
        "agents": [
            {
                "id": "decision_maker",
                "name": "DecisionMaker",
                "file": "decision_maker.md",
                "description": "분석 결과 종합 후 매매 결정을 내리는 핵심 에이전트",
                "team_id": "decision",
                "is_active": True,
            },
            {
                "id": "entry_strategy",
                "name": "EntryStrategy",
                "file": "entry_strategy.md",
                "description": "진입 시점·수량·가격 결정 전략 모듈",
                "team_id": "decision",
                "is_active": True,
            },
            {
                "id": "exit_strategy",
                "name": "ExitStrategy",
                "file": "exit_strategy.md",
                "description": "청산 시점·손절·목표가 결정 전략 모듈",
                "team_id": "decision",
                "is_active": True,
            },
        ],
    },
    {
        "id": "execution",
        "name": "실행팀",
        "agents": [
            {
                "id": "order_manager",
                "name": "OrderManager",
                "file": "order_manager.md",
                "description": "KIS API 주문 생성·취소·수정 관리자",
                "team_id": "execution",
                "is_active": True,
            },
            {
                "id": "kis_client",
                "name": "KISClient",
                "file": "kis_client.md",
                "description": "한국투자증권 OpenAPI 인증·요청 클라이언트",
                "team_id": "execution",
                "is_active": True,
            },
            {
                "id": "position_monitor",
                "name": "PositionMonitor",
                "file": "position_monitor.md",
                "description": "보유 포지션 실시간 손익·리스크 모니터",
                "team_id": "execution",
                "is_active": True,
            },
        ],
    },
    {
        "id": "safety",
        "name": "안전팀",
        "agents": [
            {
                "id": "hard_safety",
                "name": "HardSafety",
                "file": "hard_safety.md",
                "description": "절대 손실 한도·강제 청산 하드 세이프티",
                "team_id": "safety",
                "is_active": True,
            },
            {
                "id": "safety_checker",
                "name": "SafetyChecker",
                "file": "safety_checker.md",
                "description": "주문 전 다중 안전 조건 검사기",
                "team_id": "safety",
                "is_active": True,
            },
            {
                "id": "emergency_protocol",
                "name": "EmergencyProtocol",
                "file": "emergency_protocol.md",
                "description": "긴급 상황 감지 및 자동 대응 프로토콜",
                "team_id": "safety",
                "is_active": True,
            },
            {
                "id": "capital_guard",
                "name": "CapitalGuard",
                "file": "capital_guard.md",
                "description": "자본 보호·생존 트레이딩 최소 기준 수호자",
                "team_id": "safety",
                "is_active": True,
            },
        ],
    },
    {
        "id": "monitoring",
        "name": "모니터링팀",
        "agents": [
            {
                "id": "alert_manager",
                "name": "AlertManager",
                "file": "alert_manager.md",
                "description": "임계값 기반 알림 생성·분류·전송 관리자",
                "team_id": "monitoring",
                "is_active": True,
            },
            {
                "id": "telegram_notifier",
                "name": "TelegramNotifier",
                "file": "telegram_notifier.md",
                "description": "텔레그램 봇을 통한 실시간 알림 발송기",
                "team_id": "monitoring",
                "is_active": True,
            },
            {
                "id": "benchmark",
                "name": "BenchmarkComparison",
                "file": "benchmark.md",
                "description": "SPY·QQQ 대비 포트폴리오 성과 벤치마크 비교기",
                "team_id": "monitoring",
                "is_active": True,
            },
            {
                "id": "daily_feedback",
                "name": "DailyFeedback",
                "file": "daily_feedback.md",
                "description": "일일 매매 결과 분석 및 RAG 문서 업데이트",
                "team_id": "monitoring",
                "is_active": True,
            },
            {
                "id": "weekly_analysis",
                "name": "WeeklyAnalysis",
                "file": "weekly_analysis.md",
                "description": "주간 성과 종합 리포트 생성기",
                "team_id": "monitoring",
                "is_active": True,
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------


def _resolve_agent_team(agent_id: str) -> str:
    """에이전트 ID로 소속 팀 이름을 조회한다."""
    for team in AGENT_TEAMS:
        for agent in team["agents"]:
            if agent["id"] == agent_id:
                return team["name"]
    return "알 수 없음"


def _resolve_agent_name(agent_id: str) -> str:
    """에이전트 ID로 에이전트 이름을 조회한다."""
    for team in AGENT_TEAMS:
        for agent in team["agents"]:
            if agent["id"] == agent_id:
                return agent["name"]
    return agent_id


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

agent_router = APIRouter(tags=["agents"])


@agent_router.get("/agents/list")
async def get_agents_list() -> dict:
    """에이전트 목록을 팀별로 반환한다."""
    try:
        return {"teams": AGENT_TEAMS}
    except Exception as exc:
        logger.error("에이전트 목록 조회 실패: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@agent_router.get("/agents/{agent_id}")
async def get_agent_detail(agent_id: str) -> dict:
    """특정 에이전트의 .md 파일 내용을 반환한다."""
    try:
        if agent_id not in ALLOWED_AGENT_IDS:
            raise HTTPException(
                status_code=404,
                detail=f"에이전트 '{agent_id}'를 찾을 수 없습니다.",
            )

        md_path = _AGENTS_DIR / f"{agent_id}.md"
        if not md_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"에이전트 파일 '{agent_id}.md'가 존재하지 않습니다.",
            )

        content = await asyncio.to_thread(md_path.read_text, encoding="utf-8")
        return {
            "id": agent_id,
            "name": _resolve_agent_name(agent_id),
            "team": _resolve_agent_team(agent_id),
            "content": content,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("에이전트 상세 조회 실패 (%s): %s", agent_id, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@agent_router.put("/agents/{agent_id}")
async def update_agent_detail(
    agent_id: str,
    body: dict,
    _: None = Depends(verify_api_key),
) -> dict:
    """특정 에이전트의 .md 파일 내용을 수정한다."""
    try:
        if agent_id not in ALLOWED_AGENT_IDS:
            raise HTTPException(
                status_code=404,
                detail=f"에이전트 '{agent_id}'를 찾을 수 없습니다.",
            )

        new_content = body.get("content")
        if new_content is None:
            raise HTTPException(
                status_code=400,
                detail="요청 바디에 'content' 필드가 필요합니다.",
            )

        if not isinstance(new_content, str):
            raise HTTPException(
                status_code=400,
                detail="'content' 필드는 문자열이어야 합니다.",
            )

        md_path = _AGENTS_DIR / f"{agent_id}.md"
        _AGENTS_DIR.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(md_path.write_text, new_content, encoding="utf-8")
        logger.info("에이전트 파일 업데이트 완료: %s", agent_id)

        return {"success": True, "id": agent_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("에이전트 파일 업데이트 실패 (%s): %s", agent_id, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")
