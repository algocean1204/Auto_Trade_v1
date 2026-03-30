"""F7.2 Auth -- API 인증 미들웨어이다.

Bearer 토큰을 검증하여 인가된 요청만 허용한다.
API_SECRET_KEY가 반드시 설정되어야 한다. 미설정 시 서버 시작은 되지만 인증을 거부한다.
setup_mode에서는 API_SECRET_KEY 미설정 시 인증을 건너뛴다 (첫 설치 위저드용).
"""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.common.logger import get_logger
from src.common.secret_vault import get_vault

_logger = get_logger(__name__)

_security = HTTPBearer(auto_error=False)

# 서버 시작 시 API_SECRET_KEY 미설정 경고를 1회만 출력한다
_warned_no_key = False

# setup_mode 플래그 — True이면 API_SECRET_KEY 미설정 시 인증을 건너뛴다
_setup_mode: bool = False


def set_auth_setup_mode(enabled: bool) -> None:
    """setup_mode 플래그를 설정한다. api_server.py에서 호출한다."""
    global _setup_mode
    _setup_mode = enabled


def is_setup_mode() -> bool:
    """현재 setup_mode 여부를 반환한다."""
    return _setup_mode


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> str:
    """API 키를 검증한다. API_SECRET_KEY 필수이다.

    setup_mode에서 API_SECRET_KEY가 미설정이면 인증을 건너뛴다.
    첫 설치 위저드에서 .env가 없는 상태에서도 설정 저장/검증이 가능하도록 한다.

    Returns:
        검증된 토큰 문자열이다.

    Raises:
        HTTPException: 인증 실패 시 401을 반환한다.
    """
    global _warned_no_key
    vault = get_vault()
    secret = vault.get_secret_or_none("API_SECRET_KEY")

    if secret is None:
        if _setup_mode:
            # 첫 설치: API_SECRET_KEY가 아직 없으므로 인증을 건너뛴다
            return ""
        if not _warned_no_key:
            _logger.warning(
                "API_SECRET_KEY 미설정 — 모든 인증 요청이 거부된다. "
                ".env에 API_SECRET_KEY를 설정하라"
            )
            _warned_no_key = True
        raise HTTPException(
            status_code=401,
            detail="API_SECRET_KEY가 설정되지 않았다. .env를 확인하라",
        )

    if credentials is None:
        _logger.warning("인증 헤더 누락")
        raise HTTPException(status_code=401, detail="인증 헤더가 필요하다")

    # 타이밍 공격 방지를 위해 상수 시간 비교를 사용한다
    if not hmac.compare_digest(credentials.credentials, secret):
        _logger.warning("잘못된 API 키 시도")
        raise HTTPException(status_code=401, detail="유효하지 않은 API 키이다")

    return credentials.credentials
