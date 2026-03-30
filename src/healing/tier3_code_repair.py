"""Tier3 제한적 코드 수리 -- Opus 분석 → Sonnet 패치 → Opus 검증 파이프라인이다.

화이트리스트 경로만 수정 가능하며, 위험 패턴과 블랙리스트 경로를 차단한다.
수정 전 백업을 생성하고, 검증 실패 시 즉시 롤백한다.
수리 캐시와 Sticky Fix를 활용하여 불필요한 재수리를 방지한다.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from src.common.logger import get_logger
from src.common.paths import get_project_root
from src.healing.budget_tracker import BudgetTracker
from src.healing.error_classifier import ErrorEvent, RepairResult, RepairTier
from src.healing.repair_cache import RepairCache

logger: logging.Logger = get_logger(__name__)

# 수정 허용 경로 (프로젝트 루트 기준 상대경로 접두사)
_WHITELIST_PREFIXES: tuple[str, ...] = (
    "src/common/",
    "src/crawlers/",
    "src/indicators/misc/",
    "src/monitoring/",
    "src/analysis/",
)

# 수정 금지 경로 (화이트리스트 내에서도 차단)
_BLACKLIST_PATHS: tuple[str, ...] = (
    "src/executor/",
    "src/strategy/",
    "src/risk/",
    "trading_loop.py",
    "secret_vault.py",
    "auth.py",
)

# 금지 패턴 -- 매매/인증/키 관련 코드 수정을 차단한다
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "execute_buy", "execute_sell", "position_size",
    "api_key", "secret", "token", "password",
    "ANTHROPIC_API", "KIS_APP",
)

# 최대 수정 줄 수
_MAX_CHANGE_LINES: int = 15


def _is_path_allowed(rel_path: str) -> bool:
    """수정 대상 경로가 화이트리스트 내이고 블랙리스트에 없는지 확인한다."""
    if not any(rel_path.startswith(p) for p in _WHITELIST_PREFIXES):
        return False
    if any(b in rel_path for b in _BLACKLIST_PATHS):
        return False
    return True


def _has_forbidden_pattern(code: str) -> str | None:
    """코드에 금지 패턴이 포함되어 있으면 해당 패턴을 반환한다."""
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.lower() in code.lower():
            return pattern
    return None


def _validate_patch(patch_text: str) -> bool:
    """패치가 줄 수 제한을 준수하는지 확인한다."""
    added = sum(1 for line in patch_text.splitlines() if line.startswith("+"))
    removed = sum(1 for line in patch_text.splitlines() if line.startswith("-"))
    return max(added, removed) <= _MAX_CHANGE_LINES


def _build_opus_analysis_prompt(events: list[ErrorEvent]) -> str:
    """Opus에게 근본 원인과 최소 수정 계획을 요청하는 프롬프트를 구성한다."""
    lines = [
        "[자동매매 시스템 에러 — 코드 수리 분석 요청]",
        f"에러 건수: {len(events)}",
        "",
    ]
    for i, ev in enumerate(events, 1):
        lines.append(f"--- 에러 #{i} ---")
        lines.append(f"유형: {ev.error_type}")
        lines.append(f"메시지: {ev.message}")
        lines.append(f"모듈: {ev.module}")
        if ev.detail:
            lines.append(f"상세: {ev.detail}")
        lines.append("")
    lines.extend([
        "다음 형식으로 응답하라:",
        "1. ROOT_CAUSE: 근본 원인 (1줄)",
        "2. FILE: 수정할 파일 경로 (src/ 기준, 1개만)",
        "3. FIX_PLAN: 최소 수정 계획 (15줄 이내 변경)",
        "4. SEVERITY: Critical/High/Medium/Low",
        "",
        "수정 불가능하면 FILE: NONE으로 응답하라.",
    ])
    return "\n".join(lines)


_OPUS_ANALYSIS_SYSTEM: str = (
    "너는 자동매매 시스템의 에러 진단 전문가이다. "
    "근본 원인을 파악하고 최소한의 코드 수정 계획을 제시한다. "
    "15줄 이내의 변경만 허용된다."
)


def _build_sonnet_fix_prompt(
    analysis: str, file_content: str, file_path: str,
) -> str:
    """Sonnet에게 구체적인 코드 패치를 요청하는 프롬프트를 구성한다."""
    return (
        f"[코드 수리 요청]\n"
        f"파일: {file_path}\n\n"
        f"[Opus 분석 결과]\n{analysis}\n\n"
        f"[현재 파일 내용]\n```python\n{file_content}\n```\n\n"
        f"다음 형식으로 패치를 출력하라:\n"
        f"```patch\n"
        f"--- a/{file_path}\n"
        f"+++ b/{file_path}\n"
        f"@@ ... @@\n"
        f"-삭제할 줄\n"
        f"+추가할 줄\n"
        f"```\n\n"
        f"규칙:\n"
        f"- 최대 {_MAX_CHANGE_LINES}줄 변경\n"
        f"- 기존 코드 스타일(한국어 주석, snake_case) 준수\n"
        f"- import 추가는 허용\n"
        f"- 함수 시그니처 변경 금지\n"
    )


_SONNET_FIX_SYSTEM: str = (
    "너는 Python 코드 수리 전문가이다. "
    "최소한의 변경으로 에러를 수정하는 unified diff 패치를 생성한다. "
    "기존 코드 스타일을 반드시 유지한다."
)


def _build_opus_verify_prompt(
    original: str, patched: str, file_path: str,
) -> str:
    """Opus에게 패치 적용 결과를 검증하도록 요청하는 프롬프트를 구성한다."""
    return (
        f"[코드 패치 검증 요청]\n"
        f"파일: {file_path}\n\n"
        f"[원본]\n```python\n{original}\n```\n\n"
        f"[패치 후]\n```python\n{patched}\n```\n\n"
        f"검증 항목:\n"
        f"1. 구문 오류 여부\n"
        f"2. 기존 기능 파괴 여부\n"
        f"3. 보안 위험 (키/토큰/인증 관련 변경)\n"
        f"4. 부작용 가능성\n\n"
        f"결과를 다음 형식으로 출력하라:\n"
        f"VERDICT: APPROVE 또는 REJECT\n"
        f"REASON: 판정 이유 (1줄)"
    )


_OPUS_VERIFY_SYSTEM: str = (
    "너는 코드 리뷰 전문가이다. 패치의 안전성과 정확성을 검증한다. "
    "보안 위험이나 기능 파괴가 있으면 반드시 REJECT한다."
)


def _extract_file_path(analysis: str) -> str | None:
    """Opus 분석에서 FILE: 경로를 추출한다."""
    for line in analysis.splitlines():
        if line.strip().startswith("FILE:"):
            path = line.split("FILE:", 1)[1].strip()
            if path == "NONE" or not path:
                return None
            return path
    return None


def _extract_patch_content(response: str) -> str | None:
    """Sonnet 응답에서 patch 코드 블록을 추출한다."""
    match = re.search(r"```patch\s*\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    # diff 블록도 시도한다
    match = re.search(r"```diff\s*\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def _apply_simple_patch(original: str, patch: str) -> str | None:
    """단순 +/- 라인 기반 패치를 적용한다. 실패 시 None을 반환한다."""
    lines = original.splitlines(keepends=True)
    result = list(lines)
    removals: list[str] = []
    additions: list[str] = []

    for pline in patch.splitlines():
        if pline.startswith("---") or pline.startswith("+++") or pline.startswith("@@"):
            continue
        if pline.startswith("-"):
            removals.append(pline[1:].rstrip("\n"))
        elif pline.startswith("+"):
            additions.append(pline[1:].rstrip("\n"))

    if not removals and not additions:
        return None

    # 삭제 대상 줄을 찾아서 제거하고, 그 위치에 추가 줄을 삽입한다
    insert_idx: int | None = None
    for rm in removals:
        for i, line in enumerate(result):
            if line.rstrip("\n") == rm:
                if insert_idx is None:
                    insert_idx = i
                result[i] = None  # type: ignore[assignment]  # 삭제 마킹
                break
        else:
            # 삭제 대상을 찾지 못하면 패치 적용 실패이다
            return None

    # None 제거 전 삽입 위치에 추가 줄을 삽입한다
    if insert_idx is not None and additions:
        for j, add_line in enumerate(additions):
            result.insert(insert_idx + j, add_line + "\n")

    return "".join(line for line in result if line is not None)


async def attempt_code_repair(
    system: object,
    events: list[ErrorEvent],
    budget: BudgetTracker,
    cache: RepairCache | None = None,
) -> RepairResult:
    """Opus→Sonnet→Opus 3단계 코드 수리를 시도한다."""
    if not events:
        return RepairResult(
            success=True, tier=RepairTier.TIER3,
            action="코드 수리", detail="수리 대상 없음",
        )

    # 예산 확인 — Opus 2회 + Sonnet 1회 필요하다
    if not budget.can_call("opus") or not budget.can_call("sonnet"):
        logger.warning("코드 수리 예산 부족 — 건너뜀")
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리", detail="예산 부족으로 건너뜀",
        )

    from src.common.ai_gateway import get_ai_client
    ai = get_ai_client()
    root = get_project_root()

    # ── Step 1: Opus 분석 (근본 원인 + 수정 계획) ──
    try:
        analysis_resp = await ai.send_text(
            prompt=_build_opus_analysis_prompt(events),
            system=_OPUS_ANALYSIS_SYSTEM,
            model="opus",
            max_tokens=1024,
        )
        budget.record_call("opus")
        analysis = analysis_resp.content
    except Exception as exc:
        logger.error("코드 수리 Opus 분석 실패: %s", exc)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 분석", detail=f"Opus 분석 실패: {exc}",
        )

    # 수정 대상 파일 추출
    target_path = _extract_file_path(analysis)
    if target_path is None:
        logger.info("Opus 판단: 코드 수정 불필요")
        return RepairResult(
            success=True, tier=RepairTier.TIER3,
            action="코드 수리 분석", detail="코드 수정 불필요 — 분석만 완료",
        )

    # 경로 안전성 검증
    if not _is_path_allowed(target_path):
        logger.warning("수정 금지 경로: %s", target_path)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리", detail=f"수정 금지 경로: {target_path}",
        )

    # Sticky Fix: cooldown 기간 내 파일은 수리하지 않는다
    if cache is not None and cache.is_sticky(target_path):
        logger.info("Sticky Fix cooldown 중: %s", target_path)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 (Sticky)", detail=f"cooldown 중: {target_path}",
        )

    target_file = root / target_path
    if not target_file.exists():
        logger.warning("대상 파일 없음: %s", target_file)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리", detail=f"파일 없음: {target_path}",
        )

    original_content = target_file.read_text(encoding="utf-8")

    # ── Step 2: Sonnet 패치 생성 ──
    try:
        fix_resp = await ai.send_text(
            prompt=_build_sonnet_fix_prompt(analysis, original_content, target_path),
            system=_SONNET_FIX_SYSTEM,
            model="sonnet",
            max_tokens=2048,
        )
        budget.record_call("sonnet")
    except Exception as exc:
        logger.error("코드 수리 Sonnet 패치 실패: %s", exc)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 패치", detail=f"Sonnet 패치 실패: {exc}",
        )

    patch = _extract_patch_content(fix_resp.content)
    if patch is None:
        logger.warning("Sonnet 응답에서 패치를 추출하지 못함")
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 패치", detail="패치 추출 실패",
        )

    # 줄 수 제한 검증
    if not _validate_patch(patch):
        logger.warning("패치가 %d줄 제한 초과", _MAX_CHANGE_LINES)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 패치", detail=f"{_MAX_CHANGE_LINES}줄 제한 초과",
        )

    # 금지 패턴 검증
    forbidden = _has_forbidden_pattern(patch)
    if forbidden:
        logger.warning("패치에 금지 패턴 포함: %s", forbidden)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 패치", detail=f"금지 패턴 포함: {forbidden}",
        )

    # 패치 적용
    patched_content = _apply_simple_patch(original_content, patch)
    if patched_content is None:
        logger.warning("패치 적용 실패 (줄 매칭 불가)")
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 적용", detail="패치 줄 매칭 실패",
        )

    # 구문 검증 — compile()로 파이썬 구문 오류를 사전 차단한다
    try:
        compile(patched_content, target_path, "exec")
    except SyntaxError as exc:
        logger.warning("패치 후 구문 오류: %s", exc)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 검증", detail=f"구문 오류: {exc}",
        )

    # ── Step 3: Opus 검증 (검증됨 캐시는 건너뛴다) ──
    skip_verify = False
    if cache is not None and events:
        skip_verify = cache.is_verified(events[0].error_type)
        if skip_verify:
            logger.info("검증됨 캐시 → Opus 검증 건너뜀: %s", events[0].error_type)

    if not skip_verify and not budget.can_call("opus"):
        logger.warning("Opus 검증 예산 부족 — 패치 적용 취소")
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 검증", detail="검증 예산 부족",
        )

    verdict = "APPROVE (verified cache)"
    if not skip_verify:
        try:
            verify_resp = await ai.send_text(
                prompt=_build_opus_verify_prompt(
                    original_content, patched_content, target_path,
                ),
                system=_OPUS_VERIFY_SYSTEM,
                model="opus",
                max_tokens=512,
            )
            budget.record_call("opus")
        except Exception as exc:
            logger.error("Opus 검증 실패 — 패치 적용 취소: %s", exc)
            return RepairResult(
                success=False, tier=RepairTier.TIER3,
                action="코드 수리 검증", detail=f"Opus 검증 실패: {exc}",
            )

        verdict = verify_resp.content
        if "APPROVE" not in verdict.upper():
            logger.warning("Opus 검증 REJECT: %s", verdict[:200])
            return RepairResult(
                success=False, tier=RepairTier.TIER3,
                action="코드 수리 검증", detail=f"Opus REJECT: {verdict[:200]}",
            )

    # ── Step 4: 백업 생성 → 파일 적용 ──
    backup_path = target_file.with_suffix(target_file.suffix + ".heal_backup")
    shutil.copy2(str(target_file), str(backup_path))
    logger.info("백업 생성: %s", backup_path)

    try:
        target_file.write_text(patched_content, encoding="utf-8")
        logger.info("코드 수리 완료: %s", target_path)
    except Exception as exc:
        # 쓰기 실패 시 백업에서 복원한다
        shutil.copy2(str(backup_path), str(target_file))
        backup_path.unlink(missing_ok=True)
        logger.error("파일 쓰기 실패, 롤백 완료: %s", exc)
        return RepairResult(
            success=False, tier=RepairTier.TIER3,
            action="코드 수리 적용", detail=f"파일 쓰기 실패: {exc}",
        )

    # 텔레그램 보고
    await _send_repair_report(system, target_path, analysis, verdict)

    # 백업 파일은 다음 세션 초기화 시 정리한다 (롤백 가능성 유지)
    return RepairResult(
        success=True, tier=RepairTier.TIER3,
        action="코드 수리",
        detail=f"{target_path} 수정 완료 (백업: {backup_path.name})",
    )


async def _send_repair_report(
    system: object, file_path: str, analysis: str, verdict: str,
) -> None:
    """코드 수리 결과를 텔레그램으로 보고한다."""
    try:
        components = getattr(system, "components", None)
        telegram = getattr(components, "telegram", None) if components else None
        if telegram is None:
            return
        from src.common.telegram_gateway import escape_html
        msg = (
            f"<b>[Self-Healing] 코드 수리 완료</b>\n"
            f"파일: <code>{escape_html(file_path)}</code>\n\n"
            f"<b>분석:</b>\n<pre>{escape_html(analysis[:1500])}</pre>\n\n"
            f"<b>검증:</b> {escape_html(verdict[:300])}"
        )
        await telegram.send_text(msg)
    except Exception as exc:
        logger.error("코드 수리 텔레그램 보고 실패: %s", exc)
