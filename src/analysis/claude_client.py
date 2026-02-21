"""
Claude 클라이언트
- 실행 모드: local (Claude Code MAX 플랜 CLI) / api (Anthropic API 키)
- 모델 라우팅: Sonnet(빠름) vs Opus(정확)
- 비동기 호출 (async/await)
- 에러 핸들링 + 지수 백오프 재시도 (API 모드)
- 토큰 사용량 추적 (모델별 분리)
- 응답 캐싱 (동일 요청 방지)
- JSON 응답 파싱
"""
import asyncio
import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from enum import Enum

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ModelType(Enum):
    """사용 가능한 Claude 모델."""

    SONNET = "claude-sonnet-4-5-20250929"
    OPUS = "claude-opus-4-6"


# 태스크별 모델 라우팅 매핑
MODEL_ROUTING: dict[str, ModelType] = {
    # Sonnet (빠르고 효율적)
    "news_classification": ModelType.SONNET,
    "delta_analysis": ModelType.SONNET,
    "crawl_verification": ModelType.SONNET,
    "telegram_intent": ModelType.SONNET,
    "telegram_chat": ModelType.SONNET,
    # Opus (정확도 최우선)
    "trading_decision": ModelType.OPUS,
    "overnight_judgment": ModelType.OPUS,
    "regime_detection": ModelType.OPUS,
    "daily_feedback": ModelType.OPUS,
    "weekly_analysis": ModelType.OPUS,
    "monthly_review": ModelType.OPUS,
    "continuous_analysis": ModelType.OPUS,
    # Historical analysis team (Sonnet for cost efficiency on bulk historical data)
    "historical_market": ModelType.SONNET,
    "historical_company": ModelType.SONNET,
    "historical_sector": ModelType.SONNET,
    "historical_timeline": ModelType.SONNET,
    "realtime_stock_analysis": ModelType.OPUS,
    # 종합분석팀 (Opus — 3분석관 + 리더)
    "comprehensive_macro": ModelType.OPUS,
    "comprehensive_technical": ModelType.OPUS,
    "comprehensive_sentiment": ModelType.OPUS,
    "comprehensive_leader": ModelType.OPUS,
    "comprehensive_eod_report": ModelType.OPUS,
}

# 모델별 가격 (USD per 1M tokens) — API 모드에서만 의미 있음
_MODEL_PRICING: dict[ModelType, dict[str, float]] = {
    ModelType.SONNET: {"input": 3.0, "output": 15.0},
    ModelType.OPUS: {"input": 15.0, "output": 75.0},
}

# 재시도 대상 HTTP 상태 코드
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}

# 기본 최대 출력 토큰 수
_DEFAULT_MAX_TOKENS: int = 4096

# 재시도 설정 기본값
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_DELAY = 1.0  # 초

# 캐시 기본 설정
_DEFAULT_CACHE_MAX_SIZE = 128
_DEFAULT_CACHE_TTL = 300  # 5분

# JSON 코드블록 패턴: ```json ... ``` 또는 ``` ... ```
_JSON_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*\n?([\s\S]*?)\n?```",
    re.DOTALL,
)


class _LRUCache:
    """TTL 기반 LRU 캐시.

    동일한 프롬프트 + 태스크 조합에 대한 중복 API 호출을 방지한다.
    """

    def __init__(self, max_size: int = _DEFAULT_CACHE_MAX_SIZE, ttl: int = _DEFAULT_CACHE_TTL) -> None:
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def get(self, key: str) -> dict | None:
        """캐시에서 값을 조회한다. 만료되었으면 None을 반환한다."""
        if key not in self._cache:
            return None
        ts, value = self._cache[key]
        if time.monotonic() - ts > self._ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def put(self, key: str, value: dict) -> None:
        """값을 캐시에 저장한다. 최대 크기 초과 시 가장 오래된 항목을 제거한다."""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (time.monotonic(), value)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        """캐시를 초기화한다."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


class ClaudeClient:
    """Claude 비동기 클라이언트 래퍼.

    두 가지 실행 모드를 지원한다:
      - local: Claude Code MAX 플랜 CLI(``claude`` 명령)를 subprocess로 호출한다.
               API 키가 불필요하며 호출 비용이 발생하지 않는다.
      - api: Anthropic SDK를 직접 사용한다. ``anthropic_api_key`` 설정이 필요하다.

    태스크 유형에 따라 적절한 모델을 자동으로 선택하고,
    토큰 사용량을 모델별로 분리 추적한다.
    에러 발생 시 지수 백오프로 재시도(API 모드)하며,
    동일 요청에 대한 응답을 캐싱한다.
    """

    def __init__(
        self,
        mode: str = "local",
        api_key: str | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        cache_max_size: int = _DEFAULT_CACHE_MAX_SIZE,
        cache_ttl: int = _DEFAULT_CACHE_TTL,
    ) -> None:
        """ClaudeClient를 초기화한다.

        Args:
            mode: "local" (Claude Code MAX 플랜) 또는 "api" (Anthropic API 키).
            api_key: API 모드일 때 사용할 Anthropic API 키.
                     None이면 설정 파일에서 읽는다.
            max_retries: API 모드에서 지수 백오프 최대 재시도 횟수.
            cache_max_size: LRU 캐시 최대 항목 수.
            cache_ttl: 캐시 TTL (초).
        """
        settings = get_settings()
        self.mode = mode

        if self.mode == "api":
            import anthropic as _anthropic
            resolved_key = api_key or settings.anthropic_api_key
            if not resolved_key:
                raise ValueError(
                    "api 모드에서는 anthropic_api_key가 설정되어야 한다. "
                    "로컬 모드를 사용하려면 CLAUDE_MODE=local 로 설정하라."
                )
            self.client = _anthropic.AsyncAnthropic(api_key=resolved_key)
            self._anthropic = _anthropic
        else:
            # local 모드: Claude Code CLI를 subprocess로 호출한다.
            self.client = None
            self._anthropic = None

        self._max_retries = max_retries
        self._cache = _LRUCache(max_size=cache_max_size, ttl=cache_ttl)

        # 모델별 토큰 추적
        self._usage: dict[str, dict[str, int]] = {}
        for model in ModelType:
            self._usage[model.value] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
            }

        logger.info(
            "ClaudeClient 초기화 완료 | mode=%s | max_retries=%d | cache_size=%d | cache_ttl=%ds",
            self.mode,
            max_retries,
            cache_max_size,
            cache_ttl,
        )

    async def call(
        self,
        prompt: str,
        task_type: str,
        system_prompt: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 0.3,
        use_cache: bool = True,
    ) -> dict:
        """Claude를 호출하고 결과를 반환한다.

        실행 모드에 따라 로컬 CLI 또는 Anthropic API를 사용한다.

        Args:
            prompt: 사용자 프롬프트.
            task_type: MODEL_ROUTING 키. 등록되지 않은 키는 Sonnet으로 폴백한다.
            system_prompt: 시스템 프롬프트 (선택).
            max_tokens: 최대 출력 토큰 수.
            temperature: 샘플링 온도. 낮을수록 결정적이다. (API 모드에서만 적용)
            use_cache: 캐싱 사용 여부. 기본 True.

        Returns:
            ``{"content", "model", "input_tokens", "output_tokens", "cached"}`` 형태의 딕셔너리.

        Raises:
            RuntimeError: local 모드에서 CLI 호출에 실패한 경우.
            anthropic.APIError: api 모드에서 재시도 횟수 초과 후에도 실패한 경우.
        """
        model = MODEL_ROUTING.get(task_type, ModelType.SONNET)

        # 캐시 조회
        cache_key = ""
        if use_cache:
            cache_key = self._make_cache_key(prompt, task_type, system_prompt, temperature)
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info(
                    "캐시 히트 | task=%s | model=%s",
                    task_type,
                    model.value,
                )
                return {**cached, "cached": True}

        logger.info(
            "Claude 호출 시작 | mode=%s | task=%s | model=%s",
            self.mode,
            task_type,
            model.value,
        )

        if self.mode == "local":
            raw = await self._call_local(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model.value,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            input_tokens = raw["input_tokens"]
            output_tokens = raw["output_tokens"]
            content = raw["text"]
        else:
            messages = [{"role": "user", "content": prompt}]
            kwargs: dict = {
                "model": model.value,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            if system_prompt:
                kwargs["system"] = system_prompt

            response = await self._call_with_retry(kwargs, task_type)
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            content = response.content[0].text

        # 토큰 누적
        usage = self._usage[model.value]
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens
        usage["calls"] += 1

        logger.info(
            "Claude 호출 완료 | task=%s | in=%d out=%d tokens",
            task_type,
            input_tokens,
            output_tokens,
        )

        result = {
            "content": content,
            "model": model.value,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached": False,
        }

        # 캐시 저장
        if use_cache and cache_key:
            self._cache.put(cache_key, result)

        return result

    async def call_json(
        self,
        prompt: str,
        task_type: str,
        system_prompt: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        use_cache: bool = True,
    ) -> dict | list:
        """JSON 응답을 기대하는 Claude 호출.

        응답 텍스트에서 JSON을 추출하여 파이썬 객체로 반환한다.
        코드블록(```json ... ```) 안에 있거나 직접 JSON인 경우 모두 처리한다.

        Args:
            prompt: 사용자 프롬프트.
            task_type: MODEL_ROUTING 키.
            system_prompt: 시스템 프롬프트 (선택).
            max_tokens: 최대 출력 토큰 수.
            use_cache: 캐싱 사용 여부.

        Returns:
            파싱된 JSON (dict 또는 list).

        Raises:
            ValueError: 응답에서 유효한 JSON을 찾지 못한 경우.
        """
        result = await self.call(
            prompt=prompt,
            task_type=task_type,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=0.1,  # JSON 응답은 결정적으로
            use_cache=use_cache,
        )
        content: str = result["content"]
        parsed = self._extract_json(content)
        return parsed

    async def _call_local(
        self,
        prompt: str,
        system_prompt: str | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> dict:
        """Claude Code MAX 플랜 CLI를 subprocess로 호출한다.

        ``claude --print`` 명령을 비동기 subprocess로 실행하며,
        프롬프트는 stdin으로 전달한다. temperature는 CLI에서 지원되지 않으므로
        인자로는 받되 적용하지 않는다.

        Args:
            prompt: 사용자 프롬프트. stdin으로 전달된다.
            system_prompt: 시스템 프롬프트. None이면 생략한다.
            model: Claude 모델 ID.
            max_tokens: 최대 출력 토큰 수.
            temperature: 샘플링 온도. CLI에서는 무시된다.

        Returns:
            ``{"text", "model", "input_tokens", "output_tokens"}`` 딕셔너리.
            input_tokens/output_tokens는 근사값이다.

        Raises:
            RuntimeError: CLI 프로세스가 비정상 종료된 경우.
        """
        cmd = [
            "claude",
            "--print",
            "--model", model,
            "--output-format", "text",
        ]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        logger.debug(
            "local 모드 CLI 호출 | model=%s | system_prompt=%s",
            model,
            "있음" if system_prompt else "없음",
        )

        # CLAUDECODE 환경변수가 설정되어 있으면 중첩 세션 에러가 발생한다.
        # subprocess에서 이 변수를 제거하여 Claude CLI가 정상 동작하도록 한다.
        env = {**os.environ}
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE", None)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode("utf-8")),
                    timeout=300.0,
                )
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Claude CLI 프로세스 강제 종료 후 회수 타임아웃")
                raise RuntimeError(
                    "Claude CLI가 300초 이내에 응답하지 않았다. 프로세스를 강제 종료한다."
                )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "claude CLI를 찾을 수 없다. Claude Code가 PATH에 설치되어 있는지 확인하라."
            ) from exc

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.error(
                "Claude CLI 비정상 종료 | returncode=%d | stderr=%s",
                proc.returncode,
                err_msg[:500],
            )
            raise RuntimeError(
                f"Claude CLI 오류 (returncode={proc.returncode}): {err_msg[:300]}"
            )

        text = stdout.decode("utf-8", errors="replace").strip()

        # 토큰 수는 CLI에서 제공되지 않으므로 근사값을 사용한다 (4자 = 1토큰).
        approx_input = max(1, len(prompt) // 4)
        approx_output = max(1, len(text) // 4)

        logger.debug(
            "local 모드 CLI 완료 | approx_in=%d approx_out=%d",
            approx_input,
            approx_output,
        )

        return {
            "text": text,
            "model": model,
            "input_tokens": approx_input,
            "output_tokens": approx_output,
        }

    async def _call_with_retry(self, kwargs: dict, task_type: str) -> object:
        """지수 백오프로 Anthropic SDK API를 호출한다.

        rate limit(429), 서버 에러(500/502/503), overloaded(529)에 대해 재시도한다.
        API 모드에서만 호출된다.

        Args:
            kwargs: ``client.messages.create`` 에 전달할 인자.
            task_type: 로깅용 태스크 이름.

        Returns:
            API 응답 메시지.

        Raises:
            anthropic.APIStatusError: 재시도 횟수 초과 후에도 실패한 경우.
            anthropic.APIConnectionError: 네트워크 연결 실패 시.
        """
        import anthropic as _anthropic

        last_exception: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return await self.client.messages.create(**kwargs)
            except _anthropic.APIStatusError as exc:
                last_exception = exc
                if exc.status_code not in _RETRYABLE_STATUS_CODES:
                    logger.error(
                        "Claude API 비재시도 에러 | task=%s | status=%d | %s",
                        task_type,
                        exc.status_code,
                        exc.message,
                    )
                    raise

                if attempt >= self._max_retries:
                    break

                delay = _DEFAULT_BASE_DELAY * (2 ** attempt)
                # 429의 경우 retry-after 헤더 존재 시 사용
                if exc.status_code == 429:
                    retry_after = getattr(exc.response, "headers", {}).get("retry-after")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except (ValueError, TypeError):
                            pass

                logger.warning(
                    "Claude API 재시도 예정 | task=%s | attempt=%d/%d | status=%d | delay=%.1fs",
                    task_type,
                    attempt + 1,
                    self._max_retries,
                    exc.status_code,
                    delay,
                )
                await asyncio.sleep(delay)

            except _anthropic.APIConnectionError as exc:
                last_exception = exc
                if attempt >= self._max_retries:
                    break

                delay = _DEFAULT_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Claude API 연결 실패 재시도 | task=%s | attempt=%d/%d | delay=%.1fs | %s",
                    task_type,
                    attempt + 1,
                    self._max_retries,
                    delay,
                    str(exc),
                )
                await asyncio.sleep(delay)

        logger.error(
            "Claude API 최대 재시도 횟수 초과 | task=%s | retries=%d",
            task_type,
            self._max_retries,
        )
        raise last_exception  # type: ignore[misc]

    def get_usage_stats(self) -> dict:
        """모델별 토큰 사용량 통계를 반환한다.

        local 모드에서의 토큰 수는 근사값임을 유의한다.
        """
        total_input = 0
        total_output = 0
        total_calls = 0
        total_cost = 0.0
        per_model: dict[str, dict] = {}

        for model_type in ModelType:
            model_id = model_type.value
            usage = self._usage[model_id]
            pricing = _MODEL_PRICING[model_type]

            # local 모드에서는 실제 요금이 발생하지 않는다. 참고용 수치만 기록한다.
            input_cost = (usage["input_tokens"] / 1_000_000) * pricing["input"]
            output_cost = (usage["output_tokens"] / 1_000_000) * pricing["output"]
            model_cost = round(input_cost + output_cost, 4)

            per_model[model_id] = {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "calls": usage["calls"],
                "cost_usd": model_cost if self.mode == "api" else 0.0,
            }

            total_input += usage["input_tokens"]
            total_output += usage["output_tokens"]
            total_calls += usage["calls"]
            if self.mode == "api":
                total_cost += model_cost

        return {
            "mode": self.mode,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_calls": total_calls,
            "estimated_cost_usd": round(total_cost, 4),
            "per_model": per_model,
            "cache_size": self._cache.size,
        }

    def clear_cache(self) -> None:
        """응답 캐시를 초기화한다."""
        self._cache.clear()
        logger.info("응답 캐시 초기화 완료")

    @staticmethod
    def _make_cache_key(
        prompt: str,
        task_type: str,
        system_prompt: str | None,
        temperature: float,
    ) -> str:
        """캐시 키를 생성한다. 프롬프트 + 태스크 + 시스템 프롬프트 + 온도의 해시."""
        try:
            raw = f"{task_type}|{temperature}|{system_prompt or ''}|{prompt}"
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except Exception as exc:
            logger.warning(
                "캐시 키 생성 실패, 캐싱 비활성화: task=%s, error=%s",
                task_type, exc,
            )
            return ""

    @staticmethod
    def _extract_json(text: str) -> dict | list:
        """텍스트에서 JSON 객체 또는 배열을 추출한다.

        우선순위:
          1. ```json ... ``` 코드블록 내부
          2. 텍스트 전체를 직접 파싱
          3. 첫 번째 ``{`` 또는 ``[`` 부터 마지막 ``}`` 또는 ``]`` 까지 추출

        Raises:
            ValueError: 유효한 JSON을 찾지 못한 경우.
        """
        # 1) 코드블록에서 추출 시도
        match = _JSON_BLOCK_PATTERN.search(text)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
                logger.debug("JSON 추출 성공: 단계=코드블록(```json```)")
                return parsed
            except json.JSONDecodeError:
                logger.debug("JSON 코드블록 파싱 실패, 다음 단계 시도")

        # 2) 전체 텍스트 직접 파싱
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
            logger.debug("JSON 추출 성공: 단계=전체텍스트직접파싱")
            return parsed
        except json.JSONDecodeError:
            logger.debug("전체 텍스트 JSON 파싱 실패, 다음 단계 시도")

        # 3) 첫 { 또는 [ 부터 마지막 } 또는 ] 까지 추출
        start_obj = stripped.find("{")
        start_arr = stripped.find("[")
        if start_obj == -1 and start_arr == -1:
            raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]}")

        if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
            start = start_obj
            end = stripped.rfind("}") + 1
        else:
            start = start_arr
            end = stripped.rfind("]") + 1

        if end <= start:
            raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]}")

        try:
            parsed = json.loads(stripped[start:end])
            logger.debug("JSON 추출 성공: 단계=부분추출(첫괄호~끝괄호)")
            return parsed
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"JSON 파싱 실패: {exc}. 원문: {text[:300]}"
            ) from exc
