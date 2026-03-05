"""F7.18 OrderFlowEndpoints -- 주문흐름 조회 API이다.

현재 주문흐름 스냅샷, 이력, 고래 활동 데이터를 제공한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

order_flow_router = APIRouter(prefix="/api/orderflow", tags=["orderflow"])

_system: InjectedSystem | None = None


class OrderflowSnapshotResponse(BaseModel):
    """주문흐름 스냅샷 응답 모델이다."""

    tickers: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = None
    message: str = ""


class OrderflowHistoryResponse(BaseModel):
    """주문흐름 이력 응답 모델이다."""

    ticker: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class WhaleActivityResponse(BaseModel):
    """고래 활동 응답 모델이다."""

    whale_activities: list[dict[str, Any]] = Field(default_factory=list)


def set_order_flow_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("OrderFlowEndpoints 의존성 주입 완료")


@order_flow_router.get("/snapshot", response_model=OrderflowSnapshotResponse)
async def get_orderflow_snapshot() -> OrderflowSnapshotResponse:
    """현재 주문흐름 스냅샷을 반환한다.

    orderflow:snapshot 캐시 키를 우선 조회하고, 없으면
    order_flow:raw:{ticker} 키에서 직접 조합한다.
    """
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        # 1차: 사전 집계된 스냅샷 확인
        cached = await cache.read_json("orderflow:snapshot")
        if cached and isinstance(cached, dict):
            return OrderflowSnapshotResponse(
                tickers=cached.get("tickers", {}),
                updated_at=cached.get("updated_at"),
                message=cached.get("message", ""),
            )
        # 2차: ws:orderflow에서 조합 (trading_loop이 기록)
        ws_data = await cache.read_json("ws:orderflow")
        if ws_data and isinstance(ws_data, dict) and ws_data.get("data"):
            tickers_map: dict[str, Any] = {}
            for item in ws_data["data"]:
                if isinstance(item, dict) and "ticker" in item:
                    tickers_map[item["ticker"]] = item
            if tickers_map:
                return OrderflowSnapshotResponse(
                    tickers=tickers_map,
                    message="실시간 오더플로우 데이터",
                )
        return OrderflowSnapshotResponse(
            message="주문흐름 데이터가 없다 (KIS WebSocket 미연결 또는 비거래 시간)",
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("주문흐름 스냅샷 조회 실패")
        raise HTTPException(status_code=500, detail="스냅샷 조회 실패") from None


@order_flow_router.get("/history", response_model=OrderflowHistoryResponse)
async def get_orderflow_history(
    ticker: str = "",
    limit: int = 50,
) -> OrderflowHistoryResponse:
    """주문흐름 이력을 반환한다. ticker로 필터링할 수 있다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        key = f"orderflow:history:{ticker}" if ticker else "orderflow:history"
        cached = await cache.read_json(key)
        data = cached if isinstance(cached, list) else []
        return OrderflowHistoryResponse(
            ticker=ticker or "all",
            history=data[:limit],
        )
    except HTTPException:
        raise
    except Exception:
        _logger.exception("주문흐름 이력 조회 실패")
        raise HTTPException(status_code=500, detail="이력 조회 실패") from None


@order_flow_router.get("/whale", response_model=WhaleActivityResponse)
async def get_whale_activity(
    limit: int = 20,
) -> WhaleActivityResponse:
    """고래(대량 거래) 활동을 반환한다."""
    if _system is None:
        raise HTTPException(status_code=503, detail="시스템 초기화 중")
    try:
        cache = _system.components.cache
        cached = await cache.read_json("orderflow:whale")
        data = cached if isinstance(cached, list) else []
        return WhaleActivityResponse(whale_activities=data[:limit])
    except HTTPException:
        raise
    except Exception:
        _logger.exception("고래 활동 조회 실패")
        raise HTTPException(status_code=500, detail="고래 활동 조회 실패") from None
