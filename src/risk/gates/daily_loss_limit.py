"""DailyLossLimit (F6.9) -- 일일 손실 한도를 추적한다.

거래별 손익을 누적하여 일일 한도 초과 시 매매를 차단한다.
"""

from __future__ import annotations

from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 기본값 --
_DEFAULT_MAX_LOSS: float = -3.0


class DailyLossLimit:
    """일일 손실 한도 추적기이다.

    각 거래의 손익(%)을 누적하여 일일 한도에 도달하면
    추가 매매를 차단한다.
    """

    def __init__(
        self, max_daily_loss_pct: float = _DEFAULT_MAX_LOSS,
    ) -> None:
        """초기화한다.

        Args:
            max_daily_loss_pct: 최대 일일 손실(%). 음수. 기본 -3.0%.
        """
        self._max_loss = max_daily_loss_pct
        self._cumulative_pnl: float = 0.0
        self._trade_count: int = 0

    def record_trade(self, pnl_pct: float) -> None:
        """거래 손익을 기록한다.

        Args:
            pnl_pct: 거래 손익(%). 음수=손실, 양수=이익.
        """
        self._cumulative_pnl += pnl_pct
        self._trade_count += 1
        _logger.debug(
            "DailyLossLimit 기록: %.2f%% "
            "(누적=%.2f%%, 거래수=%d)",
            pnl_pct, self._cumulative_pnl, self._trade_count,
        )

    def is_limit_reached(self) -> bool:
        """일일 손실 한도에 도달했는지 반환한다."""
        reached = self._cumulative_pnl <= self._max_loss
        if reached:
            _logger.warning(
                "일일 손실 한도 도달: %.2f%% <= %.2f%%",
                self._cumulative_pnl, self._max_loss,
            )
        return reached

    def get_remaining(self) -> float:
        """한도까지 남은 손실 여유분(%)을 반환한다.

        양수이면 아직 여유가 있음을 의미한다.
        음수이면 이미 한도를 초과했음을 의미한다.
        """
        return self._cumulative_pnl - self._max_loss

    def get_cumulative_pnl(self) -> float:
        """오늘 누적 손익(%)을 반환한다."""
        return self._cumulative_pnl

    def get_trade_count(self) -> int:
        """오늘 거래 횟수를 반환한다."""
        return self._trade_count

    def reset(self) -> None:
        """일일 리셋한다."""
        _logger.info(
            "DailyLossLimit 리셋: 누적PnL=%.2f%%, 거래수=%d",
            self._cumulative_pnl, self._trade_count,
        )
        self._cumulative_pnl = 0.0
        self._trade_count = 0
