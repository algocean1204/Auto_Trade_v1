"""F9.8 GracefulShutdown -- SIGTERM/SIGINT 수신 시 안전하게 종료한다.

포지션 정리 후 모든 연결을 역순으로 해제하고 종료 결과를 반환한다.
"""
from __future__ import annotations

import asyncio
import signal
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
    """실행 중인 trading_task를 취소한다. 에러 발생 시 메시지를 반환한다."""
    task = system.trading_task
    if task is None:
        return None
    try:
        task.cancel()  # type: ignore[union-attr]
        await asyncio.sleep(0.1)  # 취소 전파 대기
        logger.info("trading_task 취소 완료")
    except Exception as exc:
        msg = f"trading_task 취소 실패: {exc}"
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
    close_coro: object,
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
    steps: list[tuple[str, object]] = [
        ("Telegram", c.telegram.close()),
        ("Broker", c.broker.close()),
        ("AI", c.ai.close()),
        ("HTTP", c.http.close()),
        ("Cache", c.cache.aclose()),
        ("DB", c.db.close()),
    ]
    for name, coro in steps:
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


async def graceful_shutdown(system: InjectedSystem) -> ShutdownResult:
    """시스템을 안전하게 종료한다. 연결을 생성 역순으로 해제한다."""
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
        if shutdown_event is not None:
            shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)
        logger.info("시그널 핸들러 등록: %s", sig.name)
