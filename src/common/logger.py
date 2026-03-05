"""
Logger (C0.8) -- 모듈명 기반 구조화 로거를 생성한다.

표준 라이브러리 logging 기반이며, SecretVault보다 먼저 초기화되므로
LOG_LEVEL만 직접 os.environ.get으로 읽는다.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# 프로젝트 루트의 logs/ 디렉토리 경로이다
_LOGS_DIR: Path = Path(__file__).resolve().parent.parent.parent / "logs"

# 로그 포맷 문자열이다
_LOG_FORMAT: str = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"

# 날짜 포맷이다
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# 이미 핸들러가 설정된 로거 이름을 추적한다
_configured_loggers: set[str] = set()


def _resolve_log_level() -> int:
    """환경변수 LOG_LEVEL을 파싱하여 logging 레벨 정수를 반환한다.

    이 함수만 os.environ.get 직접 접근이 허용된다 (SecretVault 미사용).
    """
    level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    level_map: dict[str, int] = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(level_str, logging.INFO)


def _ensure_logs_dir() -> Path:
    """logs/ 디렉토리가 없으면 생성한다."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return _LOGS_DIR


def _create_console_handler(level: int) -> logging.StreamHandler:
    """콘솔(stderr) 핸들러를 생성한다."""
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    return handler


def _create_file_handler(level: int) -> TimedRotatingFileHandler:
    """일별 로테이션 파일 핸들러를 생성한다.

    logs/trading_system.log에 기록하며 매일 자정에 로테이션한다.
    """
    logs_dir = _ensure_logs_dir()
    log_file = logs_dir / "trading_system.log"
    handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    return handler


def get_logger(module_name: str) -> logging.Logger:
    """구조화 로거를 생성한다.

    동일 모듈명으로 재호출해도 핸들러가 중복 추가되지 않는다.
    """
    logger = logging.getLogger(module_name)

    # 이미 설정된 로거는 그대로 반환한다
    if module_name in _configured_loggers:
        return logger

    level = _resolve_log_level()
    logger.setLevel(level)

    # 상위 로거로 전파하지 않아 핸들러 중복을 방지한다
    logger.propagate = False

    logger.addHandler(_create_console_handler(level))
    logger.addHandler(_create_file_handler(level))

    _configured_loggers.add(module_name)
    return logger
