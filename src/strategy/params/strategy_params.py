"""F4 전략 파라미터 관리자 -- strategy_params.json을 읽고 쓴다."""
from __future__ import annotations

import json
from pathlib import Path

from src.common.logger import get_logger
from src.strategy.models import StrategyParams

logger = get_logger(__name__)

# 기본 파일 경로
_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "strategy_params.json"


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
    """dict를 JSON 파일에 저장한다."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    file_path.write_text(text, encoding="utf-8")


def _merge_params(existing: dict, updates: dict) -> dict:
    """기존 파라미터에 업데이트를 병합한다."""
    merged = {**existing, **updates}
    return merged


class StrategyParamsManager:
    """strategy_params.json 읽기/쓰기 관리자이다."""

    def __init__(self, params_file_path: str | None = None) -> None:
        """파일 경로를 지정한다. None이면 기본 경로를 사용한다."""
        self._path = Path(params_file_path) if params_file_path else _DEFAULT_PATH

    def load(self) -> StrategyParams:
        """파일에서 전략 파라미터를 로드한다. 없으면 기본값을 반환한다."""
        raw = _read_json(self._path)
        try:
            params = StrategyParams(**raw)
        except Exception as exc:
            logger.error("파라미터 파싱 실패 (기본값 사용): %s", exc)
            params = StrategyParams()
        logger.info("전략 파라미터 로드 완료: %s", self._path)
        return params

    def save(self, params: StrategyParams) -> None:
        """전략 파라미터를 파일에 저장한다."""
        data = params.model_dump()
        _write_json(self._path, data)
        logger.info("전략 파라미터 저장 완료: %s", self._path)

    def update(self, updates: dict) -> StrategyParams:
        """기존 파라미터에 부분 업데이트를 적용한다."""
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
