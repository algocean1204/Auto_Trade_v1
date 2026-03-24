"""Stock Trading AI System V2 -- 엔트리포인트.

전체 시스템의 시작점이다. 초기화 -> 시그널 등록 -> API 서버 -> 종료 대기.
system.running은 매매 상태 전용이다. 시스템 수명은 _shutdown_event로 제어한다.
"""
from __future__ import annotations

# python src/main.py 실행 시 Python이 src/를 sys.path[0]에 추가한다.
# 이로 인해 import telegram이 src/telegram/을 먼저 찾아 python-telegram-bot과 충돌한다.
# 프로젝트 루트(PYTHONPATH=.)만 남기고 src/ 경로를 제거한다.
# PyInstaller 번들에서는 _internal/ 경로가 필수이므로 frozen 상태에서는 건너뛴다.
import os as _os
import sys as _sys

if not getattr(_sys, 'frozen', False):
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
from src.common.paths import get_data_dir, get_env_path
from src.monitoring.server.api_server import (
    create_app,
    inject_system,
    set_setup_mode,
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

    # 0. SQLite 데이터 디렉토리를 확보한다 (없으면 생성한다)
    get_data_dir()

    # 0.5. .env 존재 + KIS 키 유무로 setup_mode를 결정한다
    env_path = get_env_path()
    if env_path is None:
        setup_mode = True
        logger.warning("setup_mode 활성화 — .env 파일이 없어 초기 설정 모드로 기동한다")
    else:
        # .env를 setup_mode로 먼저 로드하여 KIS 키 유무만 확인한다
        from src.common.secret_vault import get_vault, reset_vault
        vault = get_vault(setup_mode=True)
        has_kis = vault.has_secret("KIS_VIRTUAL_APP_KEY") or vault.has_secret(
            "KIS_REAL_APP_KEY",
        )
        setup_mode = not has_kis
        # 사전 검사용 싱글톤을 리셋한다.
        # initialize_system()이 올바른 setup_mode로 재초기화하여
        # 정상 모드에서는 _validate_required()가 호출되도록 한다.
        reset_vault()
        if setup_mode:
            logger.warning(
                "setup_mode 활성화 — .env는 있지만 KIS 키가 없다: %s", env_path,
            )
        else:
            logger.info("정상 모드 기동 — .env 로드: %s", env_path)
    set_setup_mode(setup_mode)

    # 1. 시스템 초기화 (system.running은 매매 상태 전용, 여기서 설정 안 함)
    components = await initialize_system(setup_mode=setup_mode)
    system = inject_dependencies(components)

    # 1.2. SQLite 테이블 생성 (이미 존재하는 테이블은 건너뛴다)
    await system.components.db.create_tables()

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

    # M-16: 유니버스가 비어있으면 매매 불가하므로 에러를 발생시킨다
    #        setup_mode에서는 경고만 출력하고 계속 진행한다
    universe = system.components.registry.get_universe()
    if not universe:
        if setup_mode:
            logger.warning("유니버스가 비어있음 — setup_mode이므로 계속 진행한다")
        else:
            logger.error("유니버스가 비어있음 — 매매 불가")
            raise RuntimeError("빈 유니버스: 티커 데이터 로드 실패")
    else:
        logger.info("유니버스 로드 완료: %d개 티커", len(universe))

    # 2. 시그널 핸들러 등록 (SIGTERM/SIGINT → shutdown_event.set())
    #    서버 시작 전에 등록하여 시작 중 시그널 미처리 구간을 제거한다
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
    done, pending = await asyncio.wait(
        [
            asyncio.create_task(shutdown_event.wait()),
            asyncio.create_task(server_failed.wait()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )
    # 미완료 태스크를 취소하고 완료를 대기하여 누수를 방지한다
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    if server_failed.is_set():
        logger.error("서버 시작 실패로 시스템을 종료한다.")

    # 5. 서버 태스크 정리 — 어떤 예외든 흡수하여 graceful_shutdown 도달을 보장한다
    if not server_task.done():
        server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, SystemExit):
        logger.info("API 서버 태스크 정리 완료")
    except Exception as exc:
        logger.warning("API 서버 태스크 예외 (종료 진행): %s", exc)

    # 6. 안전 종료
    result = await graceful_shutdown(system)
    logger.info(
        "시스템 종료 완료: clean=%s, closed=%d",
        result.clean_exit,
        result.connections_closed,
    )


if __name__ == "__main__":
    asyncio.run(main())
