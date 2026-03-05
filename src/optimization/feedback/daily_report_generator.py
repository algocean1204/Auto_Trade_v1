"""FF 피드백 -- Markdown 일일 보고서 생성이다."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.common.logger import get_logger
from src.optimization.feedback.models import DailyReport

logger = get_logger(__name__)

# 보고서 저장 디렉토리이다
_REPORT_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "reports"
)


def _safe_float(val: object, default: float = 0.0) -> float:
    """안전하게 float 변환한다."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _build_header(date_str: str) -> str:
    """보고서 헤더를 생성한다."""
    return f"# 일일 트레이딩 보고서 ({date_str})\n\n"


def _build_portfolio_section(portfolio: dict) -> str:
    """포트폴리오 섹션을 생성한다."""
    lines: list[str] = ["## 포트폴리오 현황\n"]
    lines.append(f"- 총 자산: ${_safe_float(portfolio.get('total_value')):,.2f}")
    lines.append(f"- 현금: ${_safe_float(portfolio.get('cash')):,.2f}")
    lines.append(f"- 포지션 수: {portfolio.get('position_count', 0)}")
    lines.append(f"- 일일 PnL: ${_safe_float(portfolio.get('daily_pnl')):,.2f}\n")
    return "\n".join(lines)


def _build_trades_section(trades: list[dict]) -> str:
    """거래 내역 섹션을 생성한다."""
    lines: list[str] = ["\n## 거래 내역\n"]

    if not trades:
        lines.append("거래 없음\n")
        return "\n".join(lines)

    lines.append("| 틱커 | 방향 | PnL | 보유시간 |")
    lines.append("|------|------|-----|---------|")

    for t in trades:
        ticker = t.get("ticker", "N/A")
        side = t.get("side", "N/A")
        pnl = _safe_float(t.get("pnl"))
        hold = _safe_float(t.get("hold_minutes"))
        pnl_str = f"${pnl:+.2f}"
        lines.append(f"| {ticker} | {side} | {pnl_str} | {hold:.0f}분 |")

    lines.append("")
    return "\n".join(lines)


def _build_analysis_section(analysis: dict) -> str:
    """분석 결과 섹션을 생성한다."""
    lines: list[str] = ["\n## 시장 분석\n"]
    lines.append(f"- 시장 레짐: {analysis.get('regime', 'N/A')}")
    lines.append(f"- VIX: {_safe_float(analysis.get('vix')):.1f}")
    lines.append(f"- 시장 심리: {analysis.get('sentiment', 'N/A')}")

    # 주요 이슈이다
    issues = analysis.get("key_issues", [])
    if issues:
        lines.append("\n### 주요 이슈")
        for issue in issues[:5]:
            lines.append(f"- {issue}")

    lines.append("")
    return "\n".join(lines)


def _build_regime_section(regime: dict) -> str:
    """레짐 섹션을 생성한다."""
    lines: list[str] = ["\n## 레짐 상세\n"]
    lines.append(f"- 유형: {regime.get('type', 'N/A')}")
    lines.append(f"- VIX 레벨: {_safe_float(regime.get('vix')):.1f}")
    lines.append(f"- 전략: {regime.get('strategy', 'N/A')}")
    lines.append(f"- 배수: {_safe_float(regime.get('multiplier'), 1.0):.1f}x\n")
    return "\n".join(lines)


def _build_summary_dict(
    trades: list[dict], portfolio: dict,
) -> dict:
    """요약 dict를 생성한다."""
    pnls = [_safe_float(t.get("pnl")) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    total = len(pnls) if pnls else 1

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_trades": len(trades),
        "win_rate": wins / total if total > 0 else 0.0,
        "total_pnl": sum(pnls),
        "portfolio_value": _safe_float(portfolio.get("total_value")),
    }


def _save_report(content: str, date_str: str) -> str:
    """보고서를 파일로 저장한다."""
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / f"daily_{date_str}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


def generate_daily_report(
    trades: list[dict],
    portfolio: dict,
    analysis: dict,
    regime: dict,
) -> DailyReport:
    """Markdown 형식의 일일 보고서를 생성한다.

    거래 내역, 포트폴리오 현황, 시장 분석, 레짐 정보를
    종합하여 Markdown 보고서를 생성하고 파일로 저장한다.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info("일일 보고서 생성 시작: %s", date_str)

    sections: list[str] = [
        _build_header(date_str),
        _build_portfolio_section(portfolio),
        _build_trades_section(trades),
        _build_analysis_section(analysis),
        _build_regime_section(regime),
    ]

    markdown = "\n".join(sections)
    summary = _build_summary_dict(trades, portfolio)
    report_path = _save_report(markdown, date_str)

    logger.info("보고서 저장 완료: %s", report_path)

    return DailyReport(
        markdown_text=markdown,
        summary_dict=summary,
        report_path=report_path,
    )
