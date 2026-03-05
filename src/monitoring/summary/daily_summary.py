"""F7.30 DailySummary -- 일일 매매 요약을 텔레그램으로 발송한다.

EOD 시퀀스에서 호출되어 당일 매매 내역과 성과를 집계하고
보기 좋은 HTML 형식으로 텔레그램 알림을 보낸다.
trades:today 삭제(Step 9) 이전에 호출해야 한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.common.logger import get_logger
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """값을 float로 안전하게 변환한다."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _compute_stats(
    trades: list[dict[str, Any]], pnl_data: dict[str, Any],
) -> dict[str, Any]:
    """매매 목록에서 요약 통계를 계산한다."""
    total = len(trades)
    if total == 0:
        return {"total": 0}

    pnls = [_safe_float(t.get("pnl", t.get("realized_pnl", 0))) for t in trades]
    total_pnl = _safe_float(pnl_data.get("total_pnl", sum(pnls)))
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / total * 100 if total > 0 else 0.0

    # 최고/최저 거래를 식별한다
    best_idx = max(range(len(pnls)), key=lambda i: pnls[i])
    worst_idx = min(range(len(pnls)), key=lambda i: pnls[i])

    # 티커별 집계
    by_ticker: dict[str, dict[str, Any]] = {}
    for t in trades:
        ticker = t.get("ticker", t.get("symbol", "UNKNOWN"))
        pnl = _safe_float(t.get("pnl", t.get("realized_pnl", 0)))
        entry = by_ticker.setdefault(ticker, {"count": 0, "pnl": 0.0})
        entry["count"] += 1
        entry["pnl"] += pnl

    # 청산 사유별 집계
    by_reason: dict[str, int] = {}
    for t in trades:
        reason = t.get("exit_reason", t.get("close_reason", "unknown"))
        by_reason[reason] = by_reason.get(reason, 0) + 1

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "best_trade": trades[best_idx],
        "best_pnl": pnls[best_idx],
        "worst_trade": trades[worst_idx],
        "worst_pnl": pnls[worst_idx],
        "by_ticker": by_ticker,
        "by_reason": by_reason,
    }


def _format_telegram_html(stats: dict[str, Any]) -> str:
    """통계를 텔레그램 HTML 메시지로 포맷팅한다."""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    total = stats.get("total", 0)

    if total == 0:
        return (
            f"<b>[Daily Summary] {today}</b>\n\n"
            "오늘 체결된 매매가 없습니다."
        )

    pnl = stats["total_pnl"]
    emoji = "📈" if pnl >= 0 else "📉"
    win_rate = stats["win_rate"]

    lines = [
        f"{emoji} <b>[Daily Summary] {today}</b>",
        "",
        f"<b>총 매매:</b> {total}건 (승 {stats['wins']} / 패 {stats['losses']})",
        f"<b>승률:</b> {win_rate:.1f}%",
        f"<b>총 손익:</b> ${pnl:+,.2f}",
    ]

    # 최고/최저 거래
    best = stats["best_trade"]
    worst = stats["worst_trade"]
    lines.append("")
    lines.append(
        f"<b>Best:</b> {best.get('ticker', '?')} "
        f"${stats['best_pnl']:+,.2f}"
    )
    lines.append(
        f"<b>Worst:</b> {worst.get('ticker', '?')} "
        f"${stats['worst_pnl']:+,.2f}"
    )

    # 티커별 내역
    by_ticker: dict[str, dict] = stats.get("by_ticker", {})
    if by_ticker:
        lines.append("")
        lines.append("<b>티커별:</b>")
        # PnL 내림차순 정렬
        sorted_tickers = sorted(
            by_ticker.items(), key=lambda x: x[1]["pnl"], reverse=True,
        )
        for ticker, info in sorted_tickers:
            t_emoji = "🟢" if info["pnl"] >= 0 else "🔴"
            lines.append(
                f"  {t_emoji} {ticker}: {info['count']}건 "
                f"${info['pnl']:+,.2f}"
            )

    # 청산 사유별 내역
    by_reason: dict[str, int] = stats.get("by_reason", {})
    if by_reason:
        lines.append("")
        lines.append("<b>청산 사유:</b>")
        for reason, count in sorted(by_reason.items(), key=lambda x: -x[1]):
            lines.append(f"  • {reason}: {count}건")

    return "\n".join(lines)


async def send_daily_summary(
    system: InjectedSystem,
    trades: list[dict[str, Any]],
    pnl_data: dict[str, Any],
) -> bool:
    """일일 매매 요약을 집계하여 텔레그램으로 발송한다.

    Args:
        system: DI 시스템
        trades: 당일 거래 목록 (trades:today)
        pnl_data: 당일 PnL 데이터 (pnl:daily)

    Returns:
        발송 성공 여부
    """
    try:
        stats = _compute_stats(trades, pnl_data)
        html = _format_telegram_html(stats)
        await system.components.telegram.send_text(html)
        logger.info(
            "일일 매매 요약 발송 완료: %d건, PnL=$%.2f",
            stats.get("total", 0),
            stats.get("total_pnl", 0.0),
        )
        return True
    except Exception:
        logger.exception("일일 매매 요약 발송 실패")
        return False
