"""
트레일링 스톱로스 모듈 (Addendum 26)

포지션별 트레일링 스톱을 관리한다:
    - 초기 스톱: 진입가 대비 -5%
    - 트레일링 스톱: 최고점 대비 -3%
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 기본 설정
DEFAULT_INITIAL_STOP_PCT: float = -5.0
DEFAULT_TRAILING_STOP_PCT: float = -3.0


class TrailingStopLoss:
    """포지션별 트레일링 스톱로스를 관리한다.

    진입 시 초기 스톱(-5%)을 설정하고, 가격이 상승하면
    최고점 대비 트레일링 스톱(-3%)으로 스톱 레벨을 끌어올린다.

    Attributes:
        initial_stop_pct: 초기 스톱 비율 (음수).
        trailing_stop_pct: 트레일링 스톱 비율 (음수).
        positions: 포지션별 스톱 정보.
    """

    def __init__(
        self,
        initial_stop_pct: float = DEFAULT_INITIAL_STOP_PCT,
        trailing_stop_pct: float = DEFAULT_TRAILING_STOP_PCT,
    ) -> None:
        """TrailingStopLoss를 초기화한다.

        Args:
            initial_stop_pct: 초기 스톱 비율 (음수, %).
            trailing_stop_pct: 트레일링 스톱 비율 (음수, %).
        """
        self.initial_stop_pct = initial_stop_pct
        self.trailing_stop_pct = trailing_stop_pct
        self.positions: dict[str, dict[str, Any]] = {}

        logger.info(
            "TrailingStopLoss 초기화 | initial=%.1f%% | trailing=%.1f%%",
            initial_stop_pct,
            trailing_stop_pct,
        )

    def register_position(
        self, ticker: str, entry_price: float, quantity: int
    ) -> dict[str, Any]:
        """새 포지션을 등록하고 초기 스톱을 설정한다.

        Args:
            ticker: ETF 티커.
            entry_price: 진입 가격.
            quantity: 수량.

        Returns:
            포지션 스톱 정보.
        """
        initial_stop_price = entry_price * (1.0 + self.initial_stop_pct / 100.0)

        stop_info = {
            "ticker": ticker,
            "entry_price": entry_price,
            "quantity": quantity,
            "high_price": entry_price,
            "stop_price": initial_stop_price,
            "stop_type": "initial",
            "registered_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        self.positions[ticker] = stop_info

        logger.info(
            "포지션 등록: %s | entry=$%.2f | stop=$%.2f (initial %.1f%%)",
            ticker,
            entry_price,
            initial_stop_price,
            self.initial_stop_pct,
        )

        return stop_info

    def update_price(self, ticker: str, current_price: float) -> dict[str, Any] | None:
        """현재 가격으로 스톱 레벨을 업데이트한다.

        가격이 최고점을 갱신하면 트레일링 스톱을 끌어올린다.

        Args:
            ticker: ETF 티커.
            current_price: 현재 가격.

        Returns:
            업데이트된 스톱 정보. 미등록 포지션이면 None.
        """
        if ticker not in self.positions:
            return None

        pos = self.positions[ticker]

        # 최고점 갱신 체크
        if current_price > pos["high_price"]:
            pos["high_price"] = current_price
            trailing_stop_price = current_price * (1.0 + self.trailing_stop_pct / 100.0)

            # 트레일링 스톱이 현재 스톱보다 높으면 갱신
            if trailing_stop_price > pos["stop_price"]:
                old_stop = pos["stop_price"]
                pos["stop_price"] = trailing_stop_price
                pos["stop_type"] = "trailing"
                logger.debug(
                    "트레일링 스톱 갱신: %s | high=$%.2f | stop=$%.2f -> $%.2f",
                    ticker,
                    current_price,
                    old_stop,
                    trailing_stop_price,
                )

        return pos

    def check_stop(self, ticker: str, current_price: float) -> dict[str, Any] | None:
        """스톱 발동 여부를 확인한다.

        Args:
            ticker: ETF 티커.
            current_price: 현재 가격.

        Returns:
            스톱 발동 시 매도 지시 딕셔너리. 미발동이면 None.
        """
        if ticker not in self.positions:
            return None

        # 먼저 스톱 레벨 업데이트
        self.update_price(ticker, current_price)

        pos = self.positions[ticker]

        if current_price <= pos["stop_price"]:
            pnl_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100.0

            logger.warning(
                "스톱 발동: %s | price=$%.2f <= stop=$%.2f | type=%s | pnl=%.2f%%",
                ticker,
                current_price,
                pos["stop_price"],
                pos["stop_type"],
                pnl_pct,
            )

            return {
                "ticker": ticker,
                "action": "force_sell",
                "quantity": pos["quantity"],
                "reason": (
                    f"{pos['stop_type']} 스톱 발동: "
                    f"${current_price:.2f} <= ${pos['stop_price']:.2f} "
                    f"(pnl={pnl_pct:.2f}%)"
                ),
                "stop_type": pos["stop_type"],
                "entry_price": pos["entry_price"],
                "high_price": pos["high_price"],
                "pnl_pct": round(pnl_pct, 4),
            }

        return None

    def check_all_positions(
        self, current_prices: dict[str, float]
    ) -> list[dict[str, Any]]:
        """모든 포지션의 스톱을 확인한다.

        Args:
            current_prices: 종목별 현재 가격.

        Returns:
            스톱 발동된 포지션의 매도 지시 리스트.
        """
        stop_signals: list[dict[str, Any]] = []

        for ticker, price in current_prices.items():
            result = self.check_stop(ticker, price)
            if result is not None:
                stop_signals.append(result)

        return stop_signals

    def remove_position(self, ticker: str) -> None:
        """포지션 스톱 추적을 제거한다.

        Args:
            ticker: ETF 티커.
        """
        if ticker in self.positions:
            del self.positions[ticker]
            logger.debug("포지션 스톱 제거: %s", ticker)

    def get_status(self) -> dict[str, Any]:
        """현재 상태를 반환한다."""
        return {
            "initial_stop_pct": self.initial_stop_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "tracked_positions": len(self.positions),
            "positions": {
                ticker: {
                    "entry_price": info["entry_price"],
                    "high_price": info["high_price"],
                    "stop_price": info["stop_price"],
                    "stop_type": info["stop_type"],
                }
                for ticker, info in self.positions.items()
            },
        }
