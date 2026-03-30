"""Tier1.5 프롬프트 우회 -- 코드 변경 없이 설정/프롬프트 수정으로 에러를 우회한다.

AI 분석 프롬프트 조정, 로깅 레벨 변경, 환경변수 기반 동작 전환 등
코드를 건들지 않고 시스템 동작을 변경하여 에러를 회피한다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_data_dir
from src.healing.error_classifier import ErrorEvent, RepairResult, RepairTier

logger: logging.Logger = get_logger(__name__)

# 프롬프트 관련 에러 키워드 -- 이 키워드가 있으면 Tier 1.5로 분류된다
PROMPT_ERROR_KEYWORDS: tuple[str, ...] = (
    "prompt", "프롬프트", "분류", "classify", "parse",
    "json", "format", "schema", "validation",
    "response", "응답", "파싱",
)


def _overrides_path() -> Path:
    """프롬프트 오버라이드 파일 경로를 반환한다."""
    return get_data_dir() / "prompt_overrides.json"


def _read_overrides() -> dict:
    """현재 오버라이드 설정을 읽는다."""
    path = _overrides_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_overrides(data: dict) -> None:
    """오버라이드 설정을 저장한다."""
    path = _overrides_path()
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


async def attempt_tier1_5(event: ErrorEvent) -> RepairResult:
    """Tier 1.5 프롬프트 우회 수리를 시도한다."""
    combined = f"{event.message} {event.detail or ''}".lower()

    # JSON 파싱 에러 → 응답 형식 완화
    if any(k in combined for k in ("json", "parse", "파싱", "schema")):
        return await _relax_response_format(event)

    # 분류 에러 → 분류 카테고리 확장
    if any(k in combined for k in ("classify", "분류", "category")):
        return await _expand_classification(event)

    # AI 응답 형식 에러 → 프롬프트 간소화 플래그
    if any(k in combined for k in ("prompt", "프롬프트", "response", "응답")):
        return await _simplify_prompt_flag(event)

    # 매칭되는 우회 전략이 없으면 실패를 반환한다
    return RepairResult(
        success=False, tier=RepairTier.TIER1_5,
        action="프롬프트 우회", detail="매칭되는 우회 전략 없음",
    )


async def _relax_response_format(event: ErrorEvent) -> RepairResult:
    """AI 응답 형식 검증을 완화한다. strict JSON → 유연한 파싱 허용."""
    overrides = _read_overrides()
    overrides["relaxed_json_parsing"] = True
    overrides["max_parse_retries"] = 3
    _write_overrides(overrides)
    logger.info("프롬프트 우회: JSON 파싱 완화 적용")
    return RepairResult(
        success=True, tier=RepairTier.TIER1_5,
        action="프롬프트 우회",
        detail="JSON 파싱 완화 (relaxed_json_parsing=true)",
    )


async def _expand_classification(event: ErrorEvent) -> RepairResult:
    """분류 카테고리에 fallback 옵션을 추가한다."""
    overrides = _read_overrides()
    overrides["classification_fallback"] = "normal"
    overrides["classification_strict"] = False
    _write_overrides(overrides)
    logger.info("프롬프트 우회: 분류 fallback 설정")
    return RepairResult(
        success=True, tier=RepairTier.TIER1_5,
        action="프롬프트 우회",
        detail="분류 fallback=normal, strict=false",
    )


async def _simplify_prompt_flag(event: ErrorEvent) -> RepairResult:
    """AI 프롬프트를 간소화 모드로 전환한다."""
    overrides = _read_overrides()
    overrides["simplified_prompts"] = True
    _write_overrides(overrides)
    logger.info("프롬프트 우회: 간소화 모드 적용")
    return RepairResult(
        success=True, tier=RepairTier.TIER1_5,
        action="프롬프트 우회",
        detail="프롬프트 간소화 모드 활성화",
    )


async def restore_overrides() -> None:
    """세션 종료 시 오버라이드를 초기화한다."""
    path = _overrides_path()
    if path.exists():
        path.unlink(missing_ok=True)
        logger.info("프롬프트 오버라이드 초기화 완료")
