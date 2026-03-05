"""CapitalGuard (F6.4) -- 자본 보존 장치이다.

일일/주간 손실 한도를 추적하여 과도한 손실을 방지한다.
"""

from __future__ import annotations

from collections import deque

from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 상수 --
_WEEKLY_DAYS: int = 5


class CapitalGuard:
    """자본 보존 장치이다.

    일일 및 주간 누적 손실을 추적하여 한도 초과 시 매매를 차단한다.
    """

    def __init__(
        self,
        daily_limit_pct: float = -3.0,
        weekly_limit_pct: float = -5.0,
    ) -> None:
        """초기화한다.

        Args:
            daily_limit_pct: 일일 손실 한도(%). 음수. 기본 -3.0%.
            weekly_limit_pct: 주간 손실 한도(%). 음수. 기본 -5.0%.
        """
        self._daily_limit_pct = daily_limit_pct
        self._weekly_limit_pct = weekly_limit_pct
        self._daily_pnl: float = 0.0
        # 최근 5일 일일 PnL을 저장한다
        self._weekly_pnls: deque[float] = deque(
            maxlen=_WEEKLY_DAYS,
        )

    def record_pnl(self, pnl_pct: float) -> None:
        """거래 손익을 기록한다.

        Args:
            pnl_pct: 손익 비율(%). 음수=손실, 양수=이익.
        """
        self._daily_pnl += pnl_pct
        _logger.debug(
            "CapitalGuard PnL 기록: %.2f%% (일일 누적: %.2f%%)",
            pnl_pct, self._daily_pnl,
        )

    def is_daily_limit_reached(self) -> bool:
        """일일 손실 한도에 도달했는지 반환한다."""
        reached = self._daily_pnl <= self._daily_limit_pct
        if reached:
            _logger.warning(
                "일일 손실 한도 도달: %.2f%% <= %.2f%%",
                self._daily_pnl, self._daily_limit_pct,
            )
        return reached

    def is_weekly_limit_reached(self) -> bool:
        """주간 손실 한도에 도달했는지 반환한다."""
        weekly_total = self._calculate_weekly_pnl()
        reached = weekly_total <= self._weekly_limit_pct
        if reached:
            _logger.warning(
                "주간 손실 한도 도달: %.2f%% <= %.2f%%",
                weekly_total, self._weekly_limit_pct,
            )
        return reached

    def get_daily_pnl(self) -> float:
        """오늘 누적 손익(%)을 반환한다."""
        return self._daily_pnl

    def get_weekly_pnl(self) -> float:
        """주간 누적 손익(%)을 반환한다."""
        return self._calculate_weekly_pnl()

    def reset_daily(self) -> None:
        """일일 리셋한다. 당일 PnL을 주간 기록에 추가한다."""
        self._weekly_pnls.append(self._daily_pnl)
        _logger.info(
            "CapitalGuard 일일 리셋: 당일 PnL=%.2f%% -> 주간 기록 추가",
            self._daily_pnl,
        )
        self._daily_pnl = 0.0

    def reset_weekly(self) -> None:
        """주간 리셋한다."""
        self._weekly_pnls.clear()
        self._daily_pnl = 0.0
        _logger.info("CapitalGuard 주간 리셋 완료")

    def _calculate_weekly_pnl(self) -> float:
        """주간 누적 PnL을 계산한다. 당일 포함."""
        past_total = sum(self._weekly_pnls)
        return past_total + self._daily_pnl
