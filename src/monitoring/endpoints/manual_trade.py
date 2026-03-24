"""F7.13 ManualTradeEndpoints -- 수동 매매 분석/실행 API이다.

수동 매매 전 AI 분석 요청과 실행 기능을 제공한다.
실행 시 Bearer 인증을 요구한다.
Flutter 대시보드가 기대하는 응답 형태에 맞춰 데이터를 가공한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

manual_trade_router = APIRouter(prefix="/api/manual", tags=["manual-trade"])

_system: InjectedSystem | None = None


class ManualAnalyzeRequest(BaseModel):
    """수동 매매 분석 요청 모델이다. Flutter는 side 필드를 전송한다."""

    ticker: str = Field(..., min_length=1, max_length=10, pattern=r"^[A-Za-z0-9]+$")
    action: str = ""  # buy, sell
    side: str = ""  # Flutter 호환용 (action의 별칭)
    quantity: int = Field(default=0, ge=0, le=10000)
    reason: str = ""


class ManualExecuteRequest(BaseModel):
    """수동 매매 실행 요청 모델이다. Flutter는 side 필드를 전송한다."""

    ticker: str = Field(..., min_length=1, max_length=10, pattern=r"^[A-Za-z0-9]+$")
    action: str = ""  # buy, sell
    side: str = ""  # Flutter 호환용 (action의 별칭)
    quantity: int = Field(..., ge=1, le=10000)
    price: float = Field(default=0.0, ge=0.0)  # 0이면 시장가


class ManualAnalyzeResponse(BaseModel):
    """수동 매매 분석 응답 모델이다.

    Flutter가 기대하는 필드: ticker, ai_opinion, current_price,
    estimated_cost, technical_summary, holding.
    기존 필드(action, analysis, meta, recommendation)도 하위 호환을 위해 유지한다.
    """

    ticker: str
    action: str = ""
    # Flutter가 기대하는 필드
    ai_opinion: dict[str, Any] = Field(default_factory=dict)
    current_price: float = 0.0
    estimated_cost: float = 0.0
    technical_summary: dict[str, Any] = Field(default_factory=dict)
    holding: dict[str, Any] | None = None
    # 하위 호환용 기존 필드
    analysis: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = ""


class ManualExecuteResponse(BaseModel):
    """수동 매매 실행 응답 모델이다.

    Flutter가 기대하는 필드: side, order_id, price(체결가).
    기존 필드(action, status, message)도 하위 호환을 위해 유지한다.
    """

    status: str
    ticker: str
    action: str = ""
    side: str = ""  # Flutter 호환용 (action과 동일 값)
    quantity: int
    price: float
    order_id: str = ""  # 브로커 주문 ID
    message: str = ""


def set_manual_trade_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("ManualTradeEndpoints 의존성 주입 완료")


async def _fetch_current_price(ticker: str) -> float:
    """브로커에서 현재가를 조회한다. 실패 시 일봉 폴백, 최종 실패 시 0.0을 반환한다."""
    if _system is None:
        return 0.0
    exchange = "NAS"
    try:
        exchange = _system.components.registry.get_exchange_code(ticker)
    except (KeyError, AttributeError):
        pass

    # 1차: 실시간 시세 조회
    try:
        broker = _system.components.broker
        price_data = await broker.get_price(ticker, exchange)
        if price_data.price > 0:
            return round(price_data.price, 2)
    except Exception:
        _logger.debug("브로커 시세 조회 실패, 일봉 폴백: %s", ticker)

    # 2차: 일봉 종가 폴백
    try:
        broker = _system.components.broker
        candles = await broker.get_daily_candles(ticker, days=5, exchange=exchange)
        if candles and candles[0].close > 0:
            return round(candles[0].close, 2)
    except Exception:
        _logger.debug("일봉 폴백도 실패: %s", ticker)

    return 0.0


async def _build_ai_opinion(
    ticker: str,
    action: str,
    cached_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    """캐시된 분석 데이터에서 Flutter AI 의견 구조를 생성한다.

    Flutter가 기대하는 구조:
    {opinion, confidence, reasoning, risks, suggestion, available}
    """
    if not cached_analysis or not isinstance(cached_analysis, dict):
        return {
            "opinion": "neutral",
            "confidence": 0,
            "reasoning": "분석 데이터가 없다. 캐시된 AI 분석이 아직 수행되지 않았다.",
            "risks": ["AI 분석 없이 수동 판단으로 진행한다"],
            "suggestion": "시스템 분석을 먼저 실행하거나 직접 판단하라",
            "available": False,
        }

    # 캐시에서 sentiment/confidence/recommendations 추출
    confidence_raw = cached_analysis.get("confidence", 0.0)
    # NaN/inf 방어: 유효한 float이 아니면 0으로 처리한다
    import math
    if not isinstance(confidence_raw, (int, float)) or math.isnan(confidence_raw) or math.isinf(confidence_raw):
        confidence_raw = 0.0
    # confidence가 0~1 범위이면 백분율로 변환한다
    confidence_pct = int(confidence_raw * 100) if confidence_raw <= 1.0 else int(confidence_raw)

    # 뉴스 감성 + 분석 결과에서 의견을 도출한다
    sentiment = cached_analysis.get("news_sentiment", 0.0)
    regime = cached_analysis.get("regime_assessment", "")
    risk_level = cached_analysis.get("risk_level", "medium")

    # action(buy/sell)과 분석 결과의 방향성을 비교하여 동의/반대를 판단한다
    opinion = _derive_opinion(action, sentiment, regime, risk_level)

    # 분석 근거 문자열 생성
    recommendations = cached_analysis.get("recommendations", [])
    analysis_text = cached_analysis.get("analysis_text", "")
    reasoning = analysis_text or " / ".join(recommendations) if recommendations else ""

    # 리스크 목록 추출
    risks: list[str] = []
    if risk_level in ("high", "critical"):
        risks.append(f"리스크 수준: {risk_level}")
    if "crash" in regime.lower() or "bear" in regime.lower():
        risks.append(f"시장 레짐: {regime}")
    signals = cached_analysis.get("signals", [])
    for sig in signals[:3]:
        if isinstance(sig, dict) and sig.get("direction") == "bearish":
            risks.append(sig.get("summary", sig.get("title", "")))

    # 제안 생성
    suggestion = _build_suggestion(action, opinion, risk_level, regime)

    return {
        "opinion": opinion,
        "confidence": confidence_pct,
        "reasoning": reasoning,
        "risks": risks,
        "suggestion": suggestion,
        "available": True,
    }


def _derive_opinion(
    action: str, sentiment: float, regime: str, risk_level: str,
) -> str:
    """매매 방향과 시장 상태를 비교하여 AI 의견(agree/disagree/neutral)을 도출한다."""
    regime_lower = regime.lower()
    is_bullish_regime = "bull" in regime_lower
    is_bearish_regime = "bear" in regime_lower or "crash" in regime_lower

    if action == "buy":
        if is_bullish_regime and sentiment > 0:
            return "agree"
        if is_bearish_regime or risk_level in ("high", "critical"):
            return "disagree"
    elif action == "sell":
        if is_bearish_regime or risk_level in ("high", "critical"):
            return "agree"
        if is_bullish_regime and sentiment > 0.3:
            return "disagree"
    return "neutral"


def _build_suggestion(
    action: str, opinion: str, risk_level: str, regime: str,
) -> str:
    """AI 의견과 시장 상태에 기반한 구체적 제안을 생성한다."""
    if opinion == "disagree":
        if action == "buy":
            return "현 시장 상황에서 매수는 리스크가 높다. 진입 시점을 재고하라."
        return "현 시장 상황에서 매도는 조급할 수 있다. 보유 유지를 고려하라."
    if opinion == "agree":
        if risk_level in ("high", "critical"):
            return "방향성은 맞지만 리스크가 높다. 소량으로 분할 진입/청산을 권장한다."
        return "분석 결과와 일치한다. 계획대로 실행하라."
    return "시장 방향이 불확실하다. 소량 진입 또는 관망을 권장한다."


async def _build_technical_summary(ticker: str) -> dict[str, Any]:
    """기술 지표 요약을 생성한다. 실패 시 빈 dict(available=False)를 반환한다."""
    if _system is None:
        return {"available": False}
    try:
        builder = _system.features.get("indicator_bundle_builder")
        if builder is None:
            return {"available": False}
        bundle = await builder.build(ticker)  # type: ignore[union-attr]
        tech = bundle.technical  # type: ignore[union-attr]
        if tech is None:
            return {"available": False}
        trend = (
            "uptrend" if tech.ema_20 > tech.sma_200
            else "downtrend" if tech.ema_20 < tech.sma_200
            else "sideways"
        )
        macd_signal = (
            "bullish" if tech.macd_histogram > 0
            else "bearish" if tech.macd_histogram < 0
            else "neutral"
        )
        return {
            "available": True,
            "rsi_14": round(tech.rsi, 1),
            "macd_signal": macd_signal,
            "trend": trend,
            "support": round(tech.bb_lower, 2),
            "resistance": round(tech.bb_upper, 2),
        }
    except Exception:
        _logger.debug("기술지표 빌드 실패: %s", ticker)
        return {"available": False}


async def _get_holding_info(ticker: str) -> dict[str, Any] | None:
    """PositionMonitor에서 보유 현황을 조회한다. 미보유 시 None을 반환한다."""
    if _system is None:
        return None
    try:
        pm = _system.features.get("position_monitor")
        if pm is None:
            return None
        position = await pm.get_position(ticker)  # type: ignore[union-attr]
        if position is None:
            return None
        return {
            "quantity": position.quantity,
            "avg_price": round(position.avg_price, 2),
            "current_price": round(position.current_price, 2),
            "pnl_pct": round(position.pnl_pct, 2),
        }
    except Exception:
        _logger.debug("포지션 조회 실패: %s", ticker)
        return None


@manual_trade_router.post("/analyze", response_model=ManualAnalyzeResponse)
async def analyze_manual_trade(
    req: ManualAnalyzeRequest,
    _auth: str = Depends(verify_api_key),
) -> ManualAnalyzeResponse:
    """수동 매매 전 AI 분석을 수행한다.

    Flutter가 기대하는 응답 형태로 데이터를 가공하여 반환한다:
    ai_opinion, current_price, estimated_cost, technical_summary, holding.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        # action 또는 side 중 하나를 사용한다 (Flutter 호환)
        effective_action = req.action or req.side
        registry = _system.components.registry
        if not registry.has_ticker(req.ticker):
            raise HTTPException(
                status_code=404,
                detail=f"등록되지 않은 티커이다: {req.ticker}",
            )

        # AI 분석 캐시를 조회한다 — 캐시 키는 항상 대문자로 저장된다
        cache = _system.components.cache
        cached = await cache.read_json(f"analysis:{req.ticker.upper()}")
        cached_analysis = cached if isinstance(cached, dict) else None

        # 현재가를 조회한다
        current_price = await _fetch_current_price(req.ticker)

        # 예상 매매 금액을 계산한다
        quantity = req.quantity if req.quantity > 0 else 1
        estimated_cost = round(current_price * quantity, 2)

        # AI 의견을 구성한다
        ai_opinion = await _build_ai_opinion(
            req.ticker, effective_action, cached_analysis,
        )

        # 기술 지표 요약을 생성한다
        technical_summary = await _build_technical_summary(req.ticker)

        # 보유 현황을 조회한다
        holding = await _get_holding_info(req.ticker)

        # 하위 호환용 meta 데이터
        meta = registry.get_meta(req.ticker)

        return ManualAnalyzeResponse(
            ticker=req.ticker,
            action=effective_action,
            ai_opinion=ai_opinion,
            current_price=current_price,
            estimated_cost=estimated_cost,
            technical_summary=technical_summary,
            holding=holding,
            analysis=cached_analysis,
            meta=meta.model_dump(),
            recommendation="분석 결과를 확인하고 판단하라",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("수동 매매 분석 실패: %s", req.ticker)
        raise HTTPException(status_code=500, detail="분석 실패") from None


@manual_trade_router.post("/execute", response_model=ManualExecuteResponse)
async def execute_manual_trade(
    req: ManualExecuteRequest,
    _key: str = Depends(verify_api_key),
) -> ManualExecuteResponse:
    """수동 매매를 실행한다. 인증 필수.

    Flutter가 기대하는 응답 형태로 side, order_id, 체결가를 포함한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        # action 또는 side 중 하나를 사용한다 (Flutter 호환)
        effective_action = req.action or req.side
        if effective_action not in ("buy", "sell"):
            raise HTTPException(
                status_code=422,
                detail="action(또는 side)은 buy 또는 sell이어야 한다",
            )
        if req.quantity <= 0:
            raise HTTPException(
                status_code=422,
                detail="quantity는 1 이상이어야 한다",
            )
        registry = _system.components.registry
        if not registry.has_ticker(req.ticker):
            raise HTTPException(
                status_code=404,
                detail=f"등록되지 않은 티커이다: {req.ticker}",
            )

        _logger.info(
            "수동 매매 실행: %s %s x%d @ %.2f",
            effective_action, req.ticker, req.quantity, req.price,
        )

        # OrderManager를 통해 실제 브로커 주문을 실행한다
        om = _system.features.get("order_manager")
        if om is None:
            raise HTTPException(
                status_code=503,
                detail="OrderManager가 등록되지 않았다",
            )

        exchange = registry.get_exchange_code(req.ticker)

        if effective_action == "buy":
            result = await om.execute_buy(req.ticker, req.quantity, exchange)
        else:
            result = await om.execute_sell(req.ticker, req.quantity, exchange)

        # 체결가: 요청 가격이 있으면 사용, 없으면 현재가를 조회한다
        fill_price = req.price
        if fill_price <= 0:
            fill_price = await _fetch_current_price(req.ticker)

        # 수동 매매도 trades:today에 기록하여 DailyLossLimit/EOD 보고서에 반영한다
        if result.status == "filled":
            try:
                from datetime import datetime, timezone
                cache = _system.components.cache
                record = {
                    "ticker": req.ticker,
                    "side": effective_action,
                    "quantity": req.quantity,
                    "price": fill_price,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "exit_type": "manual",
                    "pnl": None,
                    "reason": "manual_trade",
                }
                await cache.atomic_list_append(
                    "trades:today", [record], max_size=500, ttl=86400,
                )
            except Exception as exc:
                _logger.warning("수동 매매 기록 실패 (trades:today 누락): %s", exc)

        _logger.info(
            "수동 매매 실행 결과: %s %s x%d -> %s (order_id=%s)",
            effective_action, req.ticker, req.quantity,
            result.status, result.order_id,
        )
        return ManualExecuteResponse(
            status=result.status,
            ticker=req.ticker,
            action=effective_action,
            side=effective_action,
            quantity=req.quantity,
            price=fill_price,
            order_id=result.order_id,
            message=result.message,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("수동 매매 실행 실패: %s", req.ticker)
        raise HTTPException(status_code=500, detail="실행 실패") from None
