"""TaxTracker -- 매매별 양도소득세를 계산하고 기록한다.

미국 주식 양도소득세 22% (250만원 기본공제) 기준이다.
매도 시에만 세금을 계산한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import insert

from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger
from src.tax.models import TaxResult

logger = get_logger(__name__)

# 양도소득세율 22% (소득세 20% + 지방소득세 2%)
_TAX_RATE: float = 0.22
# 기본공제 250만원
_BASIC_DEDUCTION_KRW: float = 2_500_000.0


def _calc_gain_usd(qty: int, buy_price: float, sell_price: float) -> float:
    """매매 차익(USD)을 계산한다. 매수가 대비 매도가 차이이다."""
    return (sell_price - buy_price) * qty


def _calc_tax(gain_krw: float) -> float:
    """기본공제 후 양도소득세를 계산한다. 손실이면 0이다."""
    taxable = gain_krw - _BASIC_DEDUCTION_KRW
    if taxable <= 0:
        return 0.0
    return round(taxable * _TAX_RATE, 2)


class TaxTracker:
    """매매별 세금 계산/기록 관리자이다."""

    def __init__(self, session_factory: SessionFactory, fx_rate: float = 1350.0) -> None:
        """세션 팩토리와 기준 환율을 주입받는다."""
        self._sf = session_factory
        self._fx_rate = fx_rate
        logger.info("TaxTracker 초기화 완료 (환율=%.1f)", fx_rate)

    def set_fx_rate(self, rate: float) -> None:
        """환율을 갱신한다."""
        self._fx_rate = rate

    async def calculate(self, trade: dict) -> TaxResult:
        """매매에 대한 세금을 계산하고 DB에 기록한다.

        매도(side=sell)일 때만 세금을 계산한다.
        매수일 경우 세금 0으로 반환한다.
        """
        side = trade.get("side", "")
        if side != "sell":
            return TaxResult(tax_amount=0.0, tax_rate=0.0, recorded=False)

        qty = int(trade.get("qty", trade.get("quantity", 0)))
        buy_price = float(trade.get("buy_price", 0.0))
        sell_price = float(trade.get("sell_price", 0.0))

        gain_usd = _calc_gain_usd(qty, buy_price, sell_price)
        gain_krw = gain_usd * self._fx_rate
        tax_krw = _calc_tax(gain_krw)

        recorded = await self._record(trade, gain_usd, tax_krw)
        logger.info(
            "세금 계산: %s 차익=$%.2f 세금=%.0f원",
            trade.get("ticker", "?"), gain_usd, tax_krw,
        )
        return TaxResult(tax_amount=tax_krw, tax_rate=_TAX_RATE, recorded=recorded)

    async def _record(self, trade: dict, gain_usd: float, tax_krw: float) -> bool:
        """세금 기록을 DB에 저장한다."""
        try:
            async with self._sf.get_session() as session:
                from src.db.models import TaxRecord
                stmt = insert(TaxRecord).values(
                    ticker=trade.get("ticker", ""),
                    gain_usd=gain_usd,
                    tax_krw=tax_krw,
                    fx_rate=self._fx_rate,
                )
                await session.execute(stmt)
            return True
        except Exception:
            logger.exception("세금 기록 저장 실패")
            return False
