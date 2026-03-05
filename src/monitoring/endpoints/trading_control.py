"""F7.4 TradingControlEndpoints -- 자동매매 시작/중지/상태 제어 API이다.

매매 루프의 생명주기를 관리하며, 인증된 요청만 허용한다.
시작 시 preparation -> trading_loop를 asyncio.Task로 실행한다.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from src.common.logger import get_logger
from src.common.market_clock import get_market_clock
from src.monitoring.schemas.response_models import (
    TradingActionResponse,
    TradingStatusResponse,
)
from src.monitoring.server.auth import verify_api_key

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

trading_control_router = APIRouter(
    prefix="/api/trading",
    tags=["trading-control"],
)

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None

# 종료 이벤트 -- 매매 루프에 종료 신호를 전달한다
_shutdown_event: asyncio.Event | None = None


def set_trading_control_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("TradingControlEndpoints 의존성 주입 완료")


def _build_status_response() -> TradingStatusResponse:
    """현재 매매 상태 응답을 조립한다."""
    clock = get_market_clock()
    time_info = clock.get_time_info()

    is_trading = _system is not None and _system.running
    task_done = True
    if _system and _system.trading_task:
        task_done = _system.trading_task.done()  # type: ignore[union-attr]

    return TradingStatusResponse(
        is_trading=is_trading,
        running=is_trading,
        task_done=task_done,
        is_trading_window=time_info.is_trading_window,
        session_type=time_info.session_type,
        current_kst=time_info.now_kst.isoformat(),
    )


@trading_control_router.get(
    "/status",
    response_model=TradingStatusResponse,
)
async def get_trading_status() -> TradingStatusResponse:
    """현재 자동매매 실행 상태를 반환한다."""
    return _build_status_response()


@trading_control_router.post(
    "/start",
    response_model=TradingActionResponse,
)
async def start_trading(
    force: bool = False,
    _key: str = Depends(verify_api_key),
) -> TradingActionResponse:
    """자동매매를 시작한다. 인증 필수."""
    if _system is None:
        raise HTTPException(
            status_code=409,
            detail="시스템이 초기화되지 않았습니다",
        )

    if _system.running:
        return TradingActionResponse(status="already_running")

    clock = get_market_clock()
    time_info = clock.get_time_info()

    if not force and not time_info.is_trading_window:
        raise HTTPException(
            status_code=409,
            detail="매매 가능 시간이 아닙니다 (20:00~06:30 KST)",
        )

    _launch_trading_task(_system)
    _logger.info("자동매매 시작 요청 처리 완료")
    return TradingActionResponse(status="started")


@trading_control_router.post(
    "/stop",
    response_model=TradingActionResponse,
)
async def stop_trading(
    run_eod: bool = True,
    _key: str = Depends(verify_api_key),
) -> TradingActionResponse:
    """자동매매를 중지한다. 인증 필수."""
    if _system is None or not _system.running:
        return TradingActionResponse(status="not_running")

    await _stop_trading_task(_system, run_eod)
    _logger.info("자동매매 중지 완료 (run_eod=%s)", run_eod)
    return TradingActionResponse(status="stopped")


# -- 내부 함수 --


def _launch_trading_task(system: InjectedSystem) -> None:
    """매매 루프를 asyncio.Task로 시작한다."""
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    system.running = True

    async def _lifecycle() -> None:
        """preparation -> trading_loop + continuous_analysis -> finally running=False."""
        try:
            from src.orchestration.loops.continuous_analysis import (
                run_continuous_analysis,
            )
            from src.orchestration.loops.trading_loop import run_trading_loop
            from src.orchestration.phases.preparation import run_preparation

            prep = await run_preparation(system)
            if not prep.ready:
                _logger.warning("매매 준비 실패 -- 시작 중단")
                return
            # 매매 루프와 연속 분석을 동시에 실행한다
            analysis_task = asyncio.create_task(
                run_continuous_analysis(system, _shutdown_event),  # type: ignore[arg-type]
            )
            try:
                await run_trading_loop(system, _shutdown_event)  # type: ignore[arg-type]
            finally:
                analysis_task.cancel()
                try:
                    await analysis_task
                except (asyncio.CancelledError, Exception):
                    pass
        except asyncio.CancelledError:
            _logger.info("매매 태스크 취소됨")
        except Exception:
            _logger.exception("매매 태스크 예외 발생")
        finally:
            system.running = False

    system.trading_task = asyncio.create_task(_lifecycle())


async def _stop_trading_task(
    system: InjectedSystem,
    run_eod: bool,
) -> None:
    """매매 태스크를 중지하고 선택적으로 EOD를 실행한다."""
    system.running = False

    if _shutdown_event is not None:
        _shutdown_event.set()

    if system.trading_task and not system.trading_task.done():  # type: ignore[union-attr]
        system.trading_task.cancel()  # type: ignore[union-attr]
        try:
            await system.trading_task  # type: ignore[misc]
        except (asyncio.CancelledError, Exception):
            pass

    if run_eod:
        from src.orchestration.phases.eod_sequence import run_eod_sequence
        await run_eod_sequence(system)
        # 주간 분석: 토요일 아침 (금요일 미국장 종료 후) 자동 실행
        try:
            from src.orchestration.phases.weekly_analysis import (
                run_weekly_analysis,
                should_run_weekly,
            )
            time_info = get_market_clock().get_time_info()
            # weekday 5 = 토요일 (금요일 거래 종료 후 EOD)
            if time_info.now_kst.weekday() == 5 or should_run_weekly(time_info):
                _logger.info("주간 분석 시작 (주말 EOD 후)")
                await run_weekly_analysis(system)
        except Exception as exc:
            _logger.warning("주간 분석 실행 실패 (건너뜀): %s", exc)
