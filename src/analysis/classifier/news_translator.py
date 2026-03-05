"""뉴스 번역기 -- Bllossom-8B GGUF로 영문 제목을 한국어로 번역한다."""
from __future__ import annotations

from src.analysis.models import ClassifiedNews
from src.common.ai_gateway import AiClient
from src.common.logger import get_logger

logger = get_logger(__name__)

# 한국어 소스 식별자 -- 이 문자열이 source에 포함되면 번역을 건너뛴다
_KOREAN_SOURCES: set[str] = {"naver", "hankyung", "chosun", "donga", "mk", "sedaily"}


def _is_korean_source(source: str) -> bool:
    """한국어 매체인지 확인한다."""
    lower = source.lower()
    return any(ks in lower for ks in _KOREAN_SOURCES)


class NewsTranslator:
    """분류된 뉴스의 제목을 한국어로 번역한다."""

    def __init__(self, ai_client: AiClient) -> None:
        self._ai = ai_client
        logger.info("NewsTranslator 초기화 완료")

    async def translate(self, articles: list[ClassifiedNews]) -> list[ClassifiedNews]:
        """영문 기사 제목을 한국어로 번역하여 content 앞에 추가한다.

        이미 한국어인 기사는 건너뛴다. 개별 번역 실패 시 원본을 유지한다.
        """
        results: list[ClassifiedNews] = []
        translated_count = 0

        for article in articles:
            if _is_korean_source(article.source):
                results.append(article)
                continue

            try:
                translated_title = await self._ai.local_translate(
                    article.title, target_lang="ko",
                )
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
