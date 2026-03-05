"""AI 백엔드 프로토콜 -- 모든 백엔드가 구현할 인터페이스이다."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class AiBackendResponse(BaseModel):
    """AI 백엔드 응답이다."""

    content: str
    model: str
    source: str  # "sdk" 또는 "api"


@runtime_checkable
class AiBackend(Protocol):
    """AI 백엔드 프로토콜이다. SDK와 API 모두 이 인터페이스를 구현한다."""

    async def send_text(
        self,
        prompt: str,
        system: str = "",
        model: str = "sonnet",
        max_tokens: int = 4096,
    ) -> AiBackendResponse:
        """텍스트 프롬프트를 전송하고 응답을 반환한다."""
        ...

    async def close(self) -> None:
        """리소스를 정리한다."""
        ...
