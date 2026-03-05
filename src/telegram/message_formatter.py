"""MessageFormatter -- 텔레그램 메시지를 HTML로 포맷팅한다.

매매 체결, 일일 보고서, 긴급 알림 등 다양한 템플릿을 지원한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.telegram.models import FormattedMessage

logger = get_logger(__name__)


def _fmt_trade(data: dict) -> str:
    """매매 체결 알림 템플릿이다."""
    action = data.get("action", "N/A")
    ticker = data.get("ticker", "N/A")
    qty = data.get("quantity", 0)
    price = data.get("price", 0.0)
    reason = data.get("reason", "")
    emoji = "BUY" if action == "buy" else "SELL"

    lines = [
        f"<b>[{emoji}] {ticker}</b>",
        f"수량: {qty} | 가격: ${price:,.2f}",
    ]
    if reason:
        lines.append(f"사유: {reason}")
    return "\n".join(lines)


def _fmt_daily_report(data: dict) -> str:
    """일일 보고서 템플릿이다."""
    s = data.get("summary", {})
    pnl = s.get("total_pnl_amount", 0.0)
    pnl_pct = s.get("total_pnl_pct", 0.0)
    trades = s.get("trade_count", 0)
    win = s.get("win_rate", 0.0)
    equity = s.get("total_equity", 0.0)

    lines = [
        "<b>[Daily Report]</b>",
        f"PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)",
        f"Trades: {trades} | Win: {win:.1f}%",
        f"Equity: ${equity:,.2f}",
    ]
    return "\n".join(lines)


def _fmt_emergency(data: dict) -> str:
    """긴급 알림 템플릿이다."""
    reason = data.get("reason", "알 수 없음")
    action = data.get("action", "긴급 정지")
    return f"<b>[EMERGENCY]</b>\n조치: {action}\n사유: {reason}"


def _fmt_positions(data: dict) -> str:
    """포지션 목록 템플릿이다."""
    positions = data.get("positions", [])
    if not positions:
        return "<b>[Positions]</b>\n보유 포지션 없음"
    lines = ["<b>[Positions]</b>"]
    for p in positions[:10]:
        t = p.get("ticker", "?")
        qty = p.get("quantity", 0)
        pnl = p.get("pnl_pct", 0.0)
        lines.append(f"  {t}: {qty}주 ({pnl:+.2f}%)")
    return "\n".join(lines)


# 템플릿 타입 매핑
_TEMPLATES: dict[str, object] = {
    "trade": _fmt_trade,
    "daily_report": _fmt_daily_report,
    "emergency": _fmt_emergency,
    "positions": _fmt_positions,
}


class MessageFormatter:
    """텔레그램 HTML 메시지 포맷터이다."""

    def format(self, data: dict, template_type: str) -> FormattedMessage:
        """데이터를 지정된 템플릿으로 포맷팅한다.

        Args:
            data: 포맷팅할 데이터
            template_type: 템플릿 타입 (trade, daily_report, emergency, positions)

        Returns:
            포맷팅된 메시지
        """
        formatter = _TEMPLATES.get(template_type)
        if formatter is None:
            logger.warning("알 수 없는 템플릿: %s", template_type)
            text = f"<b>[{template_type}]</b>\n{str(data)[:500]}"
            return FormattedMessage(text=text)

        try:
            text = formatter(data)  # type: ignore[operator]
        except Exception:
            logger.exception("메시지 포맷팅 실패: %s", template_type)
            text = f"<b>[{template_type}]</b>\n포맷팅 오류"
        return FormattedMessage(text=text)
