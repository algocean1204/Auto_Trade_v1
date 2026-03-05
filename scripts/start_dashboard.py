#!/usr/bin/env python3
"""대시보드 전용 서버 시작 스크립트 (V2).

전체 TradingSystem의 매매 루프를 기동하지 않고,
V2 초기화 파이프라인으로 API 서버만 단독 실행한다.

initialize_system → inject_dependencies → create_app → inject_system → start_server

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
from src.monitoring.server.api_server import create_app, inject_system, start_server
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

    # 1. 시스템 초기화 (SecretVault가 .env를 자동 로드한다)
    components = await initialize_system()
    system = inject_dependencies(components)

    # 2. API 서버 생성 + 의존성 주입
    app = create_app()
    inject_system(app, system)

    # 3. 서버 실행 (매매 루프 없이 API 서버만 서빙한다)
    logger.info("대시보드 서버 준비 완료. 매매 루프 없이 API만 서빙한다.")
    await start_server(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    asyncio.run(main())
