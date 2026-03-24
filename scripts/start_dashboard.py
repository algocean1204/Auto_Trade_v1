#!/usr/bin/env python3
"""대시보드 전용 서버 시작 스크립트 (V2).

전체 TradingSystem의 매매 루프를 기동하지 않고,
V2 초기화 파이프라인으로 API 서버만 단독 실행한다.

initialize_system → inject_dependencies → create_tables → load_from_db → create_app → inject_system → start_server

사용법:
    .venv/bin/python scripts/start_dashboard.py
    # 포트 변경:
    API_PORT=8080 .venv/bin/python scripts/start_dashboard.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가한다.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
os.chdir(_PROJECT_ROOT)

from src.common.logger import get_logger
from src.common.paths import get_data_dir, get_env_path
from src.monitoring.server.api_server import (
    create_app,
    inject_system,
    set_setup_mode,
    start_server,
)
from src.orchestration.init.dependency_injector import inject_dependencies
from src.orchestration.init.system_initializer import initialize_system

logger = get_logger(__name__)


async def main() -> None:
    """대시보드 전용 서버를 시작한다. 매매 루프는 실행하지 않는다."""
    port = int(os.environ.get("API_PORT", "9501"))

    logger.info("=" * 60)
    logger.info("  Dashboard-Only Server (V2)")
    logger.info("  Port: %d", port)
    logger.info("=" * 60)

    # 0. 데이터 디렉토리 확보 + setup_mode 판별 (main.py와 동일)
    get_data_dir()

    env_path = get_env_path()
    if env_path is None:
        setup_mode = True
        logger.warning("setup_mode 활성화 — .env 파일이 없어 초기 설정 모드로 기동한다")
    else:
        from src.common.secret_vault import get_vault
        vault = get_vault(setup_mode=True)
        has_kis = vault.has_secret("KIS_VIRTUAL_APP_KEY") or vault.has_secret(
            "KIS_REAL_APP_KEY",
        )
        setup_mode = not has_kis
        if setup_mode:
            logger.warning(
                "setup_mode 활성화 — .env는 있지만 KIS 키가 없다: %s", env_path,
            )
        else:
            logger.info("정상 모드 기동 — .env 로드: %s", env_path)
    set_setup_mode(setup_mode)

    # 1. 시스템 초기화
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

    # 2. API 서버 생성 + 의존성 주입
    app = create_app()
    inject_system(app, system)

    # 3. 서버 실행 (매매 루프 없이 API 서버만 서빙한다)
    #    localhost 전용 바인딩 — LAN 노출을 방지한다
    logger.info("대시보드 서버 준비 완료. 매매 루프 없이 API만 서빙한다.")
    await start_server(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    asyncio.run(main())
