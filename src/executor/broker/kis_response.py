"""KIS Response (F5.1 helper) -- KIS API 응답 검증과 파싱 유틸리티이다.

KIS OpenAPI의 공통 응답 구조(rt_cd, msg_cd, msg1)를 처리한다.
"""
from __future__ import annotations

from src.common.broker_gateway import KisAuth
from src.common.error_handler import BrokerError
from src.common.http_client import HttpResponse
from src.common.logger import get_logger

_logger = get_logger(__name__)


def check_response(resp: HttpResponse, context: str) -> dict:
    """KIS API 응답을 검증하고 JSON dict를 반환한다.

    HTTP 에러 또는 rt_cd != "0"이면 BrokerError를 발생시킨다.
    """
    if not resp.ok:
        detail = f"status={resp.status}, body={resp.body[:500]}"
        _logger.error("KIS HTTP 에러 [%s]: %s", context, detail)
        raise BrokerError(
            message=f"KIS API HTTP 에러: {context}",
            detail=detail,
        )
    data = resp.json()
    rt_cd = data.get("rt_cd", "")
    if rt_cd != "0":
        msg_cd = data.get("msg_cd", "")
        msg1 = data.get("msg1", "")
        detail = f"rt_cd={rt_cd}, msg_cd={msg_cd}, msg={msg1}"
        _logger.error("KIS 비즈니스 에러 [%s]: %s", context, detail)
        raise BrokerError(
            message=f"KIS API 실패: {context}",
            detail=detail,
        )
    return data


def build_url(auth: KisAuth, path: str) -> str:
    """인증 객체의 base_url과 경로를 결합한다."""
    return f"{auth._base_url}{path}"


def account_parts(auth: KisAuth) -> tuple[str, str]:
    """계좌번호를 CANO(8자리)와 ACNT_PRDT_CD(2자리)로 분리한다."""
    parts = auth._account.split("-")
    return parts[0], parts[1] if len(parts) > 1 else "01"


def safe_float(value: str | None, default: float = 0.0) -> float:
    """문자열을 float으로 안전 변환한다. None이나 빈 문자열이면 기본값을 반환한다."""
    if not value:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: str | None, default: int = 0) -> int:
    """문자열을 int로 안전 변환한다. None이나 빈 문자열이면 기본값을 반환한다."""
    if not value:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
