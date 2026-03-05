"""F4 청산 전략 -- 우선순위 기반으로 청산 판단을 내린다.

분할 청산은 단계별 상태를 추적하여 동일 단계 반복 실행을 방지한다.
트레일링 스톱은 고점(high watermark)을 추적하여 고점 대비 하락폭으로 판단한다.
"""
from __future__ import annotations

from src.analysis.models import MarketRegime
from src.common.logger import get_logger
from src.indicators.models import IndicatorBundle
from src.strategy.models import ExitDecision, Position, StatArbSignal, StrategyParams

logger = get_logger(__name__)

# 청산 유형 (우선순위순)
_EXIT_EMERGENCY = ("emergency", 0.0)
_EXIT_HARD_STOP = ("hard_stop", 1.0)
_EXIT_BEAST = ("beast_exit", 2.0)
_EXIT_TAKE_PROFIT = ("take_profit", 3.0)
_EXIT_SCALED = ("scaled_exit", 3.5)
_EXIT_NEWS_FADE = ("news_fade", 4.5)
_EXIT_STAT_ARB = ("stat_arb", 4.7)
_EXIT_TRAILING = ("trailing_stop", 5.0)
_EXIT_TIME_STOP = ("time_stop", 6.0)
_EXIT_EOD = ("eod", 9.0)

# StatArb 청산 -- mean_reversion_short 신호 시 롱 포지션 청산을 판단한다
_STAT_ARB_MIN_ZSCORE = 2.0

# NewsFading 청산 -- 뉴스 스파이크 후 하락 예상 시 롱 포지션 청산을 판단한다
_NEWS_FADE_MIN_SPIKE_PCT = 1.0

# 레짐별 하드스톱 (기본 -2%)
_REGIME_HARD_STOP: dict[str, float] = {
    "strong_bull": -3.0,
    "mild_bull": -2.0,
    "sideways": -1.5,
    "mild_bear": -1.5,
    "crash": -1.0,
}

# 분할 청산 단계 정의: (PnL 배수, 청산 비율)이다
_SCALED_LEVELS: list[tuple[float, float, int]] = [
    (1.5, 40.0, 3),  # 150% 도달: 40% 청산 (3단계)
    (1.0, 30.0, 2),  # 100% 도달: 30% 청산 (2단계)
    (0.7, 30.0, 1),  # 70% 도달: 30% 청산 (1단계)
]


def _check_emergency(bundle: IndicatorBundle) -> ExitDecision | None:
    """긴급 청산 -- VPIN 0.85 이상이면 즉시 청산한다."""
    if bundle.order_flow is None:
        return None
    if bundle.order_flow.vpin >= 0.85:
        return ExitDecision(
            should_exit=True, exit_type="emergency", exit_pct=100.0,
            priority=0.0, reason="VPIN 긴급 청산", ticker="", estimated_pnl_pct=0.0,
        )
    return None


def _check_hard_stop(position: Position, regime: MarketRegime) -> ExitDecision | None:
    """하드스톱 -- 레짐별 손절선을 초과하면 청산한다."""
    threshold = _REGIME_HARD_STOP.get(regime.regime_type, -2.0)
    if position.unrealized_pnl_pct <= threshold:
        return ExitDecision(
            should_exit=True, exit_type="hard_stop", exit_pct=100.0,
            priority=1.0, reason=f"하드스톱 {threshold}% 도달",
            ticker=position.ticker, estimated_pnl_pct=position.unrealized_pnl_pct,
        )
    return None


def _check_take_profit(
    position: Position, regime: MarketRegime,
) -> ExitDecision | None:
    """익절 -- 레짐 목표가 도달 시 청산한다. strong_bull은 트레일링만 사용하므로 스킵한다."""
    target = regime.params.take_profit
    if target == 0.0:
        return None  # strong_bull: 트레일링만 사용한다
    if position.unrealized_pnl_pct >= target:
        return ExitDecision(
            should_exit=True, exit_type="take_profit", exit_pct=100.0,
            priority=3.0, reason=f"목표 수익 {target}% 도달",
            ticker=position.ticker, estimated_pnl_pct=position.unrealized_pnl_pct,
        )
    return None


def _check_stat_arb_exit(
    position: Position,
    stat_arb_signals: list[StatArbSignal] | None,
) -> ExitDecision | None:
    """StatArb 청산 -- mean_reversion_short Z-Score 발생 시 롱 포지션을 청산한다.

    StatArb 신호 중 포지션 티커가 포함된 페어에서 short 신호가 발생하면
    해당 롱 포지션을 부분 청산(50%)하여 평균 회귀 움직임을 회피한다.
    """
    if not stat_arb_signals:
        return None
    for signal in stat_arb_signals:
        # 티커가 페어(예: QQQ/QLD)에 포함되어 있는지 확인한다
        if position.ticker in signal.pair and signal.direction == "short":
            if abs(signal.z_score) >= _STAT_ARB_MIN_ZSCORE:
                return ExitDecision(
                    should_exit=True,
                    exit_type="stat_arb",
                    exit_pct=50.0,
                    priority=4.7,
                    reason=f"StatArb 평균회귀 신호 Z={signal.z_score:.2f} ({signal.pair})",
                    ticker=position.ticker,
                    estimated_pnl_pct=position.unrealized_pnl_pct,
                )
    return None


def _check_news_fade_exit(
    position: Position,
    news_context: dict | None,
    price_spike: dict | None,
) -> ExitDecision | None:
    """NewsFading 청산 -- 뉴스 스파이크 급등 후 하락 예상 시 롱 포지션을 청산한다.

    impact_score < 0.9이고 1%+ 급등(60초 이내) 발생 시 포지션을 50% 청산하여
    뉴스 페이딩 리스크를 관리한다.
    """
    if not price_spike or not news_context:
        return None
    pct_change = price_spike.get("pct_change", 0.0)
    seconds = price_spike.get("seconds", 999)
    impact_score = news_context.get("impact_score", 0.5)

    # 급등 후 하락 예상: 롱 포지션에만 적용한다 (급등 = pct_change > 0)
    if pct_change >= _NEWS_FADE_MIN_SPIKE_PCT and seconds <= 60:
        if impact_score < 0.9:  # 고영향 뉴스는 구조적 변화일 수 있어 제외한다
            return ExitDecision(
                should_exit=True,
                exit_type="news_fade",
                exit_pct=50.0,
                priority=4.5,
                reason=f"뉴스 페이딩: {pct_change:.2f}%/{seconds}s 스파이크 (impact={impact_score:.2f})",
                ticker=position.ticker,
                estimated_pnl_pct=position.unrealized_pnl_pct,
            )
    return None


def _no_exit(ticker: str) -> ExitDecision:
    """청산 조건 미충족 시 반환한다."""
    return ExitDecision(
        should_exit=False, exit_type="none", exit_pct=0.0,
        priority=99.0, reason="청산 조건 미충족", ticker=ticker,
    )


class ExitStrategy:
    """우선순위 기반으로 청산 판단을 내린다.

    상태를 추적하여 분할 청산 반복 실행과 트레일링 스톱 조기 청산을 방지한다.
    - _executed_scales: 티커별 실행 완료된 분할 청산 단계 (1/2/3)
    - _peak_pnl: 티커별 보유 기간 중 최고 수익률 (high watermark)
    """

    def __init__(self) -> None:
        """청산 전략을 초기화한다."""
        # 분할 청산 상태: {ticker: {1, 2, 3}} — 실행된 단계 번호 집합이다
        self._executed_scales: dict[str, set[int]] = {}
        # 트레일링 스톱 고점 추적: {ticker: peak_pnl_pct} — 최고 수익률이다
        self._peak_pnl: dict[str, float] = {}

    def evaluate(
        self,
        position: Position,
        bundle: IndicatorBundle,
        regime: MarketRegime,
        params: StrategyParams,
        stat_arb_signals: list[StatArbSignal] | None = None,
        news_context: dict | None = None,
        price_spike: dict | None = None,
    ) -> ExitDecision:
        """10개 청산 유형을 우선순위순으로 평가한다.

        Args:
            position: 보유 포지션
            bundle: 지표 번들
            regime: 시장 레짐
            params: 전략 파라미터
            stat_arb_signals: StatArb 신호 목록 (없으면 None)
            news_context: 최신 뉴스 컨텍스트 (impact_score 포함)
            price_spike: 가격 스파이크 정보 (pct_change, seconds, current_price)
        """
        ticker = position.ticker

        # 고점(high watermark)을 갱신한다
        prev_peak = self._peak_pnl.get(ticker, 0.0)
        if position.unrealized_pnl_pct > prev_peak:
            self._peak_pnl[ticker] = position.unrealized_pnl_pct

        checks: list[ExitDecision | None] = [
            _check_emergency(bundle),
            _check_hard_stop(position, regime),
            # news_fade(4.5) - StatArb(4.7)보다 우선한다
            _check_news_fade_exit(position, news_context, price_spike)
            if params.news_fading_enabled else None,
            # stat_arb(4.7) - 뉴스 페이딩 다음 순서이다
            _check_stat_arb_exit(position, stat_arb_signals)
            if params.stat_arb_enabled else None,
            _check_take_profit(position, regime),
            self._check_scaled_exit(position, regime),
            self._check_trailing_stop(position, regime),
        ]

        for result in checks:
            if result is not None and result.should_exit:
                result.ticker = ticker
                logger.info(
                    "청산 판단: %s type=%s pnl=%.2f%%",
                    ticker, result.exit_type, position.unrealized_pnl_pct,
                )
                return result

        return _no_exit(ticker)

    def _check_scaled_exit(
        self, position: Position, regime: MarketRegime,
    ) -> ExitDecision | None:
        """분할 청산 -- 목표의 70/100/150% 도달 시 단계별 1회만 청산한다.

        이미 실행된 단계는 건너뛴다. 각 단계는 최초 도달 시 1회만 실행된다.
        """
        target = regime.params.take_profit
        if target == 0.0:
            return None

        ticker = position.ticker
        pnl = position.unrealized_pnl_pct
        executed = self._executed_scales.get(ticker, set())

        for multiplier, exit_pct, level in _SCALED_LEVELS:
            # 이미 실행된 단계는 건너뛴다
            if level in executed:
                continue
            threshold = target * multiplier
            if pnl >= threshold:
                return ExitDecision(
                    should_exit=True, exit_type="scaled_exit", exit_pct=exit_pct,
                    priority=3.5,
                    reason=f"분할 청산 {level}단계 ({threshold:.1f}%)",
                    ticker=ticker, estimated_pnl_pct=pnl,
                )
        return None

    def mark_scale_executed(self, ticker: str, level: int) -> None:
        """분할 청산 단계를 실행 완료로 표시한다."""
        if ticker not in self._executed_scales:
            self._executed_scales[ticker] = set()
        self._executed_scales[ticker].add(level)
        logger.debug("분할 청산 단계 기록: %s level=%d", ticker, level)

    def _check_trailing_stop(
        self, position: Position, regime: MarketRegime,
    ) -> ExitDecision | None:
        """트레일링 스톱 -- 고점 대비 하락폭이 임계값을 초과하면 청산한다.

        고점(peak PnL)에서 trailing_stop 퍼센트 이상 하락하면 청산한다.
        예: strong_bull(trailing=4.0)에서 고점 8% → 현재 3.5% → 하락 4.5% > 4.0% → 청산
        이익 구간(고점 > 0.5%)에서만 활성화한다.
        """
        trailing = regime.params.trailing_stop
        if trailing <= 0:
            return None

        ticker = position.ticker
        peak = self._peak_pnl.get(ticker, 0.0)

        # 고점이 최소 0.5% 이상 수익이었을 때만 트레일링을 활성화한다
        if peak < 0.5:
            return None

        # 고점 대비 하락폭을 계산한다
        drawdown = peak - position.unrealized_pnl_pct

        if drawdown >= trailing:
            return ExitDecision(
                should_exit=True, exit_type="trailing_stop", exit_pct=100.0,
                priority=5.0,
                reason=f"트레일링 스톱: 고점 {peak:.1f}% → 현재 {position.unrealized_pnl_pct:.1f}% (하락 {drawdown:.1f}% >= {trailing:.1f}%)",
                ticker=ticker, estimated_pnl_pct=position.unrealized_pnl_pct,
            )
        return None

    def clear_position(self, ticker: str) -> None:
        """포지션 완전 청산 시 해당 종목의 상태를 초기화한다."""
        self._executed_scales.pop(ticker, None)
        self._peak_pnl.pop(ticker, None)

    def reset_all(self) -> None:
        """세션 시작 시 모든 상태를 초기화한다."""
        self._executed_scales.clear()
        self._peak_pnl.clear()
