"""
진입 전략 모듈

Claude 매매 판단 + 기술적 지표 + 안전 규칙을 종합하여 최종 진입 결정을 생성한다.
레짐별 포지션 크기, 방향(Bull/Inverse), 주문 유형을 결정하고
MIN_CONFIDENCE 이상인 후보만 필터링한다.
"""

import math
from typing import Any

from src.strategy.etf_universe import (
    BEAR_2X_UNIVERSE,
    BULL_2X_UNIVERSE,
    get_inverse_pair,
    is_valid_ticker,
)
from src.strategy.params import (
    REGIMES,
    StrategyParams,
)
from src.utils.logger import get_logger
from src.utils.market_hours import MarketHours

logger = get_logger(__name__)

# 레짐별 포지션 크기 배수 (1.0 = 100% of calculated size)
_REGIME_POSITION_SCALE: dict[str, float] = {
    "strong_bull": 1.0,
    "mild_bull": 0.8,
    "sideways": 0.5,
    "mild_bear": 0.6,
    "crash": 0.0,
}

# 기술적 지표와 Claude 판단 방향이 일치할 때 confidence 보너스
_DIRECTION_AGREEMENT_BONUS: float = 0.1


class EntryStrategy:
    """진입 전략 결정 클래스.

    Claude AI 매매 판단과 기술적 지표 종합 신호를 결합하여
    최종 진입 후보 목록을 생성한다.
    """

    def __init__(self, params: StrategyParams, market_hours: MarketHours) -> None:
        """EntryStrategy 초기화.

        Args:
            params: 전략 파라미터 관리 인스턴스.
            market_hours: 시장 시간 관리 인스턴스.
        """
        self.params = params
        self.market_hours = market_hours
        self._ticker_params_manager = None

    def set_ticker_params_manager(self, manager: object) -> None:
        """종목별 파라미터 관리자를 주입한다.

        Args:
            manager: TickerParamsManager 인스턴스.
        """
        self._ticker_params_manager = manager
        logger.info("EntryStrategy: TickerParamsManager 주입 완료")

    def evaluate_entry(
        self,
        trading_decisions: list[dict[str, Any]],
        indicator_signals: dict[str, dict[str, Any]],
        regime: str,
        portfolio: dict[str, Any],
        vix: float,
    ) -> list[dict[str, Any]]:
        """진입 후보를 생성한다.

        1. Claude 판단에서 buy/sell 추천 추출
        2. 기술적 지표와 방향 일치 확인 (일치 시 confidence 보너스)
        3. MIN_CONFIDENCE 이상인 것만 필터
        4. 레짐별 조건 적용
        5. 포지션 크기 계산 (종목당 max 15%, 전체 max 80%)
        6. Bull vs Inverse 방향 결정

        Args:
            trading_decisions: Claude AI 판단 결과 리스트.
                각 항목: {"ticker": str, "action": "buy"|"sell"|"hold",
                         "confidence": float, "reason": str, ...}
            indicator_signals: 종목별 기술적 지표 종합 결과.
                {"TICKER": {"composite_score": float, "direction": "buy"|"sell"|"neutral",
                            "confidence": float, ...}}
            regime: 현재 시장 레짐 ("strong_bull", "mild_bull", "sideways",
                    "mild_bear", "crash").
            portfolio: 현재 포트폴리오 상태.
                {"cash": float, "total_value": float,
                 "positions": {"TICKER": {"quantity": int, "market_value": float, ...}}}
            vix: 현재 VIX 지수 값.

        Returns:
            진입 후보 리스트. 각 항목은 주문 정보를 포함한 딕셔너리.
        """
        logger.info(
            "진입 평가 시작: regime=%s, vix=%.1f, decisions=%d개",
            regime, vix, len(trading_decisions),
        )

        regime_config = REGIMES.get(regime, REGIMES["crash"])

        # crash 레짐이면 신규 매수 중단
        if regime_config.get("strategy") == "no_new_buy":
            logger.warning("Crash 레짐 감지 (VIX=%.1f) - 신규 진입 중단", vix)
            return []

        # VIX 셧다운 임계값 체크
        vix_threshold = self.params.get_param("vix_shutdown_threshold")
        if vix >= vix_threshold:
            logger.warning(
                "VIX %.1f >= 셧다운 임계값 %d - 신규 진입 중단",
                vix, vix_threshold,
            )
            return []

        min_confidence = self.params.get_param("min_confidence")
        candidates: list[dict[str, Any]] = []

        for decision in trading_decisions:
            ticker = decision.get("ticker", "").upper()
            action = decision.get("action", "").lower()
            claude_confidence = decision.get("confidence", 0.0)
            reason = decision.get("reason", "")

            # buy 또는 sell 추천만 처리
            if action not in ("buy", "sell"):
                logger.debug("종목 %s: action=%s, 스킵", ticker, action)
                continue

            if not is_valid_ticker(ticker):
                logger.warning("유효하지 않은 티커: %s, 스킵", ticker)
                continue

            # 종목별 파라미터 조회 (있으면 종목별, 없으면 글로벌)
            ticker_min_confidence = min_confidence
            if self._ticker_params_manager is not None:
                ticker_min_confidence = self._ticker_params_manager.get_effective_param(
                    ticker, "min_confidence"
                )

            # 기술적 지표 신호 조회
            ind_signal = indicator_signals.get(ticker, {})
            ind_direction = ind_signal.get("direction", "neutral")
            ind_confidence = ind_signal.get("confidence", 0.0)

            # 방향 일치 확인 및 confidence 조정
            adjusted_confidence = claude_confidence
            directions_agree = self._check_direction_agreement(
                action, ind_direction
            )
            if directions_agree:
                adjusted_confidence = min(
                    1.0, adjusted_confidence + _DIRECTION_AGREEMENT_BONUS
                )
                logger.debug(
                    "종목 %s: Claude-지표 방향 일치, confidence %.2f -> %.2f",
                    ticker, claude_confidence, adjusted_confidence,
                )

            # MIN_CONFIDENCE 필터 (종목별 파라미터 적용)
            if adjusted_confidence < ticker_min_confidence:
                logger.debug(
                    "종목 %s: confidence %.2f < min %.2f, 스킵",
                    ticker, adjusted_confidence, ticker_min_confidence,
                )
                continue

            # Inverse ETF 사용 판단
            use_inverse = self._should_use_inverse(regime, action)
            if use_inverse:
                inverse_ticker = get_inverse_pair(ticker)
                if inverse_ticker is None:
                    logger.warning(
                        "종목 %s: Inverse 페어 없음, 원래 종목으로 진행", ticker
                    )
                    actual_ticker = ticker
                    direction = "bull" if ticker in BULL_2X_UNIVERSE else "bear"
                else:
                    actual_ticker = inverse_ticker
                    direction = "bear"
                    logger.info(
                        "종목 %s -> Inverse %s 전환 (regime=%s)",
                        ticker, actual_ticker, regime,
                    )
            else:
                actual_ticker = ticker
                direction = "bull" if ticker in BULL_2X_UNIVERSE else "bear"

            # 포지션 크기 계산
            quantity = self._calculate_position_size(
                actual_ticker, adjusted_confidence, portfolio, regime_config,
            )
            if quantity <= 0:
                logger.debug(
                    "종목 %s: 계산된 수량 0, 스킵", actual_ticker
                )
                continue

            # 레짐별 take_profit / max_hold_days (종목별 파라미터 우선 적용)
            if self._ticker_params_manager is not None:
                ticker_effective = self._ticker_params_manager.get_effective_params(actual_ticker)
                take_profit_pct = regime_config.get(
                    "take_profit", ticker_effective.get("take_profit_pct", self.params.get_param("take_profit_pct"))
                )
                max_hold_days = regime_config.get(
                    "max_hold_days", ticker_effective.get("max_hold_days", self.params.get_param("max_hold_days"))
                )
                stop_loss_pct = ticker_effective.get("stop_loss_pct", self.params.get_param("stop_loss_pct"))
                trailing_stop_pct = ticker_effective.get("trailing_stop_pct", self.params.get_param("trailing_stop_pct"))
            else:
                take_profit_pct = regime_config.get(
                    "take_profit", self.params.get_param("take_profit_pct")
                )
                max_hold_days = regime_config.get(
                    "max_hold_days", self.params.get_param("max_hold_days")
                )
                stop_loss_pct = self.params.get_param("stop_loss_pct")
                trailing_stop_pct = self.params.get_param("trailing_stop_pct")

            # 주문 유형 결정
            order_type = self._get_order_type()

            candidate: dict[str, Any] = {
                "ticker": actual_ticker,
                "side": "buy",
                "direction": direction,
                "quantity": quantity,
                "order_type": order_type,
                "confidence": round(adjusted_confidence, 4),
                "reason": reason,
                "take_profit": take_profit_pct,
                "stop_loss": stop_loss_pct,
                "trailing_stop": trailing_stop_pct,
                "max_hold_days": max_hold_days,
                "indicator_direction": ind_direction,
                "indicator_confidence": round(ind_confidence, 4),
                "regime": regime,
            }

            candidates.append(candidate)
            logger.info(
                "진입 후보 생성: ticker=%s, direction=%s, qty=%d, "
                "confidence=%.2f, tp=%.1f%%, sl=%.1f%%",
                actual_ticker, direction, quantity,
                adjusted_confidence, take_profit_pct, stop_loss_pct,
            )

        logger.info("진입 평가 완료: 후보 %d개 생성", len(candidates))
        return candidates

    def _calculate_position_size(
        self,
        ticker: str,
        confidence: float,
        portfolio: dict[str, Any],
        regime_config: dict[str, Any],
    ) -> int:
        """포지션 크기를 계산한다.

        기본 크기 = 총자산 * confidence * max_position_pct
        레짐별 스케일링 적용 후, 종목당/전체 상한을 체크한다.

        Args:
            ticker: 매매 대상 ETF 티커.
            confidence: 조정된 신뢰도 (0.0~1.0).
            portfolio: 포트폴리오 상태.
            regime_config: 현재 레짐 설정.

        Returns:
            주문 수량 (정수). 0이면 진입 불가.
        """
        total_value = portfolio.get("total_value", 0.0)
        cash = portfolio.get("cash", 0.0)
        positions = portfolio.get("positions", {})

        if total_value <= 0 or cash <= 0:
            return 0

        # 종목별 max_position_pct 적용 (있으면 종목별, 없으면 글로벌)
        if self._ticker_params_manager is not None:
            max_position_pct = self._ticker_params_manager.get_effective_param(
                ticker, "max_position_pct"
            ) / 100.0
        else:
            max_position_pct = self.params.get_param("max_position_pct") / 100.0
        max_total_pct = self.params.get_param("max_total_position_pct") / 100.0

        # 기본 금액 = 총자산 * confidence * 종목당 최대 비중
        base_amount = total_value * confidence * max_position_pct

        # 레짐별 스케일링
        regime_name = regime_config.get("regime", "sideways")
        if isinstance(regime_name, tuple):
            regime_name = "sideways"
        scale = _REGIME_POSITION_SCALE.get(regime_name, 0.5)
        scaled_amount = base_amount * scale

        # 종목당 상한: 총자산의 max_position_pct
        per_ticker_limit = total_value * max_position_pct
        # 이미 보유 중인 금액 차감
        existing_value = positions.get(ticker, {}).get("market_value", 0.0)
        per_ticker_remaining = per_ticker_limit - existing_value
        if per_ticker_remaining <= 0:
            logger.debug("종목 %s: 종목당 상한 도달, 추가 진입 불가", ticker)
            return 0

        # 전체 포지션 상한 체크
        total_invested = sum(
            pos.get("market_value", 0.0) for pos in positions.values()
        )
        total_remaining = (total_value * max_total_pct) - total_invested
        if total_remaining <= 0:
            logger.debug("전체 포지션 상한 도달, 추가 진입 불가")
            return 0

        # 최종 금액: 모든 제약 중 최소값, 현금 잔고 이내
        final_amount = min(
            scaled_amount, per_ticker_remaining, total_remaining, cash
        )

        if final_amount <= 0:
            return 0

        # 현재가 기준으로 수량 계산 (시장가 주문 가정)
        # portfolio에서 현재가를 가져오거나, 없으면 보유 포지션에서 추정
        current_price = positions.get(ticker, {}).get("current_price", 0.0)
        if current_price <= 0:
            # 포지션이 없는 종목의 경우 평균 ETF 가격으로 추정
            # 실제 운영 시 실시간 시세를 사용해야 함
            logger.warning(
                "종목 %s: 현재가 정보 없음, 포지션 크기 계산에 기본값 사용", ticker
            )
            return 0

        quantity = math.floor(final_amount / current_price)
        return max(0, quantity)

    def _should_use_inverse(self, regime: str, action: str) -> bool:
        """Inverse ETF 사용 여부를 판단한다.

        mild_bear 이상에서 bearish(sell) 신호가 발생하면
        Bull ETF 대신 Inverse 2X ETF를 사용한다.

        Args:
            regime: 현재 시장 레짐.
            action: Claude 판단 액션 ("buy" 또는 "sell").

        Returns:
            Inverse ETF를 사용해야 하면 True.
        """
        bearish_regimes = ("mild_bear", "crash")
        if regime in bearish_regimes and action == "sell":
            return True
        return False

    def _get_order_type(self) -> str:
        """현재 시장 세션에 따른 주문 유형을 결정한다.

        정규장에서는 market 주문, 프리/애프터마켓에서는 limit 주문만 가능하다.

        Returns:
            "market" 또는 "limit".
        """
        session = self.market_hours.get_session_type()
        if session == "regular":
            return "market"
        return "limit"

    @staticmethod
    def _check_direction_agreement(
        claude_action: str, indicator_direction: str
    ) -> bool:
        """Claude 판단과 기술적 지표 방향이 일치하는지 확인한다.

        Args:
            claude_action: Claude 판단 ("buy" 또는 "sell").
            indicator_direction: 지표 종합 방향 ("buy", "sell", "neutral").

        Returns:
            방향이 일치하면 True.
        """
        if claude_action == "buy" and indicator_direction == "buy":
            return True
        if claude_action == "sell" and indicator_direction == "sell":
            return True
        return False
