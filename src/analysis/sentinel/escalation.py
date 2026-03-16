"""센티넬 에스컬레이션 -- Sonnet 평가 + Opus 3+1 팀 긴급 판단이다.

센티넬이 urgent/watch 신호를 감지하면 Sonnet이 평가하고,
emergency 판정 시 Opus 3+1 팀(공격형/균형형/보수형 + 리더)이 긴급 매매 판단을 내린다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from src.analysis.models import ComprehensiveReport
from src.analysis.sentinel.models import AnomalyResult, EscalationResult
from src.common.ai_gateway import AiClient
from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)


async def evaluate_anomaly(
    ai: AiClient,
    anomaly: AnomalyResult,
    system: InjectedSystem,
) -> EscalationResult:
    """Sonnet으로 이상 신호를 평가하여 긴급도를 판정한다.

    긴급도 판정 기준:
    - emergency: 즉시 매매 안 하면 큰 손실 위험 (하드스톱 임박, 급락 진행 중)
    - next_cycle: 중요하지만 다음 정기 분석(60분)에서 반영해도 늦지 않음
    - ignore: 일시적 노이즈, 이미 반영됨, 또는 오판
    """
    # 포지션 정보 수집 (진입 시점 포함)
    positions_text = "보유 포지션 없음"
    monitor = system.features.get("position_monitor")
    if monitor is not None:
        try:
            positions = monitor.get_all_positions()
            if positions:
                lines = []
                for t, p in positions.items():
                    entry_time = getattr(p, "entry_time", None)
                    entry_str = entry_time.isoformat() if entry_time else "불명"
                    lines.append(
                        f"  {t}: {p.quantity}주, 평단 ${p.avg_price:.2f}, "
                        f"PnL {p.pnl_pct:+.2f}%, 진입 {entry_str}"
                    )
                positions_text = "\n".join(lines)
        except Exception:
            pass

    # VIX 현재값 수집
    vix_text = "VIX: 조회 불가"
    vf = system.features.get("vix_fetcher")
    if vf is not None:
        try:
            vix_val = await vf.get_vix()
            vix_text = f"VIX: {vix_val:.2f}"
        except Exception:
            pass

    signals_text = "\n".join(
        f"- [{s.level}] {s.rule}: {s.detail} (값={s.value:.2f}, 임계={s.threshold:.2f})"
        for s in anomaly.signals
    )

    # 뉴스 관련 신호가 있으면 원본 헤드라인을 추가 컨텍스트로 포함한다
    news_context = ""
    news_signals = [s for s in anomaly.signals if s.rule in ("news_urgent", "news_watch")]
    if news_signals:
        headlines = [s.detail.replace("긴급 뉴스: ", "").replace("주의 뉴스: ", "") for s in news_signals]
        news_context = (
            "\n[뉴스 헤드라인 원문]\n"
            + "\n".join(f"- {h}" for h in headlines)
            + "\n"
        )

    prompt = (
        "너는 미국 2X 레버리지 ETF 단타 트레이딩 시스템의 긴급 평가관이다.\n\n"
        "센티넬이 아래 이상 신호를 감지했다. 매매 행동이 필요한 수준인지 판단하라.\n\n"
        f"[감지된 이상 신호]\n{signals_text}\n\n"
        f"[현재 보유 포지션]\n{positions_text}\n\n"
        f"[시장 상태]\n{vix_text}\n"
        f"{news_context}\n"
        "[시스템 임계값]\n"
        "  하드스톱: PnL -1.0% (자동 청산)\n"
        "  하드스톱 근접 경보: PnL -0.7%\n"
        "  기본 수익목표: +3.0%\n"
        "  트레일링 스톱: +1.5% 도달 후 -0.5%\n\n"
        "반드시 아래 JSON만 출력하라:\n"
        "{\n"
        '  "action_needed": true/false,\n'
        '  "urgency": "emergency" | "next_cycle" | "ignore",\n'
        '  "reasoning": "한국어 판단 근거 (2~3문장)",\n'
        '  "suggested_action": "sell SOXL" 또는 "buy SQQQ" 등 (action_needed=false면 빈 문자열)",\n'
        '  "ticker": "관련 티커 (없으면 빈 문자열)"\n'
        "}\n\n"
        "판단 기준:\n"
        "- emergency: 즉시 매매 안 하면 큰 손실 위험 (하드스톱 임박, 급락 진행 중, VIX 급등+포지션 보유)\n"
        "- next_cycle: 중요하지만 다음 정기 분석(60분)에서 반영해도 늦지 않음\n"
        "- ignore: 일시적 노이즈, 이미 반영됨, 또는 오판\n"
    )

    try:
        response = await ai.send_text(prompt, model="sonnet", max_tokens=512)
        parsed = _parse_json(response.content)

        # JSON 파싱 실패 시 안전하게 next_cycle로 처리한다 (urgent 신호 무시 방지)
        if not parsed:
            logger.warning("에스컬레이션 JSON 파싱 실패 — 안전하게 next_cycle 처리")
            return EscalationResult(
                action_needed=True,
                urgency="next_cycle",
                reasoning="Sonnet 응답 파싱 실패, 안전하게 다음 정기 분석에 반영",
            )

        result = EscalationResult(
            action_needed=parsed.get("action_needed", False),
            urgency=parsed.get("urgency", "next_cycle"),
            reasoning=parsed.get("reasoning", ""),
            suggested_action=parsed.get("suggested_action", ""),
            ticker=parsed.get("ticker", ""),
        )
        logger.info(
            "에스컬레이션 평가: urgency=%s, action=%s, reason=%s",
            result.urgency, result.suggested_action, result.reasoning[:60],
        )
        return result

    except Exception as exc:
        logger.warning("에스컬레이션 Sonnet 호출 실패: %s", exc)
        # Sonnet 실패 시 urgent 신호가 있으면 안전하게 next_cycle로 처리한다
        return EscalationResult(
            action_needed=True,
            urgency="next_cycle",
            reasoning=f"Sonnet 평가 실패, 안전하게 다음 정기 분석에 반영: {exc}",
        )


async def emergency_opus_judgment(
    ai: AiClient,
    anomaly: AnomalyResult,
    escalation: EscalationResult,
    system: InjectedSystem,
) -> ComprehensiveReport:
    """Opus 3+1 팀이 긴급 매매 판단을 내린다.

    정기 분석과 동일한 Opus 팀(공격형/균형형/보수형 3명 병렬 → 리더 종합)을 호출한다.
    센티넬 이상 신호 + Sonnet 에스컬레이션 결과를 Layer 1 보고서로 변환하여 전달한다.
    """
    # 센티넬 데이터를 Layer 1 보고서 형식으로 변환한다
    layer1_reports = _build_emergency_layer1(anomaly, escalation)

    # 시장 컨텍스트 수집
    market_context = await _gather_emergency_context(system, anomaly)

    try:
        from src.analysis.team.opus_judgment import opus_team_judgment

        report = await opus_team_judgment(ai, layer1_reports, market_context)
        logger.info(
            "긴급 Opus 3+1 팀 판단: confidence=%.2f, risk=%s, signals=%d",
            report.confidence, report.risk_level, len(report.signals),
        )
        return report

    except Exception as exc:
        logger.error("긴급 Opus 3+1 팀 판단 실패: %s", exc)
        # 전체 팀 호출 실패 시 보수적 hold 판단을 반환한다
        return ComprehensiveReport(
            signals=[{"action": "hold", "ticker": "", "reason": f"Opus 팀 호출 실패: {exc}"}],
            confidence=0.3,
            recommendations=["Opus 긴급 판단 실패 — 포지션 유지, 다음 정기 분석 대기"],
            regime_assessment="긴급 판단 불가",
            risk_level="high",
            timestamp=datetime.now(tz=timezone.utc),
        )


def _build_emergency_layer1(
    anomaly: AnomalyResult,
    escalation: EscalationResult,
) -> dict[str, str]:
    """센티넬 이상 신호를 Opus 팀이 읽을 Layer 1 보고서 형식으로 변환한다."""
    # 센티넬 감지 결과를 에이전트별 보고서처럼 구성한다
    signals_detail = "\n".join(
        f"- [{s.level}] {s.rule}: {s.detail} (값={s.value:.2f}, 임계={s.threshold:.2f})"
        for s in anomaly.signals
    )

    sentinel_report = (
        f"[센티넬 긴급 감지 보고]\n"
        f"감지 시각: {anomaly.timestamp.isoformat()}\n"
        f"최고 위험 수준: {anomaly.highest_level}\n"
        f"감지된 신호 수: {len(anomaly.signals)}\n\n"
        f"[이상 신호 상세]\n{signals_detail}\n\n"
        f"[Sonnet 에스컬레이션 평가]\n"
        f"긴급도: {escalation.urgency}\n"
        f"판단 근거: {escalation.reasoning}\n"
        f"제안 행동: {escalation.suggested_action}\n"
        f"관련 티커: {escalation.ticker}"
    )

    return {
        "SENTINEL_ANOMALY": sentinel_report,
        "SONNET_ESCALATION": (
            f"긴급 평가 결과: {escalation.urgency}\n"
            f"행동 필요: {escalation.action_needed}\n"
            f"근거: {escalation.reasoning}\n"
            f"제안: {escalation.suggested_action}"
        ),
    }


async def _gather_emergency_context(
    system: InjectedSystem,
    anomaly: AnomalyResult,
) -> dict:
    """긴급 판단에 필요한 시장 컨텍스트를 수집한다."""
    context: dict = {
        "emergency": True,
        "anomaly_count": len(anomaly.signals),
        "highest_level": anomaly.highest_level,
    }

    # 포지션 정보
    monitor = system.features.get("position_monitor")
    if monitor is not None:
        try:
            positions = monitor.get_all_positions()
            context["positions"] = [
                {
                    "ticker": t,
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "pnl_pct": p.pnl_pct,
                }
                for t, p in positions.items()
            ]
        except Exception:
            context["positions"] = []

    # 레짐 정보
    detector = system.features.get("regime_detector")
    if detector is not None:
        try:
            vf = system.features.get("vix_fetcher")
            vix = 20.0
            if vf is not None:
                vix = await vf.get_vix()
            regime = detector.detect(vix_value=vix)
            context["regime"] = regime.regime_type
        except Exception:
            context["regime"] = "unknown"

    # 캐시에서 최근 뉴스 요약 읽기
    try:
        news_data = await system.components.cache.read_json("news:latest_summary")
        if news_data and isinstance(news_data, dict):
            total = news_data.get("total_articles", 0)
            sentiment = news_data.get("sentiment_distribution", {})
            high_impact = news_data.get("high_impact_articles", [])
            summary_parts = [f"총 {total}건"]
            if sentiment:
                summary_parts.append(
                    f"bullish {sentiment.get('bullish', 0)}, "
                    f"bearish {sentiment.get('bearish', 0)}, "
                    f"neutral {sentiment.get('neutral', 0)}"
                )
            if high_impact:
                summary_parts.append(f"고영향 {len(high_impact)}건")
                for a in high_impact[:3]:
                    headline = a.get("headline", a.get("title", ""))
                    if headline:
                        summary_parts.append(f"  - {headline}")
            context["news_summary"] = " | ".join(summary_parts[:3]) + (
                "\n" + "\n".join(summary_parts[3:]) if len(summary_parts) > 3 else ""
            )
    except Exception:
        pass

    return context


def _parse_json(raw: str) -> dict:
    """AI 응답에서 JSON을 파싱한다."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning("JSON 파싱 실패: %s", raw[:200])
        return {}
