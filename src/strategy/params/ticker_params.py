"""F4 티커별 파라미터 -- 개별 티커의 커스텀 파라미터를 관리한다."""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_data_dir

logger = get_logger(__name__)

# 파일 쓰기 경합 방지용 Lock — 모듈 레벨 싱글톤이다
_ticker_file_lock: asyncio.Lock | None = None


def _get_ticker_file_lock() -> asyncio.Lock:
    """파일 Lock을 lazy 초기화한다."""
    global _ticker_file_lock
    if _ticker_file_lock is None:
        _ticker_file_lock = asyncio.Lock()
    return _ticker_file_lock

# 기본 파일 경로 -- get_data_dir()은 호출 시점에 평가해야 하므로 함수로 감싼다
def _default_path() -> Path:
    """기본 ticker_params.json 경로를 반환한다."""
    return get_data_dir() / "ticker_params.json"

# 티커별 기본값
_DEFAULTS: dict[str, dict] = {
    "SOXL": {"atr_multiplier": 2.0, "stop_distance_pct": 2.0, "position_size_pct": 5.0, "exchange": "AMS"},
    "SOXS": {"atr_multiplier": 2.0, "stop_distance_pct": 2.0, "position_size_pct": 5.0, "exchange": "AMS"},
    "QLD":  {"atr_multiplier": 1.8, "stop_distance_pct": 1.8, "position_size_pct": 5.0, "exchange": "AMS"},
    "QID":  {"atr_multiplier": 1.8, "stop_distance_pct": 1.8, "position_size_pct": 5.0, "exchange": "AMS"},
    "SSO":  {"atr_multiplier": 1.5, "stop_distance_pct": 1.5, "position_size_pct": 5.0, "exchange": "AMS"},
    "SDS":  {"atr_multiplier": 1.5, "stop_distance_pct": 1.5, "position_size_pct": 5.0, "exchange": "AMS"},
    "UWM":  {"atr_multiplier": 2.2, "stop_distance_pct": 2.2, "position_size_pct": 4.0, "exchange": "AMS"},
    "TWM":  {"atr_multiplier": 2.2, "stop_distance_pct": 2.2, "position_size_pct": 4.0, "exchange": "AMS"},
    "DDM":  {"atr_multiplier": 1.5, "stop_distance_pct": 1.5, "position_size_pct": 5.0, "exchange": "AMS"},
    "DXD":  {"atr_multiplier": 1.5, "stop_distance_pct": 1.5, "position_size_pct": 5.0, "exchange": "AMS"},
    "NVDL": {"atr_multiplier": 2.5, "stop_distance_pct": 2.5, "position_size_pct": 4.0, "exchange": "NAS"},
    "NVDS": {"atr_multiplier": 2.5, "stop_distance_pct": 2.5, "position_size_pct": 4.0, "exchange": "NAS"},
}

# 글로벌 기본값 (등록되지 않은 티커용)
_GLOBAL_DEFAULT: dict = {
    "atr_multiplier": 2.0,
    "stop_distance_pct": 2.0,
    "position_size_pct": 5.0,
    "exchange": "NAS",
}


def _read_file(path: Path) -> dict:
    """JSON 파일을 읽는다. 없으면 빈 dict를 반환한다."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("티커 파라미터 파일 읽기 실패: %s", exc)
        return {}


def _write_file(path: Path, data: dict) -> None:
    """dict를 JSON 파일에 원자적으로 저장한다.

    임시 파일에 먼저 쓰고 rename하여 반쪽짜리 파일을 방지한다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    tmp_fd = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        suffix=".tmp", delete=False,
    )
    try:
        tmp_fd.write(text)
        tmp_fd.flush()
        tmp_fd.close()
        Path(tmp_fd.name).replace(path)
    except Exception:
        Path(tmp_fd.name).unlink(missing_ok=True)
        raise


class TickerParams:
    """티커별 개별 파라미터를 관리한다."""

    def __init__(self, params_file_path: str | None = None) -> None:
        """파일 경로를 지정한다. None이면 기본 경로를 사용한다."""
        self._path = Path(params_file_path) if params_file_path else _default_path()
        self._cache: dict[str, dict] = {}
        self._load_all()

    def _load_all(self) -> None:
        """파일과 기본값을 병합하여 캐시에 로드한다."""
        file_data = _read_file(self._path)
        # 기본값 우선, 파일 값으로 덮어쓴다
        for ticker, defaults in _DEFAULTS.items():
            merged = {**defaults, **file_data.get(ticker, {})}
            self._cache[ticker] = merged
        # 파일에만 있는 티커 추가
        for ticker, params in file_data.items():
            if ticker not in self._cache:
                self._cache[ticker] = {**_GLOBAL_DEFAULT, **params}

    def get(self, ticker: str) -> dict:
        """티커별 파라미터를 반환한다. 미등록 티커는 글로벌 기본값을 반환한다."""
        return self._cache.get(ticker, {**_GLOBAL_DEFAULT})

    def update(self, ticker: str, updates: dict) -> dict:
        """티커 파라미터를 부분 업데이트한다."""
        current = self.get(ticker)
        merged = {**current, **updates}
        self._cache[ticker] = merged
        self._save_all()
        logger.info("티커 파라미터 업데이트: %s %s", ticker, list(updates.keys()))
        return merged

    async def async_update(self, ticker: str, updates: dict) -> dict:
        """비동기 컨텍스트에서 티커 파라미터를 부분 업데이트한다.

        asyncio.Lock으로 동시 파일 접근을 방지한다.
        """
        async with _get_ticker_file_lock():
            return self.update(ticker, updates)

    def _save_all(self) -> None:
        """전체 캐시를 파일에 저장한다."""
        _write_file(self._path, self._cache)

    def get_all(self) -> dict[str, dict]:
        """전체 티커 파라미터를 반환한다."""
        return dict(self._cache)

    def get_atr_multiplier(self, ticker: str) -> float:
        """티커의 ATR 배수를 반환한다."""
        return self.get(ticker).get("atr_multiplier", 2.0)

    def get_stop_distance(self, ticker: str) -> float:
        """티커의 스톱 거리(%)를 반환한다."""
        return self.get(ticker).get("stop_distance_pct", 2.0)

    def get_position_size(self, ticker: str) -> float:
        """티커의 포지션 크기(%)를 반환한다."""
        return self.get(ticker).get("position_size_pct", 5.0)
