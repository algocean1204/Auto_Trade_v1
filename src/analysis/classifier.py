"""
뉴스 분류기

크롤링된 기사를 Claude Sonnet으로 분류한다.
배치 20건씩 처리하여 효율적 토큰 사용을 보장한다.
기존 신호와 비교하여 변화분만 업데이트하는 델타 분류를 지원한다.
분류 완료 후 한국어 번역 및 기업 영향 분석을 별도 배치로 수행한다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.analysis.claude_client import ClaudeClient
from src.analysis.prompts import build_news_classification_prompt, get_system_prompt
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.db.models import Article

logger = get_logger(__name__)

# 분류 결과 필수 필드
_REQUIRED_FIELDS = frozenset({
    "id", "impact", "tickers", "direction", "sentiment_score", "category",
})


def classify_importance(
    article_classification: dict,
    monitored_tickers: set[str],
) -> str:
    """뉴스의 중요도를 분류한다. critical/key/normal.

    모니터링 중인 종목 유니버스와의 관련성을 기반으로 뉴스 중요도를 판단한다.
    - critical: 모니터링 종목을 직접 언급하고 영향도가 high인 경우
    - key: 모니터링 종목의 섹터와 관련되거나 영향도가 medium 이상인 경우
    - normal: 그 외 모든 경우

    Args:
        article_classification: 분류된 기사 딕셔너리.
            {"id", "impact", "tickers", "direction", "sentiment_score", "category"} 포함.
        monitored_tickers: 현재 모니터링 중인 종목 티커 집합 (대문자).

    Returns:
        "critical", "key", "normal" 중 하나의 문자열.
    """
    try:
        from src.utils.ticker_mapping import SECTOR_TICKERS, _TICKER_TO_SECTOR

        article_tickers: set[str] = {
            t.upper() for t in article_classification.get("tickers", [])
            if isinstance(t, str) and t.strip()
        }
        impact: str = article_classification.get("impact", "low")

        # 직접 언급된 종목과 모니터링 종목의 교집합
        direct_overlap = article_tickers & monitored_tickers

        if direct_overlap and impact == "high":
            return "critical"

        # 섹터 관련성 확인
        # 기사 티커가 속한 섹터 집합
        article_sectors: set[str] = {
            _TICKER_TO_SECTOR[t]
            for t in article_tickers
            if t in _TICKER_TO_SECTOR
        }
        # 모니터링 종목이 속한 섹터 집합
        monitored_sectors: set[str] = {
            _TICKER_TO_SECTOR[t]
            for t in monitored_tickers
            if t in _TICKER_TO_SECTOR
        }
        sector_overlap = article_sectors & monitored_sectors

        if (direct_overlap and impact in ("high", "medium")) or \
           (sector_overlap and impact in ("high", "medium")):
            return "key"

        return "normal"
    except Exception as exc:
        logger.warning("중요도 분류 실패, 기본값 normal 반환: %s", exc)
        return "normal"

# 허용되는 열거형 값
_VALID_IMPACTS = frozenset({"high", "medium", "low"})
_VALID_DIRECTIONS = frozenset({"bullish", "bearish", "neutral"})
_VALID_CATEGORIES = frozenset({
    "earnings", "macro", "policy", "sector", "company", "geopolitics", "other",
})

_DEFAULT_BATCH_SIZE = 20

# 번역 배치 크기 (한 번에 번역할 기사 수)
_TRANSLATE_BATCH_SIZE: int = 10

# translate_unprocessed에서 한 번에 처리할 최대 기사 수
_DEFAULT_UNPROCESSED_LIMIT: int = 50

# 기본 저장 경로
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DEFAULT_SIGNALS_FILE = _DATA_DIR / "classified_signals.json"


class NewsClassifier:
    """뉴스 기사를 Claude Sonnet으로 분류하는 클래스.

    배치 단위로 분류하여 API 호출 횟수를 최소화하고,
    델타 분류를 통해 이전 결과 대비 변화분만 업데이트한다.
    """

    def __init__(
        self,
        claude_client: ClaudeClient,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        """NewsClassifier 초기화.

        Args:
            claude_client: Claude API 클라이언트.
            batch_size: 한 번에 분류할 기사 수. 기본 20.
        """
        self.client = claude_client
        self.batch_size = batch_size
        logger.info("NewsClassifier 초기화 완료 (batch_size=%d)", self.batch_size)

    async def classify_batch(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """기사 배치 분류.

        전체 기사 목록을 batch_size 단위로 나누어 Claude Sonnet을 호출하고,
        결과를 취합하여 반환한다. 각 배치는 병렬로 처리된다.

        Args:
            articles: 뉴스 기사 목록.
                각 항목은 ``{"id", "title", "summary", "source", "published_at"}`` 형태.

        Returns:
            분류 결과 목록. 각 항목:
                - id: str -- 기사 ID
                - impact: "high" | "medium" | "low"
                - tickers: list[str] -- 관련 종목 티커
                - direction: "bullish" | "bearish" | "neutral"
                - sentiment_score: float (-1.0 ~ 1.0)
                - category: str
        """
        if not articles:
            logger.info("분류할 기사가 없습니다.")
            return []

        chunks = self._chunk_articles(articles, self.batch_size)
        logger.info(
            "뉴스 분류 시작: 총 %d건, %d개 배치",
            len(articles), len(chunks),
        )

        # 배치별 병렬 처리
        tasks = [self._classify_chunk(chunk) for chunk in chunks]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        all_classified: list[dict[str, Any]] = []
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.error(
                    "배치 %d/%d 분류 실패: %s", i + 1, len(chunks), result,
                )
                continue
            all_classified.extend(result)

        logger.info(
            "뉴스 분류 완료: %d/%d건 성공",
            len(all_classified), len(articles),
        )
        return all_classified

    async def classify_delta(
        self,
        new_articles: list[dict[str, Any]],
        existing_signals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """델타 분류 (30분마다 새로운 기사만 분류).

        기존 신호의 기사 ID를 확인하여 이미 분류된 기사는 건너뛰고,
        새로운 기사만 분류하여 기존 신호와 병합한다.

        Args:
            new_articles: 새로 크롤링된 기사 목록.
            existing_signals: 이전 분류 결과 목록.

        Returns:
            기존 신호 + 새 분류 결과가 병합된 전체 목록.
        """
        existing_ids: set[str] = {
            str(s.get("id", "")) for s in existing_signals
        }
        truly_new = [
            a for a in new_articles
            if str(a.get("id", "")) not in existing_ids
        ]

        if not truly_new:
            logger.info("델타 분류: 새로운 기사 없음, 기존 신호 %d건 유지", len(existing_signals))
            return list(existing_signals)

        logger.info(
            "델타 분류: 전체 %d건 중 신규 %d건 분류 대상",
            len(new_articles), len(truly_new),
        )

        new_signals = await self.classify_batch(truly_new)

        # 기존 신호 + 새 신호 병합
        merged = list(existing_signals) + new_signals
        logger.info(
            "델타 분류 완료: 기존 %d + 신규 %d = 총 %d건",
            len(existing_signals), len(new_signals), len(merged),
        )
        return merged

    async def _classify_chunk(self, chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """단일 배치에 대해 Claude Sonnet을 호출하여 분류한다.

        Args:
            chunk: 한 배치에 해당하는 기사 목록.

        Returns:
            분류 결과 목록.

        Raises:
            ValueError: Claude 응답에서 유효한 JSON을 파싱하지 못한 경우.
        """
        prompt = build_news_classification_prompt(
            articles=chunk,
            batch_size=len(chunk),
        )

        raw_results = await self.client.call_json(
            prompt=prompt,
            task_type="news_classification",
            system_prompt=get_system_prompt("news_classification"),
            max_tokens=4096,
            use_cache=False,  # 뉴스는 실시간이므로 캐싱하지 않음
        )

        if not isinstance(raw_results, list):
            logger.warning("Claude 응답이 배열이 아닙니다. 빈 배열 형태로 래핑합니다.")
            raw_results = [raw_results] if isinstance(raw_results, dict) else []

        validated = []
        for item in raw_results:
            cleaned = self._validate_classification(item)
            if cleaned is not None:
                validated.append(cleaned)

        logger.debug(
            "배치 분류: 입력 %d건 -> 유효 %d건",
            len(chunk), len(validated),
        )
        return validated

    def _validate_classification(self, item: Any) -> dict[str, Any] | None:
        """단일 분류 결과의 필수 필드와 값 범위를 검증한다.

        Args:
            item: Claude가 반환한 단일 분류 결과.

        Returns:
            검증 및 정제된 딕셔너리. 유효하지 않으면 None.
        """
        if not isinstance(item, dict):
            logger.warning("분류 결과가 딕셔너리가 아닙니다: %s", type(item))
            return None

        # 필수 필드 확인
        missing = _REQUIRED_FIELDS - set(item.keys())
        if missing:
            logger.warning("분류 결과 필수 필드 누락: %s", missing)
            return None

        # impact 검증
        impact = str(item.get("impact", "")).lower()
        if impact not in _VALID_IMPACTS:
            impact = "low"

        # direction 검증
        direction = str(item.get("direction", "")).lower()
        if direction not in _VALID_DIRECTIONS:
            direction = "neutral"

        # category 검증
        category = str(item.get("category", "")).lower()
        if category not in _VALID_CATEGORIES:
            category = "other"

        # sentiment_score 검증 및 클램프
        try:
            sentiment_score = float(item.get("sentiment_score", 0.0))
        except (ValueError, TypeError):
            sentiment_score = 0.0
        sentiment_score = max(-1.0, min(1.0, sentiment_score))

        # tickers 검증
        tickers = item.get("tickers", [])
        if not isinstance(tickers, list):
            tickers = []
        tickers = [str(t).upper() for t in tickers if isinstance(t, str) and t.strip()]

        return {
            "id": str(item["id"]),
            "impact": impact,
            "tickers": tickers,
            "direction": direction,
            "sentiment_score": round(sentiment_score, 4),
            "category": category,
        }

    @staticmethod
    def save_signals(
        signals: list[dict[str, Any]],
        path: Path | str | None = None,
    ) -> None:
        """분류 결과를 JSON 파일로 저장한다.

        스케줄러 플로우에서 classified_signals.json에 결과를 영속화할 때 사용한다.

        Args:
            signals: 분류된 신호 목록.
            path: 저장 경로. None이면 data/classified_signals.json 사용.
        """
        target = Path(path) if path else _DEFAULT_SIGNALS_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(signals, f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info("분류 신호 저장 완료: %s (%d건)", target, len(signals))

    @staticmethod
    def load_signals(
        path: Path | str | None = None,
    ) -> list[dict[str, Any]]:
        """이전에 저장된 분류 결과를 JSON 파일에서 로드한다.

        Args:
            path: 파일 경로. None이면 data/classified_signals.json 사용.

        Returns:
            분류 결과 목록. 파일이 없으면 빈 목록.
        """
        target = Path(path) if path else _DEFAULT_SIGNALS_FILE
        if not target.exists():
            logger.info("저장된 분류 신호 없음: %s", target)
            return []
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                logger.info("분류 신호 로드 완료: %s (%d건)", target, len(data))
                return data
            logger.warning("분류 신호 파일 형식 오류: 배열이 아닙니다.")
            return []
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("분류 신호 로드 실패: %s", exc)
            return []

    @staticmethod
    def _chunk_articles(articles: list[Any], size: int) -> list[list[Any]]:
        """기사 목록을 지정된 크기의 배치로 분할한다.

        Args:
            articles: 전체 기사 목록.
            size: 배치당 기사 수.

        Returns:
            배치 리스트의 리스트.
        """
        return [articles[i:i + size] for i in range(0, len(articles), size)]

    async def classify_and_store_batch(
        self,
        articles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """기사를 분류하고 결과를 DB의 Article 테이블에 저장한다.

        classify_batch()를 호출하여 분류 결과를 얻은 뒤,
        각 Article 레코드의 classification, sentiment_score, is_processed 필드를
        업데이트한다. 반환값은 classify_batch()와 동일한 분류 신호 목록이다.

        Args:
            articles: 뉴스 기사 목록.
                각 항목은 ``{"id", "title", "summary", "source", "published_at"}`` 형태.

        Returns:
            분류 결과 목록 (classify_batch()와 동일한 형식).
        """
        classified_signals = await self.classify_batch(articles)

        if not classified_signals:
            logger.info("classify_and_store_batch: 분류된 신호 없음, DB 업데이트 생략.")
            return classified_signals

        try:
            from sqlalchemy import update as sa_update
            from src.db.connection import get_session
            from src.db.models import Article as ArticleModel

            async with get_session() as session:
                for signal in classified_signals:
                    article_id = signal.get("id")
                    if not article_id:
                        continue
                    stmt = (
                        sa_update(ArticleModel)
                        .where(ArticleModel.id == str(article_id))
                        .values(
                            classification={
                                "impact": signal.get("impact", "low"),
                                "direction": signal.get("direction", "neutral"),
                                "category": signal.get("category", "other"),
                                "tickers": signal.get("tickers", []),
                            },
                            sentiment_score=signal.get("sentiment_score", 0.0),
                            is_processed=True,
                        )
                    )
                    await session.execute(stmt)
                await session.commit()

            logger.info(
                "classify_and_store_batch: %d건 분류 결과 DB 저장 완료",
                len(classified_signals),
            )
        except Exception as exc:
            logger.error("classify_and_store_batch: DB 저장 실패: %s", exc)

        return classified_signals

    async def translate_and_analyze_batch(self, articles: list[Article]) -> int:
        """기사 목록을 한국어로 번역하고 기업 영향을 분석한다.

        분류 완료된(is_processed=True) 기사를 배치 10건씩 Claude Sonnet에
        전달하여 headline_kr, summary_ko, companies_impact 필드를 채운다.
        결과는 DB에 즉시 저장한다.

        Args:
            articles: 번역 대상 Article ORM 객체 목록.

        Returns:
            번역 성공한 기사 수.
        """
        if not articles:
            logger.info("번역 대상 기사 없음.")
            return 0

        from src.db.connection import get_session

        chunks = self._chunk_articles(articles, _TRANSLATE_BATCH_SIZE)
        logger.info(
            "한국어 번역/분석 시작: 총 %d건, %d개 배치",
            len(articles), len(chunks),
        )

        total_success = 0
        for i, chunk in enumerate(chunks):
            try:
                translated = await self._translate_chunk(chunk)
                if not translated:
                    continue

                # DB 저장
                async with get_session() as session:
                    for article_obj, result in zip(chunk, translated):
                        article_obj.headline_kr = result.get("headline_kr")
                        article_obj.summary_ko = result.get("summary_ko")
                        companies_impact = result.get("companies_impact")
                        if isinstance(companies_impact, dict):
                            article_obj.companies_impact = companies_impact
                        await session.merge(article_obj)
                    await session.commit()

                total_success += len(translated)
                logger.info(
                    "번역 배치 %d/%d 완료: %d건 저장",
                    i + 1, len(chunks), len(translated),
                )
            except Exception as exc:
                logger.error("번역 배치 %d/%d 실패: %s", i + 1, len(chunks), exc)

        logger.info("한국어 번역/분석 완료: %d/%d건 성공", total_success, len(articles))
        return total_success

    async def _translate_chunk(self, chunk: list[Article]) -> list[dict[str, Any]]:
        """단일 배치에 대해 Claude Sonnet을 호출하여 번역 및 기업 영향을 분석한다.

        Args:
            chunk: 한 배치에 해당하는 Article ORM 객체 목록.

        Returns:
            번역 결과 딕셔너리 목록. 각 항목:
                - headline_kr: 한국어 헤드라인
                - summary_ko: 한국어 요약 (2-3줄)
                - companies_impact: {TICKER: 영향 분석 2줄} 딕셔너리
        """
        news_list_lines = []
        for idx, article in enumerate(chunk, start=1):
            tickers = article.tickers_mentioned or []
            ticker_str = ", ".join(tickers[:5]) if tickers else "없음"
            content_preview = (article.content or "")[:500]
            news_list_lines.append(
                f"{idx}. {article.headline} (관련: {ticker_str})\n"
                f"   내용: {content_preview}"
            )

        news_block = "\n".join(news_list_lines)

        prompt = (
            "다음 영어 뉴스를 한국어로 번역하고 관련 기업 영향을 분석하세요.\n\n"
            "각 뉴스에 대해 다음 JSON 형식으로 반환하세요:\n"
            "{\n"
            '  "articles": [\n'
            "    {\n"
            '      "headline": "원문 헤드라인",\n'
            '      "headline_kr": "한국어 헤드라인",\n'
            '      "summary_ko": "한국어 요약 (2-3줄. 핵심 내용과 시장 영향 포함)",\n'
            '      "companies_impact": {\n'
            '        "TICKER": "해당 기업에 대한 영향 분석 2줄"\n'
            "      }\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "규칙:\n"
            "- companies_impact는 뉴스에서 실제로 언급된 티커만 포함하세요.\n"
            "- 티커가 없으면 companies_impact를 빈 객체 {}로 반환하세요.\n"
            "- summary_ko는 반드시 한국어로 작성하세요.\n"
            "- articles 배열의 순서는 입력 뉴스 순서와 동일해야 합니다.\n\n"
            f"뉴스 목록:\n{news_block}"
        )

        try:
            raw = await self.client.call_json(
                prompt=prompt,
                task_type="telegram_chat",
                max_tokens=4096,
                use_cache=False,
            )
        except Exception as exc:
            logger.error("번역 청크 Claude 호출 실패: %s", exc)
            return []

        # call_json은 dict 또는 list를 반환한다.
        if isinstance(raw, dict):
            articles_data = raw.get("articles", [])
        elif isinstance(raw, list):
            articles_data = raw
        else:
            logger.warning("번역 응답 형식 오류: %s", type(raw))
            return []

        if not isinstance(articles_data, list):
            logger.warning("번역 articles 필드가 배열이 아닙니다.")
            return []

        results = []
        for item in articles_data:
            if not isinstance(item, dict):
                continue
            companies_impact = item.get("companies_impact", {})
            if not isinstance(companies_impact, dict):
                companies_impact = {}
            results.append({
                "headline_kr": item.get("headline_kr") or "",
                "summary_ko": item.get("summary_ko") or "",
                "companies_impact": companies_impact,
            })

        # 입력 배치 크기에 맞게 패딩 (Claude가 일부 항목을 누락한 경우)
        while len(results) < len(chunk):
            results.append({"headline_kr": "", "summary_ko": "", "companies_impact": {}})

        return results[:len(chunk)]

    async def translate_unprocessed(self, limit: int = _DEFAULT_UNPROCESSED_LIMIT) -> int:
        """미번역 기사를 DB에서 조회하여 번역 및 기업 영향 분석을 실행한다.

        is_processed=True 이지만 headline_kr IS NULL인 기사를 대상으로 한다.

        Args:
            limit: 한 번에 처리할 최대 기사 수. 기본 50.

        Returns:
            번역 성공한 기사 수.
        """
        try:
            from sqlalchemy import select
            from src.db.connection import get_session
            from src.db.models import Article

            async with get_session() as session:
                stmt = (
                    select(Article)
                    .where(Article.is_processed.is_(True))
                    .where(Article.headline_kr.is_(None))
                    .order_by(Article.published_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                articles = list(result.scalars().all())

            if not articles:
                logger.info("미번역 기사 없음.")
                return 0

            logger.info("미번역 기사 %d건 번역 시작", len(articles))
            return await self.translate_and_analyze_batch(articles)
        except Exception as exc:
            logger.error("미번역 기사 조회/번역 실패: %s", exc)
            return 0
