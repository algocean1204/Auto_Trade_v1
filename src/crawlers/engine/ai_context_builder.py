"""F1 데이터 수집 -- AI 분석용 컨텍스트 빌더이다.

검증된 기사 목록을 AI 분석에 적합한 단일 텍스트로 조합한다.
max_tokens 제한에 맞춰 기사를 우선순위(발행일 최신 + 품질 점수) 순으로
선택하고, 초과 시 truncate 처리한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.crawlers.models import AiContext, VerifiedArticle

logger = get_logger(__name__)

# 토큰 추정을 위한 문자-토큰 변환 비율이다 (영문 기준 ~4자=1토큰)
_CHARS_PER_TOKEN: int = 4

# 기사 하나당 구분자 형식이다
_ARTICLE_SEPARATOR: str = "\n---\n"

# 기사 포맷 템플릿이다
_ARTICLE_TEMPLATE: str = "[{source}] {title} ({date})\n{content}"


def _sort_by_priority(articles: list[VerifiedArticle]) -> list[VerifiedArticle]:
    """발행일 최신 + 품질 점수 높은 순으로 정렬한다."""
    return sorted(
        articles,
        key=lambda a: (a.published_at, a.quality_score),
        reverse=True,
    )


def _format_article(article: VerifiedArticle) -> str:
    """기사 하나를 포맷팅된 텍스트로 변환한다."""
    date_str = article.published_at.strftime("%Y-%m-%d %H:%M")
    return _ARTICLE_TEMPLATE.format(
        source=article.source,
        title=article.title,
        date=date_str,
        content=article.content,
    )


def _estimate_tokens(text: str) -> int:
    """텍스트의 토큰 수를 추정한다. 영문 기준 4자=1토큰이다."""
    return len(text) // _CHARS_PER_TOKEN


class AiContextBuilder:
    """AI 분석용 컨텍스트 빌더이다.

    검증된 기사를 우선순위 순으로 선택하여 max_tokens 이내의
    단일 텍스트로 조합한다.
    """

    def build(
        self,
        articles: list[VerifiedArticle],
        max_tokens: int = 8000,
    ) -> AiContext:
        """기사 목록을 AI 분석용 텍스트로 조합한다."""
        if not articles:
            return AiContext(
                context_text="", article_count=0, truncated=False,
            )

        sorted_articles = _sort_by_priority(articles)
        max_chars = max_tokens * _CHARS_PER_TOKEN

        parts: list[str] = []
        total_chars = 0
        truncated = False
        included = 0

        for article in sorted_articles:
            formatted = _format_article(article)
            separator = _ARTICLE_SEPARATOR if parts else ""
            addition = len(separator) + len(formatted)

            if total_chars + addition > max_chars:
                truncated = True
                break

            parts.append(separator + formatted)
            total_chars += addition
            included += 1

        context_text = "".join(parts)
        logger.info(
            "AI 컨텍스트 생성: %d/%d건 포함, ~%d토큰, truncated=%s",
            included, len(articles),
            _estimate_tokens(context_text), truncated,
        )

        return AiContext(
            context_text=context_text,
            article_count=included,
            truncated=truncated,
        )
