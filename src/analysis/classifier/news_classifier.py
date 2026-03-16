"""F2 AI 분석 -- MLX 1차 필터 + Claude Sonnet 정밀 분류로 뉴스를 분류한다.

MLX 3모델 앙상블로 시장 무관 기사를 빠르게 걸러내고(impact=low),
medium/high 기사는 Claude Sonnet으로 단타 트레이딩 맥락에서 정밀 분석한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.analysis.models import ClassifiedNews
from src.common.ai_gateway import AiClient, AiResponse
from src.common.logger import get_logger
from src.crawlers.models import VerifiedArticle

logger: logging.Logger = get_logger(__name__)

# 분류 카테고리 목록이다
_CATEGORIES: list[str] = ["macro", "earnings", "policy", "sector", "geopolitical"]

# 방향 분류 목록이다
_DIRECTIONS: list[str] = ["bullish", "bearish", "neutral"]

# Claude 정밀 분석 임계값이다 — medium(0.55) 이상은 모두 Claude로 분석한다
_PRECISION_THRESHOLD: float = 0.5

# 영향도 분류 — MLX가 high/medium/low를 분류하면 수치로 변환한다
_IMPACT_LEVELS: list[str] = ["high", "medium", "low"]
_IMPACT_HIGH: float = 0.85
_IMPACT_MEDIUM: float = 0.55
_IMPACT_LOW: float = 0.25
_IMPACT_SCORE_MAP: dict[str, float] = {
    "high": _IMPACT_HIGH, "medium": _IMPACT_MEDIUM, "low": _IMPACT_LOW,
}


def _build_classify_prompt(article: VerifiedArticle) -> str:
    """2X 레버리지 ETF 단타 트레이딩 관점의 Claude 분류 프롬프트를 생성한다."""
    return (
        "너는 미국 2X 레버리지 ETF(SOXL, QLD, TQQQ, UPRO, SSO, UCO, ERX 등) "
        "단타 트레이딩 전문 뉴스 분석가이다.\n\n"
        "아래 뉴스를 분석하여 반드시 JSON만 출력하라:\n"
        "{\n"
        '  "impact_score": 0.0~1.0 (이 뉴스가 레버리지 ETF 가격에 미치는 영향도. '
        "개인재무/연예/스포츠 등 시장 무관 기사는 0.0~0.05),\n"
        '  "direction": "bullish" | "bearish" | "neutral" '
        "(기술주/반도체/광범위 시장 관점 방향. 유가 상승은 비용 증가→기술주 bearish),\n"
        '  "category": "macro" | "earnings" | "policy" | "sector" | "geopolitical",\n'
        '  "tickers_affected": ["영향받는 레버리지 ETF 티커. 반드시 1개 이상 포함. '
        "예: SOXL(반도체), QLD/TQQQ(나스닥), UPRO/SSO(S&P), UCO(유가), ERX(에너지)\"],\n"
        '  "time_sensitivity": "breaking" | "developing" | "analysis" | "background"\n'
        "    (breaking=방금 발생한 속보, developing=진행 중 사건, "
        "analysis=분석/전망, background=배경 정보),\n"
        '  "actionability": "immediate" | "watch" | "informational"\n'
        "    (immediate=지금 매매 판단 필요, watch=주시 필요, "
        "informational=참고만),\n"
        '  "leveraged_etf_impact": "SOXL/QLD/TQQQ 등 2X ETF에 대한 영향 한줄 요약 (한국어)",\n'
        '  "reasoning": "한국어 분석 (2~3문장, 레버리지 ETF 단타 관점)"\n'
        "}\n\n"
        "핵심 규칙:\n"
        "- direction은 우리가 거래하는 레버리지 ETF(기술주/반도체/광범위 시장) 관점이다\n"
        "- 유가 급등/지정학 위기 → 기술주 bearish (비용 상승, 위험 회피)\n"
        "- 개인 재무 상담, 스트리밍 추천, 스포츠 등 시장 무관 기사 → impact_score 0.0~0.05\n"
        "- tickers_affected는 절대 빈 배열 금지. impact_score>0.05면 반드시 관련 ETF 포함\n"
        "  예: 반도체→SOXL, 나스닥/기술주→QLD/TQQQ, S&P→UPRO, 유가→UCO, 에너지→ERX\n"
        "- impact_score는 0.0~1.0 연속값 (0.25/0.55/0.85 같은 고정값 금지)\n\n"
        f"제목: {json.dumps(article.title, ensure_ascii=False)}\n"
        f"내용: {json.dumps(article.content[:2000], ensure_ascii=False)}\n"
        f"출처: {json.dumps(article.source, ensure_ascii=False)}\n"
        f"발행일: {json.dumps(article.published_at, default=str)}\n\n"
        "JSON만 출력하라:"
    )


def _parse_claude_response(raw: str) -> dict | None:
    """Claude 응답에서 JSON을 파싱한다. 실패 시 None을 반환한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("Claude 응답 JSON 파싱 실패 — 이번 분석 건너뜀: %s", raw[:200])
        return None


async def _classify_single_local(
    article: VerifiedArticle,
    ai_client: AiClient,
) -> ClassifiedNews:
    """MLX 로컬 모델로 단일 기사를 1차 분류한다.

    카테고리/방향/시장영향도 3개를 각각 분류한다.
    impact_score는 MLX가 high/medium/low로 평가한 결과의 수치 변환값이다.
    medium 이상은 이후 Claude에서 정밀 분석된다.
    """
    text = f"{article.title} {article.content[:500]}"
    cat_result = await ai_client.local_classify(text, _CATEGORIES)
    dir_result = await ai_client.local_classify(text, _DIRECTIONS)
    impact_result = await ai_client.local_classify(text, _IMPACT_LEVELS)
    impact = _IMPACT_SCORE_MAP.get(impact_result.category, 0.5)

    return ClassifiedNews(
        title=article.title,
        content=article.content,
        url=article.url,
        source=article.source,
        published_at=article.published_at,
        impact_score=round(impact, 3),
        direction=dir_result.category,
        category=cat_result.category,
        reasoning=cat_result.reasoning,
    )


# 유효한 레버리지 ETF 티커 목록이다
_VALID_TICKERS: set[str] = {
    "SOXL", "SOXS", "QLD", "QID", "TQQQ", "SQQQ",
    "UPRO", "SPXU", "SSO", "SDS", "UCO", "SCO",
    "ERX", "ERY", "NUGT", "DUST", "LABU", "LABD",
    "TNA", "TZA", "UDOW", "SDOW", "FAS", "FAZ",
}


def _validate_tickers(tickers: list) -> list[str]:
    """tickers_affected를 검증하고 유효한 티커만 반환한다.

    빈 배열이면 기본 QLD를 반환한다 (프롬프트에서 빈 배열 금지).
    """
    if not isinstance(tickers, list):
        return ["QLD"]
    valid = [t for t in tickers if isinstance(t, str) and t.upper() in _VALID_TICKERS]
    return valid if valid else ["QLD"]


async def _refine_with_claude(
    news: ClassifiedNews,
    ai_client: AiClient,
) -> ClassifiedNews:
    """Claude Sonnet으로 뉴스를 단타 트레이딩 관점에서 정밀 재분석한다."""
    article = VerifiedArticle(
        title=news.title, content=news.content, url=news.url,
        source=news.source, published_at=news.published_at,
        language="en", content_hash="", quality_score=1.0,
    )
    prompt = _build_classify_prompt(article)
    response: AiResponse = await ai_client.send_text(
        prompt, model="sonnet", max_tokens=1024,
    )
    parsed = _parse_claude_response(response.content)

    if not parsed:
        return news

    return news.model_copy(update={
        "impact_score": parsed.get("impact_score", news.impact_score),
        "direction": parsed.get("direction", news.direction),
        "category": parsed.get("category", news.category),
        "tickers_affected": _validate_tickers(parsed.get("tickers_affected", [])),
        "reasoning": parsed.get("reasoning", news.reasoning),
        "time_sensitivity": parsed.get("time_sensitivity", "analysis"),
        "actionability": parsed.get("actionability", "informational"),
        "leveraged_etf_impact": parsed.get("leveraged_etf_impact", ""),
    })


# 키워드 기반 3차 폴백용 패턴이다
_KEYWORD_HIGH: set[str] = {
    "crash", "halt", "halted", "surge", "plunge", "crisis", "emergency",
    "bankrupt", "default", "recession", "fed", "rate cut", "rate hike",
    "circuit breaker", "margin call", "급락", "급등", "폭락", "폭등",
    "파산", "긴급", "서킷브레이커", "금리",
}
_KEYWORD_BEARISH: set[str] = {
    "crash", "plunge", "fall", "drop", "decline", "down", "loss", "weak",
    "halt", "halted", "crisis", "bankrupt", "recession", "default",
    "급락", "폭락", "하락", "약세", "파산", "위기",
}
_KEYWORD_BULLISH: set[str] = {
    "surge", "rally", "jump", "gain", "rise", "up", "strong", "boom",
    "record", "high", "beat", "exceed",
    "급등", "폭등", "상승", "강세", "신고가", "호실적",
}
_KEYWORD_TICKERS: dict[str, list[str]] = {
    "semiconductor": ["SOXL"], "chip": ["SOXL"], "반도체": ["SOXL"],
    "nvidia": ["SOXL"], "amd": ["SOXL"], "tsmc": ["SOXL"],
    "nasdaq": ["QLD", "TQQQ"], "나스닥": ["QLD", "TQQQ"],
    "tech": ["QLD", "TQQQ"], "기술주": ["QLD", "TQQQ"],
    "s&p": ["UPRO", "SSO"], "oil": ["UCO"], "유가": ["UCO"],
    "energy": ["ERX"], "에너지": ["ERX"],
}


def _fallback_keyword(article: VerifiedArticle) -> ClassifiedNews:
    """AI 분류 전부 실패 시 키워드 기반으로 분류한다.

    긴급 뉴스가 분류 실패로 사라지는 것을 방지한다.
    키워드 매칭이므로 정확도는 낮지만, 기사 손실보다 낫다.
    """
    text = f"{article.title} {article.content[:300]}".lower()

    # 영향도 판정
    is_high = any(kw in text for kw in _KEYWORD_HIGH)
    impact = 0.7 if is_high else 0.4

    # 방향 판정
    bear_count = sum(1 for kw in _KEYWORD_BEARISH if kw in text)
    bull_count = sum(1 for kw in _KEYWORD_BULLISH if kw in text)
    if bear_count > bull_count:
        direction = "bearish"
    elif bull_count > bear_count:
        direction = "bullish"
    else:
        direction = "neutral"

    # 관련 티커 추출
    tickers: set[str] = set()
    for keyword, etfs in _KEYWORD_TICKERS.items():
        if keyword in text:
            tickers.update(etfs)
    if not tickers:
        tickers = {"QLD"}  # 기본 나스닥 ETF

    logger.info(
        "키워드 폴백 분류: %s → impact=%.1f, dir=%s, tickers=%s",
        article.title[:40], impact, direction, tickers,
    )

    return ClassifiedNews(
        title=article.title,
        content=article.content,
        url=article.url,
        source=article.source,
        published_at=article.published_at,
        impact_score=impact,
        direction=direction,
        category="macro",
        tickers_affected=list(tickers),
        reasoning="[키워드 폴백] AI 분류 실패, 키워드 기반 자동 분류",
        time_sensitivity="developing" if is_high else "background",
        actionability="watch" if is_high else "informational",
        leveraged_etf_impact="",
    )


class NewsClassifier:
    """MLX 1차 필터 + Claude Sonnet 정밀 분류로 뉴스를 분류한다.

    MLX로 low impact 기사를 빠르게 걸러내고,
    medium/high impact 기사는 Claude Sonnet으로 정밀 분석한다.
    """

    def __init__(self, ai_client: AiClient) -> None:
        self._ai = ai_client
        logger.info("NewsClassifier 초기화 완료")

    async def classify(
        self,
        articles: list[VerifiedArticle],
    ) -> list[ClassifiedNews]:
        """기사 목록을 분류한다. medium 이상은 Claude Sonnet으로 정밀 분석한다."""
        results: list[ClassifiedNews] = []
        for article in articles:
            classified = await self._classify_one(article)
            results.append(classified)
        logger.info("뉴스 분류 완료: %d건", len(results))
        return results

    async def _classify_one(self, article: VerifiedArticle) -> ClassifiedNews:
        """단일 기사를 분류한다.

        3단계 폴백: MLX 로컬 → Claude Sonnet → 룰 기반 키워드 분류.
        모든 단계 실패 시에도 기사를 unclassified 상태로 보존한다.
        Claude 폴백으로 분류된 기사는 이미 Claude가 분석했으므로 정밀 분석을 건너뛴다.
        """
        used_claude_fallback = False
        try:
            news = await _classify_single_local(article, self._ai)
        except Exception:
            logger.warning("로컬 분류 실패, Claude 폴백: %s", article.title[:50])
            try:
                news = await self._fallback_claude(article)
                used_claude_fallback = True
            except Exception:
                logger.warning("Claude 폴백도 실패, 키워드 분류: %s", article.title[:50])
                news = _fallback_keyword(article)

        # medium 이상은 Claude로 정밀 분석한다 — 단, 이미 Claude로 분류했으면 건너뛴다
        if not used_claude_fallback and news.impact_score >= _PRECISION_THRESHOLD:
            try:
                news = await _refine_with_claude(news, self._ai)
            except Exception:
                logger.warning(
                    "Claude 정밀 분석 실패, 로컬 결과 유지: %s",
                    article.title[:50],
                )
        return news

    async def _fallback_claude(self, article: VerifiedArticle) -> ClassifiedNews:
        """로컬 분류 실패 시 Claude Sonnet으로 분류한다."""
        prompt = _build_classify_prompt(article)
        response = await self._ai.send_text(
            prompt, model="sonnet", max_tokens=1024,
        )
        parsed = _parse_claude_response(response.content)

        if not parsed:
            # JSON 파싱 실패 시 키워드 폴백으로 전환한다
            logger.warning("Claude 응답 파싱 실패, 키워드 분류 전환: %s", article.title[:50])
            return _fallback_keyword(article)

        return ClassifiedNews(
            title=article.title,
            content=article.content,
            url=article.url,
            source=article.source,
            published_at=article.published_at,
            impact_score=parsed.get("impact_score", 0.5),
            direction=parsed.get("direction", "neutral"),
            category=parsed.get("category", "macro"),
            tickers_affected=_validate_tickers(parsed.get("tickers_affected", [])),
            reasoning=parsed.get("reasoning", ""),
            time_sensitivity=parsed.get("time_sensitivity", "analysis"),
            actionability=parsed.get("actionability", "informational"),
            leveraged_etf_impact=parsed.get("leveraged_etf_impact", ""),
        )
