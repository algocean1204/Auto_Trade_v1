"""앱 업데이트를 확인한다.

원격 version.json을 조회하여 새 버전 존재 여부를 판단한다.
version.json 형식: {"version": "1.2.3", "url": "https://...", "notes": "..."}
"""
from __future__ import annotations

import logging
from importlib.metadata import version as pkg_version

from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)

# 업데이트 확인 URL 기본값이다
# .env의 UPDATE_CHECK_URL이 있으면 우선 사용하고, 없으면 이 URL을 사용한다
_DEFAULT_UPDATE_URL: str = (
    "https://raw.githubusercontent.com/stocktrader-ai/releases/main/version.json"
)


def _resolve_update_url() -> str:
    """SecretVault에서 업데이트 URL을 결정한다. 미설정 시 기본값을 사용한다."""
    try:
        from src.common.secret_vault import get_vault
        vault = get_vault()
        url = vault.get_secret_or_none("UPDATE_CHECK_URL")
        if url and url.strip():
            return url.strip()
    except Exception as exc:
        logger.debug("SecretVault에서 UPDATE_CHECK_URL 조회 실패 (무시): %s", exc)

    return _DEFAULT_UPDATE_URL

# 현재 앱 버전 (pyproject.toml 또는 하드코딩 폴백)이다
_FALLBACK_VERSION: str = "1.0.0"


def _parse_version_tuple(version_str: str) -> tuple[int, ...]:
    """버전 문자열을 비교 가능한 정수 튜플로 변환한다.

    예: "1.2.3" -> (1, 2, 3)
    """
    parts: list[int] = []
    for part in version_str.strip().split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


class UpdateChecker:
    """앱 업데이트를 확인한다.

    웹사이트의 version.json을 확인하여 새 버전이 있으면 알린다.
    """

    def __init__(self, update_url: str | None = None) -> None:
        """업데이트 확인 URL을 설정한다.

        Args:
            update_url: version.json이 호스팅된 URL이다. None이면 기본값을 사용한다.
        """
        self._update_url: str = update_url or _resolve_update_url()

    async def check_for_updates(self, current_version: str) -> dict | None:
        """새 버전이 있으면 정보를 반환, 없으면 None이다.

        Args:
            current_version: 현재 설치된 앱 버전 문자열이다.

        Returns:
            새 버전 정보 딕셔너리 또는 None이다.
            {"version": "1.2.3", "url": "https://...", "notes": "..."}
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._update_url)
                response.raise_for_status()
                data = response.json()

            remote_version: str = data.get("version", "")
            if not remote_version:
                logger.warning("version.json에 version 필드가 없다")
                return None

            # 버전을 비교한다
            current_tuple = _parse_version_tuple(current_version)
            remote_tuple = _parse_version_tuple(remote_version)

            if remote_tuple > current_tuple:
                logger.info(
                    "새 버전 발견: %s -> %s", current_version, remote_version
                )
                return {
                    "version": remote_version,
                    "url": data.get("url", ""),
                    "notes": data.get("notes", ""),
                    "current_version": current_version,
                }

            logger.debug(
                "최신 버전 사용 중: %s (원격: %s)", current_version, remote_version
            )
            return None
        except ImportError:
            logger.warning("httpx 미설치 -- 업데이트 확인 불가")
            return None
        except Exception:
            logger.exception("업데이트 확인 중 오류 발생")
            return None

    def get_current_version(self) -> str:
        """현재 앱 버전을 반환한다.

        pyproject.toml의 패키지 버전을 먼저 시도하고,
        실패하면 하드코딩된 폴백 값을 사용한다.

        Returns:
            현재 버전 문자열이다.
        """
        try:
            return pkg_version("stock-trading")
        except Exception as exc:
            logger.debug("pkg_version 조회 실패 (무시): %s", exc)

        # 프로젝트 루트의 pyproject.toml에서 직접 읽기를 시도한다
        try:
            from src.common.paths import get_project_root

            pyproject = get_project_root() / "pyproject.toml"
            if pyproject.exists():
                content = pyproject.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.strip().startswith("version"):
                        # version = "1.0.0" 형태에서 추출한다
                        version_str = line.split("=", 1)[1].strip().strip('"').strip("'")
                        return version_str
        except Exception as exc:
            logger.debug("pyproject.toml 버전 파싱 실패 (무시): %s", exc)

        return _FALLBACK_VERSION
