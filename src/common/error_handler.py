"""
ErrorHandler (C0.9) -- 예외를 표준 ErrorResponse로 변환하고 글로벌 에러 핸들링을 제공한다.

커스텀 예외 계층과 FastAPI exception_handler 등록을 담당한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# 표준 에러 응답 모델
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """표준 에러 응답이다. 모든 API 에러는 이 형식으로 반환한다."""

    error_code: str
    message: str
    detail: str | None = None
    timestamp: datetime


# ---------------------------------------------------------------------------
# 커스텀 예외 계층
# ---------------------------------------------------------------------------

class TradingError(Exception):
    """자동매매 시스템 기본 예외이다. 모든 도메인 예외의 최상위 부모이다."""

    def __init__(
        self,
        error_code: str,
        message: str,
        detail: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.detail = detail
        super().__init__(message)


class BrokerError(TradingError):
    """KIS 브로커 통신 관련 예외이다."""

    def __init__(
        self,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            error_code="BROKER_ERROR",
            message=message,
            detail=detail,
        )


class AiError(TradingError):
    """AI 분석/추론 관련 예외이다."""

    def __init__(
        self,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            error_code="AI_ERROR",
            message=message,
            detail=detail,
        )


class DataError(TradingError):
    """데이터 수집/파싱/저장 관련 예외이다."""

    def __init__(
        self,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            error_code="DATA_ERROR",
            message=message,
            detail=detail,
        )


class SafetyError(TradingError):
    """안전장치 위반 예외이다. 거래를 즉시 중단해야 한다."""

    def __init__(
        self,
        message: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(
            error_code="SAFETY_ERROR",
            message=message,
            detail=detail,
        )


# ---------------------------------------------------------------------------
# 변환 함수
# ---------------------------------------------------------------------------

def to_error_response(exc: Exception) -> ErrorResponse:
    """예외를 표준 ErrorResponse로 변환한다.

    TradingError 계열은 내부 정보를 그대로 사용하고,
    알 수 없는 예외는 UNKNOWN_ERROR로 래핑한다.
    """
    now = datetime.now(tz=timezone.utc)

    if isinstance(exc, TradingError):
        return ErrorResponse(
            error_code=exc.error_code,
            message=exc.message,
            detail=exc.detail,
            timestamp=now,
        )

    # 예상치 못한 예외는 내부 정보 노출을 최소화한다
    # str(exc)는 파일 경로/DB URL 등 민감 정보를 포함할 수 있어 응답에 노출하지 않는다
    return ErrorResponse(
        error_code="UNKNOWN_ERROR",
        message="알 수 없는 오류가 발생했다",
        detail=None,
        timestamp=now,
    )


def _get_status_code(exc: TradingError) -> int:
    """예외 타입에 따른 HTTP 상태 코드를 반환한다."""
    status_map: dict[str, int] = {
        "BROKER_ERROR": 502,
        "AI_ERROR": 503,
        "DATA_ERROR": 422,
        "SAFETY_ERROR": 409,
    }
    return status_map.get(exc.error_code, 500)


def register_exception_handlers(app: Any) -> None:
    """FastAPI 앱에 글로벌 예외 핸들러를 등록한다.

    FastAPI를 직접 import하지 않고, app 객체의 메서드를 동적으로 호출한다.
    이렇게 하면 FastAPI가 설치되지 않은 환경에서도 모듈 로드가 가능하다.
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    add_handler = getattr(app, "exception_handler", None)
    if add_handler is None:
        return

    @add_handler(TradingError)
    async def _handle_trading_error(
        request: Request,
        exc: TradingError,
    ) -> JSONResponse:
        """TradingError 계열 예외를 표준 JSON으로 응답한다."""
        response = to_error_response(exc)
        return JSONResponse(
            status_code=_get_status_code(exc),
            content=response.model_dump(mode="json"),
        )

    @add_handler(Exception)
    async def _handle_unknown_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """처리되지 않은 예외를 500 에러로 응답한다."""
        response = to_error_response(exc)
        return JSONResponse(
            status_code=500,
            content=response.model_dump(mode="json"),
        )
