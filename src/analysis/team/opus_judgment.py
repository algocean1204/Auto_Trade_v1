"""Opus 3+1 최종 판단 팀이다.

3명의 독립 분석가(공격형/균형형/보수형)가 병렬로 판단하고,
리더가 3의견을 종합하여 ComprehensiveReport를 생성한다.
앵커링 편향 방지를 위해 3명은 서로의 의견을 모른다.

투표 규칙은 코드로 강제된다 (리더 프롬프트 의존 아님):
- 각 분석가의 confidence가 자기 임계값 미달이면 hold로 강제
- 보수형 critical risk → 무조건 hold (거부권)
- 3명 모두 다른 action → hold
- 만장일치 → 높은 confidence
- 2:1 다수결 → 다수 의견 채택 (리더가 세부 조정)
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone

from src.analysis.models import ComprehensiveReport
from src.common.ai_gateway import AiClient
from src.common.logger import get_logger

logger = get_logger(__name__)

# --- 분석가별 confidence 임계값 (코드 강제) ---
_CONFIDENCE_THRESHOLDS: dict[str, float] = {
    "공격형": 0.6,
    "균형형": 0.7,
    "보수형": 0.85,
}

_AGGRESSIVE_PROMPT = (
    "너는 공격형 2X 레버리지 ETF 트레이더이다.\n"
    "기회를 적극 포착하되, 리스크 대비 수익이 2:1 이상인 경우에만 진입한다.\n"
    "변동성은 기회다. 급락 시 인버스, 급등 시 불 포지션을 적극 활용한다.\n"
    "확신도 0.6 이상이면 매매를 추천한다.\n"
)

_BALANCED_PROMPT = (
    "너는 균형형 2X 레버리지 ETF 트레이더이다.\n"
    "리스크와 수익의 균형을 최우선으로 한다.\n"
    "레짐, VIX, 기술적 지표, 뉴스를 종합 판단한다.\n"
    "확신도 0.7 이상이면 매매를 추천한다.\n"
)

_CONSERVATIVE_PROMPT = (
    "너는 보수형 2X 레버리지 ETF 트레이더이다.\n"
    "자본 보전이 절대 원칙이다. 확실한 기회만 잡는다.\n"
    "불확실하면 무조건 hold. 하방 리스크를 항상 먼저 평가한다.\n"
    "확신도 0.85 이상이면 매매를 추천한다.\n"
)

_LEADER_PROMPT = (
    "너는 미국 2X 레버리지 ETF 매매 팀의 리더이다.\n"
    "3명의 독립 분석가(공격형/균형형/보수형)가 각자 판단한 결과를 받았다.\n"
    "이들의 의견을 종합하여 최종 매매 판단을 내려야 한다.\n\n"
    "참고: confidence 임계값 미달 분석가는 이미 hold로 조정되었다.\n"
    "참고: 보수형 critical risk 거부권도 이미 적용되었다.\n"
    "너의 역할은 유효한 의견들의 세부사항(티커, 비중, 타이밍)을 조율하는 것이다.\n\n"
    "종합 원칙:\n"
    "- 3명 만장일치 → 높은 확신도로 실행\n"
    "- 2:1 다수결 → 다수 의견 채택하되 반대 의견의 리스크 포인트 반영\n"
    "- 3명 모두 다른 의견 → hold (확신 부족)\n"
    "- 자본 보전 > 수익 극대화\n"
)


async def opus_team_judgment(
    ai: AiClient,
    layer1_reports: dict[str, str],
    context: dict,
) -> ComprehensiveReport:
    """Opus 3+1 팀이 Layer 1 분석을 기반으로 최종 판단한다.

    Phase 1: 3명 독립 병렬 판단 (앵커링 방지)
    Phase 2: 리더가 3의견 종합
    """
    # Layer 1 분석 결과를 텍스트로 정리
    l1_text = _format_layer1(layer1_reports)
    context_text = _format_context(context)
    base_input = f"{l1_text}\n\n{context_text}"

    # Phase 1: 3명 병렬 판단
    logger.info("Opus 팀 Phase 1: 3명 독립 분석 시작")
    results = await asyncio.gather(
        _analyst_judgment(ai, _AGGRESSIVE_PROMPT, base_input, "공격형"),
        _analyst_judgment(ai, _BALANCED_PROMPT, base_input, "균형형"),
        _analyst_judgment(ai, _CONSERVATIVE_PROMPT, base_input, "보수형"),
        return_exceptions=True,
    )

    opinions: list[dict] = []
    for name, result in zip(
        ["공격형", "균형형", "보수형"], results, strict=False,
    ):
        if isinstance(result, Exception):
            logger.warning("Opus %s 분석가 실패: %s", name, result)
            opinions.append({
                "analyst": name, "action": "hold", "error": str(result),
            })
        else:
            opinions.append(result)

    # --- CR-1: confidence 임계값 코드 강제 ---
    opinions = _enforce_confidence_thresholds(opinions)

    # --- CR-2: 투표 규칙 사전 검증 ---
    vote_override = _apply_voting_rules(opinions)
    if vote_override is not None:
        logger.info(
            "투표 규칙 오버라이드: %s (confidence=%.2f, risk=%s)",
            vote_override["reason"], vote_override["confidence"],
            vote_override["risk_level"],
        )
        # 오버라이드 결과를 리더에게 전달하되, 리더는 세부 조율만 수행한다
        # 강제 hold인 경우 리더 호출 없이 즉시 반환한다
        if vote_override.get("force_hold"):
            return ComprehensiveReport(
                signals=[{
                    "action": "hold", "ticker": "",
                    "reason": vote_override["reason"],
                }],
                confidence=vote_override["confidence"],
                recommendations=[vote_override["reason"]],
                regime_assessment=vote_override.get("regime_assessment", ""),
                risk_level=vote_override["risk_level"],
                timestamp=datetime.now(tz=timezone.utc),
            )

    # Phase 2: 리더 종합
    logger.info("Opus 팀 Phase 2: 리더 종합 시작")
    report = await _leader_synthesis(ai, opinions, base_input)

    # --- CR-2 사후 검증: 리더가 투표 규칙을 위반했는지 확인 ---
    report = _validate_leader_report(report, opinions, vote_override)

    logger.info(
        "Opus 팀 판단 완료: confidence=%.2f, risk=%s, signals=%d",
        report.confidence, report.risk_level, len(report.signals),
    )
    return report


def _safe_confidence(raw: object) -> float:
    """AI가 반환한 confidence 값을 안전하게 float로 변환하고 0.0~1.0 범위로 클램핑한다."""
    try:
        return max(0.0, min(1.0, float(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _enforce_confidence_thresholds(opinions: list[dict]) -> list[dict]:
    """CR-1: 분석가별 confidence가 임계값 미달이면 action을 hold로 강제한다."""
    enforced = []
    for o in opinions:
        name = o.get("analyst", "?")
        action = o.get("action", "hold")
        confidence = _safe_confidence(o.get("confidence", 0))
        threshold = _CONFIDENCE_THRESHOLDS.get(name, 0.7)

        if action != "hold" and confidence < threshold:
            logger.info(
                "CR-1 강제: %s confidence=%.2f < 임계값=%.2f → hold로 변경 (원래=%s)",
                name, confidence, threshold, action,
            )
            o = {**o, "action": "hold", "_original_action": action,
                 "_enforced": True,
                 "reasoning": o.get("reasoning", "") + f" [시스템: confidence {confidence:.2f} < 임계값 {threshold:.2f}, hold 강제]"}
        enforced.append(o)
    return enforced


def _apply_voting_rules(opinions: list[dict]) -> dict | None:
    """CR-2: 투표 규칙을 알고리즘으로 판정한다.

    반환값:
    - None: 특별한 오버라이드 없음, 리더가 정상 종합
    - dict: 오버라이드 정보 (force_hold=True면 리더 호출 없이 즉시 반환)
    """
    # 보수형 거부권: critical risk 경고 시 무조건 hold
    conservative = next((o for o in opinions if o.get("analyst") == "보수형"), None)
    if conservative and conservative.get("risk_assessment") == "critical":
        return {
            "force_hold": True,
            "confidence": 0.3,
            "risk_level": "critical",
            "reason": "보수형 거부권 발동: critical risk 경고 — 자본 보전 우선",
            "regime_assessment": conservative.get("reasoning", ""),
        }

    # 3명의 action 분포 분석
    actions = [o.get("action", "hold") for o in opinions]
    action_counts = Counter(actions)
    unique_actions = set(actions)

    # 3명 모두 다른 의견 → 강제 hold
    if len(unique_actions) == 3:
        return {
            "force_hold": True,
            "confidence": 0.3,
            "risk_level": "high",
            "reason": "3명 분석가 의견 불일치 (buy/sell/hold 각 1명) — hold 강제",
        }

    # 만장일치 → 리더에게 높은 confidence 힌트 전달
    if len(unique_actions) == 1:
        avg_conf = sum(_safe_confidence(o.get("confidence", 0)) for o in opinions) / 3
        return {
            "force_hold": False,
            "unanimous_action": actions[0],
            "confidence": min(avg_conf + 0.1, 1.0),
            "confidence_hint": min(avg_conf + 0.1, 1.0),
            "risk_level": "low" if actions[0] == "hold" else "medium",
            "reason": f"만장일치 {actions[0]} (평균 confidence={avg_conf:.2f})",
        }

    # 2:1 다수결 → 리더에게 다수 의견 힌트 전달
    majority_action, majority_count = action_counts.most_common(1)[0]
    if majority_count == 2:
        minority = next(o for o in opinions if o.get("action") != majority_action)
        majority_conf = sum(
            _safe_confidence(o.get("confidence", 0))
            for o in opinions if o.get("action") == majority_action
        ) / 2
        return {
            "force_hold": False,
            "majority_action": majority_action,
            "confidence": majority_conf,
            "risk_level": minority.get("risk_assessment", "medium"),
            "minority_risk": minority.get("key_risk", ""),
            "reason": f"2:1 다수결 {majority_action} (소수 의견: {minority.get('analyst', '?')})",
        }

    return None


def _validate_leader_report(
    report: ComprehensiveReport,
    opinions: list[dict],
    vote_override: dict | None,
) -> ComprehensiveReport:
    """CR-2 사후 검증: 리더가 투표 규칙을 위반했는지 확인하고 교정한다."""
    if vote_override is None:
        return report

    # 만장일치인데 리더가 반대 판단을 내린 경우 → confidence 하한 강제
    if "unanimous_action" in vote_override:
        unanimous = vote_override["unanimous_action"]
        leader_actions = {s.get("action") for s in report.signals if s.get("action")}
        if unanimous != "hold" and leader_actions == {"hold"}:
            logger.warning(
                "리더가 만장일치 %s를 hold로 뒤집음 — confidence 하한 0.5 적용",
                unanimous,
            )
            report.confidence = max(report.confidence, 0.5)

        # 만장일치 시 confidence 하한 적용
        hint = vote_override.get("confidence_hint", 0.0)
        if hint > 0 and report.confidence < hint - 0.2:
            logger.info(
                "만장일치 confidence 보정: %.2f → %.2f",
                report.confidence, hint,
            )
            report.confidence = hint

    return report


async def _analyst_judgment(
    ai: AiClient,
    persona: str,
    base_input: str,
    name: str,
) -> dict:
    """개별 분석가의 판단을 받는다."""
    prompt = (
        f"{persona}\n\n"
        f"아래 Sonnet 4에이전트의 분석 결과와 시장 데이터를 읽고 매매 판단을 내려라.\n\n"
        f"{base_input}\n\n"
        "반드시 아래 JSON만 출력하라:\n"
        "{\n"
        f'  "analyst": "{name}",\n'
        '  "action": "buy" | "sell" | "hold",\n'
        '  "ticker": "종목코드 (hold면 빈 문자열)",\n'
        '  "confidence": 0.0~1.0,\n'
        '  "risk_assessment": "low" | "medium" | "high" | "critical",\n'
        '  "reasoning": "한국어 판단 근거 (3~5문장)",\n'
        '  "key_risk": "가장 큰 리스크 요인 한줄 (한국어)"\n'
        "}\n"
    )

    response = await ai.send_text(prompt, model="opus", max_tokens=1024)
    parsed = _parse_json(response.content)
    if parsed is None:
        logger.error("Opus %s 분석가 응답 파싱 실패 — hold 처리", name)
        return {"analyst": name, "action": "hold", "error": "JSON 파싱 실패"}
    parsed.setdefault("analyst", name)
    return parsed


async def _leader_synthesis(
    ai: AiClient,
    opinions: list[dict],
    base_input: str,
) -> ComprehensiveReport:
    """리더가 3의견을 종합하여 최종 ComprehensiveReport를 생성한다."""
    opinions_text = "\n\n".join(
        f"[{o.get('analyst', '?')}]\n"
        f"  action: {o.get('action', 'hold')}\n"
        f"  ticker: {o.get('ticker', '')}\n"
        f"  confidence: {o.get('confidence', 0)}\n"
        f"  risk: {o.get('risk_assessment', 'high')}\n"
        f"  reasoning: {o.get('reasoning', o.get('error', ''))}\n"
        f"  key_risk: {o.get('key_risk', '')}"
        for o in opinions
    )

    prompt = (
        f"{_LEADER_PROMPT}\n\n"
        f"[3명의 분석가 의견]\n{opinions_text}\n\n"
        f"[원본 Sonnet 분석 + 시장 데이터]\n{base_input}\n\n"
        "반드시 아래 JSON만 출력하라:\n"
        "{\n"
        '  "signals": [{"action": "buy/sell/hold", "ticker": "종목코드", "direction": "bull/bear", "reason": "한국어"}],\n'
        '  "confidence": 0.0~1.0,\n'
        '  "recommendations": ["한국어 구체적 행동 지시"],\n'
        '  "regime_assessment": "현재 시장 상태 평가 (한국어)",\n'
        '  "risk_level": "low" | "medium" | "high" | "critical"\n'
        "}\n"
    )

    try:
        response = await ai.send_text(prompt, model="opus", max_tokens=1024)
        parsed = _parse_json(response.content)

        if parsed is None:
            logger.warning("Opus 리더 응답 파싱 실패 — hold 기본값 반환")
            return ComprehensiveReport(
                signals=[{"action": "hold", "ticker": "", "reason": "리더 JSON 파싱 실패"}],
                confidence=0.3,
                recommendations=["Opus 리더 응답 파싱 실패 — 포지션 유지"],
                regime_assessment="판단 불가",
                risk_level="high",
                timestamp=datetime.now(tz=timezone.utc),
            )

        # AI가 confidence를 범위 밖으로 반환할 수 있으므로 클램핑한다
        raw_conf = parsed.get("confidence", 0.4)
        try:
            clamped_conf = max(0.0, min(1.0, float(raw_conf)))
        except (TypeError, ValueError):
            clamped_conf = 0.4
        # risk_level이 유효 값이 아닐 경우 medium으로 보정한다
        raw_risk = parsed.get("risk_level", "medium")
        valid_risks = {"low", "medium", "high", "critical"}
        safe_risk = raw_risk if raw_risk in valid_risks else "medium"
        return ComprehensiveReport(
            signals=parsed.get(
                "signals",
                [{"action": "hold", "ticker": "", "reason": "판단 불가"}],
            ),
            confidence=clamped_conf,
            recommendations=parsed.get("recommendations", ["포지션 유지"]),
            regime_assessment=parsed.get("regime_assessment", ""),
            risk_level=safe_risk,
            timestamp=datetime.now(tz=timezone.utc),
        )
    except Exception as exc:
        logger.error("Opus 리더 판단 실패: %s", exc, exc_info=True)
        return ComprehensiveReport(
            signals=[{
                "action": "hold", "ticker": "",
                "reason": f"리더 실패: {exc}",
            }],
            confidence=0.3,
            recommendations=["Opus 리더 판단 실패 — 포지션 유지"],
            regime_assessment="판단 불가",
            risk_level="high",
            timestamp=datetime.now(tz=timezone.utc),
        )


def _format_layer1(reports: dict[str, str]) -> str:
    """Layer 1 분석 결과를 텍스트로 정리한다."""
    parts = []
    for agent, content in reports.items():
        parts.append(f"=== {agent} ===\n{content}")
    return "\n\n".join(parts)


def _format_context(context: dict) -> str:
    """시장 컨텍스트를 텍스트로 정리한다."""
    lines = ["[시장 데이터]"]
    for key, value in context.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _parse_json(raw: str) -> dict | None:
    """AI 응답에서 JSON을 파싱한다. 실패 시 None을 반환한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("Opus JSON 파싱 실패 — 이번 분석 건너뜀: %s", raw[:200])
        return None
