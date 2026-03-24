"""StockTrader 완전 삭제를 수행한다.

LaunchAgent, Application Support, 로그, 환경설정 등
설치된 모든 리소스를 정리한다.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 삭제 대상 경로를 정의한다 (macOS 전용 기능이다)
_BUNDLE_ID: str = "com.stocktrader"
_LAUNCH_AGENTS_DIR: Path = Path.home() / "Library" / "LaunchAgents"
_APP_SUPPORT_DIR: Path = Path.home() / "Library" / "Application Support" / f"{_BUNDLE_ID}.ai"
_LOG_DIR: Path = Path.home() / "Library" / "Logs" / "trading"
_PREFERENCES_DIR: Path = Path.home() / "Library" / "Preferences"
# 참고: 이 모듈은 macOS 전용이다. ~/Library/ 경로는 macOS에서만 존재한다.

# LaunchAgent plist 파일 목록이다
_PLIST_FILES: list[str] = [
    f"{_BUNDLE_ID}.server.plist",
    f"{_BUNDLE_ID}.autotrader.plist",
    "com.trading.server.plist",
    "com.trading.autotrader.plist",
]

# 환경설정 파일 패턴이다
_PREFERENCES_PATTERNS: list[str] = [
    f"{_BUNDLE_ID}.ai.plist",
    f"{_BUNDLE_ID}.server.plist",
]


class Uninstaller:
    """StockTrader 완전 삭제를 수행한다."""

    def get_uninstall_items(self) -> list[dict]:
        """삭제될 항목 목록을 반환한다.

        각 항목은 경로, 유형, 존재 여부, 크기 정보를 포함한다.

        Returns:
            삭제 대상 항목 딕셔너리 리스트이다.
        """
        items: list[dict] = []

        # 1. LaunchAgent plist 파일을 확인한다
        for plist_name in _PLIST_FILES:
            plist_path = _LAUNCH_AGENTS_DIR / plist_name
            items.append({
                "path": str(plist_path),
                "type": "launchagent",
                "description": f"LaunchAgent: {plist_name}",
                "exists": plist_path.exists(),
                "size_bytes": plist_path.stat().st_size if plist_path.exists() else 0,
                "deletable": True,
            })

        # 2. Application Support 디렉토리를 확인한다
        if _APP_SUPPORT_DIR.exists():
            total_size = self._dir_size(_APP_SUPPORT_DIR)
            items.append({
                "path": str(_APP_SUPPORT_DIR),
                "type": "data",
                "description": "앱 데이터 (DB, 모델, 설정)",
                "exists": True,
                "size_bytes": total_size,
                "deletable": True,
            })

            # 하위 항목을 개별 표시한다
            for subdir in sorted(_APP_SUPPORT_DIR.iterdir()):
                sub_size = (
                    self._dir_size(subdir) if subdir.is_dir()
                    else subdir.stat().st_size
                )
                items.append({
                    "path": str(subdir),
                    "type": "data_sub",
                    "description": f"  - {subdir.name}",
                    "exists": True,
                    "size_bytes": sub_size,
                    "deletable": True,
                })

        # 3. 로그 디렉토리를 확인한다
        if _LOG_DIR.exists():
            log_size = self._dir_size(_LOG_DIR)
            items.append({
                "path": str(_LOG_DIR),
                "type": "logs",
                "description": "서버 로그",
                "exists": True,
                "size_bytes": log_size,
                "deletable": True,
            })

        # 4. 환경설정 파일을 확인한다
        for pref_name in _PREFERENCES_PATTERNS:
            pref_path = _PREFERENCES_DIR / pref_name
            if pref_path.exists():
                items.append({
                    "path": str(pref_path),
                    "type": "preferences",
                    "description": f"환경설정: {pref_name}",
                    "exists": True,
                    "size_bytes": pref_path.stat().st_size,
                    "deletable": True,
                })

        return items

    async def uninstall(self, keep_data: bool = False) -> dict:
        """완전 삭제를 수행한다.

        Args:
            keep_data: True이면 DB와 .env 파일을 보존한다.

        Returns:
            삭제 결과 딕셔너리이다.
        """
        try:
            results: list[dict] = []

            # 1. LaunchAgent를 언로드하고 plist를 삭제한다
            for plist_name in _PLIST_FILES:
                plist_path = _LAUNCH_AGENTS_DIR / plist_name
                label = plist_name.replace(".plist", "")

                # 로드된 에이전트를 언로드한다
                self._unload_agent(label, plist_path)

                if plist_path.exists():
                    plist_path.unlink()
                    results.append({
                        "path": str(plist_path),
                        "action": "deleted",
                        "success": True,
                    })

            # 2. Application Support를 삭제한다
            if _APP_SUPPORT_DIR.exists():
                if keep_data:
                    # DB와 .env를 보존하고 나머지를 삭제한다
                    preserved = self._delete_except_data(_APP_SUPPORT_DIR)
                    results.append({
                        "path": str(_APP_SUPPORT_DIR),
                        "action": "partial_delete",
                        "success": True,
                        "preserved": preserved,
                    })
                else:
                    shutil.rmtree(_APP_SUPPORT_DIR, ignore_errors=True)
                    results.append({
                        "path": str(_APP_SUPPORT_DIR),
                        "action": "deleted",
                        "success": not _APP_SUPPORT_DIR.exists(),
                    })

            # 3. 로그를 삭제한다
            if _LOG_DIR.exists():
                shutil.rmtree(_LOG_DIR, ignore_errors=True)
                results.append({
                    "path": str(_LOG_DIR),
                    "action": "deleted",
                    "success": not _LOG_DIR.exists(),
                })

            # 4. 환경설정을 삭제한다
            for pref_name in _PREFERENCES_PATTERNS:
                pref_path = _PREFERENCES_DIR / pref_name
                if pref_path.exists():
                    pref_path.unlink()
                    results.append({
                        "path": str(pref_path),
                        "action": "deleted",
                        "success": True,
                    })

            deleted_count = sum(1 for r in results if r["success"])
            total_count = len(results)

            logger.info(
                "삭제 완료: %d/%d 항목 (keep_data=%s)",
                deleted_count, total_count, keep_data,
            )

            return {
                "success": True,
                "message": f"삭제 완료: {deleted_count}/{total_count} 항목",
                "keep_data": keep_data,
                "results": results,
            }
        except Exception as exc:
            logger.exception("삭제 실행 중 오류 발생")
            return {
                "success": False,
                "message": f"삭제 실패: {exc}",
                "keep_data": keep_data,
                "results": [],
            }

    # ── 내부 헬퍼 ────────────────────────────────────────

    def _dir_size(self, path: Path) -> int:
        """디렉토리의 전체 크기를 바이트 단위로 계산한다."""
        total = 0
        try:
            for entry in path.rglob("*"):
                if entry.is_file():
                    total += entry.stat().st_size
        except PermissionError:
            logger.warning("디렉토리 크기 계산 중 권한 오류: %s", path)
        return total

    def _unload_agent(self, label: str, plist_path: Path) -> None:
        """LaunchAgent를 안전하게 언로드한다."""
        try:
            import subprocess

            result = subprocess.run(
                ["launchctl", "list", label],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                subprocess.run(
                    ["launchctl", "unload", str(plist_path)],
                    capture_output=True,
                    timeout=5,
                )
                logger.info("LaunchAgent 언로드: %s", label)
        except Exception:
            logger.debug("LaunchAgent 언로드 건너뜀: %s", label)

    def _delete_except_data(self, app_dir: Path) -> list[str]:
        """DB 파일과 .env를 제외하고 삭제한다.

        Returns:
            보존된 파일 경로 목록이다.
        """
        preserved: list[str] = []
        preserve_names = {".env", "trading.db", "trading.db-wal", "trading.db-shm"}

        for item in list(app_dir.iterdir()):
            if item.name in preserve_names:
                preserved.append(str(item))
                continue

            if item.name == "data" and item.is_dir():
                # data 디렉토리 내 DB 파일을 보존한다
                for data_item in list(item.iterdir()):
                    if data_item.name in preserve_names or data_item.suffix == ".db":
                        preserved.append(str(data_item))
                    else:
                        if data_item.is_dir():
                            shutil.rmtree(data_item, ignore_errors=True)
                        else:
                            data_item.unlink(missing_ok=True)
                continue

            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)

        return preserved
