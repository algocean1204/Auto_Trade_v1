"""F9.4 TradingLoop -- 세션별 동적 주기로 매매 루프를 반복한다.

포지션 사이징: position_size_pct(%)를 계좌 자산과 현재가로 실제 주식 수로 변환한다.
분할 청산: ExitStrategy의 상태 추적을 활용하여 동일 단계 반복 실행을 방지한다.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from src.common.logger import get_logger
from src.common.market_clock import SessionType, TimeInfo
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)
_AUTO_STOP_MINUTES: int = 420  # 07:00 KST (분 단위)
_REGULAR_SESSIONS: frozenset[str] = frozenset({"power_open", "mid_day", "power_hour"})


def _pct_to_shares(pct: float, total_equity: float, price: float) -> int:
    """포지션 퍼센트(%)를 실제 주식 수로 변환한다.

    Args:
        pct: 계좌 대비 퍼센트 (예: 5.0 = 5%)
        total_equity: 계좌 총자산 (USD)
        price: 현재 주가 (USD)

    Returns:
        주식 수 (최소 1, 최대 9999)
    """
    if price <= 0 or total_equity <= 0 or pct <= 0:
        return 0
    dollar_amount = total_equity * pct / 100.0
    shares = int(dollar_amount / price)
    return max(1, min(shares, 9999))


def _get_current_price(bundle: object) -> float:
    """IndicatorBundle에서 현재가를 추출한다. 없으면 0.0이다.

    우선순위: technical.ema_20 → intraday.vwap → volume_profile.poc_price
    """
    tech = getattr(bundle, "technical", None)
    if tech is not None:
        ema = getattr(tech, "ema_20", 0.0)
        if ema > 0:
            return ema
    # 기술적 지표 미가용 시 장중 VWAP을 폴백으로 사용한다
    intraday = getattr(bundle, "intraday", None)
    if intraday is not None:
        vwap = getattr(intraday, "vwap", 0.0)
        if vwap > 0:
            return vwap
    # 장중 지표도 미가용 시 볼륨 프로파일 POC를 폴백으로 사용한다
    vp = getattr(bundle, "volume_profile", None)
    if vp is not None:
        poc = getattr(vp, "poc_price", 0.0)
        if poc > 0:
            return poc
    return 0.0


async def _check_iteration_safety(system: InjectedSystem) -> bool:
    """반복 시작 전 안전 조건을 검사한다.

    EmergencyProtocol 중단 상태 또는 CapitalGuard 손실 한도 도달 시 False를 반환한다.
    안전 모듈 자체에서 예외 발생 시 경고만 기록하고 True(fail-open)를 반환한다.
    """
    try:
        ep = system.features.get("emergency_protocol")
        if ep is not None and ep.is_halted():  # type: ignore[union-attr]
            logger.warning("[반복안전] EmergencyProtocol 매매 중단 상태 -- 이번 반복 건너뜀")
            return False
    except Exception as exc:
        logger.warning("[반복안전] EmergencyProtocol 검사 실패 (통과 처리): %s", exc)

    try:
        cg = system.features.get("capital_guard")
        if cg is not None:
            if cg.is_daily_limit_reached():  # type: ignore[union-attr]
                logger.warning("[반복안전] CapitalGuard 일일 손실 한도 도달 -- 이번 반복 건너뜀")
                return False
            if cg.is_weekly_limit_reached():  # type: ignore[union-attr]
                logger.warning("[반복안전] CapitalGuard 주간 손실 한도 도달 -- 이번 반복 건너뜀")
                return False
    except Exception as exc:
        logger.warning("[반복안전] CapitalGuard 검사 실패 (통과 처리): %s", exc)

    return True


def _check_buy_safety(
    system: InjectedSystem,
    ticker: str,
    quantity: int,
    regime_type: str,
    vix_val: float,
    balance: object,
) -> bool:
    """매수 주문 전 SafetyChecker + HardSafety를 순차 검증한다.

    SafetyChecker: VIX 극단치, 3x 레버리지 제한, 거래 시간 외 차단을 검사한다.
    HardSafety: 단일 종목 비중, 하락장 bull ETF 차단, 동시 포지션 수 제한을 검사한다.
    두 모듈 중 하나라도 실패하면 False를 반환한다.
    모듈 자체에서 예외 발생 시 경고만 기록하고 True(fail-open)를 반환한다.
    """
    # 1단계: SafetyChecker -- 레짐/VIX/거래시간 검증
    try:
        sc = system.features.get("safety_checker")
        if sc is not None:
            result = sc.check(ticker, regime_type, vix_val)  # type: ignore[union-attr]
            if not result.passed:
                logger.warning(
                    "[매수안전] SafetyChecker 차단: %s -- %s",
                    ticker, result.reason,
                )
                return False
    except Exception as exc:
        logger.warning("[매수안전] SafetyChecker 검사 실패 (통과 처리): %s %s", ticker, exc)

    # 2단계: HardSafety -- 비중/레짐/포지션 수 검증
    try:
        hs = system.features.get("hard_safety")
        if hs is not None:
            result = hs.check(ticker, "buy", quantity, balance, regime_type)  # type: ignore[union-attr]
            if not result.passed:
                logger.warning(
                    "[매수안전] HardSafety 차단: %s -- %s",
                    ticker, result.reason,
                )
                return False
    except Exception as exc:
        logger.warning("[매수안전] HardSafety 검사 실패 (통과 처리): %s %s", ticker, exc)

    return True


class LoopIterationResult(BaseModel):
    """루프 1회 반복 결과이다."""
    session_type: str
    interval_seconds: int
    trades_executed: int = 0
    errors: list[str] = []
    should_continue: bool = True

def determine_session(time_info: TimeInfo) -> SessionType:
    """현재 세션 유형을 결정한다. MarketClock 값을 그대로 위임한다."""
    return time_info.session_type

def calculate_interval(session_type: str) -> int:
    """세션별 루프 주기(초)를 계산한다."""
    intervals: dict[str, int] = {
        "power_open": 90, "mid_day": 180, "power_hour": 120,
        "pre_market": 60, "final_monitoring": 60, "preparation": 60,
    }
    return intervals.get(session_type, 60)

def should_run_monitor_all(session_type: str) -> bool:
    """정규 세션만 True, 비정규 세션은 sync_positions()만 실행한다."""
    return session_type in _REGULAR_SESSIONS

async def check_shutdown(
    time_info: TimeInfo,
    shutdown_event: asyncio.Event,
) -> bool:
    """종료 조건을 확인한다. 07:00 KST 이후 또는 수동 종료 시 True이다."""
    kst = time_info.now_kst
    kst_minutes = kst.hour * 60 + kst.minute
    if _AUTO_STOP_MINUTES <= kst_minutes < 1200:
        logger.info("자동 종료 시각 도달 (KST %02d:%02d)", kst.hour, kst.minute)
        return True
    if shutdown_event.is_set():
        logger.info("수동 종료 신호 수신")
        return True
    return False

async def _sync_positions_only(system: InjectedSystem) -> None:
    """비정규 세션에서 포지션 동기화만 수행한다. monitor_all 금지."""
    pos_monitor = system.features.get("position_monitor")
    if pos_monitor is None:
        logger.warning("PositionMonitor 미등록 -- 동기화 건너뜀")
        return
    try:
        positions = await pos_monitor.sync_positions()  # type: ignore[union-attr]
        logger.info("포지션 동기화 완료: %d개 종목", len(positions))
    except Exception as exc:
        logger.error("포지션 동기화 실패: %s", exc)

async def _notify_trade_telegram(
    system: InjectedSystem,
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    reason: str,
    pnl_pct: float | None,
) -> None:
    """매매 체결 시 텔레그램으로 사유를 포함한 알림을 발송한다."""
    try:
        notifier = system.features.get("telegram_notifier")
        if notifier is None:
            return
        emoji = "🟢 매수" if side == "buy" else "🔴 매도"
        total = price * quantity
        lines = [
            f"{emoji} <b>{ticker}</b>",
            f"수량: {quantity}주 | 가격: ${price:,.2f} | 금액: ${total:,.2f}",
        ]
        if reason:
            lines.append(f"📝 사유: {reason}")
        if pnl_pct is not None:
            pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
            lines.append(f"{pnl_emoji} 수익률: {pnl_pct:+.2f}%")
        message = "\n".join(lines)
        await notifier.send_raw(message)
    except Exception as exc:
        logger.debug("텔레그램 매매 알림 실패 (무시): %s", exc)


async def _record_trade(
    system: InjectedSystem,
    ticker: str,
    side: str,
    quantity: int,
    price: float,
    exit_type: str | None,
    pnl_pct: float | None,
    reason: str = "",
) -> None:
    """체결된 거래를 Redis(trades:today)에 기록하고 텔레그램 알림을 발송한다.

    EOD 피드백/최적화 시스템이 trades:today를 읽어 분석에 활용한다.
    트레이딩 루프에 영향을 주지 않도록 모든 예외를 흡수한다.
    """
    try:
        cache = system.components.cache
        record: dict = {
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exit_type": exit_type,
            "pnl": (pnl_pct * quantity * price / 100.0) if pnl_pct is not None and price > 0 else None,
            "reason": reason,
        }
        trades_list: list[dict] = await cache.read_json("trades:today") or []
        trades_list.append(record)
        await cache.write_json("trades:today", trades_list, ttl=86400)
        logger.debug("거래 기록 완료: %s %s %s %d주", side, ticker, exit_type or "", quantity)
    except Exception as exc:
        logger.warning("거래 기록 실패 (무시): %s", exc)

    # 텔레그램 알림 발송 (기록 실패와 독립적으로 실행)
    await _notify_trade_telegram(system, ticker, side, quantity, price, reason, pnl_pct)


async def _run_beast_entry(
    system: InjectedSystem,
    ticker: str,
    bundle: object,
    regime: object,
    vix_val: float,
    balance: object,
    sp: object,
    om: object,
    reg: object,
) -> int:
    """Beast Mode A+ 셋업을 평가하고 진입 주문을 실행한다.

    BeastMode 활성화 시 일반 진입과 별도 경로로 고확신 매매를 실행한다.
    실패는 개별 격리하여 정규 진입에 영향을 주지 않는다.
    """
    try:
        beast = system.features.get("beast_mode")
        if beast is None:
            return 0

        from src.indicators.models import IndicatorBundle as _IB
        from src.strategy.models import StrategyParams as _SP
        bun: _IB = bundle  # type: ignore[assignment]
        params: _SP = sp  # type: ignore[assignment]

        if not params.beast_mode_enabled:
            return 0

        # 필요한 지표 값을 추출한다. 없으면 기본값으로 폴백한다
        confidence = bun.order_flow.execution_strength if bun.order_flow else 0.5
        obi_score = bun.order_flow.obi if bun.order_flow else 0.0
        leader_momentum = bun.momentum.alignment if bun.momentum else 0.0
        volume_ratio = 1.0  # 기본 볼륨 비율 (실시간 데이터 없을 때)
        whale_alignment = (bun.whale.total_score > 0.3) if bun.whale else False

        # 일일 Beast Mode 카운트와 마지막 실패 시각을 Redis에서 읽는다
        daily_beast_count = 0
        last_failure_time_val: float | None = None
        try:
            cache = system.components.cache
            bc_raw = await cache.read("beast:daily_count")
            if bc_raw is not None:
                daily_beast_count = int(bc_raw)
            lf_raw = await cache.read("beast:last_failure_time")
            if lf_raw is not None:
                last_failure_time_val = float(lf_raw)
        except Exception:
            pass

        bd = beast.evaluate(  # type: ignore[union-attr]
            confidence=confidence,
            obi_score=obi_score,
            leader_momentum=leader_momentum,
            volume_ratio=volume_ratio,
            whale_alignment=whale_alignment,
            regime=regime,
            vix=vix_val,
            params=params,
            daily_beast_count=daily_beast_count,
            last_failure_time=last_failure_time_val,
        )

        if not bd.activated:
            logger.debug("Beast Mode 미활성화 (%s): %s", ticker, bd.rejection_reason)
            return 0

        price = _get_current_price(bundle)
        if price <= 0:
            logger.warning("Beast 진입차단: %s 현재가 미확보", ticker)
            return 0
        q = _pct_to_shares(bd.position_size_pct, balance.total_equity, price)  # type: ignore[union-attr]
        if q <= 0:
            return 0

        # SafetyChecker → HardSafety 안전 검사
        if not _check_buy_safety(
            system, ticker, q, regime.regime_type, vix_val, balance,  # type: ignore[union-attr]
        ):
            logger.info("Beast 진입차단(안전): %s", ticker)
            return 0

        exchange = reg.get_exchange_code(ticker) if reg.has_ticker(ticker) else "NAS"
        r = await om.execute_buy(ticker, q, exchange)  # type: ignore[union-attr]
        if r.status == "filled":
            logger.info(
                "Beast 진입: %s %d주 @%.2f (conviction=%.2fx, composite=%.4f)",
                ticker, q, price, bd.conviction_multiplier, bd.composite_score,
            )
            await _record_trade(
                system, ticker, "buy", q, price, "beast", None,
                reason=f"Beast Mode 진입 (확신도 {bd.conviction_multiplier:.1f}x, 종합점수 {bd.composite_score:.3f})",
            )

            # Beast 진입 성공 시 일일 카운트를 증가시킨다
            try:
                await cache.write("beast:daily_count", str(daily_beast_count + 1), ttl=86400)
            except Exception:
                pass

            # Beast 진입 이벤트를 발행한다
            from src.analysis.models import TradingDecision
            from src.common.event_bus import EventType, get_event_bus
            await get_event_bus().publish(
                EventType.BEAST_ENTRY,
                TradingDecision(
                    action="buy",
                    ticker=ticker,
                    confidence=bd.composite_score,
                    size_pct=bd.position_size_pct,
                    reason=f"Beast Mode A+ (conviction={bd.conviction_multiplier:.2f}x)",
                ),
            )
            return 1
        # Beast 주문 실패 시 마지막 실패 시각을 기록한다 (쿨다운용)
        logger.warning("Beast 진입X: %s %s", ticker, r.message)
        try:
            import time as _time
            await cache.write("beast:last_failure_time", str(_time.time()), ttl=86400)
        except Exception:
            pass
    except Exception as exc:
        logger.error("Beast 진입E (%s): %s", ticker, exc)
    return 0


async def _run_pyramiding(
    system: InjectedSystem,
    pos_items: list[object],
    regime: object,
    vix_val: float,
    balance: object,
    sp: object,
    om: object,
    reg: object,
) -> int:
    """보유 포지션에 대해 피라미딩(추가 진입)을 평가한다.

    수익 중인 포지션에 단계적 추가 진입을 실행한다.
    실패는 개별 격리하여 다른 포지션에 영향을 주지 않는다.
    """
    trades = 0
    try:
        pyramiding = system.features.get("pyramiding")
        if pyramiding is None:
            return 0
        from src.strategy.models import Position as _Pos, StrategyParams as _SP
        params: _SP = sp  # type: ignore[assignment]
        if not params.pyramiding_enabled:
            return 0
    except Exception:
        return 0

    for p in pos_items:
        try:
            market_state = {
                "regime_type": regime.regime_type,  # type: ignore[union-attr]
                "vix": vix_val,
                "portfolio_risk_pct": 5.0,  # 기본값 (실제 리스크 계산 미구현)
                "ticker_concentration_pct": 10.0,  # 기본값
            }
            pd_decision = pyramiding.evaluate(p, market_state, sp)  # type: ignore[union-attr]
            if not pd_decision.should_add:
                continue

            # 피라미딩 퍼센트를 실제 주수로 변환한다
            pyr_price = p.current_price if p.current_price > 0 else p.avg_price  # type: ignore[union-attr]
            pyr_equity = balance.total_equity if hasattr(balance, "total_equity") else 0.0  # type: ignore[union-attr]
            q = _pct_to_shares(pd_decision.add_size_pct, pyr_equity, pyr_price)
            if q <= 0:
                continue
            exchange = reg.get_exchange_code(p.ticker) if reg.has_ticker(p.ticker) else "NAS"  # type: ignore[union-attr]
            r = await om.execute_buy(p.ticker, q, exchange)  # type: ignore[union-attr]
            if r.status == "filled":
                trades += 1
                logger.info(
                    "피라미딩 진입: %s level=%d %d주 @%.2f (ratchet=%.2f%%)",
                    p.ticker, pd_decision.level, q, pyr_price, pd_decision.ratchet_stop,  # type: ignore[union-attr]
                )
                await _record_trade(
                    system, p.ticker, "buy", q, pyr_price,  # type: ignore[union-attr]
                    f"pyramid_level{pd_decision.level}", None,
                    reason=f"피라미딩 {pd_decision.level}단계 추가매수 (래칫스탑 {pd_decision.ratchet_stop:.1f}%)",
                )

                # 피라미딩 이벤트를 발행한다
                from src.analysis.models import TradingDecision
                from src.common.event_bus import EventType, get_event_bus
                await get_event_bus().publish(
                    EventType.PYRAMID_TRIGGERED,
                    TradingDecision(
                        action="buy",
                        ticker=p.ticker,  # type: ignore[union-attr]
                        confidence=0.7,
                        size_pct=pd_decision.add_size_pct,
                        reason=pd_decision.reason,
                    ),
                )
            else:
                logger.warning("피라미딩X: %s %s", p.ticker, r.message)  # type: ignore[union-attr]
        except Exception as exc:
            logger.error("피라미딩E (%s): %s", getattr(p, "ticker", "?"), exc)
    return trades


async def _run_decision_maker(
    system: InjectedSystem,
    regime: object,
    pos: dict,
    cache: object,
    balance: object | None = None,
) -> None:
    """사전 종합 분석 보고서를 기반으로 매매 판단을 생성하고 이벤트를 발행한다.

    DecisionMaker가 TradingDecision 이벤트를 발행하면 구독 모듈이
    자동으로 반응한다. 판단 결과는 Redis에 저장하여 추적 가능하도록 한다.
    """
    try:
        dm = system.features.get("decision_maker")
        if dm is None:
            return

        # 사전 분석 보고서를 Redis에서 읽는다 (Step 5에서 저장됨)
        report_data = await cache.read_json("analysis:comprehensive_report")  # type: ignore[union-attr]
        if not report_data:
            logger.debug("[DecisionMaker] 사전 분석 보고서 없음 -- 건너뜀")
            return

        from src.analysis.models import ComprehensiveReport, PortfolioState
        from datetime import datetime, timedelta, timezone
        report_data.setdefault("timestamp", datetime.now(tz=timezone.utc).isoformat())
        # 보고서 TTL 체크: 1시간 이내 보고서만 사용한다
        try:
            ts_str = report_data.get("timestamp", "")
            report_ts = datetime.fromisoformat(ts_str)
            if report_ts.tzinfo is None:
                report_ts = report_ts.replace(tzinfo=timezone.utc)
            age = datetime.now(tz=timezone.utc) - report_ts
            if age > timedelta(hours=1):
                logger.warning(
                    "[DecisionMaker] 보고서 만료 (%.1f분 전) -- 건너뜀",
                    age.total_seconds() / 60,
                )
                return
        except (ValueError, TypeError) as exc:
            logger.debug("[DecisionMaker] 타임스탬프 파싱 실패 (계속 진행): %s", exc)
        report = ComprehensiveReport(**report_data)
        portfolio = PortfolioState(
            positions=[v.model_dump() if hasattr(v, "model_dump") else v for v in pos.values()] if pos else [],
            cash_available=getattr(balance, "available_cash", 0.0) if balance else 0.0,
            total_value=getattr(balance, "total_equity", 0.0) if balance else 0.0,
        )
        decision = await dm.decide(report, portfolio)  # type: ignore[union-attr]
        logger.info(
            "[DecisionMaker] 판단: %s %s (conf=%.2f)",
            decision.action, decision.ticker, decision.confidence,
        )
    except Exception as exc:
        logger.warning("[DecisionMaker] 판단 실패 (무시): %s", exc)


async def _run_micro_regime_gate(
    system: InjectedSystem,
    ticker: str,
    builder: object,
) -> bool:
    """MicroRegime으로 미시 레짐을 평가한다. trending 레짐이면 진입을 허용한다.

    MicroRegime 미등록이거나 데이터 부족 시 fail-open으로 True를 반환한다.
    """
    try:
        micro = system.features.get("micro_regime")
        if micro is None:
            return True  # 미등록 시 통과

        # 5분봉 캔들이 IndicatorBundleBuilder에 있는지 확인한다
        if builder is None:
            return True

        # IndicatorBundleBuilder에서 5분봉 캔들을 조회한다
        candles = None
        try:
            candles = await builder.get_candles_5m(ticker)  # type: ignore[union-attr]
        except AttributeError:
            # get_candles_5m 미구현 시 통과 처리한다
            return True

        if candles is None or len(candles) < 10:
            return True  # 데이터 부족 시 통과

        result = micro.evaluate(candles)  # type: ignore[union-attr]
        # trending/mean_reverting 레짐에서만 진입을 허용한다
        allowed = result.regime in ("trending", "mean_reverting")
        if not allowed:
            logger.info(
                "MicroRegime 차단: %s regime=%s score=%.4f",
                ticker, result.regime, result.score,
            )
        return allowed
    except Exception as exc:
        logger.warning("MicroRegime 평가 실패 (통과 처리): %s %s", ticker, exc)
        return True


async def _run_wick_catcher(
    system: InjectedSystem,
    ticker: str,
    bundle: object,
    regime: object,
    vix_val: float,
    balance: object,
    sp: object,
    om: object,
    reg: object,
) -> int:
    """WickCatcher로 급격한 하방 윅에서 역방향 진입을 평가한다.

    VPIN/CVD 임계값 충족 시 리밋 주문을 실행한다.
    실패는 개별 격리하여 정규 진입에 영향을 주지 않는다.
    """
    try:
        wc = system.features.get("wick_catcher")
        if wc is None:
            return 0
        from src.strategy.models import StrategyParams as _SP
        params: _SP = sp  # type: ignore[assignment]
        if not params.wick_catcher_enabled:
            return 0
        from src.indicators.models import IndicatorBundle as _IB
        bun: _IB = bundle  # type: ignore[assignment]
        if bun.order_flow is None:
            return 0

        intraday_state = {
            "vpin": bun.order_flow.vpin,
            "cvd": bun.order_flow.cvd,
            "price": 0.0,  # 실시간 가격 미가용 시 기본값
        }
        # 현재가를 technical에서 추출한다
        if bun.technical is not None:
            intraday_state["price"] = bun.technical.ema_20

        wd = wc.evaluate(intraday_state)  # type: ignore[union-attr]
        if not wd.should_catch:
            return 0

        # 포지션 퍼센트를 실제 주수로 변환한다 (기본의 50% 사이즈)
        wick_price = intraday_state.get("price", 0.0)
        if wick_price <= 0:
            return 0
        wick_equity = balance.total_equity if hasattr(balance, "total_equity") else 0.0  # type: ignore[union-attr]
        q = _pct_to_shares(params.default_position_size_pct * 0.5, wick_equity, wick_price)
        if q <= 0:
            return 0
        if not _check_buy_safety(
            system, ticker, q, regime.regime_type, vix_val, balance,  # type: ignore[union-attr]
        ):
            logger.info("Wick 진입차단(안전): %s", ticker)
            return 0

        exchange = reg.get_exchange_code(ticker) if reg.has_ticker(ticker) else "NAS"
        r = await om.execute_buy(ticker, q, exchange)  # type: ignore[union-attr]
        if r.status == "filled":
            logger.info("WickCatcher 진입: %s %d주 @%.2f", ticker, q, wick_price)
            await _record_trade(
                system, ticker, "buy", q, wick_price, "wick_catch", None,
                reason="급락 윅(Wick) 반등 포착 진입",
            )
            return 1
        logger.warning("Wick 진입X: %s %s", ticker, r.message)
    except Exception as exc:
        logger.error("WickCatcher E (%s): %s", ticker, exc)
    return 0


def _get_sector_rotation_signal(system: InjectedSystem) -> object | None:
    """캐시된 섹터 로테이션 신호(RotationSignal)를 반환한다.

    SectorRotation 인스턴스의 cached_signal을 반환한다.
    evaluate()가 한 번도 실행되지 않았으면 None을 반환한다.
    """
    sr = system.features.get("sector_rotation")
    if sr is None:
        return None
    return getattr(sr, "cached_signal", None)


async def _fetch_stat_arb_signals(system: InjectedSystem) -> list | None:
    """StatArb 모듈로 페어 Z-Score 신호를 조회한다.

    StatArb 미등록 또는 pair_prices 데이터 미가용 시 None을 반환한다.
    """
    try:
        stat_arb = system.features.get("stat_arb")
        if stat_arb is None:
            return None
        from src.strategy.models import StrategyParams
        sp = StrategyParams()
        try:
            m = system.features.get("strategy_params")
            if m:
                sp = m.load()  # type: ignore[union-attr]
        except Exception:
            pass
        if not sp.stat_arb_enabled:
            return None

        # 페어 가격을 Redis에서 읽는다 (가격 업데이트 모듈이 별도 저장한다)
        pair_prices: dict[str, float] = {}
        try:
            cached = await system.components.cache.read_json("market:pair_prices")
            if cached and isinstance(cached, dict):
                pair_prices = cached
        except Exception:
            pass

        if not pair_prices:
            return None

        signals = await stat_arb.evaluate(pair_prices, system.components.cache)  # type: ignore[union-attr]
        if signals:
            logger.info("StatArb 신호 %d건 조회 완료", len(signals))
        return signals
    except Exception as exc:
        logger.warning("StatArb 신호 조회 실패 (무시): %s", exc)
        return None


async def _fetch_news_context(system: InjectedSystem) -> dict | None:
    """최신 뉴스 컨텍스트를 Redis에서 읽어 반환한다.

    뉴스 파이프라인이 저장한 고영향 뉴스 요약을 반환한다.
    """
    try:
        cached = await system.components.cache.read_json("news:latest_summary")
        if cached and isinstance(cached, dict) and cached.get("items"):
            # 첫 번째 고영향 뉴스를 컨텍스트로 반환한다
            items = cached.get("items", [])
            if items:
                return items[0]
        return None
    except Exception:
        return None


def _estimate_price_spike(position: object) -> dict | None:
    """현재가 대비 평단가 변동률로 간이 가격 스파이크를 추정한다.

    실시간 스파이크 감지기가 없으므로 현재가 vs 평단가로 근사한다.
    1% 이상 변동이 있고 current_price > 0이면 스파이크 딕셔너리를 반환한다.
    """
    try:
        avg = getattr(position, "avg_price", 0.0)
        cur = getattr(position, "current_price", 0.0)
        if avg <= 0 or cur <= 0:
            return None
        pct_change = (cur - avg) / avg * 100.0
        if abs(pct_change) >= 1.0:
            return {
                "pct_change": pct_change,
                "seconds": 30,  # 근사값 (실시간 측정 불가)
                "current_price": cur,
            }
        return None
    except Exception:
        return None


def _estimate_price_spike_from_bundle(bundle: object) -> dict | None:
    """IndicatorBundle의 기술적 지표로 간이 가격 스파이크를 추정한다.

    진입 판단 시 사용한다. EMA20 대비 SMA200 변동률이 1% 이상이면
    스파이크로 간주한다. 실시간 가격 데이터가 없으므로 근사값이다.
    """
    try:
        tech = getattr(bundle, "technical", None)
        if tech is None:
            return None
        ema20 = getattr(tech, "ema_20", 0.0)
        sma200 = getattr(tech, "sma_200", 0.0)
        if ema20 <= 0 or sma200 <= 0:
            return None
        pct_change = (ema20 - sma200) / sma200 * 100.0
        if abs(pct_change) >= 1.0:
            return {
                "pct_change": pct_change,
                "seconds": 30,  # 근사값
                "current_price": ema20,
            }
        return None
    except Exception:
        return None


async def _run_regular_session(system: InjectedSystem) -> int:  # noqa: C901
    """정규 세션: 동기화 + 청산 + 진입을 수행한다. 체결 건수를 반환한다.

    청산 우선순위: emergency -> hard_stop -> news_fade -> stat_arb -> take_profit -> trailing
    진입 우선순위: Beast Mode (A+ 셋업) -> MicroRegime 게이트 -> WickCatcher -> 일반 진입
    포지션 관리: Pyramiding (추가 진입)

    추가 DI 피처 활용:
      tilt_detector -- 감정적 매매 감지 시 진입 전체 건너뜀
      gap_risk_protector -- 갭 리스크 EXTREME 시 해당 종목 진입 차단
      news_fading -- 진입 시 뉴스 스파이크 역방향 페이딩 조정
      net_liquidity_tracker -- FRED 순유동성 바이어스로 포지션 배수 조정
      order_flow_aggregator -- 세션 시작 시 주문 흐름 사전 집계
      contango_detector -- VIX 기간구조 콘탱고 정보 컨텍스트 보강
      leverage_decay -- 디케이 심각 시 포지션 사이즈 감소
      nav_premium_tracker -- 과도한 프리미엄 시 진입 차단
    """
    from src.common.broker_gateway import BalanceData
    from src.indicators.models import IndicatorBundle
    from src.strategy.models import Position, StrategyParams
    _P = lambda d: Position(ticker=d.ticker, quantity=d.quantity, avg_price=d.avg_price, current_price=d.current_price, unrealized_pnl_pct=d.pnl_pct)  # type: ignore[union-attr]  # noqa: E731
    trades, f, reg = 0, system.features, system.components.registry
    pm = f.get("position_monitor")
    if not pm:
        logger.warning("PositionMonitor 미등록"); return 0
    try:
        pos = await pm.sync_positions()  # type: ignore[union-attr]
    except Exception as e:
        logger.error("동기화 실패: %s", e); return 0
    regime = None
    # 매수 안전 검사에서 사용할 VIX 값을 보존한다
    vix_val = 20.0
    try:
        d = f.get("regime_detector")
        if d:
            # VixFetcher로 실제 VIX를 조회한다. 실패 시 폴백 20.0을 사용한다
            try:
                vf = f.get("vix_fetcher")
                if vf is not None:
                    vix_val = await vf.get_vix()  # type: ignore[union-attr]
            except Exception:
                pass
            regime = d.detect(vix_val)  # type: ignore[union-attr]
    except Exception as e:
        logger.error("레짐 실패: %s", e)
    if not regime:
        logger.warning("레짐 미확보"); return 0

    # --- 콘탱고 상태를 레짐 판별 직후 1회 조회한다 (진입 컨텍스트 보강) ---
    contango_state = None
    try:
        cd = f.get("contango_detector")
        if cd is not None:
            contango_state = await cd.detect()  # type: ignore[union-attr]
            if contango_state is not None and contango_state.signal != "neutral":
                logger.info(
                    "[콘탱고] signal=%s, ratio=%.4f, drag=%.6f",
                    contango_state.signal, contango_state.contango_ratio,
                    contango_state.drag_estimate,
                )
    except Exception as exc:
        logger.warning("[콘탱고] 감지 실패 (무시): %s", exc)

    sp: StrategyParams = StrategyParams()
    try:
        m = f.get("strategy_params")
        if m: sp = m.load()  # type: ignore[union-attr]
    except Exception as e:
        logger.warning("파라미터 실패: %s", e)

    # HardSafety.check()에 잔고 데이터가 필요하므로 브로커에서 1회 조회한다
    # 조회 실패 시 빈 잔고로 폴백하여 비중 검사는 건너뛰되 다른 검사는 계속한다
    balance: BalanceData = BalanceData(total_equity=0.0, available_cash=0.0, positions=[])
    try:
        balance = await system.components.broker.get_balance()
    except Exception as exc:
        logger.warning("잔고 조회 실패 -- HardSafety 비중 검사 불가 (폴백 사용): %s", exc)

    # --- NetLiquidityTracker: FRED 순유동성 바이어스를 1회 조회한다 ---
    # 바이어스 배수(INJECT=1.1, DRAIN=0.8, NEUTRAL=1.0)를 포지션 사이즈에 곱한다
    liquidity_multiplier: float = 1.0
    try:
        nlt = f.get("net_liquidity_tracker")
        if nlt is not None:
            liquidity_bias = await nlt.get_cached()  # type: ignore[union-attr]
            liquidity_multiplier = liquidity_bias.multiplier
            if liquidity_bias.bias != "NEUTRAL":
                logger.info(
                    "[순유동성] bias=%s, NL=$%.1fB, multiplier=%.2f",
                    liquidity_bias.bias, liquidity_bias.net_liquidity_bn,
                    liquidity_multiplier,
                )
    except Exception as exc:
        logger.warning("[순유동성] 바이어스 조회 실패 (무시): %s", exc)

    # --- TiltDetector: 감정적 매매 감지 시 진입 전체를 건너뛴다 ---
    tilt_blocked = False
    try:
        tilt = f.get("tilt_detector")
        if tilt is not None:
            tilt_status = tilt.check_tilt()  # type: ignore[union-attr]
            if tilt_status.is_tilted:
                tilt_blocked = True
                logger.warning(
                    "[틸트] 매매 잠금: %s (연속손실=%d, 잠금해제=%s)",
                    tilt_status.reason, tilt_status.consecutive_losses,
                    tilt_status.locked_until,
                )
    except Exception as exc:
        logger.warning("[틸트] 감지 실패 (통과 처리): %s", exc)

    # 종합 분석 보고서 기반 DecisionMaker를 실행한다 (이벤트 발행용)
    await _run_decision_maker(system, regime, pos, system.components.cache, balance)

    es, en, om = f.get("exit_strategy"), f.get("entry_strategy"), f.get("order_manager")
    # DI에서 "indicator_bundle_builder"로 등록되어 있다 (indicator_builder는 하위 호환용)
    builder = f.get("indicator_bundle_builder") or f.get("indicator_builder")

    # StatArb 신호를 한 번만 조회하여 모든 포지션에 재사용한다 (API 절약)
    stat_arb_signals = await _fetch_stat_arb_signals(system)

    # 최신 뉴스 컨텍스트를 Redis에서 읽어 뉴스 페이딩 청산에 활용한다
    news_context = await _fetch_news_context(system)

    # --- HouseMoney: 일일 PnL 기반 포지션 배수 조회 ---
    house_money_mult: float = 1.0
    try:
        from src.risk.house_money.house_money import calculate_multiplier as _calc_hm
        # 보유 포지션의 미실현 PnL 합산으로 일일 PnL을 추정한다
        daily_pnl_pct = 0.0
        if pos:
            for _pd in pos.values():
                daily_pnl_pct += getattr(_pd, "unrealized_pnl_pct", 0.0)
        hm_result = _calc_hm(daily_pnl_pct)
        house_money_mult = hm_result.multiplier
        if house_money_mult != 1.0:
            logger.info("[하우스머니] PnL=%.2f%% multiplier=%.2f", daily_pnl_pct, house_money_mult)
    except Exception as exc:
        logger.warning("[하우스머니] 평가 실패 (무시): %s", exc)

    # --- LosingStreak: 연속 손절 감지 시 포지션 축소 ---
    streak_mult: float = 1.0
    try:
        ls = f.get("losing_streak")
        if ls is not None:
            # Redis에서 당일 거래 이력을 조회하여 연패를 분석한다
            cache = system.components.cache
            trades_raw = await cache.read_json("trades:today") if cache else None
            trade_list = trades_raw if isinstance(trades_raw, list) else []
            ls_result = ls.update(trade_list)  # type: ignore[union-attr]
            # risk_level에 따라 배수를 적용한다
            if ls_result.risk_level == "critical":
                streak_mult = 0.3
            elif ls_result.risk_level == "high":
                streak_mult = 0.5
            elif ls_result.risk_level == "medium":
                streak_mult = 0.7
            if streak_mult != 1.0:
                logger.info("[연속손절] level=%s, multiplier=%.2f", ls_result.risk_level, streak_mult)
    except Exception as exc:
        logger.warning("[연속손절] 평가 실패 (무시): %s", exc)

    # --- 청산 단계 ---
    if es and om and pos:
        for tk, pd in pos.items():
            try:
                bun = await builder.build(tk) if builder else IndicatorBundle()
                p = _P(pd)
                # 가격 스파이크 정보: current_price vs avg_price 변동률을 간이 계산한다
                price_spike = _estimate_price_spike(p)
                dec = es.evaluate(  # type: ignore[union-attr]
                    p, bun, regime, sp,
                    stat_arb_signals=stat_arb_signals,
                    news_context=news_context,
                    price_spike=price_spike,
                )
                if not dec.should_exit: continue
                q = p.quantity if dec.exit_pct >= 100.0 else max(1, int(p.quantity * dec.exit_pct / 100.0))
                ex = reg.get_exchange_code(tk) if reg.has_ticker(tk) else "NAS"
                r = await om.execute_sell(tk, q, ex)  # type: ignore[union-attr]
                if r.status == "filled":
                    trades += 1
                    logger.info("청산: %s %d주 (%s)", tk, q, dec.exit_type)
                    await _record_trade(
                        system, tk, "sell", q, p.current_price, dec.exit_type, p.unrealized_pnl_pct,
                        reason=dec.reason or dec.exit_type,
                    )

                    # 분할 청산 단계를 실행 완료로 표시한다
                    if dec.exit_type == "scaled_exit":
                        # reason에서 단계 번호를 추출한다 (예: "분할 청산 2단계")
                        level_match = re.search(r"(\d+)단계", dec.reason)
                        if level_match:
                            es.mark_scale_executed(tk, int(level_match.group(1)))  # type: ignore[union-attr]

                    # 100% 청산 시 ExitStrategy 상태를 초기화한다
                    if dec.exit_pct >= 100.0:
                        es.clear_position(tk)  # type: ignore[union-attr]

                    # TiltDetector에 청산 PnL을 기록한다 (연속 손절 추적용)
                    try:
                        tilt = f.get("tilt_detector")
                        if tilt is not None:
                            tilt.record_trade_result(p.unrealized_pnl_pct)  # type: ignore[union-attr]
                    except Exception:
                        pass

                    # LosingStreak는 trades:today에서 이력을 읽으므로
                    # 다음 루프 반복에서 자동으로 갱신된다
                else:
                    logger.warning("청산X: %s %s", tk, r.message)
            except Exception as e:
                logger.error("청산E (%s): %s", tk, e)

    # --- 보유 포지션 피라미딩 단계 ---
    if pos and om:
        pos_list = [_P(v) for v in pos.values()]
        pyr_trades = await _run_pyramiding(system, pos_list, regime, vix_val, balance, sp, om, reg)
        trades += pyr_trades

    # --- 진입 단계 ---
    held = set(pos.keys()) if pos else set()
    if en and om and not tilt_blocked:
        pl = [_P(v) for v in pos.values()] if pos else []

        # 섹터 로테이션 신호를 조회한다 (캐시에서 읽어 회피 섹터를 필터링한다)
        rotation = _get_sector_rotation_signal(system)
        avoid_sectors: set[str] = set()
        if rotation is not None:
            avoid_sectors = set(getattr(rotation, "bottom2_avoid", []))

        for mt in reg.get_universe():
            if mt.ticker in held: continue

            # 섹터 로테이션 필터 -- 회피 섹터 티커는 건너뛴다
            if avoid_sectors and hasattr(mt, "sector") and mt.sector in avoid_sectors:
                logger.debug("섹터 로테이션 차단: %s (sector=%s)", mt.ticker, mt.sector)
                continue

            try:
                bun = await builder.build(mt.ticker) if builder else IndicatorBundle()

                # --- GapRiskProtector: 갭 리스크 평가 (EXTREME이면 진입 차단) ---
                gap_size_mult: float = 1.0
                try:
                    grp = f.get("gap_risk_protector")
                    if grp is not None:
                        # 현재가를 번들에서 추출한다. 없으면 0.0 (게이트 통과 처리)
                        cur_price = bun.technical.ema_20 if bun.technical else 0.0
                        # 전일 종가를 캐시에서 읽는다 (pre_close 키)
                        pre_close = 0.0
                        try:
                            cached_close = await system.components.cache.read(
                                f"price:pre_close:{mt.ticker}",
                            )
                            if cached_close is not None:
                                pre_close = float(cached_close)
                        except Exception:
                            pass
                        if pre_close > 0 and cur_price > 0:
                            gap_result = grp.evaluate(pre_close, cur_price)  # type: ignore[union-attr]
                            gap_size_mult = gap_result.size_multiplier
                            if gap_result.blocked:
                                logger.info(
                                    "[갭리스크] EXTREME 차단: %s (gap=%.2f%%)",
                                    mt.ticker, gap_result.gap_pct,
                                )
                                continue
                except Exception as exc:
                    logger.warning("[갭리스크] 평가 실패 (통과 처리): %s %s", mt.ticker, exc)

                # Beast Mode 먼저 평가한다 (A+ 셋업, 일반 게이트와 독립)
                beast_count = await _run_beast_entry(
                    system, mt.ticker, bun, regime, vix_val, balance, sp, om, reg,
                )
                if beast_count > 0:
                    trades += beast_count
                    held.add(mt.ticker)
                    continue

                # MicroRegime 게이트 -- trending/mean_reverting만 허용한다
                micro_ok = await _run_micro_regime_gate(system, mt.ticker, builder)
                if not micro_ok:
                    continue

                # --- NAVPremiumTracker: 과도한 프리미엄(>2%) 시 진입 차단 ---
                nav_size_mult: float = 1.0
                try:
                    npt = f.get("nav_premium_tracker")
                    if npt is not None:
                        nav_state = await npt.track(mt.ticker)  # type: ignore[union-attr]
                        nav_size_mult = nav_state.multiplier_adjustment
                        if nav_state.premium_pct > 3.0:
                            logger.info(
                                "[NAV프리미엄] 과도한 프리미엄 차단: %s (%.2f%%)",
                                mt.ticker, nav_state.premium_pct,
                            )
                            continue
                except Exception as exc:
                    logger.warning("[NAV프리미엄] 조회 실패 (통과 처리): %s %s", mt.ticker, exc)

                # --- NewsFading: 뉴스 스파이크 역방향 페이딩 확인 ---
                # 진입 신호 조정용이다. should_fade=True이고 direction=short이면 매수 건너뛴다
                fade_skip = False
                try:
                    nf = f.get("news_fading")
                    if nf is not None and sp.news_fading_enabled:
                        spike = _estimate_price_spike_from_bundle(bun)
                        if spike is not None and news_context is not None:
                            fade_signal = nf.evaluate(spike, news_context)  # type: ignore[union-attr]
                            if fade_signal.should_fade and fade_signal.direction == "short":
                                # 급등 후 하락 예상 시 bull 매수를 건너뛴다
                                logger.info(
                                    "[뉴스페이딩] 진입 건너뜀 (급등 후 하락 예상): %s decay=%.1f%%",
                                    mt.ticker, fade_signal.decay_estimate * 100,
                                )
                                fade_skip = True
                except Exception as exc:
                    logger.warning("[뉴스페이딩] 평가 실패 (통과 처리): %s %s", mt.ticker, exc)
                if fade_skip:
                    continue

                # --- WickCatcher: 급격한 하방 윅 역방향 진입을 먼저 확인한다 ---
                # WickCatcher는 일반 진입과 독립된 대안 경로이다
                wc_count = await _run_wick_catcher(
                    system, mt.ticker, bun, regime, vix_val, balance, sp, om, reg,
                )
                if wc_count > 0:
                    trades += wc_count
                    held.add(mt.ticker)
                    continue  # WickCatcher로 진입했으면 일반 진입 건너뛴다

                # 일반 진입 게이트 평가
                ed = en.evaluate(mt.ticker, bun, regime, pl, sp)  # type: ignore[union-attr]
                if not ed.should_enter:
                    continue

                # --- LeverageDecay: 디케이 심각 시 포지션 사이즈 감소 ---
                decay_mult: float = 1.0
                try:
                    if bun.decay is not None:
                        # 번들에 이미 계산된 디케이가 있다 (bundle_builder가 계산)
                        if bun.decay.force_exit:
                            logger.info(
                                "[디케이] 심각한 디케이 차단: %s (%.2f%%)",
                                mt.ticker, bun.decay.decay_pct,
                            )
                            continue
                        # 디케이 2~5% 구간에서 사이즈를 0.5~0.9배로 축소한다
                        if bun.decay.decay_pct > 2.0:
                            decay_mult = max(0.5, 1.0 - (bun.decay.decay_pct - 2.0) * 0.1)
                except Exception as exc:
                    logger.warning("[디케이] 사이즈 조정 실패 (무시): %s %s", mt.ticker, exc)

                # 최종 배수 = 유동성 × 갭 × NAV × 디케이 × 하우스머니 × 연속손절
                combined_mult = (
                    liquidity_multiplier * gap_size_mult * nav_size_mult
                    * decay_mult * house_money_mult * streak_mult
                )
                # 최종 포지션 퍼센트에 배수를 적용한다
                final_pct = ed.position_size_pct * combined_mult

                # 퍼센트를 실제 주수로 변환한다
                entry_price = _get_current_price(bun)
                if entry_price <= 0:
                    # 번들에 가격 정보가 없으면 브로커 API로 직접 현재가를 조회한다
                    try:
                        pd = await system.components.broker.get_price(mt.ticker, exchange=mt.exchange)
                        entry_price = pd.price
                    except Exception:
                        pass
                if entry_price <= 0:
                    logger.info("진입 건너뜀: %s 현재가 미확보 (지표+브로커 모두 실패)", mt.ticker)
                    continue
                q = _pct_to_shares(final_pct, balance.total_equity, entry_price)
                if q <= 0:
                    continue

                # SafetyChecker → HardSafety 순서로 매수 전 안전 검사를 실행한다
                if not _check_buy_safety(
                    system, mt.ticker, q, regime.regime_type, vix_val, balance,
                ):
                    logger.info("진입차단(안전): %s", mt.ticker)
                    continue

                r = await om.execute_buy(mt.ticker, q, mt.exchange)  # type: ignore[union-attr]
                if r.status == "filled":
                    trades += 1
                    logger.info(
                        "진입: %s %d주 @%.2f (pct=%.1f%%, mult=%.2f)",
                        mt.ticker, q, entry_price, final_pct, combined_mult,
                    )
                    _entry_reason = (
                        f"진입 (확신도 {ed.confidence:.0%}, "
                        f"배수 {combined_mult:.2f}x, "
                        f"방향 {ed.direction})"
                    )
                    await _record_trade(system, mt.ticker, "buy", q, entry_price, None, None, reason=_entry_reason)
                    held.add(mt.ticker)
                else:
                    logger.warning("진입X: %s %s", mt.ticker, r.message)
            except Exception as e:
                logger.error("진입E (%s): %s", mt.ticker, e)
    elif tilt_blocked and en and om:
        logger.info("[틸트] 진입 단계 전체 건너뜀 (감정적 매매 방지)")

    logger.info("정규 세션: %d건 체결", trades); return trades

async def _update_ws_cache(
    system: InjectedSystem,
    session_type: str,
    trades_executed: int,
) -> None:
    """WebSocket 채널용 Redis 캐시를 갱신한다.

    ws:positions, ws:dashboard 키에 최신 데이터를 기록하여
    WebSocketManager가 클라이언트에 실시간 데이터를 전달할 수 있게 한다.
    트레이딩 루프에 영향을 주지 않도록 모든 예외를 흡수한다.
    """
    try:
        cache = system.components.cache
        pos_monitor = system.features.get("position_monitor")
        if pos_monitor is None:
            return

        # ws:positions -- 포지션 목록
        all_positions = pos_monitor.get_all_positions()
        position_list: list[dict] = [
            p.model_dump() for p in all_positions.values()
        ]
        await cache.write_json("ws:positions", {
            "channel": "positions",
            "data": position_list,
            "count": len(position_list),
        }, ttl=30)

        # ws:dashboard -- 대시보드 요약
        total_value: float = pos_monitor.get_total_value()
        await cache.write_json("ws:dashboard", {
            "channel": "dashboard",
            "data": {
                "status": "running" if system.running else "stopped",
                "session_type": session_type,
                "positions_count": len(all_positions),
                "total_value": total_value,
                "trades_executed": trades_executed,
            },
        }, ttl=30)

        # ws:trades -- 오늘의 거래 기록
        trades_data: list[dict] = await cache.read_json("trades:today") or []
        await cache.write_json("ws:trades", {
            "channel": "trades",
            "data": trades_data,
            "count": len(trades_data),
        }, ttl=30)

        # ws:orderflow -- 스캘퍼 테이프용 오더플로우 데이터
        try:
            bundle_builder = system.features.get("indicator_bundle_builder")
            if bundle_builder is not None:
                of_snapshots: list[dict] = []
                for ticker in list(all_positions.keys()):
                    raw = await cache.read_json(f"order_flow:raw:{ticker}")
                    if raw and isinstance(raw, dict):
                        of_snapshots.append({"ticker": ticker, **raw})
                await cache.write_json("ws:orderflow", {
                    "channel": "orderflow",
                    "data": of_snapshots if of_snapshots else None,
                    "count": len(of_snapshots),
                }, ttl=30)
        except Exception:
            pass  # orderflow 갱신 실패는 무시한다
    except Exception as exc:
        logger.debug("WS 캐시 갱신 실패 (무시): %s", exc)


async def _execute_iteration(
    system: InjectedSystem,
    time_info: TimeInfo,
    session_type: str,
) -> LoopIterationResult:
    """매매 루프 1회 반복을 실행한다."""
    interval = calculate_interval(session_type)
    is_regular = should_run_monitor_all(session_type)
    mode = "regular" if is_regular else "sync_only"
    logger.info("[%s] 매매 반복 실행 (mode=%s, interval=%ds)", session_type, mode, interval)
    trades = 0
    errors: list[str] = []

    # 반복 시작 전 안전 조건 확인 -- EmergencyProtocol/CapitalGuard 차단 시 매매 건너뜀
    # 포지션 동기화는 안전 상태와 무관하게 항상 실행한다
    iteration_safe = await _check_iteration_safety(system)
    if not iteration_safe and is_regular:
        logger.info("[%s] 안전 조건 미충족 -- 매매 로직 건너뜀 (포지션 동기화만 실행)", session_type)
        await _sync_positions_only(system)
        await _update_ws_cache(system, session_type, 0)
        return LoopIterationResult(
            session_type=session_type, interval_seconds=interval,
            trades_executed=0, errors=["안전 조건 미충족"], should_continue=True,
        )

    try:
        if is_regular:
            trades = await _run_regular_session(system)
        else:
            # 비정규 세션: sync_positions() only (monitor_all 금지)
            await _sync_positions_only(system)
    except Exception as exc:
        msg = f"반복 실행 오류: {exc}"
        logger.error(msg)
        errors.append(msg)

    # WebSocket 채널 캐시 갱신 (실패해도 루프에 영향 없음)
    await _update_ws_cache(system, session_type, trades)

    return LoopIterationResult(
        session_type=session_type, interval_seconds=interval,
        trades_executed=trades, errors=errors, should_continue=True,
    )

async def _wait_or_shutdown(
    shutdown_event: asyncio.Event,
    interval: int,
) -> bool:
    """interval초 대기하되, shutdown_event가 set되면 즉시 True를 반환한다."""
    try:
        await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        return True
    except asyncio.TimeoutError:
        return False

async def _run_single_iteration(
    system: InjectedSystem,
    shutdown_event: asyncio.Event,
    iteration: int,
) -> bool:
    """루프 1회 실행 후 계속 여부를 반환한다. False면 루프 종료이다."""
    time_info = system.components.clock.get_time_info()
    if await check_shutdown(time_info, shutdown_event):
        return False
    session = determine_session(time_info)
    interval = calculate_interval(session)
    result = await _execute_iteration(system, time_info, session)
    logger.debug(
        "루프 #%d 완료 (session=%s, trades=%d, next=%ds)",
        iteration, session, result.trades_executed, interval,
    )
    if not result.should_continue:
        logger.info("루프 중단 신호 수신 (iteration #%d)", iteration)
        return False
    stopped = await _wait_or_shutdown(shutdown_event, interval)
    return not stopped

async def run_trading_loop(
    system: InjectedSystem,
    shutdown_event: asyncio.Event,
) -> None:
    """매매 루프를 실행한다. 종료 조건까지 반복한다."""
    iteration = 0
    logger.info("=== 매매 루프 시작 ===")
    while not shutdown_event.is_set():
        iteration += 1
        should_continue = await _run_single_iteration(
            system, shutdown_event, iteration,
        )
        if not should_continue:
            break
    logger.info("=== 매매 루프 종료 (총 %d회 반복) ===", iteration)
