"""
SecretVault (C0.1) -- .env 파일에서 시크릿을 로드하고 타입 안전한 접근을 제공한다.

모든 민감 정보의 유일한 접근 경로이다. 다른 모듈은 os.environ/os.getenv 대신
반드시 SecretProvider를 통해 시크릿에 접근해야 한다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

from dotenv import dotenv_values

_instance: SecretProvider | None = None

# 필수 키이다. DATABASE_URL은 미설정 시 SQLite 기본값을 자동 부여한다
_REQUIRED_KEYS: list[str] = ["TELEGRAM_BOT_TOKEN"]

# KIS 키 쌍 -- 최소 하나의 쌍이 존재해야 한다
_KIS_KEY_PAIRS: list[tuple[str, str]] = [
    ("KIS_VIRTUAL_APP_KEY", "KIS_VIRTUAL_APP_SECRET"),
    ("KIS_REAL_APP_KEY", "KIS_REAL_APP_SECRET"),
]

# SecretVault가 관리하는 전체 시크릿 키 목록이다 (23개)
# 캐시는 인메모리 구현을 사용한다 (외부 의존성 없음)
_MANAGED_KEYS: list[str] = [
    "KIS_VIRTUAL_APP_KEY", "KIS_VIRTUAL_APP_SECRET",
    "KIS_REAL_APP_KEY", "KIS_REAL_APP_SECRET",
    "KIS_VIRTUAL_ACCOUNT", "KIS_REAL_ACCOUNT", "KIS_ACCOUNT",
    "KIS_HTS_ID", "KIS_MODE",
    "DATABASE_URL",
    "ANTHROPIC_API_KEY", "CLAUDE_MODE",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "TELEGRAM_BOT_TOKEN_2", "TELEGRAM_CHAT_ID_2",
    "FINNHUB_API_KEY", "ALPHAVANTAGE_API_KEY", "FRED_API_KEY",
    "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
    "API_SECRET_KEY", "DART_API_KEY", "SEC_USER_AGENT", "TRADING_MODE",
]


def _mask_value(value: str) -> str:
    """시크릿 값의 앞 4자만 노출하고 나머지는 마스킹한다."""
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


def _build_composite_secrets(raw: dict[str, str | None]) -> dict[str, str | None]:
    """DATABASE_URL 기본값 부여를 수행한다.

    DATABASE_URL이 미설정이면 로컬 SQLite 경로를 기본값으로 설정한다.
    """
    # DATABASE_URL 미설정 시 SQLite 기본값을 사용한다
    if not raw.get("DATABASE_URL"):
        raw["DATABASE_URL"] = "sqlite+aiosqlite:///data/trading.db"

    return raw


def _merge_with_env(dotenv_dict: dict[str, str | None]) -> dict[str, str | None]:
    """dotenv 값과 환경변수를 병합한다. 환경변수가 우선한다.

    이 함수 내부에서만 os.environ 접근이 허용된다.
    """
    merged: dict[str, str | None] = dict(dotenv_dict)
    for key in _MANAGED_KEYS:
        env_val = os.environ.get(key)
        if env_val is not None:
            merged[key] = env_val
    return merged


class SecretProvider:
    """시크릿 제공자 -- 모든 민감 정보의 유일한 접근 경로이다."""

    _MANAGED_KEYS: ClassVar[list[str]] = _MANAGED_KEYS

    def __init__(self, secrets: dict[str, str]) -> None:
        """직접 생성하지 않는다. get_vault() 팩토리를 사용한다."""
        self._secrets: dict[str, str] = secrets

    def get_secret(self, key: str) -> str:
        """키에 해당하는 시크릿 값을 반환한다. 없으면 KeyError를 발생시킨다."""
        value = self._secrets.get(key)
        if value is None:
            raise KeyError(f"시크릿 키를 찾을 수 없다: {key}")
        return value

    def get_secret_or_none(self, key: str) -> str | None:
        """키에 해당하는 시크릿 값을 반환한다. 없으면 None을 반환한다."""
        return self._secrets.get(key)

    def has_secret(self, key: str) -> bool:
        """해당 키가 존재하는지 확인한다."""
        return key in self._secrets

    def mask(self, key: str) -> str:
        """로깅용으로 마스킹된 값을 반환한다."""
        value = self._secrets.get(key)
        if value is None:
            return "<NOT_SET>"
        return _mask_value(value)

    def list_loaded_keys(self) -> list[str]:
        """로드된 시크릿 키 목록을 반환한다 (값은 노출하지 않는다)."""
        return sorted(self._secrets.keys())


def _validate_required(secrets: dict[str, str]) -> None:
    """필수 키가 모두 존재하는지 검증한다. 누락 시 즉시 실패한다."""
    missing = [k for k in _REQUIRED_KEYS if k not in secrets]
    # CLAUDE_MODE=api이면 ANTHROPIC_API_KEY도 필수이다
    if secrets.get("CLAUDE_MODE", "local") == "api":
        if "ANTHROPIC_API_KEY" not in secrets:
            missing.append("ANTHROPIC_API_KEY")
    # KIS 키 쌍 중 최소 하나가 존재해야 한다
    has_kis = any(k in secrets and s in secrets for k, s in _KIS_KEY_PAIRS)
    if not has_kis:
        missing.append("KIS_*_APP_KEY/KIS_*_APP_SECRET (최소 1쌍)")
    if missing:
        raise EnvironmentError(
            f"필수 시크릿이 누락되었다: {', '.join(missing)}"
        )


def _load_secrets(env_file_path: str) -> dict[str, str]:
    """dotenv 파일을 파싱하여 유효한 시크릿 딕셔너리를 반환한다."""
    path = Path(env_file_path)
    if not path.exists():
        raise FileNotFoundError(f".env 파일을 찾을 수 없다: {env_file_path}")
    raw = dotenv_values(str(path))
    merged = _merge_with_env(raw)
    composited = _build_composite_secrets(merged)
    # None 값과 빈 문자열을 제거한다
    return {k: v for k, v in composited.items() if v is not None and v.strip()}


def get_vault(env_file_path: str | None = None) -> SecretProvider:
    """SecretProvider 싱글톤을 반환한다.

    최초 호출 시 .env 파일을 로드하고, 이후에는 캐싱된 인스턴스를 반환한다.
    """
    global _instance
    if _instance is not None:
        return _instance
    if env_file_path is None:
        env_file_path = str(
            Path(__file__).resolve().parent.parent.parent / ".env"
        )
    secrets = _load_secrets(env_file_path)
    _validate_required(secrets)
    _instance = SecretProvider(secrets)
    return _instance


def reset_vault() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
