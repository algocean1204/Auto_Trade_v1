"""
MLX 로컬 뉴스 분류기

Qwen3-30B-A3B MoE 모델을 Apple Silicon MPS에서 MLX로 실행하여
뉴스 기사를 분류한다. Claude API의 로컬 대체로 사용된다.

2단계 필터링 파이프라인:
  1단계: Python 규칙 기반 필터 (RuleBasedFilter + SimilarityChecker)
  2단계: AI 의미 분석 (Qwen3-30B-A3B via MLX)

모델 로드 실패 시 기존 NewsClassifier(Claude API)로 graceful fallback한다.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# mlx-lm은 Apple Silicon에서만 동작하므로 지연 임포트
_MLX_AVAILABLE = False

try:
    import mlx_lm

    _MLX_AVAILABLE = True
except ImportError:
    logger.warning("mlx-lm이 설치되어 있지 않다. MLXClassifier를 사용할 수 없다.")

# JSON 코드블록 패턴
_JSON_BLOCK_PATTERN = re.compile(
    r"```(?:json)?\s*\n?([\s\S]*?)\n?```",
    re.DOTALL,
)

# 분류 결과 허용 값
_VALID_RELEVANCE = frozenset({"high", "medium", "low"})
_VALID_SENTIMENTS = frozenset({"bullish", "bearish", "neutral"})
_VALID_IMPACTS = frozenset({"high", "medium", "low"})

# 최소 신뢰도 임계값 (레버리지 ETF이므로 보수적으로 운용)
MIN_CONFIDENCE: float = 0.90

# 시스템 프롬프트
_SYSTEM_PROMPT = """You are a financial news analyst specializing in ETF and leveraged ETF trading.
Your task is to classify news articles for their relevance to ETF trading decisions.

For each article, you MUST return a JSON object with exactly these fields:
- "relevance": "high", "medium", or "low"
- "sentiment": "bullish", "bearish", or "neutral"
- "impact": "high", "medium", or "low"
- "confidence": a float between 0.0 and 1.0
- "summary": a 1-2 sentence summary of the article's market impact
- "tickers_affected": a list of ticker symbols affected (e.g., ["SPY", "QQQ", "TQQQ"])

Return ONLY valid JSON, no extra text."""


class MLXClassifier:
    """MLX를 이용한 로컬 뉴스 분류기.

    Qwen3-30B-A3B MoE 모델을 Apple Silicon MPS에서 실행하여
    뉴스 기사를 분류한다. Claude API의 로컬 대체로 사용된다.

    Attributes:
        model_name: MLX 모델 ID.
        model: 로드된 MLX 모델 인스턴스.
        tokenizer: 토크나이저 인스턴스.
    """

    MODEL_NAME: str = "mlx-community/Qwen3-30B-A3B-4bit"
    MIN_CONFIDENCE: float = MIN_CONFIDENCE  # 모듈 레벨 상수 참조

    def __init__(self) -> None:
        """MLXClassifier를 초기화한다."""
        self.model: Any = None
        self.tokenizer: Any = None
        self.is_loaded: bool = False
        self._loading: bool = False
        self._load_error: str | None = None
        self._load_lock: asyncio.Lock = asyncio.Lock()

        logger.info(
            "MLXClassifier 초기화 | model=%s | mlx_available=%s",
            self.MODEL_NAME,
            _MLX_AVAILABLE,
        )

    def is_available(self) -> bool:
        """모델 사용 가능 여부를 확인한다 (MPS 체크 + 모델 로드 상태).

        Returns:
            mlx-lm이 설치되어 있고, 모델이 로드되었거나 로드 가능한 상태이면 True.
        """
        if not _MLX_AVAILABLE:
            return False
        if self._load_error and not self.is_loaded:
            return False
        return True

    async def load_model(self) -> None:
        """모델을 로드한다 (최초 1회, 비동기).

        이미 로드되었거나 로드 중이면 무시한다.
        asyncio.Lock으로 동시 로드 레이스 컨디션을 방지한다.
        mlx-lm 미설치 시 에러 없이 반환하며, is_loaded는 False로 유지된다.
        """
        # 빠른 경로: Lock 없이 먼저 확인
        if self.is_loaded:
            return

        if not _MLX_AVAILABLE:
            self._load_error = "mlx-lm 미설치"
            logger.warning("모델 로드 불가: %s", self._load_error)
            return

        async with self._load_lock:
            # Lock 획득 후 재확인 (다른 코루틴이 먼저 로드했을 수 있음)
            if self.is_loaded or self._loading:
                return

            self._loading = True
            logger.info("MLX 모델 로드 시작: %s", self.MODEL_NAME)

            try:
                model, tokenizer = await asyncio.to_thread(
                    mlx_lm.load, self.MODEL_NAME
                )
                self.model = model
                self.tokenizer = tokenizer
                self.is_loaded = True
                self._load_error = None
                logger.info("MLX 모델 로드 완료: %s", self.MODEL_NAME)
            except Exception as exc:
                self._load_error = str(exc)
                logger.error("MLX 모델 로드 실패: %s", exc)
            finally:
                self._loading = False

    async def classify_batch(
        self, articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """기사 배치를 로컬 AI로 분류한다.

        NewsClassifier.classify_batch()와 동일한 반환 형식을 따른다.
        모델 미로드 시 자동으로 로드를 시도한다.

        Args:
            articles: 뉴스 기사 목록. 각 항목은
                ``{"id", "title", "summary", "source", "published_at"}`` 형태.

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
            logger.info("분류할 기사가 없다.")
            return []

        if not self.is_loaded:
            await self.load_model()
        if not self.is_loaded:
            logger.error(
                "MLX 모델 미로드 상태로 분류 불가: %s",
                self._load_error or "알 수 없는 오류",
            )
            return []

        logger.info("MLX 분류 시작: 총 %d건", len(articles))
        start = time.monotonic()

        results: list[dict[str, Any]] = []
        for article in articles:
            try:
                classified = await self._classify_single(article)
                if classified is not None:
                    results.append(classified)
            except Exception as exc:
                logger.error(
                    "기사 분류 실패 | id=%s | error=%s",
                    article.get("id", "unknown"),
                    exc,
                )

        elapsed = time.monotonic() - start
        logger.info(
            "MLX 분류 완료: %d/%d건 성공 | elapsed=%.1fs",
            len(results),
            len(articles),
            elapsed,
        )
        return results

    async def _classify_single(
        self, article: dict[str, Any]
    ) -> dict[str, Any] | None:
        """단일 기사를 분류한다.

        Args:
            article: 뉴스 기사 딕셔너리.

        Returns:
            NewsClassifier 호환 분류 결과 딕셔너리, 실패 시 None.
        """
        prompt = self._build_classification_prompt(article)
        article_id = str(article.get("id", "unknown"))

        try:
            raw_text = await asyncio.to_thread(
                mlx_lm.generate,
                self.model,
                self.tokenizer,
                prompt=prompt,
                max_tokens=512,
            )
        except Exception as exc:
            logger.error(
                "MLX 생성 실패 | article_id=%s | error=%s",
                article_id,
                exc,
            )
            return None

        parsed = self._extract_json(raw_text)
        if parsed is None:
            logger.warning(
                "MLX JSON 파싱 실패 | article_id=%s | content_preview=%s",
                article_id,
                raw_text[:200],
            )
            return None

        return self._validate_and_convert(article_id, parsed)

    def _build_classification_prompt(self, article: dict[str, Any]) -> str:
        """분류 프롬프트를 생성한다.

        Args:
            article: 뉴스 기사 딕셔너리.

        Returns:
            모델에 전달할 프롬프트 문자열.
        """
        title = article.get("title", article.get("headline", ""))
        summary = article.get("summary", article.get("content", ""))
        source = article.get("source", "unknown")

        prompt = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"---\n"
            f"Headline: {title}\n"
            f"Summary: {summary}\n"
            f"Source: {source}\n"
            f"---\n\n"
            f"Classify this article. Return ONLY a JSON object."
        )
        return prompt

    def _validate_and_convert(
        self, article_id: str, parsed: dict[str, Any]
    ) -> dict[str, Any] | None:
        """MLX 분류 결과를 검증하고 NewsClassifier 호환 형식으로 변환한다.

        Args:
            article_id: 기사 ID.
            parsed: MLX 모델이 반환한 파싱된 JSON 딕셔너리.

        Returns:
            NewsClassifier 호환 딕셔너리, 유효하지 않으면 None.
        """
        if not isinstance(parsed, dict):
            logger.warning("분류 결과가 딕셔너리가 아니다: %s", type(parsed))
            return None

        # relevance 검증 (high/medium만 통과)
        relevance = str(parsed.get("relevance", "low")).lower()
        if relevance not in _VALID_RELEVANCE:
            relevance = "low"
        if relevance == "low":
            logger.debug(
                "관련성 low로 필터링됨 | article_id=%s", article_id
            )
            return None

        # sentiment 검증
        sentiment = str(parsed.get("sentiment", "neutral")).lower()
        if sentiment not in _VALID_SENTIMENTS:
            sentiment = "neutral"

        # impact 검증
        impact = str(parsed.get("impact", "low")).lower()
        if impact not in _VALID_IMPACTS:
            impact = "low"

        # confidence 검증
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        # tickers 검증
        tickers = parsed.get("tickers_affected", [])
        if not isinstance(tickers, list):
            tickers = []
        tickers = [
            str(t).upper() for t in tickers if isinstance(t, str) and t.strip()
        ]

        # summary 추출
        summary = str(parsed.get("summary", ""))

        # sentiment -> sentiment_score 변환
        sentiment_score_map = {
            "bullish": 0.7,
            "bearish": -0.7,
            "neutral": 0.0,
        }
        sentiment_score = sentiment_score_map.get(sentiment, 0.0)
        # confidence로 가중
        sentiment_score = round(sentiment_score * confidence, 4)

        # relevance -> category 매핑 (기본값)
        category = "other"
        summary_lower = summary.lower()
        if any(kw in summary_lower for kw in ("earnings", "revenue", "profit")):
            category = "earnings"
        elif any(kw in summary_lower for kw in ("fed", "rate", "inflation", "gdp", "cpi")):
            category = "macro"
        elif any(kw in summary_lower for kw in ("policy", "regulation", "tariff", "sanction")):
            category = "policy"
        elif any(kw in summary_lower for kw in ("sector", "industry")):
            category = "sector"
        elif any(kw in summary_lower for kw in ("geopolit", "war", "conflict", "tension")):
            category = "geopolitics"
        elif tickers:
            category = "company"

        return {
            "id": article_id,
            "impact": impact,
            "tickers": tickers,
            "direction": sentiment,
            "sentiment_score": sentiment_score,
            "category": category,
        }

    async def unload(self) -> None:
        """모델을 메모리에서 해제한다."""
        if not self.is_loaded:
            return

        logger.info("MLX 모델 메모리 해제 시작")
        self.model = None
        self.tokenizer = None
        self.is_loaded = False

        import gc
        gc.collect()

        logger.info("MLX 모델 메모리 해제 완료")

    def get_status(self) -> dict[str, Any]:
        """모델 상태 정보를 반환한다.

        Returns:
            모델 상태 딕셔너리.
        """
        return {
            "model_name": self.MODEL_NAME,
            "is_loaded": self.is_loaded,
            "is_available": self.is_available(),
            "loading": self._loading,
            "load_error": self._load_error,
            "mlx_available": _MLX_AVAILABLE,
            "min_confidence": self.MIN_CONFIDENCE,
        }

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """텍스트에서 JSON 객체를 추출한다.

        우선순위:
          1. ```json ... ``` 코드블록 내부
          2. 텍스트 전체를 직접 파싱
          3. 첫 번째 { 부터 마지막 } 까지 추출

        Args:
            text: JSON이 포함된 텍스트.

        Returns:
            파싱된 JSON 딕셔너리, 실패 시 None.
        """
        # 1) 코드블록에서 추출
        match = _JSON_BLOCK_PATTERN.search(text)
        if match:
            try:
                result = json.loads(match.group(1).strip())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # 2) 전체 텍스트 직접 파싱
        stripped = text.strip()
        try:
            result = json.loads(stripped)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # 3) 첫 { 부터 마지막 } 까지 추출
        start = stripped.find("{")
        end = stripped.rfind("}") + 1
        if start == -1 or end <= start:
            return None

        try:
            result = json.loads(stripped[start:end])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        return None
