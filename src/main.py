"""Stock Trading AI System V2 -- 엔트리포인트.

전체 시스템의 시작점이다. 초기화 -> 시그널 등록 -> API 서버 -> 종료 대기.
system.running은 매매 상태 전용이다. 시스템 수명은 _shutdown_event로 제어한다.
"""
from __future__ import annotations

# python src/main.py 실행 시 Python이 src/를 sys.path[0]에 추가한다.
# 이로 인해 import telegram이 src/telegram/을 먼저 찾아 python-telegram-bot과 충돌한다.
# 프로젝트 루트(PYTHONPATH=.)만 남기고 src/ 경로를 제거한다.
import os as _os
import sys as _sys

_src_dir = _os.path.dirname(_os.path.abspath(__file__))
if _src_dir in _sys.path:
    _sys.path.remove(_src_dir)

import asyncio

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass  # uvloop 미설치 시 기본 asyncio 폴백

from src.common.logger import get_logger
from src.monitoring.server.api_server import (
    create_app,
    inject_system,
    start_server,
)
from src.orchestration.init.dependency_injector import inject_dependencies
from src.orchestration.init.graceful_shutdown import (
    graceful_shutdown,
    setup_signal_handlers,
)
from src.orchestration.init.system_initializer import initialize_system

logger = get_logger(__name__)


async def main() -> None:
    """메인 함수 -- 시스템 초기화 -> API 서버 시작 -> 종료 대기."""
    logger.info("Stock Trading AI System V2 시작")

    # 1. 시스템 초기화 (system.running은 매매 상태 전용, 여기서 설정 안 함)
    components = await initialize_system()
    system = inject_dependencies(components)

    # 1.5. DB에서 유니버스를 로드한다 (비어있으면 하드코딩 데이터로 시드)
    try:
        persister = system.features.get("universe_persister")
        if persister is not None:
            await system.components.registry.load_from_db(persister)
            logger.info("유니버스 DB 로드 완료")
        else:
            logger.warning("UniversePersister 미등록 -- 하드코딩 유니버스를 사용한다")
    except Exception as exc:
        logger.warning("유니버스 DB 로드 실패 (하드코딩 폴백): %s", exc)

    # 2. 시그널 핸들러 등록 (SIGTERM/SIGINT → shutdown_event.set())
    shutdown_event = asyncio.Event()
    setup_signal_handlers(system, shutdown_event)

    # 3. API 서버 생성 + 의존성 주입 + 비동기 시작 (F7.1)
    app = create_app()
    inject_system(app, system)
    server_task = asyncio.create_task(start_server(app))

    # 3.5. 서버 시작 실패 감지 -- 포트 바인드 실패 등으로 서버가 즉시 종료되면
    #       shutdown_event.wait()만으로는 감지할 수 없다.
    server_failed = asyncio.Event()

    def _on_server_done(task: asyncio.Task[None]) -> None:
        """서버 태스크 완료 시 콜백 -- 예외 발생이면 시스템을 종료한다."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("API 서버 비정상 종료: %s", exc)
            server_failed.set()

    server_task.add_done_callback(_on_server_done)

    # 4. 종료 대기 (시그널 또는 서버 실패 중 먼저 발생한 쪽)
    logger.info("시스템 준비 완료. API 서버에서 매매를 제어합니다.")
    done, _ = await asyncio.wait(
        [
            asyncio.create_task(shutdown_event.wait()),
            asyncio.create_task(server_failed.wait()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if server_failed.is_set():
        logger.error("서버 시작 실패로 시스템을 종료한다.")

    # 5. 서버 태스크 정리
    if not server_task.done():
        server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, SystemExit):
        logger.info("API 서버 태스크 정리 완료")

    # 6. 안전 종료
    result = await graceful_shutdown(system)
    logger.info(
        "시스템 종료 완료: clean=%s, closed=%d",
        result.clean_exit,
        result.connections_closed,
    )


if __name__ == "__main__":
    asyncio.run(main())
