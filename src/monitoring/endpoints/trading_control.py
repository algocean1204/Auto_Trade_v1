"""F7.4 TradingControlEndpoints -- 자동매매 시작/중지/상태 제어 API이다.

매매 루프의 생명주기를 관리하며, 인증된 요청만 허용한다.
시작 시 preparation -> trading_loop를 asyncio.Task로 실행한다.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
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


async def _record_alert(
    system: InjectedSystem,
    alert_type: str,
    title: str,
    message: str,
    severity: str = "info",
) -> None:
    """알림을 캐시 alerts:list에 기록한다.

    매매 제어 이벤트(시작/종료)를 알림으로 기록한다.
    모든 예외를 흡수하여 API 응답에 영향을 주지 않는다.
    """
    try:
        cache = system.components.cache
        alert_entry: dict = {
            "id": str(uuid.uuid4()),
            "type": alert_type,
            "title": title,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": None,
        }
        existing: list[dict] = await cache.read_json("alerts:list") or []
        existing.append(alert_entry)
        if len(existing) > 100:
            existing = existing[-100:]
        await cache.write_json("alerts:list", existing, ttl=86400)
    except Exception as exc:
        _logger.debug("알림 기록 실패 (무시): %s", exc)


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
    await _record_alert(
        _system, "system", "매매 시작",
        "자동매매가 시작되었습니다.",
        severity="info",
    )
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
    await _record_alert(
        _system, "system", "매매 종료",
        f"자동매매가 종료되었습니다. EOD 실행: {'예' if run_eod else '아니오'}",
        severity="info",
    )
    return TradingActionResponse(status="stopped")


# -- 내부 함수 --


def _launch_trading_task(system: InjectedSystem) -> None:
    """매매 루프를 asyncio.Task로 시작한다."""
    global _shutdown_event
    _shutdown_event = asyncio.Event()
    system.running = True

    # 토큰 사용량 추적 세션 초기화
    try:
        from src.common.token_tracker import reset_session
        reset_session()
    except Exception:
        _logger.debug("토큰 추적 세션 초기화 실패", exc_info=True)

    async def _lifecycle() -> None:
        """preparation -> trading_loop + continuous_analysis + sentinel_loop -> EOD -> finally running=False."""
        cancelled = False
        loop_finished_normally = False
        try:
            from src.orchestration.loops.continuous_analysis import (
                run_continuous_analysis,
            )
            from src.orchestration.loops.sentinel_loop import run_sentinel_loop
            from src.orchestration.loops.trading_loop import run_trading_loop
            from src.orchestration.phases.preparation import run_preparation

            prep = await run_preparation(system)
            if not prep.ready:
                _logger.warning("매매 준비 실패 -- 시작 중단")
                return
            # 매매 루프 + 연속 분석 + 센티넬 루프를 동시에 실행한다
            analysis_task = asyncio.create_task(
                run_continuous_analysis(system, _shutdown_event),  # type: ignore[arg-type]
            )
            sentinel_task = asyncio.create_task(
                run_sentinel_loop(system, _shutdown_event),  # type: ignore[arg-type]
            )
            try:
                await run_trading_loop(system, _shutdown_event)  # type: ignore[arg-type]
                loop_finished_normally = True
                _logger.info("매매 루프 정상 반환 완료")
            finally:
                # analysis_task 정리
                _logger.info("analysis_task 정리 시작 (done=%s)", analysis_task.done())
                if not analysis_task.done():
                    analysis_task.cancel()
                try:
                    await asyncio.shield(asyncio.sleep(0))  # yield point 확보
                    await analysis_task
                except (asyncio.CancelledError, Exception) as exc:
                    _logger.debug("analysis_task 정리 완료: %s", type(exc).__name__)
                _logger.info("analysis_task 정리 끝")
                # sentinel_task 정리
                _logger.info("sentinel_task 정리 시작 (done=%s)", sentinel_task.done())
                if not sentinel_task.done():
                    sentinel_task.cancel()
                try:
                    await sentinel_task
                except (asyncio.CancelledError, Exception) as exc:
                    _logger.debug("sentinel_task 정리 완료: %s", type(exc).__name__)
                _logger.info("sentinel_task 정리 끝")
        except asyncio.CancelledError:
            cancelled = True
            _logger.info("매매 태스크 취소됨")
        except Exception:
            _logger.exception("매매 태스크 예외 발생")
        finally:
            # EOD 시퀀스: 루프가 정상 종료된 경우 반드시 실행한다
            if loop_finished_normally and not cancelled:
                try:
                    _logger.info("매매 루프 자동 종료 -- EOD 시퀀스 실행")
                    await _run_auto_eod(system)
                except Exception:
                    _logger.exception("자동 EOD 시퀀스 finally 블록 실행 실패")
            elif cancelled:
                _logger.info("매매 취소됨 -- EOD 건너뜀 (수동 stop에서 EOD 실행)")
            else:
                _logger.warning("매매 루프 비정상 종료 -- EOD 건너뜀")
            system.running = False
            _logger.info("매매 태스크 생명주기 종료 (running=False)")

    system.trading_task = asyncio.create_task(_lifecycle())


async def _run_auto_eod(system: InjectedSystem) -> None:
    """매매 루프 자동 종료 후 EOD 시퀀스 + 주간 분석을 실행한다."""
    try:
        from src.orchestration.phases.eod_sequence import run_eod_sequence
        await run_eod_sequence(system)
    except Exception:
        _logger.exception("자동 EOD 시퀀스 실행 실패")

    # 주간 분석: 토요일 아침 (금요일 미국장 종료 후)
    try:
        from src.orchestration.phases.weekly_analysis import (
            run_weekly_analysis,
            should_run_weekly,
        )
        time_info = get_market_clock().get_time_info()
        if time_info.now_kst.weekday() == 5 or should_run_weekly(time_info):
            _logger.info("주간 분석 시작 (자동 EOD 후)")
            await run_weekly_analysis(system)
    except Exception as exc:
        _logger.warning("주간 분석 실행 실패 (건너뜀): %s", exc)


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
