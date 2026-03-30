"""Tier2 설정 조정 -- strategy_params.json 임계값을 완화하여 매매 재개를 시도한다.

Level 1(완만)과 Level 2(공격적) 두 단계로 진입 조건을 완화한다.
세션 종료(EOD) 시 반드시 restore_thresholds()로 원래 값을 복원해야 한다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_data_dir
from src.healing.error_classifier import ErrorEvent, RepairResult, RepairTier

logger: logging.Logger = get_logger(__name__)

# 임계값 완화 테이블 — (level1, level2) 순서이다
_RELAXATION_MAP: dict[str, tuple[float, float]] = {
    "beast_min_confidence": (0.5, 0.3),
    "obi_threshold": (0.05, 0.02),
    "ml_threshold": (0.15, 0.1),
    "friction_hurdle": (0.5, 0.3),
}


def _params_path() -> Path:
    """strategy_params.json 경로를 반환한다."""
    return get_data_dir() / "strategy_params.json"


def _backup_path() -> Path:
    """백업 파일 경로를 반환한다."""
    return get_data_dir() / "strategy_params_backup.json"


def _read_json(path: Path) -> dict:
    """JSON 파일을 읽는다. 기존 strategy_params.py와 동일한 동기 패턴을 따른다."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("JSON 읽기 실패: %s (%s)", path, exc)
        return {}


def _write_json(path: Path, data: dict) -> None:
    """dict를 JSON 파일에 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    path.write_text(text, encoding="utf-8")


async def attempt_tier2(event: ErrorEvent, level: int = 1) -> RepairResult:
    """Tier2 설정 조정을 시도한다. 에러 유형에 따라 진입 임계값을 완화한다."""
    return await relax_entry_thresholds(level=level)


async def relax_entry_thresholds(level: int = 1) -> RepairResult:
    """진입 임계값을 완화한다. level=1(완만), level=2(공격적)."""
    try:
        params = _read_json(_params_path())
        if not params:
            return RepairResult(success=False, tier=RepairTier.TIER2, action="임계값 완화", detail="파라미터 파일 없음")

        # 최초 완화 시에만 원본 백업을 생성한다 (이미 백업 있으면 덮어쓰지 않는다)
        backup = _backup_path()
        if not backup.exists():
            _write_json(backup, params)
            logger.info("원본 파라미터 백업 완료: %s", backup)

        # level에 따라 임계값을 완화한다
        idx = min(level, 2) - 1  # 0 또는 1
        changed: list[str] = []
        for key, (v1, v2) in _RELAXATION_MAP.items():
            target = (v1, v2)[idx]
            if key in params:
                params[key] = target
                changed.append(f"{key}={target}")

        _write_json(_params_path(), params)
        detail = f"level={level}, {', '.join(changed)}"
        logger.info("임계값 완화 적용: %s", detail)
        return RepairResult(success=True, tier=RepairTier.TIER2, action="임계값 완화", detail=detail)
    except Exception as exc:
        logger.error("임계값 완화 실패: %s", exc)
        return RepairResult(success=False, tier=RepairTier.TIER2, action="임계값 완화", detail=str(exc))


async def restore_thresholds() -> RepairResult:
    """백업에서 원래 임계값을 복원한다. EOD에서 호출하여 세션 변경을 되돌린다."""
    try:
        backup = _backup_path()
        if not backup.exists():
            return RepairResult(success=True, tier=RepairTier.TIER2, action="임계값 복원", detail="백업 없음 (변경 없었음)")

        original = _read_json(backup)
        if not original:
            return RepairResult(success=False, tier=RepairTier.TIER2, action="임계값 복원", detail="백업 파일 비어있음")

        _write_json(_params_path(), original)
        backup.unlink(missing_ok=True)
        logger.info("원본 파라미터 복원 완료")
        return RepairResult(success=True, tier=RepairTier.TIER2, action="임계값 복원")
    except Exception as exc:
        logger.error("임계값 복원 실패: %s", exc)
        return RepairResult(success=False, tier=RepairTier.TIER2, action="임계값 복원", detail=str(exc))
