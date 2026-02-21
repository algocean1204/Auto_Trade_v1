"""자동매매 시작/중지/상태 제어 API 엔드포인트.

대시보드 버튼으로 자동매매를 시작하거나 중지하고 현재 상태를 조회한다.
/start 및 /stop 엔드포인트는 Authorization: Bearer 헤더로 인증이 필요하다.
API_SECRET_KEY가 설정되지 않은 개발 환경에서는 인증을 비활성화한다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from src.monitoring.auth import verify_api_key
from src.monitoring.schemas import (
    ErrorResponse,
    TradingActionResponse,
    TradingStatusResponse,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

trading_control_router = APIRouter(prefix="/api/trading", tags=["trading-control"])

# ---------------------------------------------------------------------------
# 의존성 레지스트리 — set_trading_control_deps() 호출로 주입된다.
# ---------------------------------------------------------------------------

_trading_system: Any = None


def set_trading_control_deps(trading_system: Any = None) -> None:
    """TradingSystem 인스턴스를 라우터에 주입한다.

    api_server.py의 set_dependencies()에서 호출한다.

    Args:
        trading_system: src.main.TradingSystem 인스턴스.
    """
    global _trading_system
    _trading_system = trading_system


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@trading_control_router.get(
    "/status",
    response_model=TradingStatusResponse,
    responses={503: {"model": ErrorResponse}},
)
async def get_trading_status() -> TradingStatusResponse:
    """현재 자동매매 실행 상태를 반환한다.

    Returns:
        is_trading: 매매 루프가 실제로 실행 중인지 여부.
        running: TradingSystem.running 플래그 값.
        task_done: 매매 태스크가 완료(종료)되었는지 여부.
    """
    if _trading_system is None:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Trading system not initialized",
                "error_code": "TRADING_SYSTEM_NOT_READY",
            },
        )

    try:
        raw = _trading_system.get_trading_status()
        return TradingStatusResponse(**raw)
    except Exception as exc:
        logger.exception("거래 상태 조회 오류: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="거래 상태를 조회하는 중 오류가 발생했습니다.",
        ) from exc


@trading_control_router.post(
    "/start",
    response_model=TradingActionResponse,
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    dependencies=[Depends(verify_api_key)],
)
async def start_trading(force: bool = False) -> TradingActionResponse:
    """자동매매 루프를 시작한다.

    이미 실행 중인 경우 {"status": "already_running"}을 반환한다.
    운영 윈도우 밖이거나 거래일이 아닌 경우 force=False(기본값)이면 409 Conflict를 반환한다.
    force=True이면 시간 검증을 우회하여 강제 시작한다 (긴급 수동 오버라이드 용도).

    Args:
        force: True이면 운영 윈도우 및 거래일 검증을 건너뛴다.

    Returns:
        status: "started" 또는 "already_running".
    """
    if _trading_system is None:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Trading system not initialized",
                "error_code": "TRADING_SYSTEM_NOT_READY",
            },
        )

    try:
        result = await _trading_system.start_trading(force=force)
        result_status = result.get("status", "started")

        if result_status == "outside_trading_hours":
            message = result.get("message", "매매 가능 시간이 아닙니다")
            next_window = result.get("next_window", "")
            detail_msg = f"{message} (다음 운영 윈도우: {next_window})" if next_window else message
            logger.info("자동매매 시작 거부 (운영 윈도우 밖): %s", detail_msg)
            return JSONResponse(
                status_code=409,
                content={
                    "detail": detail_msg,
                    "error_code": "OUTSIDE_TRADING_HOURS",
                },
            )

        if result_status == "not_trading_day":
            message = result.get("message", "오늘은 매매일이 아닙니다")
            logger.info("자동매매 시작 거부 (비거래일): %s", message)
            return JSONResponse(
                status_code=409,
                content={
                    "detail": message,
                    "error_code": "NOT_TRADING_DAY",
                },
            )

        logger.info("자동매매 시작 API 호출 완료: %s", result)
        return TradingActionResponse(status=result_status)
    except Exception as exc:
        logger.exception("자동매매 시작 API 오류: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "error_code": "TRADING_START_FAILED",
            },
        )


@trading_control_router.post(
    "/stop",
    response_model=TradingActionResponse,
    responses={
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    dependencies=[Depends(verify_api_key)],
)
async def stop_trading(run_eod: bool = True) -> TradingActionResponse:
    """자동매매 루프를 중지한다.

    run_eod=True(기본값)이면 EOD 시퀀스(EOD → 보고서 → Telegram)를 실행한 뒤 종료한다.
    실행 중이 아닌 경우 {"status": "not_running"}을 반환한다.

    Args:
        run_eod: True이면 EOD 종료 시퀀스를 실행한다 (기본값: True).

    Returns:
        status: "stopped" 또는 "not_running".
    """
    if _trading_system is None:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Trading system not initialized",
                "error_code": "TRADING_SYSTEM_NOT_READY",
            },
        )

    try:
        result = await _trading_system.stop_trading(run_eod=run_eod)
        logger.info("자동매매 중지 API 호출 완료: %s", result)
        return TradingActionResponse(status=result.get("status", "stopped"))
    except Exception as exc:
        logger.exception("자동매매 중지 API 오류: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc),
                "error_code": "TRADING_STOP_FAILED",
            },
        )
