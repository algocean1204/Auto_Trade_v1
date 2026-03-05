"""SDK 백엔드 -- Claude CLI(로컬 SDK)를 사용한 AI 호출이다."""
from __future__ import annotations

import asyncio
import json
import os

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


class SdkBackend:
    """Claude CLI(SDK)를 사용하는 AI 백엔드이다.

    claude 명령어를 서브프로세스로 실행하여 AI 응답을 받는다.
    CLAUDECODE 환경변수를 제거하여 중첩 세션 오류를 방지한다.
    --max-tokens 플래그는 Claude CLI에서 지원하지 않으므로 사용하지 않는다.
    create_subprocess_exec를 사용하여 쉘 인젝션을 방지한다.
    """

    def __init__(self, timeout: int = 120) -> None:
        self._timeout = timeout
        _logger.info("SdkBackend 초기화 완료 (timeout=%ds)", timeout)

    async def send_text(
        self,
        prompt: str,
        system: str = "",
        model: str = "sonnet",
        max_tokens: int = 4096,
    ) -> AiBackendResponse:
        """Claude CLI로 텍스트 프롬프트를 전송한다.

        max_tokens는 CLI에서 지원하지 않아 인터페이스 호환용으로만 유지한다.
        시스템 프롬프트가 있으면 --system-prompt 플래그로 전달한다.
        인자 배열을 직접 전달하므로 쉘 인젝션 위험이 없다.
        """
        resolved = _MODEL_MAP.get(model, model)

        # CLI 명령어를 구성한다 -- 인자 배열로 직접 전달하여 쉘 인젝션을 방지한다
        cmd: list[str] = [
            "claude",
            "--print",
            "--output-format", "json",
            "--model", resolved,
        ]
        if system:
            cmd.extend(["--system-prompt", system])

        # 중첩 Claude 세션 오류 방지를 위해 CLAUDECODE를 제거한다
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=self._timeout,
            )

            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                _logger.error(
                    "Claude CLI 실행 실패 (returncode=%d): %s",
                    proc.returncode,
                    err_msg,
                )
                raise AiError(message="Claude CLI 실행 실패", detail=err_msg)

            raw = stdout.decode("utf-8", errors="replace").strip()
            content = self._parse_output(raw)
            _logger.debug(
                "SdkBackend 응답 수신 (model=%s, len=%d)",
                resolved,
                len(content),
            )
            return AiBackendResponse(content=content, model=resolved, source="sdk")

        except asyncio.TimeoutError:
            _logger.error("Claude CLI 타임아웃 (%ds 초과)", self._timeout)
            raise AiError(
                message="Claude CLI 타임아웃",
                detail=f"{self._timeout}초 초과",
            ) from None
        except AiError:
            raise
        except Exception as exc:
            _logger.exception("Claude CLI 호출 중 예상치 못한 오류 발생")
            raise AiError(message="Claude CLI 호출 실패", detail=str(exc)) from exc

    def _parse_output(self, raw: str) -> str:
        """CLI JSON 출력을 파싱하여 텍스트 콘텐츠를 추출한다.

        JSON 파싱에 실패하면 원본 텍스트를 그대로 반환한다.
        result 필드 → content 필드 순으로 우선 탐색한다.
        """
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                # result 필드가 있으면 우선 사용하고, 없으면 content 필드를 사용한다
                return data.get("result", data.get("content", str(data)))
            return str(data)
        except json.JSONDecodeError:
            # JSON이 아닌 경우 원본 텍스트를 그대로 반환한다
            return raw

    async def close(self) -> None:
        """SDK 백엔드는 정리할 영속 리소스가 없다."""
        _logger.info("SdkBackend 종료 완료")
