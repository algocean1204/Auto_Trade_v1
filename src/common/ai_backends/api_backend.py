"""API 백엔드 -- Anthropic Python SDK를 사용한 AI 호출이다."""
from __future__ import annotations

from src.common.ai_backends.base import AiBackendResponse
from src.common.error_handler import AiError
from src.common.logger import get_logger

_logger = get_logger(__name__)

# 모델 별칭 → 실제 모델 ID 매핑이다
_MODEL_MAP: dict[str, str] = {
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


class ApiBackend:
    """Anthropic API를 사용하는 AI 백엔드이다.

    anthropic 패키지의 AsyncAnthropic 클라이언트를 통해 API를 호출한다.
    lazy import를 사용하여 미설치 환경에서도 모듈 로드가 가능하다.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = self._create_client(api_key)
        _logger.info("ApiBackend 초기화 완료")

    def _create_client(self, api_key: str) -> object:
        """AsyncAnthropic 클라이언트를 생성한다.

        anthropic 패키지가 설치되지 않은 경우 AiError를 발생시킨다.
        """
        try:
            from anthropic import AsyncAnthropic  # type: ignore[import-untyped]
            return AsyncAnthropic(api_key=api_key)
        except ImportError as exc:
            raise AiError(message="anthropic SDK 미설치", detail=str(exc)) from exc

    async def send_text(
        self,
        prompt: str,
        system: str = "",
        model: str = "sonnet",
        max_tokens: int = 4096,
    ) -> AiBackendResponse:
        """Anthropic API로 텍스트 프롬프트를 전송한다.

        시스템 프롬프트가 있으면 system 파라미터로 전달한다.
        API 오류 발생 시 AiError로 래핑하여 상위로 전파한다.
        """
        resolved = _MODEL_MAP.get(model, model)
        kwargs: dict = {
            "model": resolved,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        try:
            response = await self._client.messages.create(**kwargs)  # type: ignore[union-attr]
            text = response.content[0].text if response.content else ""
            _logger.debug(
                "ApiBackend 응답 수신 (model=%s, len=%d)",
                resolved,
                len(text),
            )
            # 토큰 사용량 기록
            input_tok = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
            output_tok = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
            from src.common.token_tracker import record_usage
            record_usage(
                model=resolved, source="api",
                input_tokens=input_tok, output_tokens=output_tok,
            )
            return AiBackendResponse(content=text, model=resolved, source="api")
        except Exception as exc:
            _logger.error("Anthropic API 호출 실패: %s", exc)
            from src.common.token_tracker import record_error
            record_error(model=resolved, source="api")
            raise AiError(message="Anthropic API 호출 실패", detail=str(exc)) from exc

    async def close(self) -> None:
        """AsyncAnthropic 클라이언트를 정리한다."""
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()  # type: ignore[union-attr]
        _logger.info("ApiBackend 종료 완료")
