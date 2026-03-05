"""F7.13 ManualTradeEndpoints -- 수동 매매 분석/실행 API이다.

수동 매매 전 AI 분석 요청과 실행 기능을 제공한다.
실행 시 Bearer 인증을 요구한다.
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

    ticker: str
    action: str = ""  # buy, sell
    side: str = ""  # Flutter 호환용 (action의 별칭)
    quantity: int = 0
    reason: str = ""


class ManualExecuteRequest(BaseModel):
    """수동 매매 실행 요청 모델이다. Flutter는 side 필드를 전송한다."""

    ticker: str
    action: str = ""  # buy, sell
    side: str = ""  # Flutter 호환용 (action의 별칭)
    quantity: int
    price: float = 0.0  # 0이면 시장가


class ManualAnalyzeResponse(BaseModel):
    """수동 매매 분석 응답 모델이다."""

    ticker: str
    action: str
    analysis: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = ""


class ManualExecuteResponse(BaseModel):
    """수동 매매 실행 응답 모델이다."""

    status: str
    ticker: str
    action: str
    quantity: int
    price: float
    message: str = ""


def set_manual_trade_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("ManualTradeEndpoints 의존성 주입 완료")


@manual_trade_router.post("/analyze", response_model=ManualAnalyzeResponse)
async def analyze_manual_trade(
    req: ManualAnalyzeRequest,
) -> ManualAnalyzeResponse:
    """수동 매매 전 AI 분석을 수행한다."""
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
        # AI 분석 캐시를 조회하거나, 없으면 기본 정보를 반환한다
        cache = _system.components.cache
        cached = await cache.read_json(f"analysis:{req.ticker}")
        meta = registry._ticker_map[req.ticker]
        return ManualAnalyzeResponse(
            ticker=req.ticker,
            action=effective_action,
            analysis=cached if isinstance(cached, dict) else None,
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
    """수동 매매를 실행한다. 인증 필수."""
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

        _logger.info(
            "수동 매매 실행 결과: %s %s x%d -> %s",
            effective_action, req.ticker, req.quantity, result.status,
        )
        return ManualExecuteResponse(
            status=result.status,
            ticker=req.ticker,
            action=effective_action,
            quantity=req.quantity,
            price=req.price,
            message=result.message,
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("수동 매매 실행 실패: %s", req.ticker)
        raise HTTPException(status_code=500, detail="실행 실패") from None
