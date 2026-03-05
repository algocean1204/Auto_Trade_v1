"""F7.19 WebSocketManager -- 실시간 데이터 스트림 관리이다.

5개 WebSocket 채널을 관리하며 3초 주기로 데이터를 갱신한다.
/ws/dashboard, /ws/positions, /ws/orderflow, /ws/alerts, /ws/trades

크롤링 진행 상태 스트림:
/ws/crawl/{task_id} -- Redis crawl:task:{task_id} 를 1초 주기로 폴링하여 전송한다.
                       태스크가 completed/failed 상태이면 최종 결과를 보내고 연결을 종료한다.
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

ws_router = APIRouter(tags=["websocket"])

_system: InjectedSystem | None = None

_REFRESH_INTERVAL: float = 3.0

# 채널별 활성 연결을 관리한다
_connections: dict[str, list[WebSocket]] = {
    "dashboard": [],
    "positions": [],
    "orderflow": [],
    "alerts": [],
    "trades": [],
}


def set_ws_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다."""
    global _system
    _system = system
    _logger.info("WebSocketManager 의존성 주입 완료")


def _add_connection(channel: str, ws: WebSocket) -> None:
    """채널에 WebSocket 연결을 추가한다."""
    if channel in _connections:
        _connections[channel].append(ws)
        _logger.debug("WS 연결 추가: %s (총 %d)", channel, len(_connections[channel]))


def _remove_connection(channel: str, ws: WebSocket) -> None:
    """채널에서 WebSocket 연결을 제거한다."""
    if channel in _connections and ws in _connections[channel]:
        _connections[channel].remove(ws)
        _logger.debug("WS 연결 제거: %s (총 %d)", channel, len(_connections[channel]))


async def _get_channel_data(channel: str) -> dict:
    """채널별 최신 데이터를 캐시에서 조회한다."""
    if _system is None:
        return {"error": "시스템 초기화 중"}
    try:
        cache = _system.components.cache
        cached = await cache.read_json(f"ws:{channel}")
        if cached and isinstance(cached, dict):
            return cached
        return {"channel": channel, "data": None}
    except Exception:
        return {"channel": channel, "error": "데이터 조회 실패"}


async def _stream_loop(channel: str, ws: WebSocket) -> None:
    """3초 주기로 데이터를 전송하는 스트림 루프이다."""
    try:
        while True:
            data = await _get_channel_data(channel)
            await ws.send_text(json.dumps(data, default=str))
            await asyncio.sleep(_REFRESH_INTERVAL)
    except WebSocketDisconnect:
        pass
    except Exception:
        _logger.debug("WS 스트림 종료: %s", channel)


async def _handle_ws(channel: str, ws: WebSocket) -> None:
    """WebSocket 연결을 수락하고 스트림을 시작한다."""
    await ws.accept()
    _add_connection(channel, ws)
    try:
        await _stream_loop(channel, ws)
    finally:
        _remove_connection(channel, ws)


@ws_router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket) -> None:
    """대시보드 실시간 스트림이다."""
    await _handle_ws("dashboard", ws)


@ws_router.websocket("/ws/positions")
async def ws_positions(ws: WebSocket) -> None:
    """포지션 실시간 스트림이다."""
    await _handle_ws("positions", ws)


@ws_router.websocket("/ws/orderflow")
async def ws_orderflow(ws: WebSocket) -> None:
    """주문흐름 실시간 스트림이다."""
    await _handle_ws("orderflow", ws)


@ws_router.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket) -> None:
    """알림 실시간 스트림이다."""
    await _handle_ws("alerts", ws)


@ws_router.websocket("/ws/trades")
async def ws_trades(ws: WebSocket) -> None:
    """매매 실시간 스트림이다."""
    await _handle_ws("trades", ws)


@ws_router.websocket("/ws/crawl/{task_id}")
async def ws_crawl_progress(ws: WebSocket, task_id: str) -> None:
    """크롤링 태스크의 진행 상태를 실시간으로 스트리밍한다.

    Redis crawl:task:{task_id} 키를 1초 주기로 폴링하여 클라이언트에 전송한다.
    태스크 상태가 completed 또는 failed가 되면 최종 결과를 전송하고 연결을 종료한다.
    존재하지 않는 task_id이면 즉시 에러 메시지를 전송하고 연결을 종료한다.
    """
    await ws.accept()
    _logger.debug("크롤링 WS 연결 수락: task_id=%s", task_id)

    # 시스템이 초기화되지 않은 경우 에러를 전송하고 종료한다
    if _system is None:
        await ws.send_text(json.dumps({"error": "시스템 초기화 중", "task_id": task_id}))
        await ws.close()
        return

    redis_key = f"crawl:task:{task_id}"
    # 연결 종료 상태 집합 — 이 상태에 도달하면 스트림을 닫는다
    _TERMINAL_STATUSES = frozenset({"completed", "failed"})
    # 태스크가 존재하지 않을 때 재시도 횟수 상한이다 (3초 대기 후 종료)
    _MAX_NOT_FOUND_RETRIES = 3
    not_found_count = 0

    try:
        while True:
            try:
                cache = _system.components.cache
                raw = await cache.read_json(redis_key)
            except Exception:
                _logger.debug("크롤링 WS 캐시 조회 실패: %s", task_id)
                raw = None

            if raw is None:
                not_found_count += 1
                if not_found_count >= _MAX_NOT_FOUND_RETRIES:
                    # 태스크가 존재하지 않음을 알리고 연결을 종료한다
                    await ws.send_text(
                        json.dumps({
                            "error": f"크롤링 태스크를 찾을 수 없다: {task_id}",
                            "task_id": task_id,
                            "status": "not_found",
                        })
                    )
                    break
            else:
                not_found_count = 0
                # 진행 상태를 클라이언트에 전송한다
                await ws.send_text(json.dumps(raw, default=str))

                # 종료 상태이면 더 이상 폴링하지 않는다
                current_status = raw.get("status", "")
                if current_status in _TERMINAL_STATUSES:
                    _logger.debug(
                        "크롤링 WS 스트림 종료 (태스크 완료): task_id=%s status=%s",
                        task_id,
                        current_status,
                    )
                    break

            # 1초 대기 후 재폴링한다
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        _logger.debug("크롤링 WS 클라이언트 연결 해제: task_id=%s", task_id)
    except Exception:
        _logger.debug("크롤링 WS 스트림 오류: task_id=%s", task_id)
    finally:
        # WebSocket이 아직 열려 있으면 정상 종료한다
        try:
            await ws.close()
        except Exception:
            pass


def get_connection_stats() -> dict[str, int]:
    """채널별 활성 연결 수를 반환한다. 모니터링용이다."""
    return {ch: len(conns) for ch, conns in _connections.items()}
