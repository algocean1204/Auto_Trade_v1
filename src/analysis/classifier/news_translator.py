"""뉴스 번역기 -- MarianMT(opus-mt-en-ko)로 영문 제목을 한국어로 번역한다.

MarianMT 실패 시 Claude Haiku API를 폴백으로 사용한다.
Bllossom-8B 대신 번역 전문 모델을 사용하여 번역 품질과 안정성을 보장한다.
"""
from __future__ import annotations

import re

from src.analysis.models import ClassifiedNews
from src.common.ai_gateway import AiClient
from src.common.logger import get_logger

logger = get_logger(__name__)

# 한국어 소스 식별자 -- 이 문자열이 source에 포함되면 번역을 건너뛴다
_KOREAN_SOURCES: set[str] = {"naver", "hankyung", "chosun", "donga", "mk", "sedaily"}

# Claude Haiku 폴백 번역 프롬프트이다
_HAIKU_TRANSLATE_SYSTEM: str = (
    "영어 뉴스 제목을 한국어로 번역하라. 번역만 출력, 설명 없음."
)


def _is_korean_source(source: str) -> bool:
    """한국어 매체인지 확인한다."""
    lower = source.lower()
    return any(ks in lower for ks in _KOREAN_SOURCES)


def _has_korean(text: str) -> bool:
    """텍스트에 한글이 포함되어 있는지 확인한다."""
    return bool(re.search(r"[가-힣]", text))


class NewsTranslator:
    """분류된 뉴스의 제목을 한국어로 번역한다."""

    def __init__(self, ai_client: AiClient) -> None:
        self._ai = ai_client
        logger.info("NewsTranslator 초기화 완료")

    async def _translate_one(self, title: str) -> str:
        """단일 제목을 번역한다. MarianMT → Haiku 폴백 순서이다."""
        # 1차: MarianMT 로컬 번역 (EN→KO 전문 모델)
        try:
            from src.common.marian_translator import translate_en_to_ko
            result = await translate_en_to_ko(title)
            if _has_korean(result):
                return result
            logger.debug("[Step 3] MarianMT 결과에 한글 없음, Haiku 폴백: %s", title[:50])
        except Exception as exc:
            logger.debug("[Step 3] MarianMT 실패, Haiku 폴백: %s -- %s", title[:50], exc)

        # 2차: Claude Haiku API 폴백
        try:
            response = await self._ai.send_text(
                prompt=title,
                system=_HAIKU_TRANSLATE_SYSTEM,
                model="haiku",
                max_tokens=200,
            )
            haiku_result = response.content.strip()
            if _has_korean(haiku_result):
                return haiku_result
            logger.warning("[Step 3] Haiku 번역도 한글 없음: %s", title[:50])
        except Exception as exc:
            logger.warning("[Step 3] Haiku 번역 폴백 실패: %s -- %s", title[:50], exc)

        # 둘 다 실패하면 예외를 발생시켜 원본을 유지하게 한다
        raise ValueError(f"MarianMT+Haiku 번역 모두 실패: {title[:50]}")

    async def translate(self, articles: list[ClassifiedNews]) -> list[ClassifiedNews]:
        """영문 기사 제목을 한국어로 번역하여 content 앞에 추가한다.

        이미 한국어인 기사는 건너뛴다. 개별 번역 실패 시 원본을 유지한다.
        Bllossom 실패 시 Claude Haiku API를 폴백으로 사용한다.
        """
        results: list[ClassifiedNews] = []
        translated_count = 0
        haiku_fallback_count = 0

        for article in articles:
            if _is_korean_source(article.source):
                results.append(article)
                continue

            try:
                translated_title = await self._translate_one(article.title)
                updated = article.model_copy(update={
                    "content": f"[한국어] {translated_title}\n\n{article.content}",
                })
                results.append(updated)
                translated_count += 1
            except Exception as exc:
                logger.warning(
                    "[Step 3] 번역 실패 (원본 유지): %s -- %s",
                    article.title[:50], exc,
                )
                results.append(article)

        logger.info("[Step 3] 뉴스 번역 완료: %d/%d건", translated_count, len(articles))
        return results
