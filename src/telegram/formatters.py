"""
텔레그램 메시지 포맷터.

뉴스, 리포트, 분석 결과를 텔레그램에 최적화된 Markdown 형식으로
포맷팅한다. 이모지, 구분선, 공백을 활용하여 모바일에서 직관적으로
읽을 수 있도록 구성한다.
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 텔레그램 메시지 최대 길이 (안전 마진 포함)
_MAX_MESSAGE_LENGTH = 4000

# 한국어 매핑 테이블
_REGIME_KR: dict[str, str] = {
    "strong_bull": "강한 상승장",
    "mild_bull": "약한 상승장",
    "sideways": "횡보장",
    "mild_bear": "약한 하락장",
    "crash": "급락장",
    "unknown": "미확인",
}

_SAFETY_KR: dict[str, str] = {
    "NORMAL": "정상",
    "WARNING": "주의",
    "DANGER": "위험",
    "CRITICAL": "긴급",
}

_CATEGORY_KR: dict[str, str] = {
    "macro": "거시경제",
    "earnings": "실적",
    "sector": "섹터",
    "policy": "정책",
    "geopolitics": "지정학",
    "company": "기업",
    "other": "기타",
}

_IMPACT_KR: dict[str, str] = {
    "high": "높음",
    "medium": "중간",
    "low": "낮음",
}

_DIRECTION_KR: dict[str, str] = {
    "bullish": "강세",
    "bearish": "약세",
    "neutral": "중립",
}


def _truncate(text: str, max_len: int = _MAX_MESSAGE_LENGTH) -> str:
    """텔레그램 메시지 길이 제한에 맞게 잘라낸다."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n\n... (이하 생략)"


async def format_status(
    portfolio: dict[str, Any],
    safety_status: str,
    today_pnl: float,
    today_pnl_pct: float,
    emergency_status: dict[str, Any] | None = None,
) -> str:
    """시스템 상태를 포맷팅한다.

    Args:
        portfolio: 포트폴리오 요약 딕셔너리.
        safety_status: 안전 등급 문자열.
        today_pnl: 오늘 손익(USD).
        today_pnl_pct: 오늘 손익(%).
        emergency_status: 긴급 프로토콜 상태.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    pnl_emoji = "\U0001f4c8" if today_pnl >= 0 else "\U0001f4c9"  # chart up/down
    total_value = portfolio.get("total_value", 0.0)
    cash = portfolio.get("cash", 0.0)
    position_count = portfolio.get("position_count", 0)

    # 안전 등급 이모지
    safety_emoji = {
        "NORMAL": "\U0001f7e2",   # green
        "WARNING": "\U0001f7e1",  # yellow
        "DANGER": "\U0001f534",   # red
        "CRITICAL": "\U0001f6a8",  # police light
    }.get(safety_status, "\u2753")  # question mark

    lines = [
        "\U0001f4ca *시스템 상태*",
        "\u2500" * 16,
        "",
        f"\U0001f4b0 총 자산: ${total_value:,.2f}",
        f"\U0001f4b5 현금: ${cash:,.2f}",
        f"\U0001f4c1 활성 포지션: {position_count}개",
        "",
        f"{pnl_emoji} 일일 손익: ${today_pnl:+,.2f} ({today_pnl_pct:+.2f}%)",
        f"{safety_emoji} 안전 등급: {_SAFETY_KR.get(safety_status, safety_status)}",
    ]

    if emergency_status:
        cb = emergency_status.get("circuit_breaker_active", False)
        rl = emergency_status.get("runaway_loss_shutdown", False)
        if cb or rl:
            lines.append("")
            lines.append("\U0001f6a8 *긴급 상태*")
            if cb:
                lines.append("  - Circuit Breaker 발동 중")
            if rl:
                lines.append("  - 손실 비상 정지 활성화")

    return _truncate("\n".join(lines))


async def format_positions(positions: list[dict[str, Any]]) -> str:
    """보유 포지션 목록을 포맷팅한다.

    Args:
        positions: 포지션 딕셔너리 리스트.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    if not positions:
        return "\U0001f4c1 *보유 포지션*\n\n보유 중인 포지션이 없습니다."

    lines = [
        f"\U0001f4c1 *보유 포지션* ({len(positions)}개)",
        "\u2500" * 16,
    ]

    for pos in positions:
        ticker = pos.get("ticker", "N/A")
        qty = pos.get("quantity", 0)
        avg_price = pos.get("avg_price", 0.0)
        current_price = pos.get("current_price", 0.0)
        pnl_pct = pos.get("pnl_pct", 0.0)
        pnl_amount = pos.get("pnl_amount", 0.0)

        pnl_emoji = "\U0001f4c8" if pnl_pct >= 0 else "\U0001f4c9"

        lines.append("")
        lines.append(f"*{ticker}* {pnl_emoji}")
        lines.append(f"  수량: {qty}주 | 평균가: ${avg_price:.2f}")
        lines.append(f"  현재가: ${current_price:.2f}")
        lines.append(f"  손익: ${pnl_amount:+,.2f} ({pnl_pct:+.2f}%)")

    return _truncate("\n".join(lines))


async def format_news(articles: list[dict[str, Any]]) -> str:
    """뉴스 기사 목록을 포맷팅한다.

    Args:
        articles: 기사 딕셔너리 리스트.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    if not articles:
        return "\U0001f4f0 *뉴스 브리핑*\n\n최근 주요 뉴스가 없습니다."

    # 카테고리별 이모지
    category_emoji = {
        "macro": "\U0001f30d",      # globe
        "earnings": "\U0001f4b5",   # dollar
        "sector": "\U0001f3ed",     # factory
        "policy": "\U0001f3db",     # classical building (policy)
        "geopolitics": "\u2694\ufe0f",  # swords
        "company": "\U0001f3e2",    # office building
        "other": "\U0001f4cb",      # clipboard
    }

    # 영향도별 이모지
    impact_emoji = {
        "high": "\U0001f534",    # red
        "medium": "\U0001f7e1",  # yellow
        "low": "\U0001f7e2",     # green
    }

    lines = [
        f"\U0001f4f0 *주요 뉴스 브리핑*",
        "\u2501" * 16,
    ]

    high_count = sum(1 for a in articles if a.get("impact") == "high")

    for i, article in enumerate(articles):
        if i > 0:
            lines.append("\u2500" * 16)

        category = article.get("category", "other")
        impact = article.get("impact", "low")
        headline = article.get("headline", article.get("title", "N/A"))
        source = article.get("source", "")
        tickers = article.get("tickers", article.get("tickers_mentioned", []))
        sentiment = article.get("sentiment_score", 0.0)
        direction = article.get("direction", "neutral")

        cat_e = category_emoji.get(category, "\U0001f4cb")
        imp_e = impact_emoji.get(impact, "\U0001f7e2")
        category_label = _CATEGORY_KR.get(category, category)
        impact_label = _IMPACT_KR.get(impact, impact)
        direction_label = _DIRECTION_KR.get(direction, direction)

        dir_emoji = (
            "\U0001f4c8" if direction == "bullish"
            else "\U0001f4c9" if direction == "bearish"
            else "\u27a1\ufe0f"
        )

        lines.append("")
        lines.append(f"{imp_e} *[{category_label}]* {headline}")
        if source:
            lines.append(f"  {cat_e} {source} | 영향도: {impact_label} | {dir_emoji} {direction_label}")
        else:
            lines.append(f"  영향도: {impact_label} | {dir_emoji} {direction_label}")
        ticker_str = ", ".join(tickers[:5]) if tickers else "-"
        lines.append(f"  관련 종목: {ticker_str}")

        # 기업별 영향 분석 (최대 3개 티커)
        companies_impact = article.get("companies_impact") or {}
        if companies_impact and isinstance(companies_impact, dict):
            for ticker, impact_text in list(companies_impact.items())[:3]:
                lines.append(f"  \U0001f4cc {ticker}: {impact_text}")

    lines.append("")
    lines.append("\u2501" * 16)
    lines.append(f"\U0001f4a1 총 {len(articles)}건 중 주요 뉴스 {high_count}건")

    return _truncate("\n".join(lines))


async def format_analysis(
    ticker: str,
    rsi_data: dict[str, Any] | None = None,
    price_data: dict[str, Any] | None = None,
    regime: str = "unknown",
) -> str:
    """종목 분석 결과를 포맷팅한다.

    Args:
        ticker: 종목 티커.
        rsi_data: RSI 분석 데이터.
        price_data: 가격 데이터.
        regime: 현재 시장 레짐.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    lines = [
        f"\U0001f50d *{ticker} 분석*",
        "\u2500" * 16,
    ]

    if price_data:
        current = price_data.get("current_price", 0.0)
        change_pct = price_data.get("change_pct", 0.0)
        change_emoji = "\U0001f4c8" if change_pct >= 0 else "\U0001f4c9"
        lines.append("")
        lines.append(f"\U0001f4b2 현재가: ${current:.2f} ({change_pct:+.2f}%) {change_emoji}")

    if rsi_data:
        rsi_7 = rsi_data.get("rsi_7", 0.0)
        rsi_14 = rsi_data.get("rsi_14", 0.0)
        rsi_21 = rsi_data.get("rsi_21", 0.0)
        signal = rsi_data.get("signal_9", 0.0)

        def _rsi_label(val: float) -> str:
            if val >= 70:
                return "과매수"
            elif val <= 30:
                return "과매도"
            return "중립"

        lines.append("")
        lines.append("*Triple RSI*")
        lines.append(f"  RSI(7):  {rsi_7:.1f} - {_rsi_label(rsi_7)}")
        lines.append(f"  RSI(14): {rsi_14:.1f} - {_rsi_label(rsi_14)}")
        lines.append(f"  RSI(21): {rsi_21:.1f} - {_rsi_label(rsi_21)}")
        lines.append(f"  Signal(9): {signal:.1f}")

    lines.append("")
    regime_emoji = {
        "strong_bull": "\U0001f680",
        "mild_bull": "\U0001f4c8",
        "sideways": "\u27a1\ufe0f",
        "mild_bear": "\U0001f4c9",
        "crash": "\U0001f4a5",
    }.get(regime, "\u2753")
    regime_label = _REGIME_KR.get(regime, regime)
    lines.append(f"{regime_emoji} 시장 레짐: {regime_label}")

    return _truncate("\n".join(lines))


async def format_report(report: dict[str, Any]) -> str:
    """일일 리포트를 포맷팅한다.

    Args:
        report: 일일 리포트 딕셔너리.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    if not report:
        return "\U0001f4c4 *일일 리포트*\n\n오늘의 리포트가 아직 생성되지 않았습니다."

    date = report.get("date", report.get("report_date", "N/A"))
    total_pnl = report.get("total_pnl", report.get("daily_pnl", 0.0))
    total_pnl_pct = report.get("total_pnl_pct", report.get("daily_pnl_pct", 0.0))
    trade_count = report.get("trade_count", 0)
    win_rate = report.get("win_rate", 0.0)
    best_trade = report.get("best_trade", {})
    worst_trade = report.get("worst_trade", {})

    pnl_emoji = "\U0001f4c8" if total_pnl >= 0 else "\U0001f4c9"

    lines = [
        f"\U0001f4c4 *일일 리포트* ({date})",
        "\u2501" * 16,
        "",
        f"{pnl_emoji} 일일 손익: ${total_pnl:+,.2f} ({total_pnl_pct:+.2f}%)",
        f"\U0001f504 거래 수: {trade_count}건",
        f"\U0001f3af 승률: {win_rate:.1f}%",
    ]

    if best_trade:
        bt = best_trade.get("ticker", "N/A")
        bp = best_trade.get("pnl_pct", 0.0)
        lines.append(f"\U0001f31f 최고 매매: {bt} ({bp:+.2f}%)")

    if worst_trade:
        wt = worst_trade.get("ticker", "N/A")
        wp = worst_trade.get("pnl_pct", 0.0)
        lines.append(f"\U0001f4a2 최저 매매: {wt} ({wp:+.2f}%)")

    return _truncate("\n".join(lines))


async def format_balance(balance: dict[str, Any]) -> str:
    """계좌 잔고 정보를 포맷팅한다.

    Args:
        balance: 잔고 딕셔너리.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    total = balance.get("total_value", 0.0)
    cash = balance.get("cash", balance.get("available_cash", 0.0))
    invested = balance.get("invested", total - cash)
    margin_used = balance.get("margin_used", 0.0)

    lines = [
        "\U0001f4b0 *계좌 잔고*",
        "\u2500" * 16,
        "",
        f"\U0001f3e6 총 자산: ${total:,.2f}",
        f"\U0001f4b5 현금: ${cash:,.2f}",
        f"\U0001f4c8 투자금: ${invested:,.2f}",
    ]

    if margin_used > 0:
        lines.append(f"\u26a0\ufe0f 마진 사용: ${margin_used:,.2f}")

    # 현금 비율
    if total > 0:
        cash_ratio = (cash / total) * 100
        lines.append(f"\U0001f4ca 현금 비율: {cash_ratio:.1f}%")

    return _truncate("\n".join(lines))


async def format_help(is_admin: bool) -> str:
    """사용 가능한 명령어 도움말을 포맷팅한다.

    Args:
        is_admin: 관리자(User 1)인지 여부.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    lines = [
        "\U0001f4d6 *사용 가능한 명령어*",
        "\u2501" * 16,
        "",
        "*조회 명령어*",
        "  /status (/s) - 시스템 상태",
        "  /positions (/p) - 보유 포지션",
        "  /news (/n) - 최근 주요 뉴스",
        "  /news [카테고리] - 카테고리별 뉴스",
        "  /analyze [티커] (/a) - 종목 분석",
        "  /report (/r) - 일일 리포트",
        "  /balance (/b) - 계좌 잔고",
        "  /help (/h) - 이 도움말",
    ]

    if is_admin:
        lines.extend([
            "",
            "*관리 명령어* (관리자 전용)",
            "  /stop - 매매 긴급 중단",
            "  /resume - 매매 재개",
            "  /buy [티커] [금액] - 매수 지시",
            "  /sell [티커] [금액|all] - 매도 지시",
            "  /confirm - 대기 중 주문 확인",
            "  /cancel - 대기 중 주문 취소",
        ])

    lines.extend([
        "",
        "\u2500" * 16,
        "\U0001f4ac 자연어로도 질문 가능합니다",
        '  예: "포지션 보여줘", "SOXL 어때?"',
    ])

    return "\n".join(lines)


async def format_trade_confirmation(
    direction: str,
    ticker: str,
    amount: str,
) -> str:
    """매매 확인 메시지를 포맷팅한다.

    Args:
        direction: "buy" 또는 "sell".
        ticker: 종목 티커.
        amount: 금액 또는 수량 문자열.

    Returns:
        포맷된 텔레그램 메시지 문자열.
    """
    direction_kr = "매수" if direction == "buy" else "매도"
    emoji = "\U0001f7e2" if direction == "buy" else "\U0001f534"

    lines = [
        f"{emoji} *{direction_kr} 주문 확인*",
        "\u2500" * 16,
        "",
        f"종목: *{ticker}*",
        f"금액: {amount}",
        "",
        f"/confirm - {direction_kr} 실행",
        f"/cancel - 주문 취소",
        "",
        "\u23f0 30초 내 응답이 없으면 자동 취소됩니다.",
    ]

    return "\n".join(lines)


async def format_permission_denied() -> str:
    """권한 부족 메시지를 반환한다."""
    return (
        "\U0001f6ab *접근 권한 없음*\n\n"
        "이 명령은 관리자만 사용할 수 있습니다.\n"
        "조회 명령어(/status, /positions 등)는 사용 가능합니다."
    )


async def format_rate_limited() -> str:
    """Rate limit 초과 메시지를 반환한다."""
    return (
        "\u26a0\ufe0f *요청 제한 초과*\n\n"
        "분당 최대 30회 명령을 사용할 수 있습니다.\n"
        "잠시 후 다시 시도해 주세요."
    )
