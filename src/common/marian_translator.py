"""C0.7 MarianTranslator -- Helsinki-NLP/opus-mt-en-ko 전용 영한 번역기이다.

Bllossom-8B 대신 번역 전문 모델을 사용하여 안정적인 영한 번역을 제공한다.
모델은 ~300MB로 가볍고, CPU에서도 빠르게 동작한다.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

_MODEL_NAME: str = "Helsinki-NLP/opus-mt-en-ko"

# 모델 캐시 — lazy 로드
_model: Any | None = None
_tokenizer: Any | None = None

# CPU 전용 스레드 — MarianMT는 가벼워서 CPU로 충분하다
_executor: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="marian",
)


def _load_model() -> tuple[Any, Any]:
    """MarianMT 모델과 토크나이저를 로드한다. 최초 1회만 실행된다."""
    global _model, _tokenizer
    if _model is not None and _tokenizer is not None:
        return _model, _tokenizer

    from transformers import MarianMTModel, MarianTokenizer

    logger.info("MarianMT 번역 모델 로딩 시작: %s", _MODEL_NAME)
    _tokenizer = MarianTokenizer.from_pretrained(_MODEL_NAME)
    _model = MarianMTModel.from_pretrained(_MODEL_NAME)
    logger.info("MarianMT 로딩 완료 (EN→KO 번역 전용)")
    return _model, _tokenizer


def _sync_translate(text: str) -> str:
    """MarianMT로 영한 번역을 수행한다. 동기 함수이다."""
    model, tokenizer = _load_model()
    inputs = tokenizer(
        text, return_tensors="pt",
        padding=True, truncation=True, max_length=512,
    )
    translated = model.generate(**inputs, max_length=512)
    result: str = tokenizer.decode(translated[0], skip_special_tokens=True)
    return result


async def translate_en_to_ko(text: str) -> str:
    """영문 텍스트를 한국어로 번역한다. 비동기 인터페이스이다."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _sync_translate, text)
