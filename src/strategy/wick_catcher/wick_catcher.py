"""F4 윅 캐처 -- 급격한 하방 윅에서 역방향 진입을 판단한다."""
from __future__ import annotations

from src.common.logger import get_logger
from src.strategy.models import WickDecision

logger = get_logger(__name__)

# 활성화 임계값
_VPIN_THRESHOLD = 0.7
_CVD_THRESHOLD = -0.6

# 진입 가격 오프셋 (현재가 대비 %)
_ENTRY_OFFSETS = [-2.0, -3.0, -4.0]

# 바운스 청산 수익률
_BOUNCE_EXIT_PCT = 2.0


def _check_activation(vpin: float, cvd: float) -> bool:
    """활성화 조건을 검증한다. VPIN>0.7 + CVD<-0.6이면 True이다."""
    return vpin > _VPIN_THRESHOLD and cvd < _CVD_THRESHOLD


def _calculate_entry_prices(current_price: float) -> list[float]:
    """3단계 진입 가격을 계산한다 (현재가 대비 -2%, -3%, -4%)."""
    return [
        round(current_price * (1 + offset / 100), 2)
        for offset in _ENTRY_OFFSETS
    ]


def _validate_inputs(intraday_state: dict) -> tuple[float, float, float]:
    """입력 데이터를 검증하고 추출한다."""
    vpin = intraday_state.get("vpin", 0.0)
    cvd = intraday_state.get("cvd", 0.0)
    price = intraday_state.get("price", 0.0)
    return vpin, cvd, price


class WickCatcher:
    """급격한 하방 윅에서 역방향 진입을 판단한다."""

    def evaluate(self, intraday_state: dict) -> WickDecision:
        """장중 상태에서 윅 캐처 활성화를 판단한다.

        Args:
            intraday_state: vpin, cvd, price, low 키를 포함하는 딕셔너리
        """
        vpin, cvd, price = _validate_inputs(intraday_state)

        # 가격 데이터 없으면 비활성화
        if price <= 0:
            return WickDecision(should_catch=False)

        # 활성화 조건 미충족
        if not _check_activation(vpin, cvd):
            return WickDecision(should_catch=False)

        entry_prices = _calculate_entry_prices(price)

        logger.info(
            "윅 캐처 활성화: VPIN=%.2f CVD=%.2f price=$%.2f entries=%s",
            vpin, cvd, price, entry_prices,
        )

        return WickDecision(
            should_catch=True,
            entry_prices=entry_prices,
            bounce_exit_pct=_BOUNCE_EXIT_PCT,
        )
