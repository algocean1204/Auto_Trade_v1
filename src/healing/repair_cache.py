"""수리 학습 캐시 -- 성공한 수리를 기록하고 재활용한다.

동일 에러가 재발하면 캐시된 수리를 먼저 시도하여 Opus 호출을 절약한다.
3회 이상 성공한 수리는 "검증됨"으로 승격하여 Opus 검증도 건너뛴다.
Sticky Fix: 수리된 파일에 cooldown을 적용하여 롤백 루프를 방지한다.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_data_dir

logger: logging.Logger = get_logger(__name__)

_CACHE_FILENAME: str = "repair_history.json"

# 검증됨 승격 기준 (성공 횟수)
_VERIFIED_THRESHOLD: int = 3

# Sticky Fix cooldown (초) — 수리 후 3세션(~24시간) 동안 재수리 차단
_STICKY_COOLDOWN_SECONDS: int = 86400

# 같은 파일 최대 롤백 횟수
_MAX_ROLLBACKS_PER_FILE: int = 1


def _cache_path() -> Path:
    """캐시 파일 경로를 반환한다."""
    return get_data_dir() / _CACHE_FILENAME


def _load_cache() -> dict:
    """캐시 파일을 읽는다. 없으면 빈 구조를 반환한다."""
    path = _cache_path()
    if not path.exists():
        return {"repairs": {}, "sticky": {}, "rollbacks": {}}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        # 하위 호환 — 필드가 없으면 추가한다
        data.setdefault("repairs", {})
        data.setdefault("sticky", {})
        data.setdefault("rollbacks", {})
        return data
    except Exception as exc:
        logger.warning("수리 캐시 읽기 실패 (초기화): %s", exc)
        return {"repairs": {}, "sticky": {}, "rollbacks": {}}


def _save_cache(data: dict) -> None:
    """캐시를 파일에 저장한다."""
    path = _cache_path()
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _patch_hash(patch_text: str) -> str:
    """패치 텍스트의 짧은 해시를 반환한다."""
    return hashlib.sha256(patch_text.encode()).hexdigest()[:12]


class RepairCache:
    """수리 학습 캐시이다. 성공 수리를 기록하고 재활용한다."""

    def __init__(self) -> None:
        self._data = _load_cache()

    def lookup(self, error_type: str) -> dict | None:
        """캐시에서 에러 유형에 대한 기존 수리를 조회한다."""
        return self._data["repairs"].get(error_type)

    def is_verified(self, error_type: str) -> bool:
        """해당 에러의 수리가 검증됨(3회 이상 성공) 상태인지 확인한다."""
        entry = self.lookup(error_type)
        if entry is None:
            return False
        return entry.get("success_count", 0) >= _VERIFIED_THRESHOLD

    def record_success(
        self, error_type: str, file_path: str, patch_summary: str,
    ) -> None:
        """수리 성공을 기록한다. 기존 항목이 있으면 카운트를 증가시킨다."""
        repairs = self._data["repairs"]
        existing = repairs.get(error_type)
        if existing and existing.get("file_path") == file_path:
            existing["success_count"] = existing.get("success_count", 0) + 1
            existing["last_success"] = datetime.now(tz=timezone.utc).isoformat()
        else:
            repairs[error_type] = {
                "file_path": file_path,
                "patch_hash": _patch_hash(patch_summary),
                "patch_summary": patch_summary[:500],
                "success_count": 1,
                "last_success": datetime.now(tz=timezone.utc).isoformat(),
            }
        self._save()
        logger.info(
            "수리 캐시 기록: %s → %s (count=%d)",
            error_type, file_path,
            repairs[error_type]["success_count"],
        )

    def record_failure(self, error_type: str) -> None:
        """수리 실패를 기록한다. 성공 카운트를 1 감소시킨다."""
        entry = self._data["repairs"].get(error_type)
        if entry:
            entry["success_count"] = max(0, entry.get("success_count", 0) - 1)
            self._save()

    # ── Sticky Fix ──

    def set_sticky(self, file_path: str) -> None:
        """수리된 파일에 cooldown을 설정한다."""
        self._data["sticky"][file_path] = datetime.now(tz=timezone.utc).isoformat()
        self._save()
        logger.info("Sticky Fix 설정: %s", file_path)

    def is_sticky(self, file_path: str) -> bool:
        """파일이 cooldown 기간 내인지 확인한다."""
        ts_str = self._data["sticky"].get(file_path)
        if ts_str is None:
            return False
        ts = datetime.fromisoformat(ts_str)
        elapsed = (datetime.now(tz=timezone.utc) - ts).total_seconds()
        return elapsed < _STICKY_COOLDOWN_SECONDS

    # ── 롤백 제한 ──

    def record_rollback(self, file_path: str) -> None:
        """파일의 롤백 횟수를 기록한다."""
        rollbacks = self._data["rollbacks"]
        rollbacks[file_path] = rollbacks.get(file_path, 0) + 1
        self._save()

    def can_rollback(self, file_path: str) -> bool:
        """파일의 롤백이 허용되는지 확인한다."""
        count = self._data["rollbacks"].get(file_path, 0)
        return count < _MAX_ROLLBACKS_PER_FILE

    # ── 상태 조회 ──

    def get_status(self) -> dict:
        """캐시 상태 요약을 반환한다."""
        repairs = self._data["repairs"]
        return {
            "total_cached": len(repairs),
            "verified_count": sum(
                1 for r in repairs.values()
                if r.get("success_count", 0) >= _VERIFIED_THRESHOLD
            ),
            "sticky_files": len(self._data["sticky"]),
            "rollback_counts": dict(self._data["rollbacks"]),
        }

    def reset(self) -> None:
        """세션 초기화 — sticky와 rollback만 리셋한다. 학습 캐시는 유지한다."""
        self._data["sticky"].clear()
        self._data["rollbacks"].clear()
        self._save()

    def _save(self) -> None:
        """내부 저장 헬퍼이다."""
        _save_cache(self._data)
