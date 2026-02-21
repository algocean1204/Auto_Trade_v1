"""
공유 API 키 인증 모듈.

모든 모니터링 라우터가 임포트하여 사용하는 단일 verify_api_key 의존성을 제공한다.
api_server.py의 원본 구현을 그대로 유지하되, 순환 임포트 없이 분리된 모듈로 관리한다.
"""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.utils.config import get_settings

_http_bearer = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(_http_bearer),
) -> None:
    """Authorization: Bearer <API_SECRET_KEY> 헤더를 검증한다.

    API_SECRET_KEY가 설정된 경우에만 검증을 수행한다.
    설정되지 않은 경우(개발 환경) 모든 요청을 허용한다.

    Args:
        credentials: HTTPBearer에서 추출한 Bearer 토큰.

    Raises:
        HTTPException: 토큰이 없거나 올바르지 않은 경우 401을 반환한다.
    """
    settings = get_settings()
    secret_key = settings.api_secret_key
    if not secret_key:
        # API_SECRET_KEY 미설정: 인증 비활성화 (개발 환경)
        return
    if credentials is None or credentials.credentials != secret_key:
        raise HTTPException(
            status_code=401,
            detail="유효하지 않은 API 키입니다. Authorization: Bearer <API_SECRET_KEY> 헤더를 확인하세요.",
        )
