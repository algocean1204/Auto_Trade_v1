"""텔레그램 뉴스 포맷터 -- Claude Haiku로 2X 레버리지 ETF 단타용 뉴스를 정리한다.

모든 분류된 뉴스를 3개 섹션(핵심/일반/진행 상황)으로 나누어
직관적인 한국어 텔레그램 메시지를 생성한다.
Haiku 호출 실패 시 동일한 3섹션 구조의 간단 포맷으로 폴백한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.common.ai_gateway import AiClient
from src.common.logger import get_logger

logger = get_logger(__name__)

# 고영향 뉴스 임팩트 임계값이다
_HIGH_IMPACT_THRESHOLD: float = 0.7

# 방향 → 이모지 매핑이다
_DIRECTION_EMOJI: dict[str, str] = {
    "bullish": "📈",
    "bearish": "📉",
    "neutral": "➡️",
}

# 카테고리 → 이모지 매핑이다
_CATEGORY_EMOJI: dict[str, str] = {
    "geopolitical": "🌍",
    "macro": "🏦",
    "earnings": "💰",
    "sector": "🏭",
    "policy": "📜",
    "other": "📰",
}

# actionability → 이모지/라벨 매핑이다
_ACTION_EMOJI: dict[str, str] = {
    "immediate": "🚨",
    "watch": "👀",
    "informational": "📋",
}

# 상황 상태 → 이모지 매핑이다
_STATUS_EMOJI: dict[str, str] = {
    "escalating": "🔴",
    "stable": "🟡",
    "de_escalating": "🟢",
    "resolved": "✅",
}

_SYSTEM_PROMPT = """너는 미국 2X 레버리지 ETF(SOXL, QLD, TQQQ, UPRO, SSO) 단타 트레이더를 위한 뉴스 브리핑 전문가이다.

입력받은 뉴스를 반드시 아래 3개 섹션 구조로 정리하라.

━━━━━━━━━━━━━━━━
📡 레버리지 ETF 뉴스 브리핑
━━━━━━━━━━━━━━━━

🔴 핵심 뉴스 (N건)

[각 핵심 뉴스는 아래 형식으로 작성]
{카테고리이모지} {방향이모지} 한국어 제목 한줄
   영향: {영향받는 ETF 티커}
   💡 레버리지 ETF 관점 한줄 요약

━━━━━━━━━━━━━━━━

📰 일반 뉴스 (N건)

[각 일반 뉴스는 한줄 요약 — 방향이모지 + 한국어 제목만]
{방향이모지} 한국어 제목

━━━━━━━━━━━━━━━━

⚠️ 진행 중인 상황

[각 상황은 아래 형식]
{상태이모지} 상황명 [{status}]
   평가: 한줄 평가

━━━━━━━━━━━━━━━━
📊 총 N건 | 강세 N | 약세 N | 중립 N
🕐 {현재시각} KST

규칙:
1. 핵심 뉴스 = impact_score >= 0.7인 뉴스. 상세 포맷 (제목 + 영향 ETF + 💡요약)
2. 일반 뉴스 = impact_score < 0.7인 뉴스. 방향이모지 + 제목 한줄만
3. 진행 중인 상황 = situation_reports 데이터. 없으면 섹션 생략
4. headline_kr(한국어 번역 제목)이 있으면 반드시 그것을 사용하라
5. headline_kr가 없으면 title(원문)을 사용하라
6. 카테고리 이모지: 🌍지정학 🏦거시경제 💰실적 🏭섹터 📜정책 📰기타
7. 방향 이모지: 📈강세 📉약세 ➡️중립
8. 상태 이모지: 🔴확전 🟡안정 🟢완화 ✅해결
9. 모든 내용은 한국어로 작성. 영어 사용 금지
10. HTML: <b>굵게</b>, 줄바꿈은 \\n
11. 4096자 제한이므로 핵심만 간결하게
12. 번호 매기지 않는다
13. 마지막에 📊 통계 줄과 🕐 시각 줄을 반드시 포함하라"""


async def format_news_for_telegram(
    ai: AiClient,
    articles: list[dict],
    situation_reports: list[Any] | None = None,
) -> str:
    """Claude Haiku로 전체 뉴스를 3섹션(핵심/일반/상황) 구조로 정리하여 텔레그램 메시지를 생성한다.

    articles에는 분류된 전체 뉴스(핵심+일반 모두)가 포함된다.
    Haiku 실패 시 동일 구조의 _simple_format으로 폴백한다.
    """
    if not articles:
        return ""

    try:
        prompt = _build_prompt(articles, situation_reports)
        response = await ai.send_text(
            prompt=prompt,
            system=_SYSTEM_PROMPT,
            model="haiku",
            max_tokens=2000,
        )
        formatted = response.content.strip()
        if len(formatted) > 4000:
            formatted = formatted[:3990] + "\n..."
        logger.info("[Haiku] 텔레그램 메시지 포맷팅 완료 (%d자)", len(formatted))
        return formatted
    except Exception as exc:
        logger.warning("[Haiku] 포맷팅 실패, 간단 포맷 폴백: %s", exc)
        return _simple_format(articles, situation_reports)


def _build_prompt(
    articles: list[dict],
    situation_reports: list[Any] | None = None,
) -> str:
    """Haiku에게 전달할 전체 뉴스 데이터 프롬프트를 구성한다.

    핵심 뉴스와 일반 뉴스를 구분하여 전달한다.
    """
    high_impact: list[dict] = []
    normal_impact: list[dict] = []

    for a in articles:
        entry = {
            "title": a.get("title", ""),
            "headline_kr": a.get("headline_kr") or _extract_headline_kr(a),
            "category": a.get("category", "other"),
            "direction": a.get("direction", "neutral"),
            "impact_score": a.get("impact_score", 0.0),
            "source": a.get("source", ""),
            "tickers": a.get("tickers_affected", a.get("tickers", [])),
            "actionability": a.get("actionability", "informational"),
            "time_sensitivity": a.get("time_sensitivity", "analysis"),
            "leveraged_etf_impact": a.get("leveraged_etf_impact", ""),
        }
        if a.get("impact_score", 0.0) >= _HIGH_IMPACT_THRESHOLD:
            high_impact.append(entry)
        else:
            normal_impact.append(entry)

    # 핵심 뉴스는 최대 20건, 일반 뉴스는 최대 30건으로 제한한다
    high_impact = high_impact[:20]
    normal_impact = normal_impact[:30]

    prompt_parts: list[str] = [
        "다음 뉴스를 3섹션(핵심/일반/진행상황) 구조로 정리하라.",
        "",
        f"🔴 핵심 뉴스 ({len(high_impact)}건, impact >= 0.7):",
        json.dumps(high_impact, ensure_ascii=False, indent=2),
        "",
        f"📰 일반 뉴스 ({len(normal_impact)}건, impact < 0.7):",
        json.dumps(normal_impact, ensure_ascii=False, indent=2),
    ]

    if situation_reports:
        sit_data: list[dict] = []
        for r in situation_reports:
            sit_dict = r.model_dump() if hasattr(r, "model_dump") else r
            sit_data.append({
                "name": sit_dict.get("name", ""),
                "status": sit_dict.get("status", ""),
                "assessment": sit_dict.get("assessment", "")[:200],
            })
        prompt_parts.extend([
            "",
            f"⚠️ 진행 중인 상황 보고서 ({len(sit_data)}건):",
            json.dumps(sit_data, ensure_ascii=False, indent=2),
        ])

    # 통계 정보를 프롬프트에 포함한다
    total = len(articles)
    bullish = sum(1 for a in articles if a.get("direction") == "bullish")
    bearish = sum(1 for a in articles if a.get("direction") == "bearish")
    neutral = total - bullish - bearish
    prompt_parts.extend([
        "",
        f"통계: 총 {total}건, 강세 {bullish}, 약세 {bearish}, 중립 {neutral}",
    ])

    return "\n".join(prompt_parts)


def _extract_headline_kr(article: dict) -> str:
    """content에서 한국어 번역 제목을 추출한다."""
    content = article.get("content", "")
    if content.startswith("[한국어]"):
        lines = content.split("\n", 1)
        return lines[0].replace("[한국어]", "").strip()
    return ""


def _get_korean_title(article: dict) -> str:
    """한국어 제목을 우선 반환한다. 없으면 원문 제목을 반환한다."""
    headline_kr = article.get("headline_kr") or _extract_headline_kr(article)
    if headline_kr:
        return headline_kr
    return article.get("title", "제목 없음")


def _simple_format(
    articles: list[dict],
    situation_reports: list[Any] | None = None,
) -> str:
    """Haiku 실패 시 사용하는 3섹션 포맷이다.

    핵심 뉴스(상세), 일반 뉴스(한줄), 진행 상황을 구분하여 직관적으로 표시한다.
    """
    lines: list[str] = [
        "━━━━━━━━━━━━━━━━",
        "<b>📡 레버리지 ETF 뉴스 브리핑</b>",
        "━━━━━━━━━━━━━━━━",
        "",
    ]

    # 핵심 뉴스와 일반 뉴스를 분리한다
    high_impact: list[dict] = []
    normal_impact: list[dict] = []
    for a in articles:
        if a.get("impact_score", 0.0) >= _HIGH_IMPACT_THRESHOLD:
            high_impact.append(a)
        else:
            normal_impact.append(a)

    # --- 섹션 1: 핵심 뉴스 (상세 포맷) ---
    if high_impact:
        lines.append(f"<b>🔴 핵심 뉴스</b> ({len(high_impact)}건)")
        lines.append("")

        for a in high_impact[:15]:
            cat_emoji = _CATEGORY_EMOJI.get(a.get("category", "other"), "📰")
            dir_emoji = _DIRECTION_EMOJI.get(a.get("direction", "neutral"), "➡️")
            title = _get_korean_title(a)

            # 제목 줄
            lines.append(f"{cat_emoji} {dir_emoji} {title[:60]}")

            # 영향 ETF 표시
            tickers = a.get("tickers_affected", a.get("tickers", []))
            if tickers:
                lines.append(f"   영향: {', '.join(tickers[:5])}")

            # 레버리지 ETF 영향 요약
            etf_impact = a.get("leveraged_etf_impact", "")
            if etf_impact:
                lines.append(f"   💡 {etf_impact[:80]}")

            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("")

    # --- 섹션 2: 일반 뉴스 (한줄 요약) ---
    if normal_impact:
        lines.append(f"<b>📰 일반 뉴스</b> ({len(normal_impact)}건)")
        lines.append("")

        for a in normal_impact[:25]:
            dir_emoji = _DIRECTION_EMOJI.get(a.get("direction", "neutral"), "➡️")
            title = _get_korean_title(a)
            lines.append(f"{dir_emoji} {title[:60]}")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("")

    # --- 섹션 3: 진행 중인 상황 ---
    if situation_reports:
        lines.append(f"<b>⚠️ 진행 중인 상황</b> ({len(situation_reports)}건)")
        lines.append("")

        for r in situation_reports:
            name = r.name if hasattr(r, "name") else r.get("name", "")
            status = r.status if hasattr(r, "status") else r.get("status", "")
            assessment = (
                r.assessment if hasattr(r, "assessment") else r.get("assessment", "")
            )
            status_emoji = _STATUS_EMOJI.get(status, "🔴")

            lines.append(f"{status_emoji} {name} [{status}]")
            if assessment:
                lines.append(f"   평가: {assessment[:80]}")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━")
        lines.append("")

    # --- 통계 푸터 ---
    total = len(articles)
    bullish = sum(1 for a in articles if a.get("direction") == "bullish")
    bearish = sum(1 for a in articles if a.get("direction") == "bearish")
    neutral = total - bullish - bearish

    now_kst = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines.append(f"📊 총 {total}건 | 강세 {bullish} | 약세 {bearish} | 중립 {neutral}")
    lines.append(f"🕐 {now_kst} UTC")

    result = "\n".join(lines)

    # 텔레그램 4096자 제한을 준수한다
    if len(result) > 4000:
        result = result[:3990] + "\n..."

    return result
