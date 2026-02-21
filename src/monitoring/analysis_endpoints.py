"""
Flutter 대시보드용 종합 주식 분석 API 엔드포인트.

KIS API로 가격 데이터를 수집하고 기술적 지표를 계산한 뒤,
Claude Opus로 심층 AI 분석(현재 상황, 멀티타임프레임 예측, 매매 권고)을
수행하여 종합 분석 결과를 반환한다.

엔드포인트 목록:
  GET /api/analysis/comprehensive/{ticker}  - 종합 AI 분석 (가격 + 지표 + 뉴스 + AI)
  GET /api/analysis/ticker-news/{ticker}    - 티커별 관련 뉴스 (페이지네이션)
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from src.db.connection import get_session
from src.db.models import Article
from src.utils.logger import get_logger
from src.utils.ticker_mapping import (
    SECTOR_TICKERS,
    UNDERLYING_TO_LEVERAGED,
    get_analysis_ticker,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# api_server.py 가 startup 시 set_analysis_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}


def set_analysis_deps(kis_client: Any = None, claude_client: Any = None) -> None:
    """런타임 의존성을 주입한다.

    api_server.py 의 set_dependencies() 호출 시 함께 호출되어야 한다.

    Args:
        kis_client: KIS API 클라이언트 인스턴스.
        claude_client: Claude 클라이언트 인스턴스.
    """
    _deps["kis_client"] = kis_client
    _deps["claude_client"] = claude_client


async def _get_or_create_claude_client() -> Any | None:
    """주입된 claude_client를 반환하거나 없으면 지연 초기화한다.

    main.py 또는 start_dashboard.py가 실행 중일 때는
    set_analysis_deps()로 주입된 클라이언트를 사용한다.
    클라이언트가 없으면 설정값(CLAUDE_MODE)을 그대로 읽어 ClaudeClient를 직접 생성한다.

    호스트에서 직접 실행되므로 Docker 모드 전환 로직이 없다.

    우선순위:
      1. 이미 주입된 claude_client 사용
      2. CLAUDE_MODE=api 이면 api 모드로 생성 (ANTHROPIC_API_KEY 필요)
      3. CLAUDE_MODE=local 이면 local 모드로 생성 (claude CLI 설치 필요)

    Returns:
        ClaudeClient 인스턴스 또는 None (생성 불가 시).
    """
    client = _deps.get("claude_client")
    if client is not None:
        return client

    # 지연 초기화: 이미 한 번 시도했다면 재시도하지 않는다.
    if _deps.get("_claude_init_attempted"):
        return None

    _deps["_claude_init_attempted"] = True

    try:
        from src.analysis.claude_client import ClaudeClient
        from src.utils.config import get_settings

        settings = get_settings()
        mode = settings.claude_mode  # "local" 또는 "api"
        api_key = settings.anthropic_api_key

        if mode == "api":
            if not api_key:
                logger.warning(
                    "CLAUDE_MODE=api 이지만 ANTHROPIC_API_KEY가 설정되지 않아 "
                    "Claude 클라이언트를 초기화할 수 없습니다."
                )
                return None
            client = ClaudeClient(mode="api", api_key=api_key)
        else:
            # local 모드: Claude Code CLI가 설치되어 있어야 한다.
            client = ClaudeClient(mode="local")

        _deps["claude_client"] = client
        logger.info(
            "Claude 클라이언트 지연 초기화 완료 | mode=%s",
            mode,
        )
        return client
    except Exception as exc:
        logger.warning("Claude 클라이언트 지연 초기화 실패: %s", exc)
        return None


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _article_to_dict(article: Article) -> dict[str, Any]:
    """Article ORM 객체를 분석 응답용 딕셔너리로 변환한다.

    Args:
        article: Article ORM 인스턴스.

    Returns:
        id, headline, headline_original, summary_ko, companies_impact,
        published_at, sentiment_score, impact, source 키를 포함하는 딕셔너리.
    """
    classification = article.classification or {}
    return {
        "id": str(article.id),
        "headline": article.headline_kr or article.headline,
        "headline_original": article.headline,
        "summary_ko": article.summary_ko,
        "companies_impact": article.companies_impact,
        "published_at": (
            article.published_at.isoformat() if article.published_at else None
        ),
        "sentiment_score": article.sentiment_score,
        "impact": classification.get("impact", "low"),
        "source": article.source,
    }


def _safe_dict(value: Any, default: dict | None = None) -> dict:
    """값이 dict가 아닌 경우 빈 dict 또는 기본값을 반환한다.

    calculator.py 의 일부 지표(adx, atr, volume_ratio, obv)는 float 을 반환하므로
    dict 로 가정한 .get() 호출 전에 반드시 이 함수를 거쳐야 한다.

    Args:
        value: 검사할 값.
        default: dict 가 아닌 경우 반환할 기본값. None 이면 {} 를 사용한다.

    Returns:
        value 가 dict 이면 value, 아니면 default (또는 {}).
    """
    if isinstance(value, dict):
        return value
    return default if default is not None else {}


def _build_technical_summary(indicators: dict[str, Any], current_price: float) -> dict[str, Any]:
    """기술적 지표 딕셔너리에서 요약 정보를 추출한다.

    Args:
        indicators: TechnicalCalculator.calculate_all() 반환 딕셔너리.
        current_price: 현재가.

    Returns:
        composite_score, rsi_14, macd_signal, trend, support, resistance 키를
        포함하는 요약 딕셔너리.
    """
    rsi_14_raw = indicators.get("rsi_14")
    if isinstance(rsi_14_raw, dict):
        rsi_14 = float(rsi_14_raw.get("rsi", 50.0) or 50.0)
    elif rsi_14_raw is not None:
        try:
            rsi_14 = float(rsi_14_raw)
        except (TypeError, ValueError):
            rsi_14 = 50.0
    else:
        rsi_14 = 50.0

    macd_data = _safe_dict(indicators.get("macd"))
    macd_val = float(macd_data.get("macd", 0.0) or 0.0)
    macd_signal_val = float(macd_data.get("signal", 0.0) or 0.0)
    macd_signal = "bullish" if macd_val > macd_signal_val else "bearish"

    ma_cross_data = _safe_dict(indicators.get("ma_cross"))
    price_above_20 = bool(ma_cross_data.get("price_above_20", False))
    price_above_50 = bool(ma_cross_data.get("price_above_50", False))
    cross_type = str(ma_cross_data.get("cross_type", "none"))

    if price_above_20 and price_above_50:
        trend = "uptrend"
    elif not price_above_20 and not price_above_50:
        trend = "downtrend"
    else:
        trend = "sideways"

    # Bollinger Band 기반 지지/저항
    bollinger_data = _safe_dict(indicators.get("bollinger"))
    lower_band = bollinger_data.get("lower", current_price * 0.97)
    upper_band = bollinger_data.get("upper", current_price * 1.03)
    support = round(float(lower_band or current_price * 0.97), 2)
    resistance = round(float(upper_band or current_price * 1.03), 2)

    # 복합 점수: RSI 위치, MACD, MA Cross, ADX 기반 간단 합산 (-1 ~ +1)
    score_parts: list[float] = []
    if rsi_14 > 50:
        score_parts.append(min((rsi_14 - 50) / 50, 1.0))
    else:
        score_parts.append(max((rsi_14 - 50) / 50, -1.0))
    score_parts.append(0.5 if macd_signal == "bullish" else -0.5)
    if price_above_50:
        score_parts.append(0.3)
    else:
        score_parts.append(-0.3)
    if cross_type == "golden_cross":
        score_parts.append(0.2)
    elif cross_type == "dead_cross":
        score_parts.append(-0.2)

    composite_score = round(sum(score_parts) / len(score_parts), 4) if score_parts else 0.0
    composite_score = max(-1.0, min(1.0, composite_score))

    return {
        "composite_score": composite_score,
        "rsi_14": round(rsi_14, 2),
        "macd_signal": macd_signal,
        "trend": trend,
        "support": support,
        "resistance": resistance,
    }


def _build_analysis_prompt(
    ticker: str,
    current_price: float,
    price_change_pct: float,
    technical_summary: dict[str, Any],
    indicators: dict[str, Any],
    news_headlines: list[str],
) -> str:
    """Claude Opus 에 전달할 종합 분석 프롬프트를 생성한다.

    Args:
        ticker: 종목 심볼.
        current_price: 현재가 (USD).
        price_change_pct: 전일 대비 등락률 (%).
        technical_summary: 기술적 지표 요약 딕셔너리.
        indicators: 전체 기술적 지표 원본 딕셔너리.
        news_headlines: 최근 뉴스 헤드라인 목록 (최대 10개).

    Returns:
        Claude 에게 전달할 프롬프트 문자열.
    """
    # RSI: calculator 는 각 rsi_N 에 dict {"rsi": float, ...} 를 반환하지만
    #      방어적으로 float/None 도 처리한다.
    def _extract_rsi(key: str) -> Any:
        raw = indicators.get(key)
        if isinstance(raw, dict):
            return raw.get("rsi", "N/A")
        if raw is not None:
            try:
                return round(float(raw), 2)
            except (TypeError, ValueError):
                pass
        return "N/A"

    rsi_7 = _extract_rsi("rsi_7")
    rsi_14 = _extract_rsi("rsi_14")
    rsi_21 = _extract_rsi("rsi_21")

    # MACD, Stochastic, MA Cross, Bollinger 는 dict 를 반환하지만 방어적으로 처리
    macd_data = _safe_dict(indicators.get("macd"))
    stoch_data = _safe_dict(indicators.get("stochastic"))
    ma_cross = _safe_dict(indicators.get("ma_cross"))
    bollinger = _safe_dict(indicators.get("bollinger"))

    # ADX: calculator 가 float 를 직접 반환한다 → dict 로 감싼다
    adx_raw = indicators.get("adx", "N/A")
    adx_data: dict[str, Any] = adx_raw if isinstance(adx_raw, dict) else {"adx": adx_raw}

    # ATR: calculator 가 float 를 직접 반환한다 → dict 로 감싼다
    atr_raw = indicators.get("atr", "N/A")
    atr_data: dict[str, Any] = atr_raw if isinstance(atr_raw, dict) else {"atr": atr_raw}

    headlines_text = "\n".join(
        f"  - {h}" for h in news_headlines[:10]
    ) if news_headlines else "  (관련 뉴스 없음)"

    prompt = f"""당신은 미국 주식 전문 애널리스트입니다. 다음 데이터를 바탕으로 {ticker} 에 대한 심층 종합 분석을 수행하고, 반드시 JSON 형식으로만 응답하세요.

## 현재 시장 데이터
- 티커: {ticker}
- 현재가: ${current_price:.2f}
- 전일 대비 등락률: {price_change_pct:+.2f}%

## 기술적 지표
- RSI(7): {rsi_7}
- RSI(14): {rsi_14}
- RSI(21): {rsi_21}
- MACD: {macd_data.get('macd', 'N/A')} / Signal: {macd_data.get('signal', 'N/A')} / Histogram: {macd_data.get('histogram', 'N/A')}
- Stochastic K: {stoch_data.get('k', 'N/A')} / D: {stoch_data.get('d', 'N/A')}
- ADX: {adx_data.get('adx', 'N/A')} (추세 강도)
- MA20: {ma_cross.get('ma_20', 'N/A')} / MA50: {ma_cross.get('ma_50', 'N/A')}
- MA Cross: {ma_cross.get('cross_type', 'N/A')} (price_above_20={ma_cross.get('price_above_20')}, price_above_50={ma_cross.get('price_above_50')})
- Bollinger Upper: {bollinger.get('upper', 'N/A')} / Lower: {bollinger.get('lower', 'N/A')}
- ATR(14): {atr_data.get('atr', 'N/A')}
- 종합 점수: {technical_summary.get('composite_score', 'N/A')} (-1=극단적 약세, +1=극단적 강세)
- 추세: {technical_summary.get('trend', 'N/A')}
- 지지: ${technical_summary.get('support', 'N/A')} / 저항: ${technical_summary.get('resistance', 'N/A')}

## 최근 관련 뉴스 (최대 10개)
{headlines_text}

## 요청 사항
위 데이터를 바탕으로 다음 JSON 구조로 분석 결과를 반환하세요. 모든 텍스트 필드는 한국어로 작성하세요.

```json
{{
  "current_situation": "현재 시장 상황에 대한 종합적 서술 (3-5문장)",
  "reasoning": "기술적 지표와 뉴스를 종합한 판단 근거 (3-5문장)",
  "key_factors": ["핵심 요인 1", "핵심 요인 2", "핵심 요인 3"],
  "risk_factors": ["리스크 요인 1", "리스크 요인 2", "리스크 요인 3"],
  "predictions": [
    {{
      "timeframe": "1일",
      "direction": "bullish",
      "confidence": 70,
      "target_price": {current_price * 1.01:.2f},
      "reasoning": "단기 예측 근거"
    }},
    {{
      "timeframe": "3일",
      "direction": "bullish",
      "confidence": 65,
      "target_price": {current_price * 1.015:.2f},
      "reasoning": "3일 예측 근거"
    }},
    {{
      "timeframe": "7일",
      "direction": "neutral",
      "confidence": 55,
      "target_price": {current_price:.2f},
      "reasoning": "7일 예측 근거"
    }},
    {{
      "timeframe": "10일",
      "direction": "neutral",
      "confidence": 50,
      "target_price": {current_price:.2f},
      "reasoning": "10일 예측 근거"
    }},
    {{
      "timeframe": "20일",
      "direction": "neutral",
      "confidence": 50,
      "target_price": {current_price:.2f},
      "reasoning": "20일 예측 근거"
    }},
    {{
      "timeframe": "1개월",
      "direction": "neutral",
      "confidence": 45,
      "target_price": {current_price:.2f},
      "reasoning": "1개월 예측 근거"
    }},
    {{
      "timeframe": "3개월",
      "direction": "neutral",
      "confidence": 40,
      "target_price": {current_price:.2f},
      "reasoning": "3개월 예측 근거"
    }}
  ],
  "recommendation": {{
    "action": "hold",
    "reasoning": "매매 권고 근거 (2-3문장)"
  }}
}}
```

direction 값은 반드시 "bullish", "bearish", "neutral" 중 하나여야 합니다.
action 값은 반드시 "buy", "sell", "hold", "watch" 중 하나여야 합니다.
confidence 는 0~100 사이의 정수입니다.
target_price 는 실제 데이터 기반으로 합리적인 값을 계산하세요.
JSON 외의 다른 텍스트는 포함하지 마세요."""

    return prompt


# ---------------------------------------------------------------------------
# GET /api/analysis/comprehensive/{ticker}
# ---------------------------------------------------------------------------


# Claude AI 분석 호출 타임아웃 (초)
_AI_ANALYSIS_TIMEOUT: int = 120


@router.get("/comprehensive/{ticker}")
async def get_comprehensive_analysis(
    ticker: str,
    days: int = Query(default=100, ge=30, le=500, description="가격 데이터 조회 기간 (거래일 수)"),
    ai: bool = Query(default=True, description="AI 분석 포함 여부 (False이면 기술적 지표만 반환)"),
) -> dict[str, Any]:
    """특정 티커에 대한 종합 AI 분석을 반환한다.

    가격 데이터 수집 → 기술적 지표 계산 → 관련 뉴스 조회 → Claude Opus 심층 분석
    순서로 진행하며, 멀티타임프레임 예측(1일~3개월)과 매매 권고를 포함한다.

    레버리지 ETF 티커를 입력하면 자동으로 본주 데이터를 분석에 활용한다.
    ai=false 로 호출하면 Claude 분석 없이 기술적 지표만 빠르게 반환한다.

    Args:
        ticker: 종목 심볼 (예: "NVDA", "SOXL", "QLD").
        days: 가격 데이터 조회 기간 (기본 100 거래일).
        ai: AI 분석 포함 여부 (기본 True).

    Returns:
        ticker, current_price, price_change_pct, analysis_timestamp,
        technical_summary, ai_analysis, ai_available, related_news,
        price_history, indicators 키를 포함하는 종합 분석 딕셔너리.

    Raises:
        HTTPException 503: KIS 클라이언트 미초기화.
        HTTPException 404: 가격 데이터를 찾을 수 없는 경우.
        HTTPException 500: 분석 처리 중 내부 오류.
    """
    try:
        from src.indicators.calculator import TechnicalCalculator
        from src.indicators.data_fetcher import PriceDataFetcher

        original_ticker = ticker.upper()
        analysis_ticker = get_analysis_ticker(original_ticker)

        kis_client = _deps.get("kis_client")
        claude_client = await _get_or_create_claude_client()

        if kis_client is None:
            raise HTTPException(
                status_code=503,
                detail="KIS 클라이언트가 초기화되지 않았습니다. 트레이딩 시스템이 실행 중인지 확인하세요.",
            )

        # 1. 가격 데이터 수집 (본주 티커 우선, 실패 시 원래 티커)
        # 기술적 지표 계산에는 약 30일의 여유 기간이 필요하다.
        fetch_days = days + 30

        fetcher = PriceDataFetcher(kis_client)
        df = await fetcher.get_daily_prices(analysis_ticker, days=fetch_days)

        if (df is None or df.empty) and analysis_ticker != original_ticker:
            logger.warning(
                "가격 데이터 없음 (analysis_ticker=%s), 원래 티커로 재시도: %s",
                analysis_ticker,
                original_ticker,
            )
            df = await fetcher.get_daily_prices(original_ticker, days=fetch_days)
            if df is not None and not df.empty:
                analysis_ticker = original_ticker

        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"가격 데이터를 찾을 수 없습니다: {original_ticker}",
            )

        # 2. 현재가 조회 (실패 시 최근 종가 사용)
        current_price: float = float(df["Close"].iloc[-1])
        price_change_pct: float = 0.0
        try:
            price_info = await fetcher.fetch_current_price(original_ticker)
            if price_info and price_info.get("current_price", 0.0) > 0:
                current_price = float(price_info["current_price"])
                price_change_pct = float(price_info.get("change_pct", 0.0))
            elif len(df) >= 2:
                prev_close = float(df["Close"].iloc[-2])
                if prev_close > 0:
                    price_change_pct = round(
                        (current_price - prev_close) / prev_close * 100, 2
                    )
        except Exception as price_exc:
            logger.warning("현재가 조회 실패, 최근 종가 사용: %s", price_exc)
            if len(df) >= 2:
                prev_close = float(df["Close"].iloc[-2])
                if prev_close > 0:
                    price_change_pct = round(
                        (current_price - prev_close) / prev_close * 100, 2
                    )

        # 3. 기술적 지표 계산
        calculator = TechnicalCalculator()
        indicators = calculator.calculate_all(df)
        technical_summary = _build_technical_summary(indicators, current_price)

        # 4. 관련 뉴스 조회 (최근 30일, 최대 20개)
        news_cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
        related_news: list[dict[str, Any]] = []
        news_headlines: list[str] = []
        try:
            async with get_session() as session:
                stmt = (
                    select(Article)
                    .where(Article.published_at >= news_cutoff)
                    .where(Article.tickers_mentioned.contains([original_ticker]))
                    .order_by(Article.published_at.desc())
                    .limit(20)
                )
                result = await session.execute(stmt)
                articles = result.scalars().all()
                related_news = [_article_to_dict(a) for a in articles]
                news_headlines = [
                    a.headline_kr or a.headline
                    for a in articles[:10]
                ]
        except Exception as news_exc:
            logger.warning("뉴스 조회 실패 (무시됨): %s", news_exc)

        # 5. Claude Opus AI 분석
        ai_analysis: dict[str, Any] = {
            "current_situation": "AI 분석이 비활성화되어 있습니다.",
            "reasoning": "",
            "key_factors": [],
            "risk_factors": [],
            "predictions": [],
            "recommendation": {"action": "watch", "reasoning": "AI 분석 미요청"},
        }
        ai_available = False

        if ai and claude_client is not None:
            try:
                prompt = _build_analysis_prompt(
                    ticker=original_ticker,
                    current_price=current_price,
                    price_change_pct=price_change_pct,
                    technical_summary=technical_summary,
                    indicators=indicators,
                    news_headlines=news_headlines,
                )
                raw_analysis = await asyncio.wait_for(
                    claude_client.call_json(
                        prompt=prompt,
                        task_type="continuous_analysis",
                        max_tokens=4096,
                        use_cache=False,
                    ),
                    timeout=_AI_ANALYSIS_TIMEOUT,
                )
                if isinstance(raw_analysis, dict):
                    ai_analysis = raw_analysis
                    ai_available = True
                    logger.info("Claude 종합 분석 완료: ticker=%s", original_ticker)
            except asyncio.TimeoutError:
                logger.warning(
                    "Claude 분석 타임아웃 (%ds 초과, ticker=%s)",
                    _AI_ANALYSIS_TIMEOUT,
                    original_ticker,
                )
                ai_analysis["current_situation"] = (
                    "AI 분석 시간이 초과되었습니다. 기술적 지표 데이터를 참고하세요."
                )
                ai_analysis["reasoning"] = (
                    f"Claude 분석이 {_AI_ANALYSIS_TIMEOUT}초 내에 완료되지 않았습니다."
                )
            except Exception as claude_exc:
                logger.error(
                    "Claude 분석 실패 (ticker=%s): %s\n%s",
                    original_ticker,
                    claude_exc,
                    traceback.format_exc(),
                )
                ai_analysis["current_situation"] = (
                    "AI 분석 중 오류가 발생했습니다. 기술적 지표 데이터를 참고하세요."
                )
                ai_analysis["reasoning"] = str(claude_exc)[:200]
        elif not ai:
            logger.info("AI 분석 비활성화 (ai=false): ticker=%s", original_ticker)
        else:
            logger.warning("Claude 클라이언트 미초기화, AI 분석 생략: ticker=%s", original_ticker)
            ai_analysis["current_situation"] = (
                "Claude 클라이언트가 초기화되지 않았습니다."
            )
            ai_analysis["reasoning"] = (
                "트레이딩 시스템이 실행 중이 아니거나 Claude CLI를 사용할 수 없습니다."
            )

        # 6. 가격 이력 구성 (최근 60거래일)
        price_history: list[dict[str, Any]] = []
        try:
            tail_df = df.tail(60)
            for ts, row in tail_df.iterrows():
                price_history.append({
                    "date": ts.strftime("%Y-%m-%d"),  # type: ignore[union-attr]
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                })
        except Exception as hist_exc:
            logger.warning("가격 이력 구성 실패 (무시됨): %s", hist_exc)

        # 7. 지표 원본 데이터 직렬화 (JSON 직렬화 가능하도록 변환)
        indicators_serializable: dict[str, Any] = {}
        try:
            indicators_serializable = json.loads(
                json.dumps(indicators, default=str)
            )
        except Exception as serial_exc:
            logger.warning("지표 직렬화 실패 (무시됨): %s", serial_exc)

        return {
            "ticker": original_ticker,
            "analysis_ticker": analysis_ticker,
            "current_price": round(current_price, 4),
            "price_change_pct": round(price_change_pct, 2),
            "analysis_timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "technical_summary": technical_summary,
            "ai_analysis": ai_analysis,
            "ai_available": ai_available,
            "related_news": related_news,
            "price_history": price_history,
            "indicators": indicators_serializable,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "종합 분석 처리 중 내부 오류 (ticker=%s): %s", ticker, exc
        )
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ---------------------------------------------------------------------------
# GET /api/analysis/tickers
# ---------------------------------------------------------------------------

# 우선순위 고정 종목 (항상 맨 앞에 이 순서로 배치한다)
_PRIORITY_TICKERS: list[str] = ["NVDA", "GOOGL", "TSLA", "SOXL"]


def _build_sorted_ticker_list() -> list[str]:
    """분석 가능한 종목 목록을 지정된 정렬 순서로 반환한다.

    정렬 규칙:
        1. NVDA → GOOGL → TSLA → SOXL (고정 우선순위)
        2. 나머지는 알파벳 오름차순

    본주(underlying) 티커: UNDERLYING_TO_LEVERAGED 의 키들.
    섹터 레버리지 ETF: SECTOR_TICKERS 각 섹터의 sector_leveraged["bull"] 값.
    GOOG 은 GOOGL 과 중복되므로 제외한다.

    Returns:
        정렬된 종목 티커 문자열 목록.
    """
    ticker_set: set[str] = set(UNDERLYING_TO_LEVERAGED.keys())

    # 섹터 레버리지 ETF bull 값 추가 (SOXL, QLD, TSLL 등)
    for sector_info in SECTOR_TICKERS.values():
        sl = sector_info.get("sector_leveraged")
        if sl and sl.get("bull"):
            ticker_set.add(sl["bull"])

    # GOOG 은 GOOGL 과 동일 종목이므로 제외한다.
    ticker_set.discard("GOOG")

    # 우선순위 티커 중 실제로 존재하는 것만 추려 순서를 유지한다.
    priority = [t for t in _PRIORITY_TICKERS if t in ticker_set]

    # 나머지는 알파벳 오름차순 정렬한다.
    remaining = sorted(ticker_set - set(priority))

    return priority + remaining


@router.get("/tickers")
async def get_analysis_tickers() -> dict[str, Any]:
    """분석 가능한 종목 목록을 정렬된 순서로 반환한다.

    NVDA → GOOGL → TSLA → SOXL 순서가 맨 앞에 오고,
    나머지 종목은 알파벳 오름차순으로 정렬된다.

    본주(underlying) 티커(UNDERLYING_TO_LEVERAGED 키)와
    섹터 레버리지 ETF bull 티커(SECTOR_TICKERS sector_leveraged["bull"])를
    합산하여 반환한다. GOOG 은 GOOGL 과 중복이므로 제외한다.

    Returns:
        tickers 키와 정렬된 종목 목록을 포함하는 딕셔너리::

            {
                "tickers": ["NVDA", "GOOGL", "TSLA", "SOXL", ...]
            }
    """
    tickers = _build_sorted_ticker_list()
    return {"tickers": tickers}


# ---------------------------------------------------------------------------
# GET /api/analysis/ticker-news/{ticker}
# ---------------------------------------------------------------------------


@router.get("/ticker-news/{ticker}")
async def get_ticker_news(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=100, description="반환할 기사 수"),
    offset: int = Query(default=0, ge=0, description="페이지네이션 오프셋"),
    days: int = Query(default=30, ge=1, le=180, description="조회 기간 (일)"),
) -> dict[str, Any]:
    """특정 티커와 관련된 뉴스 기사 목록을 반환한다.

    articles 테이블에서 tickers_mentioned 컬럼이 해당 티커를 포함하는
    기사를 최신순으로 조회한다. 한국어 번역 및 기업별 영향 분석을 포함한다.

    Args:
        ticker: 종목 심볼 (예: "NVDA", "TSLA").
        limit: 반환할 최대 기사 수 (1~100, 기본 20).
        offset: 페이지네이션 오프셋 (기본 0).
        days: 조회 기간 (기본 30일).

    Returns:
        ticker, total, articles, limit, offset 키를 포함하는 딕셔너리.

    Raises:
        HTTPException 500: DB 조회 오류.
    """
    try:
        original_ticker = ticker.upper()
        news_cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

        async with get_session() as session:
            # 전체 건수 조회
            count_stmt = (
                select(func.count(Article.id))
                .where(Article.published_at >= news_cutoff)
                .where(Article.tickers_mentioned.contains([original_ticker]))
            )
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            # 기사 목록 조회
            articles_stmt = (
                select(Article)
                .where(Article.published_at >= news_cutoff)
                .where(Article.tickers_mentioned.contains([original_ticker]))
                .order_by(Article.published_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(articles_stmt)
            articles = result.scalars().all()

        return {
            "ticker": original_ticker,
            "total": total,
            "articles": [_article_to_dict(a) for a in articles],
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        logger.error(
            "티커 뉴스 조회 실패 (ticker=%s): %s", ticker, exc
        )
        raise HTTPException(
            status_code=500,
            detail="티커 관련 뉴스 조회 중 오류가 발생했습니다",
        )
