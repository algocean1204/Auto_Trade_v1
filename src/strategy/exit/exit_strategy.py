"""F4 청산 전략 -- 우선순위 기반으로 청산 판단을 내린다.

분할 청산은 단계별 상태를 추적하여 동일 단계 반복 실행을 방지한다.
트레일링 스톱은 고점(high watermark)을 추적하여 고점 대비 하락폭으로 판단한다.

C-5 수정: _executed_scales / _peak_pnl 상태를 캐시에 영속하여
프로세스 재시작 시 분할 청산 중복 실행과 트레일링 스톱 조기 트리거를 방지한다.
"""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine

from src.analysis.models import MarketRegime
from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.indicators.models import IndicatorBundle
from src.strategy.models import ExitDecision, Position, StatArbSignal, StrategyParams

logger = get_logger(__name__)

# 캐시 저장용 백그라운드 태스크 참조 — GC 소멸을 방지한다
_background_tasks: set[asyncio.Task] = set()

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

# Beast Mode 전용 하드스톱 (-1.0%) -- 일반 레짐 하드스톱보다 타이트하다
_BEAST_HARD_STOP_PCT = -1.0

# Beast Mode 공격적 트레일링: +1.5% 수익 진입 시 고점 대비 -0.5% 하락으로 청산한다
_BEAST_TRAILING_ACTIVATION_PCT = 1.5
_BEAST_TRAILING_DRAWDOWN_PCT = 0.5

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


def _check_hard_stop(
    position: Position,
    regime: MarketRegime,
    bundle: IndicatorBundle | None = None,
) -> ExitDecision | None:
    """하드스톱 -- ATR 기반 동적 손절 또는 레짐별 고정 손절선을 적용한다.

    ATR 데이터가 있으면 ATR 기반 동적 스톱 거리(%)를 계산하여 사용하고,
    없으면 기존 레짐별 고정 퍼센트를 폴백으로 사용한다.
    """
    threshold = _REGIME_HARD_STOP.get(regime.regime_type, -2.0)

    # ATR 기반 동적 스톱: 지표 번들에 ATR 데이터가 있으면 활용한다
    if bundle is not None and bundle.technical is not None:
        atr = getattr(bundle.technical, "atr", 0.0)
        if atr > 0 and position.avg_price > 0:
            try:
                from src.risk.gates.stop_loss import calculate_stop_loss
                sl_result = calculate_stop_loss(
                    entry_price=position.avg_price,
                    current_price=position.avg_price,  # 진입가 기준 스톱 거리 계산
                    atr=atr,
                    regime=regime.regime_type,
                )
                # ATR 스톱 가격 → 퍼센트 변환 (음수)
                atr_stop_pct = ((sl_result.stop_price - position.avg_price)
                                / position.avg_price) * 100.0
                if atr_stop_pct < 0:
                    threshold = atr_stop_pct
                    logger.debug(
                        "ATR 동적 스톱 적용: %s threshold=%.2f%% (ATR=$%.2f)",
                        position.ticker, threshold, atr,
                    )
            except Exception as exc:
                logger.debug("ATR 동적 스톱 계산 실패 (고정 스톱 사용): %s", exc)

    if position.unrealized_pnl_pct <= threshold:
        return ExitDecision(
            should_exit=True, exit_type="hard_stop", exit_pct=100.0,
            priority=1.0, reason=f"하드스톱 {threshold:.2f}% 도달",
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
    impact_threshold: float = 0.9,
) -> ExitDecision | None:
    """NewsFading 청산 -- 뉴스 스파이크 급등 후 하락 예상 시 롱 포지션을 청산한다.

    impact_score < impact_threshold이고 1%+ 급등(60초 이내) 발생 시 포지션을 50% 청산하여
    뉴스 페이딩 리스크를 관리한다.
    """
    if not price_spike or not news_context:
        return None
    pct_change = price_spike.get("pct_change", 0.0)
    seconds = price_spike.get("seconds", 999)
    impact_score = news_context.get("impact_score", 0.5)

    # 급등 후 하락 예상: 롱 포지션에만 적용한다 (급등 = pct_change > 0)
    if pct_change >= _NEWS_FADE_MIN_SPIKE_PCT and seconds <= 60:
        if impact_score < impact_threshold:  # 고영향 뉴스는 구조적 변화일 수 있어 제외한다
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


def _check_beast_exit(position: Position) -> ExitDecision | None:
    """Beast Mode 하드스톱 -- Beast 포지션이 -1.0% 도달 시 즉시 청산한다.

    Beast 포지션은 비중이 크므로 일반 하드스톱보다 타이트한 -1.0%를 적용한다.
    position.is_beast 필드가 True인 포지션에만 작동한다.
    """
    if not getattr(position, "is_beast", False):
        return None
    if position.unrealized_pnl_pct <= _BEAST_HARD_STOP_PCT:
        return ExitDecision(
            should_exit=True, exit_type="beast_exit", exit_pct=100.0,
            priority=2.0,
            reason=f"Beast 하드스톱 {_BEAST_HARD_STOP_PCT}% 도달",
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

    cache가 주입되면 캐시에 상태를 영속하여 프로세스 재시작 시 복원한다.
    """

    # 캐시 키 상수
    _CACHE_KEY_SCALES = "exit:scales"
    _CACHE_KEY_PEAK_PNL = "exit:peak_pnl"
    _CACHE_TTL = 86400  # 24시간

    def __init__(self, cache: CacheClient | None = None) -> None:
        """청산 전략을 초기화한다.

        Args:
            cache: 캐시 클라이언트. None이면 메모리 전용 모드로 동작한다.
        """
        self._cache = cache
        # 분할 청산 상태: {ticker: {1, 2, 3}} — 실행된 단계 번호 집합이다
        self._executed_scales: dict[str, set[int]] = {}
        # 트레일링 스톱 고점 추적: {ticker: peak_pnl_pct} — 최고 수익률이다
        self._peak_pnl: dict[str, float] = {}

    # -- 캐시 영속화 --

    async def load_state(self) -> None:
        """캐시에서 영속된 상태를 복원한다. 초기화 직후 호출해야 한다."""
        if self._cache is None:
            return
        self._load_scales_from(await self._read_json_safe(self._CACHE_KEY_SCALES))
        self._load_peak_pnl_from(await self._read_json_safe(self._CACHE_KEY_PEAK_PNL))

    async def _read_json_safe(self, key: str) -> dict | list | None:
        """캐시에서 JSON을 읽는다. 실패 시 None을 반환한다 (fail-open)."""
        if self._cache is None:
            return None
        try:
            return await self._cache.read_json(key)
        except Exception:
            logger.warning("캐시 읽기 실패 (메모리 전용으로 계속): key=%s", key)
            return None

    def _load_scales_from(self, data: dict | list | None) -> None:
        """캐시에서 읽은 scales 데이터를 메모리에 적용한다 (list→set 변환)."""
        if not isinstance(data, dict):
            return
        for ticker, levels in data.items():
            if isinstance(levels, list):
                self._executed_scales[ticker] = set(levels)
        logger.info("캐시에서 분할 청산 상태 복원: %d건", len(self._executed_scales))

    def _load_peak_pnl_from(self, data: dict | list | None) -> None:
        """캐시에서 읽은 peak_pnl 데이터를 메모리에 적용한다."""
        if not isinstance(data, dict):
            return
        for ticker, peak in data.items():
            if isinstance(peak, (int, float)):
                self._peak_pnl[ticker] = float(peak)
        logger.info("캐시에서 고점 PnL 상태 복원: %d건", len(self._peak_pnl))

    def _save_scales(self) -> None:
        """_executed_scales를 캐시에 비동기로 저장한다 (set→list 변환)."""
        if self._cache is None:
            return
        # JSON 직렬화를 위해 set → list 변환한다
        serializable = {t: list(s) for t, s in self._executed_scales.items()}
        self._fire_and_forget(
            self._cache.write_json(self._CACHE_KEY_SCALES, serializable, ttl=self._CACHE_TTL),
        )

    def _save_peak_pnl(self) -> None:
        """_peak_pnl을 캐시에 비동기로 저장한다."""
        if self._cache is None:
            return
        self._fire_and_forget(
            self._cache.write_json(self._CACHE_KEY_PEAK_PNL, dict(self._peak_pnl), ttl=self._CACHE_TTL),
        )

    @staticmethod
    def _fire_and_forget(coro: Coroutine[object, object, None]) -> None:
        """코루틴을 현재 이벤트 루프에 fire-and-forget으로 예약한다.

        캐시 저장 실패 시 로그만 남기고 매매 로직에 영향을 주지 않는다.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 이벤트 루프가 없으면 저장을 건너뛴다 (테스트 등 동기 환경)
            return

        async def _safe_save() -> None:
            try:
                await coro  # type: ignore[misc]
            except Exception:
                logger.warning("캐시 저장 실패 (매매 로직에 영향 없음)")

        task = loop.create_task(_safe_save())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

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
        self._current_sp = params
        ticker = position.ticker

        # 고점(high watermark)을 갱신한다
        prev_peak = self._peak_pnl.get(ticker, 0.0)
        if position.unrealized_pnl_pct > prev_peak:
            self._peak_pnl[ticker] = position.unrealized_pnl_pct
            self._save_peak_pnl()

        checks: list[ExitDecision | None] = [
            _check_emergency(bundle),
            _check_hard_stop(position, regime, bundle),
            _check_beast_exit(position),
            # Beast 공격적 트레일링 (+1.5% 진입 → -0.5% 하락 청산)
            self._check_beast_trailing(position),
            # news_fade(4.5) - StatArb(4.7)보다 우선한다
            _check_news_fade_exit(position, news_context, price_spike, params.news_fade_impact_threshold)
            if params.news_fading_enabled else None,
            # stat_arb(4.7) - 뉴스 페이딩 다음 순서이다
            _check_stat_arb_exit(position, stat_arb_signals)
            if params.stat_arb_enabled else None,
            self._check_scaled_exit(position, regime),
            _check_take_profit(position, regime),
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
                    exit_level=level,
                )
        return None

    def mark_scale_executed(self, ticker: str, level: int) -> None:
        """분할 청산 단계를 실행 완료로 표시한다."""
        if ticker not in self._executed_scales:
            self._executed_scales[ticker] = set()
        self._executed_scales[ticker].add(level)
        self._save_scales()
        logger.debug("분할 청산 단계 기록: %s level=%d", ticker, level)

    def _check_beast_trailing(self, position: Position) -> ExitDecision | None:
        """Beast 공격적 트레일링 -- +1.5% 수익권 진입 후 고점 대비 -0.5% 하락 시 청산한다.

        고정 익절을 없애고, 수익이 +1.5%에 진입하면 고점 대비 -0.5% 하락할 때까지
        끝까지 수익을 쫓아가는 탐욕적 파도타기(Greedy Ride) 전략이다.
        Beast 포지션에만 적용한다.
        """
        if not getattr(position, "is_beast", False):
            return None
        ticker = position.ticker
        peak = self._peak_pnl.get(ticker, 0.0)
        # 고점이 +1.5% 이상이었을 때만 Beast 트레일링을 활성화한다
        if peak < _BEAST_TRAILING_ACTIVATION_PCT:
            return None
        drawdown = peak - position.unrealized_pnl_pct
        if drawdown >= _BEAST_TRAILING_DRAWDOWN_PCT:
            return ExitDecision(
                should_exit=True, exit_type="beast_trailing", exit_pct=100.0,
                priority=2.5,
                reason=(
                    f"Beast 트레일링: 고점 {peak:.1f}% → 현재 "
                    f"{position.unrealized_pnl_pct:.1f}% "
                    f"(하락 {drawdown:.1f}% >= {_BEAST_TRAILING_DRAWDOWN_PCT}%)"
                ),
                ticker=ticker,
                estimated_pnl_pct=position.unrealized_pnl_pct,
            )
        return None

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

        # 소량 잔여 포지션은 트레일링 폭을 완화한다 (파라미터 기반)
        sp = getattr(self, '_current_sp', None)
        small_qty = sp.min_exit_qty if sp else 5
        trail_mult = sp.small_position_trailing_multiplier if sp else 1.5
        if position.quantity <= small_qty:
            trailing = trailing * trail_mult

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
        self._save_scales()
        self._save_peak_pnl()

    def reset_all(self) -> None:
        """세션 시작 시 모든 상태를 초기화한다."""
        self._executed_scales.clear()
        self._peak_pnl.clear()
        self._save_scales()
        self._save_peak_pnl()
