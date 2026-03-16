"""AiGateway (C0.5) -- Claude SDK/API + GGUF 로컬 모델 통합 AI 호출 인터페이스이다.

Claude: mode "sdk"(CLI 기본), "api"(Anthropic API), "hybrid"(SDK 우선 + API 폴백)
로컬 분류: Qwen2.5+Llama3.1+DeepSeek-R1 3중 앙상블 (local_llm.py)
로컬 번역: Bllossom-8B 전용 (local_llm.py)

모델별 동시 호출 제한 (Semaphore):
- opus: 최대 4개 동시 (3+1 팀 = 4 Opus 병렬)
- sonnet: 최대 6개 동시 (Layer 1 4에이전트 + 에스컬레이션 + 여유 1)
- haiku: 최대 4개 동시
"""
from __future__ import annotations

import asyncio
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

    # 모델별 동시 호출 제한 — Anthropic rate limit 보호
    _CONCURRENCY_LIMITS: dict[str, int] = {
        "opus": 4,
        "sonnet": 6,
        "haiku": 4,
    }

    def __init__(self, api_key: str = "", mode: str = "sdk") -> None:
        self._mode = mode
        self._api_key = api_key
        self._sdk_backend = SdkBackend()
        self._api_backend: ApiBackend | None = None
        if api_key and mode in ("api", "hybrid"):
            self._api_backend = ApiBackend(api_key=api_key)
        # 모델별 Semaphore 생성
        self._semaphores: dict[str, asyncio.Semaphore] = {
            model: asyncio.Semaphore(limit)
            for model, limit in self._CONCURRENCY_LIMITS.items()
        }
        logger.info("AiClient 초기화 완료 (mode=%s)", mode)

    def _get_semaphore(self, model: str) -> asyncio.Semaphore:
        """모델명에 해당하는 Semaphore를 반환한다. 미등록 모델은 sonnet 제한 사용."""
        return self._semaphores.get(model, self._semaphores["sonnet"])

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
        """Claude SDK/API로 텍스트 프롬프트를 보내고 응답을 받는다.

        모델별 Semaphore로 동시 호출 수를 제한하여 rate limit 429를 방지한다.
        """
        sem = self._get_semaphore(model)
        async with sem:
            return await self._send_text_inner(prompt, system, model, max_tokens)

    # AI 호출 최대 재시도 횟수이다
    _AI_MAX_RETRIES: int = 3

    async def _send_text_inner(
        self,
        prompt: str,
        system: str,
        model: str,
        max_tokens: int,
    ) -> AiResponse:
        """send_text의 내부 구현이다. Semaphore 획득 후 호출된다.

        일시적 장애(503, 타임아웃 등) 시 지수 백오프로 최대 3회 재시도한다.
        """
        last_exc: Exception | None = None
        for _attempt in range(self._AI_MAX_RETRIES):
            try:
                return await self._send_text_once(prompt, system, model, max_tokens)
            except Exception as exc:
                last_exc = exc
                if _attempt == self._AI_MAX_RETRIES - 1:
                    raise
                _wait = 1.0 * (2 ** _attempt)
                logger.warning(
                    "AI 호출 실패 → %.1f초 후 재시도 (%d/%d): %s",
                    _wait, _attempt + 1, self._AI_MAX_RETRIES, exc,
                )
                await asyncio.sleep(_wait)
        # 이론상 도달 불가이지만 타입 안전을 위해 예외를 발생시킨다
        raise AiError(message="AI 재시도 루프 이탈", detail=str(last_exc))

    async def _send_text_once(
        self,
        prompt: str,
        system: str,
        model: str,
        max_tokens: int,
    ) -> AiResponse:
        """단일 AI 텍스트 호출을 수행한다."""
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
            # 토큰 사용량 기록 (API 과금)
            input_tok = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
            output_tok = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
            from src.common.token_tracker import record_usage
            record_usage(model=resolved, source="api", input_tokens=input_tok, output_tokens=output_tok)
            return AiResponse(
                content="\n".join(parts),
                model=resolved,
                source="api",
            )
        except Exception as exc:
            from src.common.token_tracker import record_error
            record_error(model=resolved, source="api")
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

    async def fast_local_classify(self, text: str, categories: list[str]) -> ClassifyResult:
        """센티넬용 빠른 3모델 앙상블 분류이다.

        입력 200자 제한으로 헤드라인 스캔 속도를 우선한다.
        """
        from src.common.local_llm import fast_classify

        category, confidence, reasoning = await fast_classify(text, categories)
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
