"""F9.8 GracefulShutdown -- SIGTERM/SIGINT 수신 시 안전하게 종료한다.

포지션 정리 후 모든 연결을 역순으로 해제하고 종료 결과를 반환한다.
"""
from __future__ import annotations

import asyncio
import signal
from collections.abc import Coroutine
from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)


class ShutdownResult(BaseModel):
    """종료 결과이다."""

    connections_closed: int
    clean_exit: bool
    errors: list[str] = []


async def _cancel_trading_task(system: InjectedSystem) -> str | None:
    """실행 중인 trading_task를 종료하고 완료를 대기한다.

    signal_trading_shutdown()으로 shutdown_event가 이미 설정된 상태이므로
    매매 루프가 자연 종료(→ EOD 실행)할 시간을 먼저 준다.
    30초 내 자연 종료되지 않으면 cancel()로 강제 취소한다.
    연결 해제는 이 대기 이후에 진행되어야 EOD가 브로커/캐시를 안전하게 사용할 수 있다.
    """
    task = system.trading_task
    if task is None:
        return None
    try:
        if not task.done():  # type: ignore[union-attr]
            # shutdown_event 설정 후 자연 종료를 30초 대기한다
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=30)  # type: ignore[arg-type]
            except asyncio.TimeoutError:
                # 자연 종료 실패 → 강제 취소
                logger.warning("trading_task 30초 내 자연 종료 안 됨 — cancel() 실행")
                task.cancel()  # type: ignore[union-attr]
            except (asyncio.CancelledError, Exception):
                pass
            # finally 블록(EOD 등)이 완료될 때까지 최대 120초 대기한다
            if not task.done():  # type: ignore[union-attr]
                try:
                    await asyncio.wait_for(task, timeout=120)  # type: ignore[arg-type]
                except asyncio.TimeoutError:
                    logger.warning("trading_task 120초 내 미완료 — 강제 진행")
                except (asyncio.CancelledError, Exception):
                    pass
        logger.info("trading_task 종료 완료")
    except Exception as exc:
        msg = f"trading_task 종료 실패: {exc}"
        logger.error(msg)
        return msg
    return None


async def _send_shutdown_notice(system: InjectedSystem) -> str | None:
    """텔레그램으로 종료 알림을 발송한다."""
    try:
        await system.components.telegram.send_text(
            "[시스템] Stock Trading AI System V2 종료 중..."
        )
        logger.info("텔레그램 종료 알림 발송 완료")
    except Exception as exc:
        msg = f"텔레그램 종료 알림 실패: {exc}"
        logger.warning(msg)
        return msg
    return None


async def _close_connection(
    name: str,
    close_coro: Coroutine[object, object, None],
) -> str | None:
    """단일 연결을 해제한다. 실패 시 에러 메시지를 반환한다."""
    try:
        await close_coro  # type: ignore[misc]
        logger.info("%s 연결 해제 완료", name)
    except Exception as exc:
        msg = f"{name} 연결 해제 실패: {exc}"
        logger.error(msg)
        return msg
    return None


async def _close_all_connections(system: InjectedSystem) -> tuple[int, list[str]]:
    """모든 외부 연결을 생성 역순으로 해제한다. (해제 수, 에러 목록)을 반환한다."""
    errors: list[str] = []
    closed = 0
    c = system.components

    # 텔레그램 알림은 연결 해제 전에 발송한다
    notice_err = await _send_shutdown_notice(system)
    if notice_err:
        errors.append(notice_err)

    # 생성 역순: Telegram -> Broker -> AI -> HTTP -> Cache -> DB
    # 코루틴을 지연 생성하여 한 컴포넌트의 .close() 접근 실패가 나머지를 누락시키는 것을 방지한다
    step_names = ["Telegram", "Broker", "AI", "HTTP", "Cache", "DB"]
    step_closers = [
        lambda: c.telegram.close(),
        lambda: c.broker.close(),
        lambda: c.ai.close(),
        lambda: c.http.close(),
        lambda: c.cache.aclose(),
        lambda: c.db.close(),
    ]
    for name, closer in zip(step_names, step_closers):
        try:
            coro = closer()
        except Exception as exc:
            errors.append(f"{name} close() 생성 실패: {exc}")
            logger.error("%s close() 호출 실패: %s", name, exc)
            continue
        err = await _close_connection(name, coro)
        if err:
            errors.append(err)
        else:
            closed += 1
    return closed, errors


def _clear_event_bus(system: InjectedSystem) -> str | None:
    """이벤트 버스를 정리한다. 실패 시 에러 메시지를 반환한다."""
    try:
        system.components.event_bus.clear()
        logger.info("EventBus 정리 완료")
    except Exception as exc:
        return f"EventBus 정리 실패: {exc}"
    return None


# 이중 종료 방지 플래그이다. 시그널 재수신 등으로 graceful_shutdown이 중복 호출되는 것을 방지한다.
_shutdown_in_progress: bool = False


async def graceful_shutdown(system: InjectedSystem) -> ShutdownResult:
    """시스템을 안전하게 종료한다. 연결을 생성 역순으로 해제한다.

    이중 호출 시 두 번째 호출은 즉시 반환한다.
    """
    global _shutdown_in_progress
    if _shutdown_in_progress:
        logger.warning("graceful_shutdown 이중 호출 감지 -- 건너뜀")
        return ShutdownResult(connections_closed=0, clean_exit=True)
    _shutdown_in_progress = True

    logger.info("=== 시스템 종료 시작 ===")
    errors: list[str] = []

    system.running = False

    task_err = await _cancel_trading_task(system)
    if task_err:
        errors.append(task_err)

    closed, conn_errors = await _close_all_connections(system)
    errors.extend(conn_errors)

    bus_err = _clear_event_bus(system)
    if bus_err:
        errors.append(bus_err)
    else:
        closed += 1

    result = ShutdownResult(
        connections_closed=closed,
        clean_exit=len(errors) == 0,
        errors=errors,
    )
    logger.info("=== 시스템 종료 완료 (해제 %d개, 에러 %d개) ===", closed, len(errors))
    return result


def setup_signal_handlers(
    system: InjectedSystem,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """SIGTERM/SIGINT 시그널 핸들러를 등록한다.

    시그널 수신 시 매매 running 플래그를 해제하고,
    shutdown_event가 있으면 set()하여 메인 루프를 종료한다.
    """
    loop = asyncio.get_running_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        """시그널을 수신하면 매매 중지 + 시스템 종료 이벤트를 발행한다."""
        sig_name = sig.name
        logger.info("시그널 수신: %s -- 종료를 시작한다", sig_name)
        system.running = False
        # 매매 루프의 shutdown_event도 설정하여 루프가 자연 종료 → EOD 실행되게 한다
        try:
            from src.monitoring.endpoints.trading_control import signal_trading_shutdown
            signal_trading_shutdown()
        except Exception:
            pass  # 시그널 핸들러에서 예외 전파를 방지한다
        if shutdown_event is not None:
            shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)
        logger.info("시그널 핸들러 등록: %s", sig.name)
