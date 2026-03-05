"""AiGateway (C0.5) -- Claude SDK/API + GGUF 로컬 모델 통합 AI 호출 인터페이스이다.

Claude: mode "sdk"(CLI 기본), "api"(Anthropic API), "hybrid"(SDK 우선 + API 폴백)
로컬 분류: Qwen2.5+Llama3.1+DeepSeek-R1 3중 앙상블 (local_llm.py)
로컬 번역: Bllossom-8B 전용 (local_llm.py)
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from src.common.ai_backends.api_backend import ApiBackend
from src.common.ai_backends.sdk_backend import SdkBackend
from src.common.error_handler import AiError
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_instance: AiClient | None = None


class AiResponse(BaseModel):
    """AI 응답 결과이다."""

    content: str
    model: str
    source: Literal["claude", "local", "sdk", "api"]
    confidence: float = 1.0


class ClassifyResult(BaseModel):
    """분류 결과이다."""

    category: str
    confidence: float
    reasoning: str = ""


class AiClient:
    """AI 통합 클라이언트이다.

    Claude SDK/API로 텍스트 생성, GGUF 로컬 모델로 분류/번역을 처리한다.
    분류: 3모델 앙상블 다수결 (Qwen2.5 + Llama3.1 + DeepSeek-R1)
    번역: Bllossom-8B 전용 (번역만 수행, 추론 없음)
    """

    def __init__(self, api_key: str = "", mode: str = "sdk") -> None:
        self._mode = mode
        self._api_key = api_key
        self._sdk_backend = SdkBackend()
        self._api_backend: ApiBackend | None = None
        if api_key and mode in ("api", "hybrid"):
            self._api_backend = ApiBackend(api_key=api_key)
        logger.info("AiClient 초기화 완료 (mode=%s)", mode)

    @property
    def mode(self) -> str:
        """현재 활성 백엔드 모드를 반환한다."""
        return self._mode

    def switch_backend(self, mode: str) -> None:
        """런타임에 백엔드를 전환한다."""
        if mode == "api" and self._api_backend is None:
            if not self._api_key:
                raise AiError(message="API 모드 전환 실패: API 키 미설정")
            self._api_backend = ApiBackend(api_key=self._api_key)
        self._mode = mode
        logger.info("AI 백엔드 전환: %s", mode)

    async def send_text(
        self,
        prompt: str,
        system: str = "",
        model: str = "sonnet",
        max_tokens: int = 4096,
    ) -> AiResponse:
        """Claude SDK/API로 텍스트 프롬프트를 보내고 응답을 받는다."""
        if self._mode in ("sdk", "hybrid", "local"):
            try:
                resp = await self._sdk_backend.send_text(prompt, system, model, max_tokens)
                return AiResponse(
                    content=resp.content,
                    model=resp.model,
                    source="sdk",
                )
            except Exception as exc:
                if self._mode in ("sdk", "local"):
                    raise AiError(message="SDK 호출 실패", detail=str(exc)) from exc
                logger.warning("SDK 실패, API 폴백 진행: %s", exc)

        if self._api_backend is not None:
            try:
                resp = await self._api_backend.send_text(prompt, system, model, max_tokens)
                return AiResponse(
                    content=resp.content,
                    model=resp.model,
                    source="api",
                )
            except Exception as exc:
                raise AiError(message="API 호출 실패", detail=str(exc)) from exc

        raise AiError(
            message="텍스트 생성 불가",
            detail=f"mode={self._mode}, api_backend=None",
        )

    async def send_with_tools(
        self,
        prompt: str,
        tools: list[dict],
        model: str = "sonnet",
    ) -> AiResponse:
        """도구 호출이 포함된 프롬프트를 보낸다. API 모드 전용이다."""
        if self._api_backend is None:
            raise AiError(message="도구 호출은 API 모드에서만 지원한다")

        try:
            _model_map: dict[str, str] = {
                "opus": "claude-opus-4-6",
                "sonnet": "claude-sonnet-4-6",
                "haiku": "claude-haiku-4-5-20251001",
            }
            resolved = _model_map.get(model, model)
            response = await self._api_backend._client.messages.create(  # type: ignore[union-attr]
                model=resolved,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                tools=tools,
            )
            parts: list[str] = []
            for block in response.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                elif hasattr(block, "input"):
                    parts.append(str(block.input))
            return AiResponse(
                content="\n".join(parts),
                model=resolved,
                source="api",
            )
        except Exception as exc:
            raise AiError(message="도구 호출 실패", detail=str(exc)) from exc

    async def local_classify(self, text: str, categories: list[str]) -> ClassifyResult:
        """GGUF 3모델 앙상블로 텍스트를 분류한다.

        Qwen2.5-7B + Llama-3.1-8B + DeepSeek-R1-8B 다수결 투표이다.
        """
        from src.common.local_llm import ensemble_classify

        category, confidence, reasoning = await ensemble_classify(text, categories)
        return ClassifyResult(
            category=category, confidence=confidence, reasoning=reasoning,
        )

    async def local_translate(self, text: str, target_lang: str = "ko") -> str:
        """Bllossom-8B로 텍스트를 번역한다. 번역 전용, 추론 없음."""
        from src.common.local_llm import translate

        return await translate(text, target_lang)

    async def close(self) -> None:
        """클라이언트 리소스를 정리한다."""
        await self._sdk_backend.close()
        if self._api_backend is not None:
            await self._api_backend.close()
        logger.info("AiClient 종료 완료")


def get_ai_client(api_key: str | None = None, mode: str = "sdk") -> AiClient:
    """AiClient 싱글톤을 반환한다."""
    global _instance
    if _instance is not None:
        return _instance
    _instance = AiClient(api_key=api_key or "", mode=mode)
    return _instance


def reset_ai_client() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
