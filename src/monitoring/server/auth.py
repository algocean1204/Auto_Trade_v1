"""F7.2 Auth -- API 인증 미들웨어이다.

Bearer 토큰을 검증하여 인가된 요청만 허용한다.
API_SECRET_KEY가 설정되지 않은 경우 개발 모드로 동작한다.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.common.logger import get_logger
from src.common.secret_vault import get_vault

_logger = get_logger(__name__)

_security = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> str:
    """API 키를 검증한다. API_SECRET_KEY가 없으면 인증을 비활성화한다.

    Returns:
        검증된 토큰 문자열. 개발 모드면 "dev-mode"을 반환한다.

    Raises:
        HTTPException: 인증 실패 시 401을 반환한다.
    """
    vault = get_vault()
    secret = vault.get_secret_or_none("API_SECRET_KEY")

    if secret is None:
        _logger.debug("API_SECRET_KEY 미설정 -- 개발 모드 인증 통과")
        return "dev-mode"

    if credentials is None:
        _logger.warning("인증 헤더 누락")
        raise HTTPException(status_code=401, detail="인증 헤더가 필요하다")

    if credentials.credentials != secret:
        _logger.warning("잘못된 API 키 시도")
        raise HTTPException(status_code=401, detail="유효하지 않은 API 키이다")

    return credentials.credentials
