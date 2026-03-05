"""MacroFlashCrash (F6.13) -- SPY/QQQ 플래시 크래시를 감지한다.

3분 이내 -1.0% 하락 감지 시 전량 청산 + 매매 중단을 트리거한다.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from pydantic import BaseModel

from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 상수 --
_DEFAULT_THRESHOLD: float = -1.0
_DEFAULT_WINDOW: int = 180
_MAX_PRICE_HISTORY: int = 200
_MONITORED_TICKERS: frozenset[str] = frozenset({"SPY", "QQQ"})


class FlashCrashResult(BaseModel):
    """플래시 크래시 감지 결과이다."""

    detected: bool
    ticker: str = ""
    drop_pct: float = 0.0
    time_window_seconds: int = _DEFAULT_WINDOW


class _PriceRecord:
    """가격 기록 엔트리이다."""

    __slots__ = ("price", "timestamp")

    def __init__(self, price: float, timestamp: datetime) -> None:
        self.price = price
        self.timestamp = timestamp


class MacroFlashCrashDetector:
    """매크로 플래시 크래시 감지기이다.

    SPY와 QQQ의 가격을 추적하여 window_seconds 이내
    threshold_pct 이상 하락하면 크래시로 판정한다.
    """

    def __init__(
        self,
        threshold_pct: float = _DEFAULT_THRESHOLD,
        window_seconds: int = _DEFAULT_WINDOW,
    ) -> None:
        """초기화한다.

        Args:
            threshold_pct: 하락 임계값(%). 음수. 기본 -1.0%.
            window_seconds: 감시 시간 윈도우(초). 기본 180초.
        """
        self._threshold = threshold_pct
        self._window = window_seconds
        # 티커별 가격 이력 (시간순)
        self._history: dict[str, deque[_PriceRecord]] = {
            t: deque(maxlen=_MAX_PRICE_HISTORY)
            for t in _MONITORED_TICKERS
        }

    def record_price(
        self, ticker: str, price: float,
    ) -> None:
        """가격을 기록한다.

        SPY, QQQ만 처리하며 그 외 티커는 무시한다.
        """
        if ticker not in _MONITORED_TICKERS:
            return
        if price <= 0:
            return
        record = _PriceRecord(
            price=price,
            timestamp=datetime.now(tz=timezone.utc),
        )
        self._history[ticker].append(record)

    def check(self) -> FlashCrashResult:
        """플래시 크래시 여부를 확인한다.

        각 모니터링 티커에 대해 윈도우 내 최대 하락폭을 계산한다.
        """
        for ticker in _MONITORED_TICKERS:
            result = self._check_ticker(ticker)
            if result.detected:
                return result

        return FlashCrashResult(
            detected=False,
            time_window_seconds=self._window,
        )

    def reset(self) -> None:
        """일일 리셋한다. 가격 이력을 초기화한다."""
        for ticker in _MONITORED_TICKERS:
            self._history[ticker].clear()
        _logger.info("MacroFlashCrashDetector 리셋 완료")

    def _check_ticker(self, ticker: str) -> FlashCrashResult:
        """특정 티커의 플래시 크래시를 감지한다."""
        records = self._history[ticker]
        if len(records) < 2:
            return FlashCrashResult(
                detected=False,
                time_window_seconds=self._window,
            )

        now = datetime.now(tz=timezone.utc)
        cutoff_seconds = self._window

        # 윈도우 내 가장 오래된 유효 가격을 찾는다
        oldest_price: float | None = None
        for rec in records:
            elapsed = (now - rec.timestamp).total_seconds()
            if elapsed <= cutoff_seconds:
                oldest_price = rec.price
                break

        if oldest_price is None or oldest_price <= 0:
            return FlashCrashResult(
                detected=False,
                time_window_seconds=self._window,
            )

        # 현재 가격 (가장 최근 기록)
        current_price = records[-1].price
        drop_pct = ((current_price - oldest_price) / oldest_price) * 100

        if drop_pct <= self._threshold:
            _logger.error(
                "플래시 크래시 감지: %s %.2f%% "
                "(%.2f -> %.2f, %d초 이내)",
                ticker, drop_pct,
                oldest_price, current_price, self._window,
            )
            return FlashCrashResult(
                detected=True,
                ticker=ticker,
                drop_pct=drop_pct,
                time_window_seconds=self._window,
            )

        return FlashCrashResult(
            detected=False,
            time_window_seconds=self._window,
        )
