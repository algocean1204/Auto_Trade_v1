"""
로컬 Qwen3 Fallback 모델

Claude API 장애 또는 Quota 초과 시 자동 전환되는 로컬 LLM.
Apple Silicon M4 Pro MPS 가속을 사용한다.

레버리지 ETF를 거래하므로 confidence 0.90 이상일 때만 매매를 허용한다.
모델이 설치되어 있지 않거나 로드에 실패해도 graceful하게 처리한다.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# torch, transformers는 설치되지 않았을 수 있으므로 지연 임포트
_TORCH_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False

try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:
    logger.warning("torch가 설치되어 있지 않습니다. 로컬 Fallback 모델을 사용할 수 없습니다.")

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    logger.warning("transformers가 설치되어 있지 않습니다. 로컬 Fallback 모델을 사용할 수 없습니다.")


# JSON 코드블록 패턴: ```json ... ``` 또는 ``` ... ```
_JSON_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*\n?([\s\S]*?)\n?```",
    re.DOTALL,
)

# 기본 최대 생성 토큰 수
_DEFAULT_MAX_TOKENS: int = 2048

# 최소 신뢰도 임계값 (레버리지 ETF이므로 Fallback은 보수적으로 운용)
MIN_CONFIDENCE: float = 0.90


class LocalModel:
    """로컬 Qwen3 Fallback 모델.

    싱글톤 패턴으로 구현되어 메모리를 효율적으로 사용한다.
    모델은 lazy loading으로 첫 호출 시에만 로드한다.
    """

    _instance: LocalModel | None = None

    MODEL_NAME: str = "Qwen/Qwen2.5-7B-Instruct"
    MIN_CONFIDENCE: float = MIN_CONFIDENCE  # 모듈 레벨 상수 참조, Fallback은 보수적으로 운용

    def __init__(self) -> None:
        self._device: str = "cpu"
        self._model: Any = None
        self._tokenizer: Any = None
        self.is_loaded: bool = False
        self._loading: bool = False
        self._load_error: str | None = None

        if _TORCH_AVAILABLE:
            import torch as _torch

            if _torch.backends.mps.is_available():
                self._device = "mps"
            elif _torch.cuda.is_available():
                self._device = "cuda"

        logger.info(
            "LocalModel 초기화 | device=%s | torch=%s | transformers=%s",
            self._device,
            _TORCH_AVAILABLE,
            _TRANSFORMERS_AVAILABLE,
        )

    @classmethod
    def get_instance(cls) -> LocalModel:
        """싱글톤 인스턴스를 반환한다."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def load(self) -> None:
        """모델을 로드한다 (lazy loading, 비동기).

        이미 로드되었거나 로드 중이면 무시한다.
        torch/transformers 미설치 시 에러 없이 반환하며,
        is_loaded는 False로 유지된다.
        """
        if self.is_loaded or self._loading:
            return

        if not _TORCH_AVAILABLE or not _TRANSFORMERS_AVAILABLE:
            self._load_error = "torch 또는 transformers 미설치"
            logger.warning("모델 로드 불가: %s", self._load_error)
            return

        self._loading = True
        logger.info("로컬 모델 로드 시작: %s (device=%s)", self.MODEL_NAME, self._device)

        try:
            # 블로킹 작업을 스레드로 위임
            await asyncio.to_thread(self._load_sync)
            self.is_loaded = True
            self._load_error = None
            logger.info("로컬 모델 로드 완료: %s", self.MODEL_NAME)
        except Exception as exc:
            self._load_error = str(exc)
            logger.error("로컬 모델 로드 실패: %s", exc)
        finally:
            self._loading = False

    def _load_sync(self) -> None:
        """모델과 토크나이저를 동기적으로 로드한다 (별도 스레드에서 실행)."""
        import torch as _torch
        from transformers import AutoModelForCausalLM as _AutoModel
        from transformers import AutoTokenizer as _AutoTokenizer

        start = time.monotonic()

        self._tokenizer = _AutoTokenizer.from_pretrained(
            self.MODEL_NAME,
            trust_remote_code=True,
        )

        self._model = _AutoModel.from_pretrained(
            self.MODEL_NAME,
            torch_dtype=_torch.float16,
            device_map="auto" if self._device != "mps" else None,
            trust_remote_code=True,
        )

        # MPS의 경우 device_map="auto"가 지원되지 않으므로 수동 이동
        if self._device == "mps":
            self._model = self._model.to(self._device)

        self._model.eval()

        elapsed = time.monotonic() - start
        logger.info(
            "모델 로드 소요 시간: %.1f초 | device=%s",
            elapsed,
            self._device,
        )

    async def generate(
        self,
        prompt: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """텍스트를 생성한다.

        Args:
            prompt: 입력 프롬프트.
            max_tokens: 최대 생성 토큰 수.
            temperature: 샘플링 온도. 낮을수록 결정적이다.

        Returns:
            생성 결과 딕셔너리:
                - content: str -- 생성된 텍스트
                - model: str -- 모델 이름
                - confidence: float -- 평균 로그 확률에서 추정한 신뢰도

        Raises:
            RuntimeError: 모델이 로드되지 않은 경우.
        """
        if not self.is_loaded:
            await self.load()
        if not self.is_loaded:
            raise RuntimeError(
                f"로컬 모델을 사용할 수 없습니다: {self._load_error or '알 수 없는 오류'}"
            )

        logger.info(
            "로컬 모델 생성 시작 | max_tokens=%d | temperature=%.2f",
            max_tokens,
            temperature,
        )

        result = await asyncio.to_thread(
            self._generate_sync, prompt, max_tokens, temperature
        )
        return result

    def _generate_sync(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """텍스트를 동기적으로 생성한다 (별도 스레드에서 실행).

        생성된 토큰의 평균 로그 확률을 기반으로 confidence를 추정한다.
        """
        import torch as _torch

        start = time.monotonic()

        # 채팅 형식으로 프롬프트 구성
        messages = [{"role": "user", "content": prompt}]
        text = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        inputs = self._tokenizer(text, return_tensors="pt").to(self._device)
        input_length = inputs["input_ids"].shape[1]

        with _torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=max(temperature, 0.01),  # 0 방지
                do_sample=temperature > 0.01,
                top_p=0.9,
                return_dict_in_generate=True,
                output_scores=True,
            )

        # 생성된 토큰만 추출
        generated_ids = outputs.sequences[0][input_length:]
        content = self._tokenizer.decode(generated_ids, skip_special_tokens=True)

        # confidence 추정: 각 스텝의 로그 확률 평균을 시그모이드로 변환
        confidence = self._estimate_confidence(outputs.scores, generated_ids)

        elapsed = time.monotonic() - start
        token_count = len(generated_ids)
        tokens_per_sec = token_count / elapsed if elapsed > 0 else 0.0

        logger.info(
            "로컬 모델 생성 완료 | tokens=%d | %.1f tok/s | confidence=%.4f | elapsed=%.1fs",
            token_count,
            tokens_per_sec,
            confidence,
            elapsed,
        )

        return {
            "content": content.strip(),
            "model": self.MODEL_NAME,
            "confidence": confidence,
        }

    def _estimate_confidence(
        self,
        scores: tuple[Any, ...],
        generated_ids: Any,
    ) -> float:
        """생성된 토큰의 로그 확률에서 confidence를 추정한다.

        각 토큰의 softmax 확률을 구해 기하 평균을 계산한다.

        Args:
            scores: 각 생성 스텝의 logit 텐서 튜플.
            generated_ids: 생성된 토큰 ID 텐서.

        Returns:
            0.0~1.0 범위의 신뢰도 값.
        """
        import torch as _torch

        if not scores or len(scores) == 0:
            return 0.5

        total_log_prob = 0.0
        count = 0

        for step_idx, logits in enumerate(scores):
            if step_idx >= len(generated_ids):
                break

            probs = _torch.softmax(logits[0], dim=-1)
            token_id = generated_ids[step_idx].item()
            token_prob = probs[token_id].item()

            if token_prob > 0:
                total_log_prob += math.log(token_prob)
                count += 1

        if count == 0:
            return 0.5

        # 기하 평균 확률
        avg_log_prob = total_log_prob / count
        geo_mean_prob = math.exp(avg_log_prob)

        # 0.0~1.0 범위로 클램프
        return max(0.0, min(1.0, geo_mean_prob))

    async def generate_json(
        self,
        prompt: str,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> dict | list | None:
        """JSON 응답을 기대하는 텍스트 생성.

        생성된 텍스트에서 JSON을 추출하여 파이썬 객체로 반환한다.
        JSON 파싱에 실패하면 None을 반환한다.

        Args:
            prompt: 입력 프롬프트. JSON 형식 출력을 유도하는 내용이어야 한다.
            max_tokens: 최대 생성 토큰 수.

        Returns:
            파싱된 JSON (dict 또는 list), 파싱 실패 시 None.
        """
        result = await self.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=0.1,  # JSON은 결정적으로
        )

        content: str = result["content"]
        parsed = self._extract_json(content)

        if parsed is not None:
            logger.debug("로컬 모델 JSON 파싱 성공")
        else:
            logger.warning(
                "로컬 모델 JSON 파싱 실패 | content_preview=%s",
                content[:200],
            )

        return parsed

    def is_available(self) -> bool:
        """모델 사용 가능 여부를 반환한다.

        torch/transformers가 설치되어 있고 모델이 로드되었거나
        로드할 수 있는 상태이면 True.
        """
        if not _TORCH_AVAILABLE or not _TRANSFORMERS_AVAILABLE:
            return False
        if self._load_error and not self.is_loaded:
            return False
        return True

    async def unload(self) -> None:
        """모델을 메모리에서 해제한다."""
        if not self.is_loaded:
            return

        logger.info("로컬 모델 메모리 해제 시작")

        def _unload() -> None:
            if _TORCH_AVAILABLE:
                import torch as _torch

                del self._model
                del self._tokenizer
                self._model = None
                self._tokenizer = None

                if self._device == "mps":
                    _torch.mps.empty_cache()
                elif self._device == "cuda":
                    _torch.cuda.empty_cache()

                import gc

                gc.collect()

        await asyncio.to_thread(_unload)
        self.is_loaded = False
        logger.info("로컬 모델 메모리 해제 완료")

    def get_status(self) -> dict[str, Any]:
        """모델 상태 정보를 반환한다.

        Returns:
            모델 상태 딕셔너리.
        """
        return {
            "model_name": self.MODEL_NAME,
            "device": self._device,
            "is_loaded": self.is_loaded,
            "is_available": self.is_available(),
            "loading": self._loading,
            "load_error": self._load_error,
            "torch_available": _TORCH_AVAILABLE,
            "transformers_available": _TRANSFORMERS_AVAILABLE,
            "min_confidence": self.MIN_CONFIDENCE,
        }

    @staticmethod
    def _extract_json(text: str) -> dict | list | None:
        """텍스트에서 JSON 객체 또는 배열을 추출한다.

        우선순위:
          1. ```json ... ``` 코드블록 내부
          2. 텍스트 전체를 직접 파싱
          3. 첫 번째 { 또는 [ 부터 마지막 } 또는 ] 까지 추출

        Args:
            text: JSON이 포함된 텍스트.

        Returns:
            파싱된 JSON 객체, 실패 시 None.
        """
        # 1) 코드블록에서 추출 시도
        match = _JSON_BLOCK_PATTERN.search(text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 2) 전체 텍스트 직접 파싱
        stripped = text.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        # 3) 첫 { 또는 [ 부터 마지막 } 또는 ] 까지 추출
        start_obj = stripped.find("{")
        start_arr = stripped.find("[")
        if start_obj == -1 and start_arr == -1:
            return None

        if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
            start = start_obj
            end = stripped.rfind("}") + 1
        else:
            start = start_arr
            end = stripped.rfind("]") + 1

        if end <= start:
            return None

        try:
            return json.loads(stripped[start:end])
        except json.JSONDecodeError:
            return None
