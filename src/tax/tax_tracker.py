"""TaxTracker -- 매매별 양도소득세를 계산하고 기록한다.

미국 주식 양도소득세 22% (소득세 20% + 지방소득세 2%) 기준이다.
매도 시 개별 거래의 차익과 추정 세금을 기록한다.

주의: 250만원 기본공제는 연간 합산에만 적용된다.
개별 거래 세금은 공제 전 추정치이다 (연간 합산은 tax_writer.py가 담당한다).
"""
from __future__ import annotations

import math

from src.common.database_gateway import SessionFactory
from src.common.logger import get_logger
from src.tax.models import TaxResult

logger = get_logger(__name__)

# 양도소득세율 22% (소득세 20% + 지방소득세 2%)
_TAX_RATE: float = 0.22


def _calc_gain_usd(qty: int, buy_price: float, sell_price: float) -> float:
    """매매 차익(USD)을 계산한다. 매수가 대비 매도가 차이이다."""
    return (sell_price - buy_price) * qty


def _calc_trade_tax(gain_krw: float) -> float:
    """개별 거래의 추정 세금을 계산한다. 손실이면 0이다.

    250만원 기본공제는 연간 총 합산에만 적용되므로
    개별 거래에서는 공제 없이 이익분에 대해 세율만 적용한다.
    연간 합산 세금은 tax_writer.compute_tax_status()가 정확히 계산한다.
    """
    if gain_krw <= 0:
        return 0.0
    return round(gain_krw * _TAX_RATE, 2)


class TaxTracker:
    """매매별 세금 계산/기록 관리자이다."""

    def __init__(
        self, session_factory: SessionFactory, fx_rate: float | None = None,
    ) -> None:
        """세션 팩토리와 기준 환율을 주입받는다. 환율 미제공 시 None이다."""
        self._sf = session_factory
        self._fx_rate = fx_rate
        if fx_rate is not None:
            logger.info("TaxTracker 초기화 완료 (환율=%.1f)", fx_rate)
        else:
            logger.info("TaxTracker 초기화 완료 (환율=미설정, 매도 시 세금 미계산)")

    def set_fx_rate(self, rate: float) -> None:
        """환율을 갱신한다."""
        self._fx_rate = rate

    async def calculate(self, trade: dict) -> TaxResult:
        """매매에 대한 세금을 계산하고 DB에 기록한다.

        매도(side=sell)일 때만 세금을 계산한다.
        매수일 경우 세금 0으로 반환한다.
        환율이 None이면 KRW 변환 없이 세금 0으로 처리한다.
        """
        side = trade.get("side", "")
        if side != "sell":
            return TaxResult(tax_amount=0.0, tax_rate=0.0, recorded=False)

        if self._fx_rate is None:
            logger.warning(
                "환율 조회불가 -- 세금 계산 스킵: %s",
                trade.get("ticker", "?"),
            )
            return TaxResult(tax_amount=0.0, tax_rate=0.0, recorded=False)

        qty = int(trade.get("qty", trade.get("quantity", 0)))
        buy_price = float(trade.get("buy_price", 0.0))
        sell_price = float(trade.get("sell_price", 0.0))

        # NaN/inf 방어: 유효하지 않은 가격이면 세금 계산을 스킵한다
        if math.isnan(buy_price) or math.isinf(buy_price) or math.isnan(sell_price) or math.isinf(sell_price):
            logger.warning("유효하지 않은 가격 -- 세금 계산 스킵: %s", trade.get("ticker", "?"))
            return TaxResult(tax_amount=0.0, tax_rate=0.0, recorded=False)

        gain_usd = _calc_gain_usd(qty, buy_price, sell_price)
        gain_krw = gain_usd * self._fx_rate
        tax_krw = _calc_trade_tax(gain_krw)

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
                record = TaxRecord(
                    ticker=trade.get("ticker", ""),
                    gain_usd=gain_usd,
                    tax_krw=tax_krw,
                    fx_rate=self._fx_rate,
                )
                session.add(record)
            return True
        except Exception:
            logger.exception("세금 기록 저장 실패")
            return False
