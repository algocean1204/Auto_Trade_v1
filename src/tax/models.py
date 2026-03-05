"""FX 세금/환율 -- 공용 모델이다."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TaxResult(BaseModel):
    """세금 계산 결과이다."""

    tax_amount: float
    tax_rate: float
    recorded: bool


class FxRate(BaseModel):
    """USD/KRW 환율 데이터이다."""

    usd_krw: float
    last_updated: datetime


class SlippageRecord(BaseModel):
    """슬리피지 측정 기록이다."""

    slippage_pct: float
    slippage_amount: float
    order_id: str = ""
