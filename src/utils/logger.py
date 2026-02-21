"""
프로젝트 전체 로깅 설정
- 콘솔 + 파일 출력
- 날짜별 로그 파일 로테이션
- 모듈별 로거 생성 헬퍼
"""
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from src.utils.config import get_settings

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_initialized: bool = False


def _ensure_log_dir() -> None:
    """로그 디렉토리가 존재하지 않으면 생성한다."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    """루트 로거에 콘솔 핸들러와 파일 핸들러를 설정한다.

    최초 한 번만 실행되며, 이후 호출은 무시된다.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    _ensure_log_dir()

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root_logger.addHandler(console_handler)

    # 파일 핸들러 (날짜별 로테이션, 30일 보관)
    file_handler = TimedRotatingFileHandler(
        filename=LOG_DIR / "trading.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    file_handler.suffix = "%Y-%m-%d"
    root_logger.addHandler(file_handler)

    # 외부 라이브러리 로그 레벨 제한
    for noisy_logger in ("httpx", "httpcore", "urllib3", "asyncio", "aiohttp"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """모듈별 로거를 생성하여 반환한다.

    Args:
        name: 로거 이름. 보통 ``__name__`` 을 전달한다.

    Returns:
        설정이 적용된 ``logging.Logger`` 인스턴스.
    """
    setup_logging()
    return logging.getLogger(name)
