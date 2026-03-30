"""에러 분류기 -- 예외를 RepairTier로 분류하고 ErrorEvent를 생성한다.

Tier1(운영 복구), Tier2(설정 조정), Tier3(AI 분석) 3단계로 구분한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum

from src.common.error_handler import BrokerError, DataError, TradingError
from src.common.logger import get_logger

logger: logging.Logger = get_logger(__name__)


class RepairTier(IntEnum):
    """복구 계층이다. 숫자가 클수록 비용이 높다."""

    TIER1 = 1    # 운영 복구 (프로세스/토큰/캐시/네트워크)
    TIER1_5 = 15  # 프롬프트 우회 (코드 변경 없이 설정/프롬프트 조정)
    TIER2 = 2    # 설정 조정 (strategy_params 임계값)
    TIER3 = 3    # AI 분석 + 제한적 코드 수리


@dataclass
class ErrorEvent:
    """분류 대상 에러 이벤트이다."""

    error_type: str
    message: str
    detail: str | None
    timestamp: datetime
    module: str
    tier: RepairTier = RepairTier.TIER3


@dataclass
class RepairResult:
    """복구 시도 결과이다."""

    success: bool
    tier: RepairTier
    action: str
    detail: str | None = None


# Tier1 패턴: 네트워크/토큰/캐시 관련 키워드
_TIER1_KEYWORDS: tuple[str, ...] = (
    "token", "인증", "만료", "port", "ECONNREFUSED", "refused",
)

# Tier1.5 패턴: AI 응답/프롬프트/파싱 관련 키워드
_TIER1_5_KEYWORDS: tuple[str, ...] = (
    "prompt", "프롬프트", "classify", "분류", "parse", "파싱",
    "json", "schema", "format", "validation", "응답",
)

# Tier2 패턴: 데이터 부족/임계값 관련 키워드
_TIER2_KEYWORDS: tuple[str, ...] = (
    "insufficient", "부족", "threshold", "임계", "zero trades", "0건",
)


def create_error_event(exc: Exception, module: str) -> ErrorEvent:
    """예외에서 ErrorEvent를 생성한다. TradingError 계열은 상세 정보를 추출한다."""
    msg = str(exc)
    detail: str | None = None
    if isinstance(exc, TradingError):
        msg = exc.message
        detail = exc.detail
    event = ErrorEvent(
        error_type=type(exc).__name__,
        message=msg,
        detail=detail,
        timestamp=datetime.now(tz=timezone.utc),
        module=module,
    )
    event.tier = classify_tier(event)
    return event


def classify_tier(event: ErrorEvent) -> RepairTier:
    """에러 이벤트의 복구 계층을 패턴 매칭으로 결정한다."""
    etype = event.error_type
    combined = f"{event.message} {event.detail or ''}".lower()

    # Tier1: 연결/타임아웃/OS 에러 또는 브로커 토큰 문제
    if etype in ("ConnectionError", "TimeoutError", "OSError"):
        return RepairTier.TIER1
    if etype == "BrokerError" and any(k in combined for k in _TIER1_KEYWORDS):
        return RepairTier.TIER1
    if any(k.lower() in combined for k in _TIER1_KEYWORDS):
        return RepairTier.TIER1

    # Tier1.5: AI 응답/프롬프트/파싱 관련 — 코드 변경 없이 설정으로 우회
    if etype == "AiError" and any(k.lower() in combined for k in _TIER1_5_KEYWORDS):
        return RepairTier.TIER1_5
    if any(k.lower() in combined for k in _TIER1_5_KEYWORDS):
        return RepairTier.TIER1_5

    # Tier2: 데이터 부족 또는 임계값 조정 필요
    if etype == "DataError":
        return RepairTier.TIER2
    if any(k.lower() in combined for k in _TIER2_KEYWORDS):
        return RepairTier.TIER2

    # Tier3: 나머지 — AI 진단 + 제한적 코드 수리
    return RepairTier.TIER3
