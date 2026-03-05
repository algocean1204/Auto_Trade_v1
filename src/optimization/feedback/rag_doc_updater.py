"""FF 피드백 -- 일일 결과를 RAG 지식베이스에 반영한다."""

from __future__ import annotations

import json
from datetime import datetime

from src.common.logger import get_logger
from src.optimization.feedback.models import DailyFeedbackResult, UpdateResult

logger = get_logger(__name__)

# 메타데이터 카테고리이다
_CAT_LESSON: str = "daily_lesson"
_CAT_IMPROVEMENT: str = "daily_improvement"
_CAT_SUMMARY: str = "daily_summary"


def _build_summary_doc(result: DailyFeedbackResult) -> str:
    """요약 문서 텍스트를 생성한다."""
    summary = result.summary
    parts: list[str] = [
        f"일일 거래 요약 ({datetime.now():%Y-%m-%d})",
        f"총 거래: {summary.get('total', 0)}건",
        f"승률: {summary.get('win_rate', 0):.1%}",
        f"총 PnL: ${summary.get('total_pnl', 0):.2f}",
        f"최대 수익: ${summary.get('max_gain', 0):.2f}",
        f"최대 손실: ${summary.get('max_loss', 0):.2f}",
    ]
    return " | ".join(parts)


def _build_lesson_docs(
    result: DailyFeedbackResult,
) -> list[tuple[str, dict]]:
    """교훈 문서 목록을 생성한다."""
    docs: list[tuple[str, dict]] = []
    date_str = datetime.now().strftime("%Y-%m-%d")

    for i, lesson in enumerate(result.lessons):
        text = f"[{date_str}] 교훈 #{i + 1}: {lesson}"
        meta = {
            "category": _CAT_LESSON,
            "date": date_str,
            "index": i,
        }
        docs.append((text, meta))

    return docs


def _build_improvement_docs(
    result: DailyFeedbackResult,
) -> list[tuple[str, dict]]:
    """개선 제안 문서 목록을 생성한다."""
    docs: list[tuple[str, dict]] = []
    date_str = datetime.now().strftime("%Y-%m-%d")

    for i, imp in enumerate(result.improvements):
        text = f"[{date_str}] 개선 #{i + 1}: {imp}"
        meta = {
            "category": _CAT_IMPROVEMENT,
            "date": date_str,
            "index": i,
        }
        docs.append((text, meta))

    return docs


def update_from_daily(
    daily_result: DailyFeedbackResult,
    knowledge_manager: object,
) -> UpdateResult:
    """일일 피드백 결과를 RAG 지식베이스에 저장한다.

    요약, 교훈, 개선 제안을 각각 문서로 변환하여
    ChromaDB에 임베딩하고 저장한다.
    """
    logger.info("RAG 문서 업데이트 시작")

    added = 0
    embedded = 0

    # 요약 문서 저장이다
    summary_text = _build_summary_doc(daily_result)
    summary_meta = {
        "category": _CAT_SUMMARY,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    try:
        knowledge_manager.store_document(summary_text, summary_meta)
        added += 1
        embedded += 1
    except Exception as exc:
        logger.warning("요약 저장 실패: %s", exc)

    # 교훈 문서 저장이다
    for text, meta in _build_lesson_docs(daily_result):
        try:
            knowledge_manager.store_document(text, meta)
            added += 1
            embedded += 1
        except Exception as exc:
            logger.warning("교훈 저장 실패: %s", exc)

    # 개선 제안 문서 저장이다
    for text, meta in _build_improvement_docs(daily_result):
        try:
            knowledge_manager.store_document(text, meta)
            added += 1
            embedded += 1
        except Exception as exc:
            logger.warning("개선 저장 실패: %s", exc)

    logger.info("RAG 업데이트 완료: 추가=%d, 임베딩=%d", added, embedded)

    return UpdateResult(
        documents_added=added,
        embeddings_created=embedded,
    )
