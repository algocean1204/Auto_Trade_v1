"""
뉴스 한국어 번역 모듈.

Claude Sonnet을 사용하여 크롤링된 영어 뉴스 기사를
한국어로 번역한다. 배치 처리로 API 호출 횟수를 최소화한다.

DB Article 모델의 headline_kr, summary_ko 컬럼에 결과를 저장한다.
"""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from src.analysis.claude_client import ClaudeClient
from src.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# 배치당 번역 기사 수 (비용 효율 + 토큰 한도 고려)
_TRANSLATE_BATCH_SIZE: int = 10

# 번역 task_type (Sonnet 라우팅)
_TRANSLATE_TASK_TYPE: str = "telegram_chat"


class NewsTranslator:
    """크롤링된 뉴스를 한국어로 번역한다.

    배치 처리: 최대 10개씩 묶어서 1회 API 호출로 번역하여
    비용 효율을 높인다. Claude Sonnet을 사용한다.

    번역 대상 필드:
        - headline → headline_kr (한국어 제목)
        - content 요약 → summary_ko (한국어 요약 2-3줄)
    """

    def __init__(self, claude_client: ClaudeClient) -> None:
        """NewsTranslator를 초기화한다.

        Args:
            claude_client: Claude API 클라이언트. Sonnet 모드로 호출한다.
        """
        self.client = claude_client
        logger.info(
            "NewsTranslator 초기화 완료 (batch_size=%d)", _TRANSLATE_BATCH_SIZE
        )

    async def translate_articles(
        self, articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """뉴스 기사 목록을 한국어로 번역한다.

        배치 처리: 최대 10개씩 묶어서 1회 API 호출로 번역.
        번역 실패한 기사는 원문 그대로 반환하며 파이프라인을 중단하지 않는다.

        Args:
            articles: 뉴스 기사 목록.
                각 항목은 {"id", "headline", "content", "tickers_mentioned"} 형태.

        Returns:
            번역 결과가 추가된 기사 목록.
            각 항목에 "headline_kr", "summary_ko" 필드가 추가된다.
            번역 실패 시 해당 필드는 빈 문자열로 채워진다.
        """
        if not articles:
            logger.info("번역 대상 기사 없음.")
            return []

        chunks = self._chunk_articles(articles, _TRANSLATE_BATCH_SIZE)
        logger.info(
            "한국어 번역 시작: 총 %d건, %d개 배치",
            len(articles),
            len(chunks),
        )

        # 배치별 순차 처리 (순서 보장 + 에러 격리)
        all_results: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            try:
                translated_chunk = await self._translate_batch(chunk)
                all_results.extend(translated_chunk)
                logger.debug(
                    "번역 배치 %d/%d 완료: %d건",
                    i + 1,
                    len(chunks),
                    len(translated_chunk),
                )
            except Exception as exc:
                logger.error(
                    "번역 배치 %d/%d 실패 (원문 유지): %s",
                    i + 1,
                    len(chunks),
                    exc,
                )
                # 실패한 배치는 원문 기사에 빈 번역 필드를 추가하여 반환
                for article in chunk:
                    all_results.append(
                        {
                            **article,
                            "headline_kr": "",
                            "summary_ko": "",
                        }
                    )

        logger.info(
            "한국어 번역 완료: %d/%d건 처리",
            len(all_results),
            len(articles),
        )
        return all_results

    async def translate_and_save(
        self, articles: list[dict[str, Any]]
    ) -> int:
        """뉴스 기사를 번역하고 DB에 저장한다.

        article dict의 "id" 필드를 기반으로 Article ORM을 조회하여
        headline_kr, summary_ko 컬럼을 업데이트한다.

        Args:
            articles: 번역 대상 기사 목록.
                각 항목은 {"id", "headline", "content", "tickers_mentioned"} 형태.

        Returns:
            DB 저장 성공 건수.
        """
        if not articles:
            return 0

        translated = await self.translate_articles(articles)
        if not translated:
            return 0

        try:
            from sqlalchemy import update as sa_update
            from src.db.connection import get_session
            from src.db.models import Article as ArticleModel

            success_count = 0
            async with get_session() as session:
                for item in translated:
                    article_id = item.get("id")
                    headline_kr = item.get("headline_kr", "")
                    summary_ko = item.get("summary_ko", "")

                    if not article_id:
                        continue

                    # 번역 결과가 없으면 DB 업데이트 건너뜀
                    if not headline_kr and not summary_ko:
                        continue

                    stmt = (
                        sa_update(ArticleModel)
                        .where(ArticleModel.id == str(article_id))
                        .values(
                            headline_kr=headline_kr or None,
                            summary_ko=summary_ko or None,
                        )
                    )
                    await session.execute(stmt)
                    success_count += 1

                await session.commit()

            logger.info(
                "번역 결과 DB 저장 완료: %d/%d건",
                success_count,
                len(translated),
            )
            return success_count

        except Exception as exc:
            logger.error("번역 결과 DB 저장 실패: %s", exc)
            return 0

    async def _translate_batch(
        self, articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """단일 배치에 대해 Claude Sonnet을 호출하여 번역한다.

        Args:
            articles: 한 배치에 해당하는 기사 목록.

        Returns:
            번역 결과가 추가된 기사 목록.
        """
        # 프롬프트용 뉴스 목록 구성
        news_lines = []
        for idx, article in enumerate(articles, start=1):
            headline = article.get("headline", "")
            content = (article.get("content") or "")[:500]
            tickers = article.get("tickers_mentioned") or []
            ticker_str = (
                ", ".join(str(t) for t in tickers[:5]) if tickers else "없음"
            )
            news_lines.append(
                f"{idx}. 제목: {headline}\n"
                f"   관련 종목: {ticker_str}\n"
                f"   내용: {content}"
            )

        news_block = "\n\n".join(news_lines)

        prompt = (
            "다음 영어 뉴스 기사들의 제목과 요약을 한국어로 번역하라. "
            "금융/투자 용어는 전문 용어를 사용하라.\n\n"
            "각 기사에 대해 다음 JSON 배열 형식으로 반환하라:\n"
            "[\n"
            "  {\n"
            '    "headline_kr": "한국어 제목 (원문 의미를 정확하게 번역)",\n'
            '    "summary_ko": "한국어 요약 2-3줄. 핵심 내용과 시장 영향 포함. '
            '투자자 관점에서 중요한 내용 위주로 작성."\n'
            "  }\n"
            "]\n\n"
            "규칙:\n"
            "- 배열 순서는 입력 뉴스 순서와 반드시 동일해야 한다.\n"
            "- headline_kr은 한국어로 자연스럽게 번역하라.\n"
            "- summary_ko는 2-3줄로 핵심 내용을 요약하라.\n"
            "- 전문 금융 용어(EPS, FOMC, CPI 등)는 영문 약어를 유지하라.\n"
            f"- 총 {len(articles)}개의 기사를 번역하라.\n\n"
            f"뉴스 목록:\n{news_block}"
        )

        try:
            raw = await self.client.call_json(
                prompt=prompt,
                task_type=_TRANSLATE_TASK_TYPE,
                max_tokens=4096,
                use_cache=False,
            )
        except Exception as exc:
            logger.error("번역 Claude 호출 실패: %s", exc)
            raise

        # 응답 파싱
        if isinstance(raw, dict):
            # {"articles": [...]} 형태로 반환된 경우
            translations_raw = raw.get("articles", raw.get("translations", [raw]))
        elif isinstance(raw, list):
            translations_raw = raw
        else:
            logger.warning("번역 응답 형식 오류: %s", type(raw))
            translations_raw = []

        # 기사 목록과 번역 결과 매핑
        results = []
        for i, article in enumerate(articles):
            if i < len(translations_raw) and isinstance(translations_raw[i], dict):
                trans = translations_raw[i]
                results.append(
                    {
                        **article,
                        "headline_kr": trans.get("headline_kr", ""),
                        "summary_ko": trans.get("summary_ko", ""),
                    }
                )
            else:
                # 번역 결과가 없으면 원문 유지
                results.append(
                    {
                        **article,
                        "headline_kr": "",
                        "summary_ko": "",
                    }
                )

        return results

    @staticmethod
    def _chunk_articles(
        articles: list[Any], size: int
    ) -> list[list[Any]]:
        """기사 목록을 지정된 크기의 배치로 분할한다.

        Args:
            articles: 전체 기사 목록.
            size: 배치당 기사 수.

        Returns:
            배치 리스트의 리스트.
        """
        return [articles[i : i + size] for i in range(0, len(articles), size)]
