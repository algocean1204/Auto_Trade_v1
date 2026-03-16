"""에이전트 메타데이터 모델을 정의한다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentMeta:
    """개별 에이전트의 정적 메타데이터이다.

    kind는 "ai"(Claude 페르소나) 또는 "module"(시스템 모듈)이다.
    AI 에이전트는 source_path가 None이다.
    """

    id: str
    name: str
    role: str
    team: str
    kind: str
    source_path: str | None = None
