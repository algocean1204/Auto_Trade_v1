"""F7.21 TelegramNotifier -- 텔레그램 알림 포맷팅/발송이다.

매매 체결, 일일 보고서, 긴급 알림, 핵심 뉴스 등을 HTML 형식으로
TelegramSender를 통해 발송한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.common.telegram_gateway import TelegramSender, escape_html

_logger = get_logger(__name__)


def _format_trade(data: dict) -> str:
    """매매 체결 알림을 HTML로 포맷팅한다."""
    action = data.get("action", "N/A")
    ticker = escape_html(str(data.get("ticker", "N/A")))
    qty = data.get("quantity", 0)
    price = data.get("price", 0.0)
    reason = escape_html(str(data.get("reason", "")))
    emoji = "🟢" if action == "buy" else "🔴"

    lines = [
        f"{emoji} <b>매매 체결</b>",
        f"티커: <code>{ticker}</code>",
        f"방향: {escape_html(action.upper())} x{qty}",
        f"가격: ${price:,.2f}",
    ]
    if reason:
        lines.append(f"근거: {reason}")
    return "\n".join(lines)


def _format_daily_report(data: dict) -> str:
    """일일 보고서를 HTML로 포맷팅한다."""
    summary = data.get("summary", {})
    pnl = summary.get("total_pnl_amount", 0.0)
    pnl_pct = summary.get("total_pnl_pct", 0.0)
    trades = summary.get("trade_count", 0)
    win_rate = summary.get("win_rate", 0.0)
    equity = summary.get("total_equity", 0.0)
    emoji = "📈" if pnl >= 0 else "📉"

    lines = [
        f"{emoji} <b>일일 보고서</b>",
        f"손익: ${pnl:+,.2f} ({pnl_pct:+.2f}%)",
        f"매매: {trades}건 (승률 {win_rate:.1f}%)",
        f"총자산: ${equity:,.2f}",
    ]
    positions = data.get("positions", [])
    if positions:
        lines.append("\n<b>보유 포지션:</b>")
        for pos in positions[:5]:
            t = escape_html(str(pos.get("ticker", "?")))
            pnl_pos = pos.get("pnl_pct", 0.0)
            lines.append(f"  {t}: {pnl_pos:+.2f}%")
    return "\n".join(lines)


def _format_emergency(data: dict) -> str:
    """긴급 알림을 HTML로 포맷팅한다."""
    reason = escape_html(str(data.get("reason", "알 수 없는 사유")))
    action = escape_html(str(data.get("action", "긴급 정지")))
    return (
        f"🚨 <b>긴급 알림</b>\n"
        f"조치: {action}\n"
        f"사유: {reason}"
    )


def _format_news(data: dict) -> str:
    """핵심 뉴스 알림을 HTML로 포맷팅한다."""
    title = escape_html(str(data.get("title", "제목 없음")))
    impact = data.get("impact", "unknown")
    tickers = data.get("related_tickers", [])
    summary = escape_html(str(data.get("summary", "")))

    ticker_str = ", ".join(escape_html(str(t)) for t in tickers[:5]) if tickers else "없음"
    impact_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "⚪")

    lines = [
        f"📰 <b>핵심 뉴스</b>",
        f"영향도: {impact_emoji} {escape_html(impact.upper())}",
        f"제목: {title}",
        f"관련: {ticker_str}",
    ]
    if summary:
        lines.append(f"요약: {summary[:200]}")
    return "\n".join(lines)


# 이벤트 타입별 포맷터 매핑
_FORMATTERS: dict = {
    "trade": _format_trade,
    "daily_report": _format_daily_report,
    "emergency": _format_emergency,
    "news": _format_news,
}


class TelegramNotifier:
    """텔레그램 알림 포맷팅 + 발송 관리자이다."""

    def __init__(self, sender: TelegramSender) -> None:
        """TelegramSender를 주입받는다."""
        self._sender = sender
        _logger.info("TelegramNotifier 초기화 완료")

    async def notify(self, event_type: str, data: dict) -> bool:
        """이벤트를 포맷팅하여 텔레그램으로 발송한다.

        Args:
            event_type: 이벤트 타입 (trade, daily_report, emergency, news)
            data: 이벤트 데이터 딕셔너리

        Returns:
            발송 성공 여부
        """
        formatter = _FORMATTERS.get(event_type)
        if formatter is None:
            _logger.warning("알 수 없는 이벤트 타입: %s", event_type)
            return False

        try:
            message = formatter(data)
            result = await self._sender.send_text(message)
            if not result.success:
                _logger.error("텔레그램 발송 실패: %s", result.error)
            return result.success
        except Exception:
            _logger.exception("텔레그램 알림 발송 오류: %s", event_type)
            return False

    async def send_raw(self, message: str) -> bool:
        """포맷팅 없이 원본 HTML 메시지를 발송한다."""
        try:
            result = await self._sender.send_text(message)
            return result.success
        except Exception:
            _logger.exception("텔레그램 원본 메시지 발송 오류")
            return False
