"""
한국 해외주식 양도소득세 추적 모듈.

연간 기본공제 250만원, 세율 22% (양도소득세 20% + 지방소득세 2%) 기준으로
실현 손익을 추적하고, 세금 최적화를 위한 손실 확정 매도(tax-loss harvesting)를 제안한다.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from src.db.connection import get_session
from src.db.models import TaxRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 한국 해외주식 양도소득세 상수
ANNUAL_EXEMPTION_KRW: int = 2_500_000
TAX_RATE: float = 0.22


class TaxTracker:
    """한국 해외주식 양도소득세를 관리한다.

    연간 실현손익을 USD/KRW 기준으로 추적하며,
    연말 세금 절감을 위한 손실 확정 매도 전략을 제안한다.
    """

    async def record_trade_tax(
        self, trade_id: str, pnl_usd: float, fx_rate: float
    ) -> None:
        """거래의 실현손익을 세금 기록에 저장한다.

        Args:
            trade_id: 거래 UUID.
            pnl_usd: 실현 손익 (USD). 양수=이익, 음수=손실.
            fx_rate: 거래 시점 USD/KRW 환율.
        """
        try:
            now = datetime.now(tz=timezone.utc)
            pnl_krw = pnl_usd * fx_rate

            record = TaxRecord(
                trade_id=trade_id,
                year=now.year,
                realized_gain_usd=max(pnl_usd, 0.0),
                realized_loss_usd=min(pnl_usd, 0.0),
                fx_rate_at_trade=round(fx_rate, 2),
                realized_gain_krw=max(pnl_krw, 0.0),
                realized_loss_krw=min(pnl_krw, 0.0),
                tax_category="양도소득세",
            )

            async with get_session() as session:
                session.add(record)

            logger.info(
                "세금 기록 저장 | trade_id=%s | pnl_usd=%.2f | fx_rate=%.2f | pnl_krw=%.0f",
                trade_id,
                pnl_usd,
                fx_rate,
                pnl_krw,
            )
        except Exception as exc:
            logger.exception("세금 기록 저장 실패 | trade_id=%s", trade_id)
            raise

    async def get_yearly_summary(self, year: int) -> dict[str, Any]:
        """연간 세금 요약을 반환한다.

        Args:
            year: 조회 연도.

        Returns:
            연간 실현이익, 실현손실, 순이익, 과세대상금액, 예상세액 등.
        """
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(
                        func.coalesce(func.sum(TaxRecord.realized_gain_usd), 0.0).label("total_gain_usd"),
                        func.coalesce(func.sum(TaxRecord.realized_loss_usd), 0.0).label("total_loss_usd"),
                        func.coalesce(func.sum(TaxRecord.realized_gain_krw), 0.0).label("total_gain_krw"),
                        func.coalesce(func.sum(TaxRecord.realized_loss_krw), 0.0).label("total_loss_krw"),
                    ).where(TaxRecord.year == year)
                )
                row = result.one()

            total_gain_usd = float(row.total_gain_usd)
            total_loss_usd = float(row.total_loss_usd)
            total_gain_krw = float(row.total_gain_krw)
            total_loss_krw = float(row.total_loss_krw)

            net_gain_usd = total_gain_usd + total_loss_usd
            net_gain_krw = total_gain_krw + total_loss_krw

            taxable_krw = max(net_gain_krw - ANNUAL_EXEMPTION_KRW, 0.0)
            estimated_tax_krw = taxable_krw * TAX_RATE

            summary = {
                "total_gain_usd": round(total_gain_usd, 2),
                "total_loss_usd": round(total_loss_usd, 2),
                "net_gain_usd": round(net_gain_usd, 2),
                "net_gain_krw": round(net_gain_krw, 0),
                "exemption_krw": ANNUAL_EXEMPTION_KRW,
                "taxable_krw": round(taxable_krw, 0),
                "estimated_tax_krw": round(estimated_tax_krw, 0),
                "tax_rate": TAX_RATE,
            }

            logger.info(
                "연간 세금 요약 | year=%d | net_gain_krw=%.0f | taxable=%.0f | tax=%.0f",
                year,
                net_gain_krw,
                taxable_krw,
                estimated_tax_krw,
            )
            return summary
        except Exception as exc:
            logger.exception("연간 세금 요약 조회 실패 | year=%d", year)
            raise

    async def suggest_tax_loss_harvest(
        self, positions: list[dict]
    ) -> list[dict]:
        """연말 손실 확정 매도 대상 포지션을 추천한다.

        12월에만 동작하며, 연간 순이익이 250만원을 초과할 때
        미실현 손실이 있는 포지션을 매도하여 세금을 절감할 수 있는 후보를 반환한다.

        Args:
            positions: 현재 보유 포지션 목록. 각 항목은
                {"ticker", "quantity", "avg_price", "current_price", "pnl_amount"} 를 포함한다.

        Returns:
            손실 확정 매도 추천 포지션 목록. 각 항목은
            {"ticker", "unrealized_loss_usd", "potential_tax_saving_krw", "recommendation"} 를 포함한다.
        """
        try:
            now = datetime.now(tz=timezone.utc)
            if now.month != 12:
                logger.info("세금 손실 확정 매도 제안: 12월이 아니므로 제안 없음")
                return []

            summary = await self.get_yearly_summary(now.year)
            net_gain_krw = summary["net_gain_krw"]

            if net_gain_krw <= ANNUAL_EXEMPTION_KRW:
                logger.info(
                    "세금 손실 확정 매도 제안: 순이익(%.0f원)이 기본공제(%.0f원) 이하",
                    net_gain_krw,
                    ANNUAL_EXEMPTION_KRW,
                )
                return []

            recommendations: list[dict] = []
            for pos in positions:
                pnl_amount = pos.get("pnl_amount", 0.0)
                if pnl_amount >= 0:
                    continue

                unrealized_loss_usd = pnl_amount
                potential_saving_krw = abs(unrealized_loss_usd) * summary.get(
                    "net_gain_krw", 0.0
                ) / max(summary.get("net_gain_usd", 1.0), 0.01) * TAX_RATE

                recommendations.append({
                    "ticker": pos.get("ticker", ""),
                    "unrealized_loss_usd": round(unrealized_loss_usd, 2),
                    "potential_tax_saving_krw": round(potential_saving_krw, 0),
                    "recommendation": "손실 확정 매도 검토 권장",
                })

            recommendations.sort(key=lambda x: x["unrealized_loss_usd"])

            logger.info(
                "세금 손실 확정 매도 제안 | 후보 %d건 | 연간순이익=%.0f원",
                len(recommendations),
                net_gain_krw,
            )
            return recommendations
        except Exception as exc:
            logger.exception("세금 손실 확정 매도 제안 실패")
            raise

    async def get_remaining_exemption(self, year: int) -> dict[str, Any]:
        """연간 남은 면제 금액을 계산한다.

        Args:
            year: 조회 연도.

        Returns:
            {"exemption_krw", "used_krw", "remaining_krw", "utilization_pct"}.
        """
        try:
            summary = await self.get_yearly_summary(year)
            net_gain_krw = max(summary["net_gain_krw"], 0.0)
            used_krw = min(net_gain_krw, ANNUAL_EXEMPTION_KRW)
            remaining_krw = ANNUAL_EXEMPTION_KRW - used_krw
            utilization_pct = (used_krw / ANNUAL_EXEMPTION_KRW) * 100.0

            result = {
                "exemption_krw": ANNUAL_EXEMPTION_KRW,
                "used_krw": round(used_krw, 0),
                "remaining_krw": round(remaining_krw, 0),
                "utilization_pct": round(utilization_pct, 2),
            }

            logger.info(
                "면제 잔여액 | year=%d | remaining=%.0f원 | utilization=%.1f%%",
                year,
                remaining_krw,
                utilization_pct,
            )
            return result
        except Exception as exc:
            logger.exception("면제 잔여액 조회 실패 | year=%d", year)
            raise
