"""C0.6 LocalLlm -- GGUF 로컬 모델 관리자이다.

번역: Bllossom-8B (Q8_0) 전용 — 번역만 수행, 추론/사고 없음.
분류: Qwen2.5-7B + Llama-3.1-8B + DeepSeek-R1-8B 3중 앙상블 다수결.
모든 추론은 단일 스레드에서 실행하여 Metal GPU 경합을 방지한다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 프로젝트 루트 기준 모델 경로
_BASE: Path = Path(__file__).resolve().parents[2] / "models"
_BLLOSSOM_PATH: Path = _BASE / "llama-3-Korean-Bllossom-8B.Q8_0.gguf"
_QWEN_PATH: Path = _BASE / "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
_LLAMA_PATH: Path = _BASE / "Meta-Llama-3.1-8B-Instruct.Q4_K_M.gguf"
_DEEPSEEK_PATH: Path = _BASE / "DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf"

# 모델 캐시 — 전용 스레드 내에서만 접근한다
_bllossom: Any | None = None
_classifiers: dict[str, Any] = {}

# Metal GPU 단일 스레드 — 모든 GGUF 추론이 여기서 실행된다
_executor: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="gguf",
)


# ──────────────────────────────────────────
# 모델 로딩 (lazy, 최초 호출 시 1회만 실행)
# ──────────────────────────────────────────

def _load_bllossom() -> Any:
    """Bllossom 번역 모델을 로드한다."""
    global _bllossom
    if _bllossom is not None:
        return _bllossom
    from llama_cpp import Llama  # type: ignore[import-untyped]

    logger.info("Bllossom-8B 번역 모델 로딩 시작: %s", _BLLOSSOM_PATH.name)
    _bllossom = Llama(
        model_path=str(_BLLOSSOM_PATH),
        n_gpu_layers=-1,  # Metal GPU 전체 오프로드
        n_ctx=2048,
        verbose=False,
    )
    logger.info("Bllossom-8B 로딩 완료 (번역 전용)")
    return _bllossom


def _load_classifiers() -> dict[str, Any]:
    """3개 분류 모델을 순서대로 로드한다."""
    if _classifiers:
        return _classifiers
    from llama_cpp import Llama  # type: ignore[import-untyped]

    configs: list[tuple[str, Path, str]] = [
        ("qwen", _QWEN_PATH, "Qwen2.5-7B"),
        ("llama", _LLAMA_PATH, "Llama-3.1-8B"),
        ("deepseek", _DEEPSEEK_PATH, "DeepSeek-R1-8B"),
    ]
    for name, path, label in configs:
        logger.info("%s 분류 모델 로딩 시작: %s", label, path.name)
        _classifiers[name] = Llama(
            model_path=str(path),
            n_gpu_layers=-1,
            n_ctx=1024,  # 분류는 짧은 컨텍스트로 충분하다
            verbose=False,
        )
        logger.info("%s 로딩 완료", label)
    return _classifiers


# ──────────────────────────────────────────
# 내부 동기 함수 (전용 스레드에서 실행)
# ──────────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """DeepSeek <think> 블록을 제거한다."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.DOTALL).strip()
    return cleaned if cleaned else text


def _single_classify(model: Any, text: str, categories: list[str]) -> str:
    """단일 GGUF 모델로 텍스트를 분류한다. 카테고리 문자열을 반환한다."""
    cats_str = ", ".join(categories)
    response: dict = model.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    f"Classify into exactly one of: [{cats_str}]. "
                    "Output ONLY the category name. No explanation."
                ),
            },
            {"role": "user", "content": text[:1000]},
        ],
        max_tokens=20,
        temperature=0.0,
    )
    raw: str = response["choices"][0]["message"]["content"].strip()
    cleaned = _strip_thinking(raw)
    # 카테고리 매칭 — cleaned에서 먼저, 없으면 raw에서 재시도
    matched = next((c for c in categories if c.lower() in cleaned.lower()), None)
    if matched is None:
        matched = next((c for c in categories if c.lower() in raw.lower()), None)
    return matched or categories[0]


def _sync_translate(text: str, target_lang: str) -> str:
    """Bllossom-8B로 번역한다. 번역만 출력, 추론 없음."""
    model = _load_bllossom()
    lang_name: str = {"ko": "한국어", "en": "English"}.get(target_lang, target_lang)
    response: dict = model.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a translator. Translate to {lang_name}. "
                    "Output ONLY the translation."
                ),
            },
            {"role": "user", "content": text},
        ],
        max_tokens=200,
        temperature=0.1,
    )
    result: str = response["choices"][0]["message"]["content"].strip()
    # 한국어 번역 시 비한국어 줄 제거 (안전망)
    if target_lang == "ko":
        korean_lines = [
            line.strip() for line in result.split("\n")
            if line.strip() and re.search(r"[가-힣]", line)
        ]
        if korean_lines:
            return "\n".join(korean_lines)
    return result


def _sync_ensemble_classify(
    text: str, categories: list[str],
) -> tuple[str, float, str]:
    """3모델 앙상블 다수결 분류이다. (category, confidence, reasoning)을 반환한다."""
    models = _load_classifiers()
    votes: dict[str, str] = {}

    for name, model in models.items():
        try:
            votes[name] = _single_classify(model, text, categories)
        except Exception:
            logger.warning("%s 분류 실패, 건너뜀", name)

    if not votes:
        return categories[0], 0.3, "모든 모델 분류 실패"

    # 다수결 — 가장 많이 나온 카테고리가 승리한다
    counter: Counter[str] = Counter(votes.values())
    winner, count = counter.most_common(1)[0]

    # 신뢰도: 만장일치=0.95, 2/3=0.80, 1/3=0.50
    confidence_map: dict[int, float] = {3: 0.95, 2: 0.80, 1: 0.50}
    confidence = confidence_map.get(count, 0.50)

    reasoning = " | ".join(f"{k}={v}" for k, v in votes.items())
    return winner, confidence, reasoning


# ──────────────────────────────────────────
# 비동기 공개 인터페이스
# ──────────────────────────────────────────

async def translate(text: str, target_lang: str = "ko") -> str:
    """Bllossom-8B 번역이다. 번역 전용, 추론 없음."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _sync_translate, text, target_lang)


async def ensemble_classify(
    text: str, categories: list[str],
) -> tuple[str, float, str]:
    """3모델 앙상블 분류이다. 다수결 투표로 최종 카테고리를 결정한다."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor, _sync_ensemble_classify, text, categories,
    )


def _single_fast_classify(model: Any, text: str, categories: list[str]) -> str:
    """센티넬용 금융 뉴스 특화 단일 모델 분류이다. 카테고리 문자열을 반환한다."""
    cats_str = ", ".join(categories)
    response: dict = model.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a financial news urgency classifier for US leveraged ETF trading.\n"
                    f"Classify the headline into exactly one of: [{cats_str}].\n"
                    f"urgent: market crash, Fed emergency, circuit breaker, flash crash, war outbreak, "
                    f"major bankruptcy, sanctions, tariff shock — anything requiring immediate trading action.\n"
                    f"watch: significant earnings miss/beat, sector rotation, policy change, "
                    f"notable market move — important but not immediately actionable.\n"
                    f"normal: routine reports, minor moves, opinion pieces, scheduled events.\n"
                    "Output ONLY the category name. No explanation."
                ),
            },
            {"role": "user", "content": text},
        ],
        max_tokens=20,
        temperature=0.0,
    )
    raw: str = response["choices"][0]["message"]["content"].strip()
    cleaned = _strip_thinking(raw)
    matched = next((c for c in categories if c.lower() in cleaned.lower()), None)
    if matched is None:
        matched = next((c for c in categories if c.lower() in raw.lower()), None)
    return matched or categories[-1]  # 매칭 실패 시 normal(마지막) 반환


def _sync_fast_classify(
    text: str, categories: list[str],
) -> tuple[str, float, str]:
    """센티넬용 빠른 3모델 앙상블이다.

    일반 앙상블과 동일한 3모델 다수결이지만,
    입력 텍스트를 200자로 제한하고 금융 도메인 특화 프롬프트를 사용한다.
    """
    models = _load_classifiers()
    votes: dict[str, str] = {}
    short_text = text[:200]

    for name, model in models.items():
        try:
            votes[name] = _single_fast_classify(model, short_text, categories)
        except Exception:
            logger.warning("%s 빠른 분류 실패, 건너뜀", name)

    if not votes:
        return categories[0], 0.3, "모든 모델 빠른 분류 실패"

    counter: Counter[str] = Counter(votes.values())
    winner, count = counter.most_common(1)[0]

    confidence_map: dict[int, float] = {3: 0.95, 2: 0.80, 1: 0.50}
    confidence = confidence_map.get(count, 0.50)

    reasoning = " | ".join(f"{k}={v}" for k, v in votes.items())
    return winner, confidence, reasoning


# 센티넬 fast_classify 타임아웃 — 뉴스 파이프라인이 executor를 점유해도 대기하지 않는다
_FAST_CLASSIFY_TIMEOUT: float = 30.0


async def fast_classify(
    text: str, categories: list[str],
) -> tuple[str, float, str]:
    """센티넬용 빠른 3모델 앙상블이다. 헤드라인 200자 제한으로 속도 우선한다.

    뉴스 파이프라인이 executor를 점유 중이면 최대 30초만 대기한다.
    타임아웃 시 첫 번째 카테고리 + 낮은 confidence를 반환한다.
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                _executor, _sync_fast_classify, text, categories,
            ),
            timeout=_FAST_CLASSIFY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("fast_classify 타임아웃 (%.0fs) — executor 점유 중", _FAST_CLASSIFY_TIMEOUT)
        return categories[0], 0.3, "executor 점유로 타임아웃"
