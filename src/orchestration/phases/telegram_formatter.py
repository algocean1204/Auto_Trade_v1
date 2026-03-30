"""텔레그램 뉴스 포맷터 -- Claude Haiku로 2X 레버리지 ETF 단타용 뉴스를 정리한다.

모든 분류된 뉴스를 3개 섹션(핵심/일반/진행 상황)으로 나누어
직관적인 한국어 텔레그램 메시지를 생성한다.
카테고리 그룹핑, 긴급도 라벨, 소스 출처, 영향도 수치, 발행 시각,
감성 비율 시각화, 수집 시간 범위를 포함한다.
Haiku 호출 실패 시 동일 구조의 간단 포맷으로 폴백한다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.analysis.classifier.key_news_filter import HIGH_IMPACT_THRESHOLD
from src.common.ai_gateway import AiClient
from src.common.logger import get_logger
from src.common.telegram_gateway import escape_html

logger = get_logger(__name__)

_HIGH_IMPACT_THRESHOLD: float = HIGH_IMPACT_THRESHOLD
_KST = ZoneInfo("Asia/Seoul")

_DIRECTION_EMOJI: dict[str, str] = {
    "bullish": "📈",
    "bearish": "📉",
    "neutral": "➡️",
}

_CATEGORY_EMOJI: dict[str, str] = {
    "geopolitical": "🌍",
    "macro": "🏦",
    "earnings": "💰",
    "sector": "🏭",
    "policy": "📜",
    "other": "📰",
}

_CATEGORY_LABEL: dict[str, str] = {
    "geopolitical": "지정학",
    "macro": "거시경제",
    "earnings": "실적",
    "sector": "섹터",
    "policy": "정책",
    "other": "기타",
}

_ACTION_EMOJI: dict[str, str] = {
    "immediate": "🚨",
    "watch": "👀",
    "informational": "📋",
}

_SOURCE_DISPLAY: dict[str, str] = {
    "bloomberg_rss": "Bloomberg",
    "finnhub": "Finnhub",
    "marketwatch": "MarketWatch",
    "wsj_rss": "WSJ",
    "reuters": "Reuters",
    "cnbc": "CNBC",
    "yahoo_finance": "Yahoo",
    "fed_announcements": "FED",
    "alphavantage": "AlphaVantage",
}

_STATUS_EMOJI: dict[str, str] = {
    "escalating": "🔴",
    "stable": "🟡",
    "de_escalating": "🟢",
    "resolved": "✅",
}


# ──────────────────── 유틸리티 ────────────────────


def _parse_dt(raw: datetime | str | None) -> datetime | None:
    """published_at 필드를 datetime으로 파싱한다."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None
    return None


def _extract_time_range(
    articles: list[dict],
) -> tuple[datetime | None, datetime | None]:
    """기사 목록에서 가장 오래된/최신 발행 시각을 추출한다."""
    dates = [
        dt for a in articles
        if (dt := _parse_dt(a.get("published_at"))) is not None
    ]
    if not dates:
        return None, None
    return min(dates), max(dates)


def _format_time_range(
    oldest: datetime | None,
    newest: datetime | None,
) -> str:
    """시간 범위를 KST 문자열로 포맷한다."""
    if oldest is None or newest is None:
        return ""
    return (
        f"{oldest.astimezone(_KST).strftime('%m/%d %H:%M')}"
        f" ~ {newest.astimezone(_KST).strftime('%m/%d %H:%M')} KST"
    )


def _time_ago(published_at: datetime | str | None) -> str:
    """발행 시각을 'Xh전' 형식으로 반환한다."""
    dt = _parse_dt(published_at)
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = max(0.0, (now - dt).total_seconds())
    hours = int(secs // 3600)
    minutes = int((secs % 3600) // 60)
    if hours >= 24:
        return f"{hours // 24}d전"
    if hours > 0:
        return f"{hours}h전"
    if minutes > 0:
        return f"{minutes}m전"
    return "방금"


def _sentiment_bar(bullish: int, bearish: int, neutral: int) -> str:
    """텍스트 감성 비율 막대를 생성한다.

    ▓ = 약세, ▒ = 강세, ░ = 중립. 범례를 뒤에 붙여 구분한다.
    """
    total = bullish + bearish + neutral
    if total == 0:
        return ""
    size = 10
    b = round(bearish / total * size)
    u = round(bullish / total * size)
    n = max(0, size - b - u)
    b_pct = round(bearish / total * 100)
    u_pct = round(bullish / total * 100)
    n_pct = 100 - b_pct - u_pct
    bar = "▓" * b + "░" * n + "▒" * u
    return f"[{bar}] ▓약세{b_pct}% ▒강세{u_pct}% ░중립{n_pct}%"


def _source_name(source: str) -> str:
    """소스명을 표시명으로 변환한다."""
    return _SOURCE_DISPLAY.get(source, source)


def _extract_headline_kr(article: dict) -> str:
    """content에서 한국어 번역 제목을 추출한다."""
    content = article.get("content", "")
    if content.startswith("[한국어]"):
        lines = content.split("\n", 1)
        return lines[0].replace("[한국어]", "").strip()
    return ""


def _korean_title(article: dict) -> str:
    """한국어 제목을 우선 반환한다. 없으면 원문 제목을 반환한다.

    외부 뉴스 데이터이므로 HTML 특수문자를 이스케이프한다.
    """
    headline_kr = article.get("headline_kr") or _extract_headline_kr(article)
    raw = headline_kr if headline_kr else article.get("title", "제목 없음")
    return escape_html(str(raw))


# ──────────────────── Haiku 포맷 ────────────────────


_SYSTEM_PROMPT = """너는 미국 2X 레버리지 ETF(SOXL, QLD, TQQQ, UPRO, SSO) 단타 트레이더를 위한 뉴스 브리핑 전문가이다.

입력받은 뉴스를 반드시 아래 구조로 정리하라.

━━━━━━━━━━━━━━━━
📡 레버리지 ETF 뉴스 브리핑
📅 수집: {시작} ~ {종료} KST
━━━━━━━━━━━━━━━━

🔴 핵심 뉴스 (N건)

[카테고리별로 그룹핑]
{카테고리이모지} <b>{카테고리명}</b> (N건)
{긴급도} {방향} 한국어 제목 [Xh전] (출처) [0.85]
   영향: ETF 티커
   💡 레버리지 ETF 관점 한줄 요약

━━━━━━━━━━━━━━━━

📰 일반 뉴스 (N건)

{방향} 한국어 제목 [Xh전] (출처)

━━━━━━━━━━━━━━━━

⚠️ 진행 중인 상황

{상태이모지} 상황명 [{status}]
   평가: 한줄 평가

━━━━━━━━━━━━━━━━
📊 총 N건 | 📉약세 N | 📈강세 N | ➡️중립 N
{감성막대}
🕐 {현재시각} KST

규칙:
1. 핵심 뉴스 = impact_score >= 0.7. 반드시 카테고리별로 묶어서 표시
2. 일반 뉴스 = impact_score < 0.7. 방향+제목+시간+출처 한줄
3. 진행 중인 상황 = situation_reports. 없으면 섹션 생략
4. headline_kr이 있으면 반드시 사용. 없으면 title을 한국어로 직접 번역하여 표시
5. 카테고리: 🌍지정학 🏦거시경제 💰실적 🏭섹터 📜정책 📰기타
6. 방향: 📈강세 📉약세 ➡️중립
7. 긴급도: 🚨즉시대응 👀관찰 📋참고 (actionability 필드)
8. 상태: 🔴확전 🟡안정 🟢완화 ✅해결
9. 한국어 작성. 출처명/티커는 영어 허용
10. HTML <b>굵게</b> 사용
11. 4096자 제한 — 핵심만 간결하게
12. 번호 매기지 않는다
13. [Xh전] = time_ago 값을 그대로 사용
14. [0.85] = impact_score (핵심 뉴스만)
15. (출처) = source 필드를 괄호 안에 표시
16. 감성 막대 = 제공된 sentiment_bar 값을 그대로 사용
17. 📅 수집 범위는 제공된 time_range 값을 그대로 사용"""


async def format_news_for_telegram(
    ai: AiClient,
    articles: list[dict],
    situation_reports: list[Any] | None = None,
) -> str:
    """Claude Haiku로 전체 뉴스를 구조화된 텔레그램 메시지로 포맷한다.

    Haiku 실패 시 _simple_format으로 폴백한다.
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
        # Haiku가 지원되지 않는 HTML 태그를 생성할 수 있으므로 안전 변환한다
        import re
        # Telegram이 지원하는 태그만 허용한다: b, i, u, s, code, pre, a
        _ALLOWED = {"b", "i", "u", "s", "code", "pre", "a"}
        def _sanitize_tag(m: re.Match) -> str:
            tag_name = m.group(1).split()[0].lower().strip("/")
            return m.group(0) if tag_name in _ALLOWED else ""
        formatted = re.sub(r"<(/?\w[^>]*)>", _sanitize_tag, formatted)
        logger.info("[Haiku] 텔레그램 메시지 포맷팅 완료 (%d자)", len(formatted))
        return formatted
    except Exception as exc:
        logger.warning("[Haiku] 포맷팅 실패, 간단 포맷 폴백: %s", exc)
        return _simple_format(articles, situation_reports)


def _build_prompt(
    articles: list[dict],
    situation_reports: list[Any] | None = None,
) -> str:
    """Haiku에게 전달할 뉴스 데이터 프롬프트를 구성한다."""
    oldest, newest = _extract_time_range(articles)
    time_range = _format_time_range(oldest, newest)

    high_impact: list[dict] = []
    normal_impact: list[dict] = []

    for a in articles:
        entry = {
            "title": a.get("title", ""),
            "headline_kr": a.get("headline_kr") or _extract_headline_kr(a),
            "category": a.get("category", "other"),
            "direction": a.get("direction", "neutral"),
            "impact_score": a.get("impact_score", 0.0),
            "source": _source_name(a.get("source", "")),
            "tickers": a.get("tickers_affected", a.get("tickers", [])),
            "actionability": a.get("actionability", "informational"),
            "leveraged_etf_impact": a.get("leveraged_etf_impact", ""),
            "time_ago": _time_ago(a.get("published_at")),
        }
        if a.get("impact_score", 0.0) >= _HIGH_IMPACT_THRESHOLD:
            high_impact.append(entry)
        else:
            normal_impact.append(entry)

    high_impact = high_impact[:20]
    normal_impact = normal_impact[:30]

    total = len(articles)
    bullish = sum(1 for a in articles if a.get("direction") == "bullish")
    bearish = sum(1 for a in articles if a.get("direction") == "bearish")
    neutral = total - bullish - bearish
    bar = _sentiment_bar(bullish, bearish, neutral)

    prompt_parts: list[str] = [
        "다음 뉴스를 구조화된 브리핑으로 정리하라.",
    ]
    if time_range:
        prompt_parts.append(f"📅 수집 범위(그대로 사용): {time_range}")
    prompt_parts.extend([
        "",
        f"🔴 핵심 뉴스 ({len(high_impact)}건, impact >= 0.7):",
        json.dumps(high_impact, ensure_ascii=False, indent=2),
        "",
        f"📰 일반 뉴스 ({len(normal_impact)}건, impact < 0.7):",
        json.dumps(normal_impact, ensure_ascii=False, indent=2),
    ])

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
            f"⚠️ 진행 중인 상황 ({len(sit_data)}건):",
            json.dumps(sit_data, ensure_ascii=False, indent=2),
        ])

    prompt_parts.extend([
        "",
        f"통계: 총 {total}건, 강세 {bullish}, 약세 {bearish}, 중립 {neutral}",
        f"감성 막대(그대로 사용): {bar}",
    ])

    return "\n".join(prompt_parts)


# ──────────────────── 폴백 포맷 ────────────────────


def _format_key_news_section(high_impact: list[dict]) -> list[str]:
    """핵심 뉴스를 카테고리별로 그룹핑하여 포맷한다."""
    if not high_impact:
        return []

    lines: list[str] = [
        f"<b>🔴 핵심 뉴스</b> ({len(high_impact)}건)",
        "",
    ]

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for a in high_impact[:15]:
        by_cat[a.get("category", "other")].append(a)

    for cat, cat_articles in by_cat.items():
        cat_emoji = _CATEGORY_EMOJI.get(cat, "📰")
        cat_label = _CATEGORY_LABEL.get(cat, escape_html(cat))
        lines.append(f"{cat_emoji} <b>{cat_label}</b> ({len(cat_articles)}건)")

        for a in cat_articles:
            dir_emoji = _DIRECTION_EMOJI.get(
                a.get("direction", "neutral"), "➡️",
            )
            act_emoji = _ACTION_EMOJI.get(
                a.get("actionability", "informational"), "📋",
            )
            title = _korean_title(a)
            ago = _time_ago(a.get("published_at"))
            source = escape_html(_source_name(a.get("source", "")))
            score = a.get("impact_score", 0.0)

            meta = []
            if ago:
                meta.append(ago)
            if source:
                meta.append(source)
            meta.append(f"{score:.2f}")
            lines.append(
                f"{act_emoji}{dir_emoji} {title[:50]} [{' · '.join(meta)}]",
            )

            tickers = a.get("tickers_affected", a.get("tickers", []))
            if tickers:
                safe_tickers = [escape_html(str(t)) for t in tickers[:5]]
                lines.append(f"   영향: {', '.join(safe_tickers)}")

            etf_impact = a.get("leveraged_etf_impact", "")
            if etf_impact:
                lines.append(f"   💡 {escape_html(str(etf_impact)[:70])}")

        lines.append("")

    lines.extend(["━━━━━━━━━━━━━━━━", ""])
    return lines


def _format_normal_news_section(normal_impact: list[dict]) -> list[str]:
    """일반 뉴스를 한줄씩 포맷한다."""
    if not normal_impact:
        return []

    lines: list[str] = [
        f"<b>📰 일반 뉴스</b> ({len(normal_impact)}건)",
        "",
    ]

    for a in normal_impact[:20]:
        dir_emoji = _DIRECTION_EMOJI.get(
            a.get("direction", "neutral"), "➡️",
        )
        title = _korean_title(a)
        ago = _time_ago(a.get("published_at"))
        source = escape_html(_source_name(a.get("source", "")))

        meta = []
        if ago:
            meta.append(ago)
        if source:
            meta.append(source)
        suffix = f" [{' · '.join(meta)}]" if meta else ""
        lines.append(f"{dir_emoji} {title[:55]}{suffix}")

    lines.extend(["", "━━━━━━━━━━━━━━━━", ""])
    return lines


def _format_situation_section(situation_reports: list[Any]) -> list[str]:
    """진행 상황 섹션을 포맷한다."""
    if not situation_reports:
        return []

    lines: list[str] = [
        f"<b>⚠️ 진행 중인 상황</b> ({len(situation_reports)}건)",
        "",
    ]

    for r in situation_reports:
        name = r.name if hasattr(r, "name") else r.get("name", "")
        status = r.status if hasattr(r, "status") else r.get("status", "")
        assessment = (
            r.assessment if hasattr(r, "assessment")
            else r.get("assessment", "")
        )
        status_emoji = _STATUS_EMOJI.get(status, "🔴")
        lines.append(f"{status_emoji} {escape_html(str(name))} [{escape_html(str(status))}]")
        if assessment:
            lines.append(f"   평가: {escape_html(str(assessment)[:80])}")
        lines.append("")

    lines.extend(["━━━━━━━━━━━━━━━━", ""])
    return lines


def _simple_format(
    articles: list[dict],
    situation_reports: list[Any] | None = None,
) -> str:
    """Haiku 실패 시 사용하는 폴백 포맷이다.

    카테고리 그룹핑, 긴급도, 소스, 영향도, 시간, 감성 막대를 모두 포함한다.
    """
    oldest, newest = _extract_time_range(articles)
    time_range = _format_time_range(oldest, newest)

    lines: list[str] = [
        "━━━━━━━━━━━━━━━━",
        "<b>📡 레버리지 ETF 뉴스 브리핑</b>",
    ]
    if time_range:
        lines.append(f"📅 수집: {time_range}")
    lines.extend(["━━━━━━━━━━━━━━━━", ""])

    high = [a for a in articles if a.get("impact_score", 0.0) >= _HIGH_IMPACT_THRESHOLD]
    normal = [a for a in articles if a.get("impact_score", 0.0) < _HIGH_IMPACT_THRESHOLD]

    lines.extend(_format_key_news_section(high))
    lines.extend(_format_normal_news_section(normal))
    if situation_reports:
        lines.extend(_format_situation_section(situation_reports))

    total = len(articles)
    bullish = sum(1 for a in articles if a.get("direction") == "bullish")
    bearish = sum(1 for a in articles if a.get("direction") == "bearish")
    neutral = total - bullish - bearish

    lines.append(
        f"📊 총 {total}건 | 📉약세 {bearish} | 📈강세 {bullish} | ➡️중립 {neutral}",
    )
    bar = _sentiment_bar(bullish, bearish, neutral)
    if bar:
        lines.append(f"📈 감성: {bar}")
    now_kst = datetime.now(_KST).strftime("%Y-%m-%d %H:%M")
    lines.append(f"🕐 {now_kst} KST")

    result = "\n".join(lines)
    if len(result) > 4000:
        result = result[:3990] + "\n..."
    return result
