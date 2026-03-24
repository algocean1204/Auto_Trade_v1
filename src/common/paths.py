"""경로 통합 모듈 (C0.0) -- 프로젝트 전체 경로를 중앙에서 관리한다.

PyInstaller frozen 번들과 개발 환경 모두를 지원한다.
모든 경로 참조는 이 모듈을 통해 수행해야 한다.
번들 첫 실행 시 시드 데이터를 Application Support로 복사한다.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# macOS Application Support 번들 식별자이다
_BUNDLE_ID: str = "com.stocktrader.ai"


def is_bundled() -> bool:
    """PyInstaller frozen 환경인지 확인한다.

    PyInstaller로 패키징된 실행 파일이면 True를 반환한다.
    """
    return getattr(sys, "frozen", False)


def get_project_root() -> Path:
    """프로젝트 루트 경로를 반환한다.

    bundled이면 sys._MEIPASS(압축 해제 임시 디렉토리)를 반환한다.
    개발 환경이면 src/common/에서 2단계 위 경로를 반환한다.
    """
    if is_bundled():
        # PyInstaller가 번들 내용을 압축 해제하는 임시 디렉토리이다
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass is not None:
            return Path(meipass)
        # _MEIPASS가 없으면 실행 파일 기준 디렉토리를 사용한다
        return Path(sys.executable).resolve().parent
    # 개발 환경: src/common/paths.py -> src/common/ -> src/ -> 프로젝트 루트
    return Path(__file__).resolve().parents[2]


def get_app_support_dir() -> Path:
    """앱 데이터 디렉토리를 반환한다.

    macOS: ~/Library/Application Support/com.stocktrader.ai/
    Linux: ~/.local/share/com.stocktrader.ai/
    디렉토리가 없으면 생성한다.
    """
    import platform

    if platform.system() == "Darwin":
        app_support = Path.home() / "Library" / "Application Support" / _BUNDLE_ID
    else:
        # Linux/기타: XDG_DATA_HOME 또는 ~/.local/share/ 를 사용한다
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            app_support = Path(xdg_data) / _BUNDLE_ID
        else:
            app_support = Path.home() / ".local" / "share" / _BUNDLE_ID
    try:
        app_support.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("앱 데이터 디렉토리 생성에 실패했다: %s", app_support)
    return app_support


# 번들 시드 파일 복사 완료 여부이다 (프로세스 수명 동안 1회만 실행한다)
_seed_done: bool = False

# 번들에서 App Support로 복사할 시드 파일 목록이다
_SEED_FILES: tuple[str, ...] = (
    "strategy_params.json",
    "ticker_params.json",
    "trading_principles.json",
)


def _seed_bundled_data(dest_dir: Path) -> None:
    """번들(_MEIPASS) 내 시드 데이터를 App Support data/로 복사한다.

    이미 존재하는 파일은 덮어쓰지 않는다 (사용자 수정 보존).
    번들 환경에서만 호출되며, 프로세스당 1회만 실행한다.
    """
    global _seed_done
    if _seed_done:
        return
    _seed_done = True

    bundle_data = get_project_root() / "data"
    if not bundle_data.is_dir():
        logger.debug("번들 시드 디렉토리 없음: %s", bundle_data)
        return

    for filename in _SEED_FILES:
        src_file = bundle_data / filename
        dst_file = dest_dir / filename
        if src_file.exists() and not dst_file.exists():
            try:
                shutil.copy2(str(src_file), str(dst_file))
                logger.info("시드 파일 복사: %s → %s", src_file, dst_file)
            except OSError:
                logger.exception("시드 파일 복사 실패: %s", filename)


def get_data_dir() -> Path:
    """데이터 디렉토리를 반환한다.

    bundled이면 Application Support 하위 data/를 반환한다.
    개발 환경이면 프로젝트 루트 하위 data/를 반환한다.
    디렉토리가 없으면 생성한다.
    번들 첫 실행 시 시드 데이터를 자동 복사한다.
    """
    if is_bundled():
        data_dir = get_app_support_dir() / "data"
    else:
        data_dir = get_project_root() / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("데이터 디렉토리 생성에 실패했다: %s", data_dir)
    # 번들 환경에서 첫 실행 시 시드 파일을 복사한다
    if is_bundled():
        _seed_bundled_data(data_dir)
    return data_dir


def get_models_dir() -> Path:
    """모델 디렉토리를 반환한다.

    bundled이면 Application Support 하위 models/를 반환한다.
    개발 환경이면 프로젝트 루트 하위 models/를 반환한다.
    디렉토리가 없으면 생성한다.
    """
    if is_bundled():
        models_dir = get_app_support_dir() / "models"
    else:
        models_dir = get_project_root() / "models"
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("모델 디렉토리 생성에 실패했다: %s", models_dir)
    return models_dir


def get_logs_dir() -> Path:
    """로그 디렉토리를 반환한다.

    bundled이면 Application Support 하위 logs/를 반환한다.
    개발 환경이면 프로젝트 루트 하위 logs/를 반환한다.
    디렉토리가 없으면 생성한다.
    """
    if is_bundled():
        logs_dir = get_app_support_dir() / "logs"
    else:
        logs_dir = get_project_root() / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("로그 디렉토리 생성에 실패했다: %s", logs_dir)
    return logs_dir


def get_env_path() -> Path | None:
    """존재하는 .env 파일 경로를 반환한다.

    탐색 순서:
    1. Application Support 디렉토리의 .env
    2. 프로젝트 루트의 .env

    존재하는 첫 번째 경로를 반환한다. 없으면 None을 반환한다.
    """
    # Application Support에 있는 .env를 우선 탐색한다 (배포 환경)
    app_support_env = get_app_support_dir() / ".env"
    if app_support_env.exists():
        logger.debug("Application Support에서 .env 발견: %s", app_support_env)
        return app_support_env

    # 프로젝트 루트의 .env를 탐색한다 (개발 환경)
    project_env = get_project_root() / ".env"
    if project_env.exists():
        logger.debug("프로젝트 루트에서 .env 발견: %s", project_env)
        return project_env

    # 어디서도 .env를 찾지 못했다
    logger.warning(".env 파일을 찾을 수 없다 (탐색 경로: %s, %s)", app_support_env, project_env)
    return None
