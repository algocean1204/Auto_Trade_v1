"""F4 전략 파라미터 관리자 -- strategy_params.json을 읽고 쓴다.

파일 동시 접근을 방지하기 위해 asyncio.Lock으로 update/save를 보호한다.
EOD 파라미터 조정과 API 엔드포인트가 동시에 접근할 수 있기 때문이다.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_data_dir
from src.strategy.models import StrategyParams

logger = get_logger(__name__)

# 파일 쓰기 경합 방지용 Lock — 모듈 레벨 싱글톤이다
_file_lock: asyncio.Lock | None = None


def _get_file_lock() -> asyncio.Lock:
    """파일 Lock을 lazy 초기화한다."""
    global _file_lock
    if _file_lock is None:
        _file_lock = asyncio.Lock()
    return _file_lock


# 기본 파일 경로 -- get_data_dir()은 호출 시점에 평가해야 하므로 함수로 감싼다
def _default_path() -> Path:
    """기본 strategy_params.json 경로를 반환한다."""
    return get_data_dir() / "strategy_params.json"


def _read_json(file_path: Path) -> dict:
    """JSON 파일을 읽어 dict로 반환한다. 파일이 없으면 빈 dict를 반환한다."""
    if not file_path.exists():
        logger.warning("파라미터 파일 없음: %s (기본값 사용)", file_path)
        return {}
    try:
        text = file_path.read_text(encoding="utf-8")
        return json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("파라미터 파일 읽기 실패: %s (%s)", file_path, exc)
        return {}


def _write_json(file_path: Path, data: dict) -> None:
    """dict를 JSON 파일에 원자적으로 저장한다.

    임시 파일에 먼저 쓰고 rename하여, 쓰기 도중 프로세스가 죽어도
    반쪽짜리 파일이 남지 않도록 한다.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    # 같은 디렉토리에 임시 파일을 생성해야 rename이 원자적이다
    tmp_fd = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=file_path.parent,
        suffix=".tmp", delete=False,
    )
    try:
        tmp_fd.write(text)
        tmp_fd.flush()
        tmp_fd.close()
        Path(tmp_fd.name).replace(file_path)
    except Exception:
        Path(tmp_fd.name).unlink(missing_ok=True)
        raise


def _merge_params(existing: dict, updates: dict) -> dict:
    """기존 파라미터에 업데이트를 병합한다."""
    merged = {**existing, **updates}
    return merged


class StrategyParamsManager:
    """strategy_params.json 읽기/쓰기 관리자이다."""

    def __init__(self, params_file_path: str | None = None) -> None:
        """파일 경로를 지정한다. None이면 기본 경로를 사용한다."""
        self._path = Path(params_file_path) if params_file_path else _default_path()

    def load(self) -> StrategyParams:
        """파일에서 전략 파라미터를 로드한다. 없으면 기본값을 반환한다."""
        raw = _read_json(self._path)
        try:
            params = StrategyParams(**raw)
            logger.info("전략 파라미터 로드 완료: %s", self._path)
        except Exception as exc:
            logger.warning("파라미터 파싱 실패 (기본값 사용): %s", exc)
            params = StrategyParams()
        return params

    def save(self, params: StrategyParams) -> None:
        """전략 파라미터를 파일에 저장한다."""
        data = params.model_dump()
        _write_json(self._path, data)
        logger.info("전략 파라미터 저장 완료: %s", self._path)

    async def async_update(self, updates: dict) -> StrategyParams:
        """기존 파라미터에 부분 업데이트를 원자적으로 적용한다.

        asyncio.Lock으로 동시 파일 접근을 방지한다.
        EOD 파라미터 조정과 API 엔드포인트가 동시에 호출할 수 있다.
        """
        async with _get_file_lock():
            return self.update(updates)

    def update(self, updates: dict) -> StrategyParams:
        """기존 파라미터에 부분 업데이트를 적용한다.

        동기 컨텍스트에서 호출된다. 비동기 컨텍스트에서는 async_update()를 사용한다.
        """
        existing = _read_json(self._path)
        merged = _merge_params(existing, updates)
        try:
            params = StrategyParams(**merged)
        except Exception as exc:
            logger.error("파라미터 병합 실패: %s", exc)
            params = self.load()
            return params
        self.save(params)
        logger.info("전략 파라미터 업데이트 완료: %d개 항목", len(updates))
        return params

    def get_path(self) -> str:
        """현재 파일 경로를 반환한다."""
        return str(self._path)
