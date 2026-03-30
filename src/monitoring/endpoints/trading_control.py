"""F7.4 TradingControlEndpoints -- 자동매매 시작/중지/상태 제어 API이다.

매매 루프의 생명주기를 관리하며, 인증된 요청만 허용한다.
시작 시 preparation -> trading_loop를 asyncio.Task로 실행한다.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

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

# EOD 실행 중 플래그 -- 수동 stop의 EOD 실행 중 새 매매 시작을 차단한다
_eod_running: bool = False

# 사용자 의도적 정지 플래그 -- 워치독의 무조건 재시작을 방지한다
_user_stopped: bool = False

# 매매 제어 상태 전이의 TOCTOU 레이스를 방지한다
_control_lock = asyncio.Lock()

# ensure_future로 생성된 독립 EOD 태스크 추적 — main.py 셧다운이 완료를 대기할 수 있게 한다
_active_eod_task: asyncio.Task[None] | None = None


def set_trading_control_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("TradingControlEndpoints 의존성 주입 완료")


def is_eod_running() -> bool:
    """EOD 시퀀스 실행 중 여부를 반환한다. 외부 모듈에서 상태 조회 시 사용한다."""
    return _eod_running


def signal_trading_shutdown() -> None:
    """외부에서 매매 종료 신호를 보낸다.

    SIGTERM 등 시그널 핸들러에서 호출하여 매매 루프가
    자연스럽게 종료되도록 shutdown_event를 설정한다.
    이렇게 해야 매매 루프가 정상 종료 → EOD 시퀀스 실행 경로를 탈 수 있다.
    """
    if _shutdown_event is not None:
        _shutdown_event.set()
        _logger.info("매매 shutdown_event 시그널 설정 완료")


def get_active_eod_task() -> asyncio.Task[None] | None:
    """현재 실행 중인 독립 EOD 태스크를 반환한다. main.py 셧다운 대기에 사용한다."""
    return _active_eod_task


def _on_eod_task_done(task: asyncio.Task[None]) -> None:
    """EOD 태스크 완료 콜백 — 플래그와 추적 변수를 정리한다."""
    global _eod_running, _active_eod_task
    _eod_running = False
    if _active_eod_task is task:
        _active_eod_task = None


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
        # atomic_list_append로 read→append→write를 원자적으로 수행한다.
        # 동시에 여러 코루틴이 알림을 추가해도 유실이 발생하지 않는다.
        await cache.atomic_list_append(
            "alerts:list", [alert_entry], max_size=100, ttl=86400,
        )
    except Exception as exc:
        _logger.debug("알림 기록 실패 (무시): %s", exc)


_KST = ZoneInfo("Asia/Seoul")


def _compute_is_trading_day(now_kst: datetime) -> bool:
    """주말(토/일) 및 미국 시장 공휴일인지 판별한다."""
    from src.common.market_clock import is_us_market_holiday
    from zoneinfo import ZoneInfo

    # weekday(): 0=월, ..., 5=토, 6=일
    # KST 기준 토요일 새벽(미국 금요일 밤)은 거래 가능이므로,
    # 실제 비거래일은 KST 일요일 전체 + 토요일 06:30 이후이다.
    wd = now_kst.weekday()
    if wd == 6:  # 일요일 — 비거래일
        return False
    if wd == 5:  # 토요일
        # 06:30 이전이면 금요일 미장 세션 중이므로 거래일이다
        if now_kst.hour < 6 or (now_kst.hour == 6 and now_kst.minute < 30):
            return True
        return False

    # 미국 시장 공휴일 검사 (ET 기준 날짜로 판별한다)
    et_now = now_kst.astimezone(ZoneInfo("US/Eastern"))
    if is_us_market_holiday(et_now.date()):
        return False

    return True


def _compute_next_window_start(now_kst: datetime) -> str | None:
    """다음 매매 윈도우(20:00 KST) 시작 시각을 ISO 문자열로 반환한다.

    현재 매매 윈도우 안이면 None을 반환한다 (이미 열려 있으므로).
    """
    from src.common.market_clock import get_market_clock
    clock = get_market_clock()
    if clock.is_trading_window():
        return None
    # 오늘 20:00 KST가 아직 오지 않았으면 오늘 20:00, 지났으면 내일 20:00
    today_20 = now_kst.replace(hour=20, minute=0, second=0, microsecond=0)
    if now_kst < today_20:
        return today_20.isoformat()
    # 이미 20시 이후인데 매매 윈도우가 아닌 경우(06:30~20:00 사이가 아님)는 없으므로
    # 보수적으로 내일 20:00을 반환한다
    return (today_20 + timedelta(days=1)).isoformat()


def _build_status_response() -> TradingStatusResponse:
    """현재 매매 상태 응답을 조립한다."""
    clock = get_market_clock()
    time_info = clock.get_time_info()

    is_trading = _system is not None and _system.running
    task_done = True
    if _system and _system.trading_task:
        task_done = _system.trading_task.done()  # type: ignore[union-attr]

    # Flutter TradingControlProvider가 기대하는 is_trading_day, next_window_start를 계산한다
    is_trading_day = _compute_is_trading_day(time_info.now_kst)
    next_window_start = _compute_next_window_start(time_info.now_kst)

    return TradingStatusResponse(
        is_trading=is_trading,
        running=is_trading,
        task_done=task_done,
        is_trading_window=time_info.is_trading_window,
        session_type=time_info.session_type,
        current_kst=time_info.now_kst.isoformat(),
        is_trading_day=is_trading_day,
        next_window_start=next_window_start,
        user_stopped=_user_stopped,
        eod_running=_eod_running,
    )


@trading_control_router.get(
    "/status",
    response_model=TradingStatusResponse,
)
async def get_trading_status(_auth: str = Depends(verify_api_key)) -> TradingStatusResponse:
    """현재 자동매매 실행 상태를 반환한다. 인증 필수."""
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

    # Lock으로 동시 start/stop 요청의 상태 전이 레이스를 방지한다
    async with _control_lock:
        if _system.running:
            return TradingActionResponse(status="already_running")

        # EOD 시퀀스 실행 중이면 시작을 차단한다 (태스크 내부 EOD + 수동 stop EOD 모두 포함)
        if _eod_running or (_system.trading_task and not _system.trading_task.done()):
            raise HTTPException(
                status_code=409,
                detail="EOD 시퀀스 실행 중입니다. 완료 후 다시 시도하세요.",
            )

        clock = get_market_clock()
        time_info = clock.get_time_info()

        if not force and not time_info.is_trading_window:
            raise HTTPException(
                status_code=409,
                detail="매매 가능 시간이 아닙니다 (20:00~06:30 KST)",
            )

        global _user_stopped
        _user_stopped = False
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
    async with _control_lock:
        if _system is None or not _system.running:
            return TradingActionResponse(status="not_running")

        global _user_stopped
        _user_stopped = True
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
            # Self-Healing: 에러 모니터링봇과 매매 감시봇을 동시 실행한다
            _monitor = system.features.get("error_monitor")
            _watchdog = system.features.get("trade_watchdog")
            healing_tasks: list[asyncio.Task[None]] = []
            if _monitor is not None:
                healing_tasks.append(asyncio.create_task(
                    _monitor.run(_shutdown_event),
                ))
            if _watchdog is not None:
                healing_tasks.append(asyncio.create_task(
                    _watchdog.run(_shutdown_event),
                ))
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
                # Self-Healing 태스크 정리
                for ht in healing_tasks:
                    if not ht.done():
                        ht.cancel()
                for ht in healing_tasks:
                    try:
                        await ht
                    except (asyncio.CancelledError, Exception):
                        pass
                _logger.info("healing_tasks 정리 끝 (%d개)", len(healing_tasks))
        except asyncio.CancelledError:
            cancelled = True
            _logger.info("매매 태스크 취소됨")
        except Exception as exc:
            _logger.exception("매매 태스크 예외 발생")
            # 크래시 알림을 대시보드에 전송하여 운영자가 즉시 인지할 수 있게 한다
            try:
                await _record_alert(
                    system, "system", "매매 루프 크래시",
                    f"매매 루프가 예외로 종료되었습니다: {exc}",
                    severity="critical",
                )
            except Exception:
                _logger.debug("크래시 알림 기록 실패 (무시)")
        finally:
            # 매매 루프 종료 즉시 running=False 설정 -- 대시보드가 즉시 반영한다
            system.running = False
            _logger.info("매매 루프 종료 (running=False)")

            # Self-Healing 세션 초기화
            _heal_monitor = system.features.get("error_monitor")
            if _heal_monitor is not None and hasattr(_heal_monitor, "reset_session"):
                _heal_monitor.reset_session()

            # EOD 시퀀스: 루프가 정상 종료된 경우 반드시 실행한다
            # asyncio.shield로 보호하여 SIGTERM 중 CancelledError로 중단되지 않게 한다
            if loop_finished_normally and not cancelled:
                global _eod_running, _active_eod_task
                _eod_running = True
                eod_task = asyncio.ensure_future(_run_auto_eod(system))
                _active_eod_task = eod_task
                eod_task.add_done_callback(_on_eod_task_done)
                try:
                    _logger.info("매매 루프 자동 종료 -- EOD 시퀀스 실행")
                    await asyncio.shield(eod_task)
                except asyncio.CancelledError:
                    # shield가 외부 취소를 흡수해도 내부 태스크는 계속 실행 중이다
                    # 내부 태스크가 완료될 때까지 대기하여 조기 해제를 방지한다
                    _logger.warning("EOD 중 취소 신호 수신 — shield로 보호됨, EOD 완료 대기")
                    try:
                        await eod_task
                    except Exception:
                        _logger.exception("shield 후 EOD 태스크 완료 중 예외")
                except Exception:
                    _logger.exception("자동 EOD 시퀀스 실행 실패")
                # _on_eod_task_done 콜백이 _eod_running/_active_eod_task를 정리한다
                # 핸들러 취소로 eod_task가 독립 실행을 계속해도 콜백이 완료 시 정리한다
            elif cancelled:
                _logger.info("매매 취소됨 -- EOD 건너뜀 (수동 stop에서 EOD 실행)")
            else:
                _logger.warning("매매 루프 비정상 종료 -- EOD 건너뜀")
                # 비정상 종료 시 EOD 미실행 알림을 대시보드에 전송한다
                try:
                    await _record_alert(
                        system, "system", "EOD 미실행 경고",
                        "매매 루프가 비정상 종료되어 EOD 시퀀스를 건너뛰었습니다. "
                        "포지션 동기화, PnL 기록 등이 수행되지 않았습니다.",
                        severity="critical",
                    )
                except Exception:
                    _logger.debug("EOD 미실행 알림 기록 실패 (무시)")
            _logger.info("매매 태스크 생명주기 종료")

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
    global _eod_running, _active_eod_task
    system.running = False

    # EOD 예정이면 태스크 취소 전에 _eod_running을 선점하여
    # stop→start 레이스 조건을 방지한다
    if run_eod:
        _eod_running = True

    if _shutdown_event is not None:
        _shutdown_event.set()

    if system.trading_task and not system.trading_task.done():  # type: ignore[union-attr]
        system.trading_task.cancel()  # type: ignore[union-attr]
        try:
            await system.trading_task  # type: ignore[misc]
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _logger.warning("매매 태스크 정리 중 예외 (무시): %s", exc)

    if run_eod:
        # EOD 태스크를 독립 태스크로 생성하고 추적한다
        # done callback이 완료 시 _eod_running과 _active_eod_task를 정리한다
        try:
            from src.orchestration.phases.eod_sequence import run_eod_sequence
            eod_task = asyncio.ensure_future(run_eod_sequence(system))
        except Exception:
            _logger.exception("EOD 태스크 생성 실패")
            _eod_running = False
            return
        _active_eod_task = eod_task
        eod_task.add_done_callback(_on_eod_task_done)
        try:
            await asyncio.shield(eod_task)
        except asyncio.CancelledError:
            _logger.warning("stop EOD 중 취소 신호 수신 — EOD 완료 대기")
            try:
                await eod_task
            except Exception:
                _logger.exception("shield 후 stop EOD 태스크 완료 중 예외")
        except Exception:
            _logger.exception("stop EOD 대기 중 예외")
        # _on_eod_task_done 콜백이 _eod_running/_active_eod_task를 정리한다
        # 핸들러 취소로 여기를 건너뛰어도 eod_task는 독립 실행을 계속하며
        # main.py가 get_active_eod_task()로 완료를 대기한다

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
                weekly_task = asyncio.ensure_future(run_weekly_analysis(system))
                try:
                    await asyncio.shield(weekly_task)
                except asyncio.CancelledError:
                    _logger.warning("주간 분석 중 취소 신호 수신 — 완료 대기")
                    try:
                        await weekly_task
                    except Exception:
                        _logger.exception("shield 후 주간 분석 완료 중 예외")
        except Exception as exc:
            _logger.warning("주간 분석 실행 실패 (건너뜀): %s", exc)
