"""에이전트 레지스트리 -- 30개 에이전트의 단일 진실 소스이다.

AI 페르소나(5개) + 시스템 모듈(25개) 에이전트를 관리하며
팀 구조, 문서 경로 조회 기능을 제공한다.
"""
from __future__ import annotations

from pathlib import Path

from src.agents.agent_meta import AgentMeta

# 문서 디렉터리 경로이다.
_DOCS_DIR: Path = Path(__file__).resolve().parent / "docs"

# ── AI 에이전트 (5개, Claude 페르소나) ──

_AI_AGENTS: tuple[AgentMeta, ...] = (
    AgentMeta(
        id="master_analyst", name="Master Analyst",
        role="종합 분석/매매 판단", team="decision", kind="ai",
    ),
    AgentMeta(
        id="news_analyst", name="News Analyst",
        role="뉴스 분석/영향도 평가", team="analysis", kind="ai",
    ),
    AgentMeta(
        id="risk_manager", name="Risk Manager",
        role="리스크 관리/안전장치", team="decision", kind="ai",
    ),
    AgentMeta(
        id="macro_strategist", name="Macro Strategist",
        role="거시 경제 분석", team="decision", kind="ai",
    ),
    AgentMeta(
        id="short_term_trader", name="Short Term Trader",
        role="단기 매매 전략", team="decision", kind="ai",
    ),
)

# ── 시스템 모듈 에이전트 (25개) ──

_MODULE_AGENTS: tuple[AgentMeta, ...] = (
    # 크롤링팀
    AgentMeta(
        id="crawl_engine", name="Crawl Engine",
        role="뉴스 크롤링 엔진", team="crawling", kind="module",
        source_path="src/crawlers/engine/crawl_engine.py",
    ),
    AgentMeta(
        id="crawl_scheduler", name="Crawl Scheduler",
        role="크롤링 스케줄러", team="crawling", kind="module",
        source_path="src/crawlers/scheduler/crawl_scheduler.py",
    ),
    AgentMeta(
        id="crawl_verifier", name="Crawl Verifier",
        role="크롤링 검증", team="crawling", kind="module",
        source_path="src/crawlers/verifier/crawl_verifier.py",
    ),
    # 분석팀
    AgentMeta(
        id="news_classifier", name="News Classifier",
        role="뉴스 분류", team="analysis", kind="module",
        source_path="src/analysis/classifier/news_classifier.py",
    ),
    AgentMeta(
        id="mlx_classifier", name="MLX Classifier",
        role="로컬 ML 분류기", team="analysis", kind="module",
        source_path="src/common/local_llm.py",
    ),
    AgentMeta(
        id="key_news_filter", name="Key News Filter",
        role="핵심 뉴스 필터링", team="analysis", kind="module",
        source_path="src/analysis/classifier/key_news_filter.py",
    ),
    AgentMeta(
        id="situation_tracker", name="Situation Tracker",
        role="진행 상황 추적", team="analysis", kind="module",
        source_path="src/analysis/classifier/situation_tracker.py",
    ),
    AgentMeta(
        id="regime_detector", name="Regime Detector",
        role="시장 레짐 탐지", team="analysis", kind="module",
        source_path="src/analysis/regime/regime_detector.py",
    ),
    AgentMeta(
        id="claude_client", name="Claude Client",
        role="Claude AI 통신", team="analysis", kind="module",
        source_path="src/common/ai_gateway.py",
    ),
    AgentMeta(
        id="knowledge_manager", name="Knowledge Manager",
        role="지식 관리(RAG)", team="analysis", kind="module",
        source_path="src/optimization/rag/knowledge_manager.py",
    ),
    # 의사결정팀
    AgentMeta(
        id="decision_maker", name="Decision Maker",
        role="매매 의사결정", team="decision", kind="module",
        source_path="src/analysis/decision/decision_maker.py",
    ),
    AgentMeta(
        id="entry_strategy", name="Entry Strategy",
        role="진입 전략", team="decision", kind="module",
        source_path="src/strategy/entry/entry_strategy.py",
    ),
    AgentMeta(
        id="exit_strategy", name="Exit Strategy",
        role="청산 전략", team="decision", kind="module",
        source_path="src/strategy/exit/exit_strategy.py",
    ),
    # 실행팀
    AgentMeta(
        id="order_manager", name="Order Manager",
        role="주문 관리", team="execution", kind="module",
        source_path="src/executor/order/order_manager.py",
    ),
    AgentMeta(
        id="kis_client", name="KIS Client",
        role="KIS API 클라이언트", team="execution", kind="module",
        source_path="src/executor/broker/kis_api.py",
    ),
    AgentMeta(
        id="position_monitor", name="Position Monitor",
        role="포지션 모니터링", team="execution", kind="module",
        source_path="src/executor/position/position_monitor.py",
    ),
    # 안전팀
    AgentMeta(
        id="hard_safety", name="Hard Safety",
        role="하드 안전장치", team="safety", kind="module",
        source_path="src/safety/hard_safety/hard_safety.py",
    ),
    AgentMeta(
        id="safety_checker", name="Safety Checker",
        role="안전 검사", team="safety", kind="module",
        source_path="src/safety/hard_safety/safety_checker.py",
    ),
    AgentMeta(
        id="emergency_protocol", name="Emergency Protocol",
        role="비상 프로토콜", team="safety", kind="module",
        source_path="src/safety/emergency/emergency_protocol.py",
    ),
    AgentMeta(
        id="capital_guard", name="Capital Guard",
        role="자본 보호/손실 한도", team="safety", kind="module",
        source_path="src/safety/guards/capital_guard.py",
    ),
    # 모니터링팀
    AgentMeta(
        id="alert_manager", name="Alert Manager",
        role="알림 관리", team="monitoring", kind="module",
        source_path="src/monitoring/endpoints/alerts.py",
    ),
    AgentMeta(
        id="telegram_notifier", name="Telegram Notifier",
        role="텔레그램 알림", team="monitoring", kind="module",
        source_path="src/monitoring/telegram/telegram_notifier.py",
    ),
    AgentMeta(
        id="benchmark", name="Benchmark",
        role="벤치마크 비교 분석", team="monitoring", kind="module",
        source_path="src/monitoring/endpoints/benchmark.py",
    ),
    AgentMeta(
        id="daily_feedback", name="Daily Feedback",
        role="일일 피드백 생성", team="monitoring", kind="module",
        source_path="src/analysis/feedback/eod_feedback_report.py",
    ),
    AgentMeta(
        id="weekly_analysis", name="Weekly Analysis",
        role="주간 분석", team="monitoring", kind="module",
        source_path="src/orchestration/phases/weekly_analysis.py",
    ),
)

# ── 전체 에이전트 인덱스 ──

_ALL_AGENTS: dict[str, AgentMeta] = {
    a.id: a for a in (*_AI_AGENTS, *_MODULE_AGENTS)
}

# ── 팀 구성 (순서 보존) ──

_TEAM_ORDER: tuple[str, ...] = (
    "crawling", "analysis", "decision", "execution", "safety", "monitoring",
)

_TEAMS: dict[str, list[str]] = {
    "crawling": ["crawl_engine", "crawl_scheduler", "crawl_verifier"],
    "analysis": [
        "news_analyst", "news_classifier", "mlx_classifier",
        "key_news_filter", "situation_tracker",
        "regime_detector", "claude_client", "knowledge_manager",
    ],
    "decision": [
        "master_analyst", "decision_maker", "entry_strategy",
        "exit_strategy", "macro_strategist", "short_term_trader",
        "risk_manager",
    ],
    "execution": ["order_manager", "kis_client", "position_monitor"],
    "safety": [
        "hard_safety", "safety_checker", "emergency_protocol", "capital_guard",
    ],
    "monitoring": [
        "alert_manager", "telegram_notifier", "benchmark",
        "daily_feedback", "weekly_analysis",
    ],
}


# ── 공개 API ──

def get_all_agents() -> list[AgentMeta]:
    """등록된 모든 에이전트를 반환한다."""
    return list(_ALL_AGENTS.values())


def get_agent(agent_id: str) -> AgentMeta | None:
    """에이전트 ID로 메타데이터를 조회한다."""
    return _ALL_AGENTS.get(agent_id)


def get_team_members(team_id: str) -> list[AgentMeta]:
    """특정 팀의 에이전트 목록을 반환한다."""
    member_ids = _TEAMS.get(team_id, [])
    return [_ALL_AGENTS[mid] for mid in member_ids if mid in _ALL_AGENTS]


def get_all_teams() -> dict[str, list[AgentMeta]]:
    """모든 팀과 소속 에이전트를 반환한다. 순서가 보존된다."""
    return {
        tid: get_team_members(tid)
        for tid in _TEAM_ORDER
    }


def get_team_ids() -> tuple[str, ...]:
    """팀 ID 목록을 순서대로 반환한다."""
    return _TEAM_ORDER


def get_docs_dir() -> Path:
    """에이전트 문서 디렉터리 경로를 반환한다."""
    return _DOCS_DIR


def get_agent_doc_path(agent_id: str) -> Path | None:
    """에이전트 .md 문서 경로를 반환한다. 파일이 없으면 None이다."""
    path = _DOCS_DIR / f"{agent_id}.md"
    return path if path.is_file() else None
