"""F9.4 TradingLoop -- 세션별 동적 주기로 매매 루프를 반복한다.

포지션 사이징: position_size_pct(%)를 계좌 자산과 현재가로 실제 주식 수로 변환한다.
분할 청산: ExitStrategy의 상태 추적을 활용하여 동일 단계 반복 실행을 방지한다.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from src.common.logger import get_logger
from src.common.market_clock import SessionType, TimeInfo
from src.orchestration.init.dependency_injector import InjectedSystem

logger = get_logger(__name__)
_AUTO_STOP_MINUTES: int = 420  # 07:00 KST (분 단위)
_WINDING_DOWN_MINUTES: int = 330  # 05:30 KST — 매매 마무리 모드 진입 시각
_REGULAR_SESSIONS: frozenset[str] = frozenset({"power_open", "mid_day", "power_hour"})

# M-6: 티커 섹터 → 섹터 로테이션 섹터 매핑
_SECTOR_TO_ROTATION: dict[str, str] = {
    "tech": "Technology", "semiconductor": "Technology",
    "broad_market": "Industrial", "small_cap": "Finance",
    "energy": "Energy", "financials": "Finance",
    "healthcare": "Healthcare",
}

# 소액 계좌 포지션 사이징 보호: 최소 주문 금액 미만이면 거래를 건너뛴다
_MIN_ORDER_DOLLAR_AMOUNT: float = 20.0


def _obi_signal(obi: float) -> str:
    """OBI 값을 매매 신호 문자열로 변환한다."""
    if obi >= 0.6:
        return "strong_buy"
    if obi >= 0.3:
        return "buy"
    if obi <= -0.6:
        return "strong_sell"
    if obi <= -0.3:
        return "sell"
    return "neutral"


def _vpin_level(vpin: float) -> str:
    """VPIN 값을 위험 레벨 문자열로 변환한다."""
    if vpin >= 0.8:
        return "critical"
    if vpin >= 0.6:
        return "danger"
    if vpin >= 0.4:
        return "warning"
    return "safe"


# 오더플로우 히스토리 슬라이딩 윈도우 크기 (6시간 = 360개 1분 스냅샷)
_ORDERFLOW_HISTORY_MAX: int = 360


def _extract_ticker_metrics(item: dict) -> dict:
    """오더플로우 스냅샷 항목에서 핵심 지표를 추출한다."""
    obi_data = item.get("obi", {})
    cvd_data = item.get("cvd", {})
    return {
        "obi": obi_data.get("value", 0.0) if isinstance(obi_data, dict) else 0.0,
        "cvd": cvd_data.get("cumulative", 0.0) if isinstance(cvd_data, dict) else 0.0,
        "spread": item.get("spread_bps", 0.0),
        "volume": item.get("last_volume", 0),
    }


async def _accumulate_orderflow_history(
    cache: object,
    snapshots: list[dict],
) -> None:
    """오더플로우 스냅샷을 슬라이딩 윈도우 히스토리에 누적한다.

    orderflow:history (글로벌)와 orderflow:history:{ticker} (티커별)
    두 캐시 키에 타임스탬프 포함 엔트리를 atomic_list_append한다.
    order_flow.py의 get_orderflow_history()가 조회한다.
    """
    now = datetime.now(timezone.utc).isoformat()

    # 글로벌 히스토리 엔트리 구성
    tickers_map = {
        item["ticker"]: _extract_ticker_metrics(item)
        for item in snapshots if "ticker" in item
    }
    global_entry = {"timestamp": now, "tickers": tickers_map}
    await cache.atomic_list_append(  # type: ignore[union-attr]
        "orderflow:history", [global_entry], max_size=_ORDERFLOW_HISTORY_MAX,
    )

    # 티커별 히스토리 엔트리 누적
    for item in snapshots:
        ticker = item.get("ticker")
        if not ticker:
            continue
        ticker_entry = {"timestamp": now, **_extract_ticker_metrics(item)}
        await cache.atomic_list_append(  # type: ignore[union-attr]
            f"orderflow:history:{ticker}",
            [ticker_entry],
            max_size=_ORDERFLOW_HISTORY_MAX,
        )


def _pct_to_shares(pct: float, total_equity: float, price: float) -> int:
    """포지션 퍼센트(%)를 실제 주식 수로 변환한다.

    dollar_amount가 _MIN_ORDER_DOLLAR_AMOUNT(20 USD) 미만이면 0을 반환하여
    소액 주문으로 인한 불필요한 거래를 방지한다.

    Args:
        pct: 계좌 대비 퍼센트 (예: 5.0 = 5%)
        total_equity: 계좌 총자산 (USD)
        price: 현재 주가 (USD)

    Returns:
        주식 수 (최소 1, 최대 9999). 최소 주문 금액 미만이면 0.
    """
    if price <= 0 or total_equity <= 0 or pct <= 0:
        return 0
    dollar_amount = total_equity * pct / 100.0
    if dollar_amount < _MIN_ORDER_DOLLAR_AMOUNT:
        return 0
    shares = int(dollar_amount / price)
    return max(1, min(shares, 9999))


async def _get_broker_price(
    system: InjectedSystem, ticker: str, exchange: str = "NAS",
) -> float:
    """브로커 API에서 실시간 현재가를 조회한다. 실패 시 0.0을 반환한다."""
    try:
        price_data = await system.components.broker.get_price(ticker, exchange=exchange)
        if price_data.price > 0:
            return price_data.price
    except Exception as exc:
        logger.debug("브로커 현재가 조회 실패 (%s): %s", ticker, exc)
    return 0.0


def _get_current_price(bundle: object) -> float:
    """IndicatorBundle에서 현재가를 추출한다. 없으면 0.0이다.

    우선순위: technical.ema_20 → intraday.vwap → volume_profile.poc_price
    브로커 API 우선 조회는 async 호출자(_get_current_price_with_broker)에서 처리한다.
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


async def _get_current_price_with_broker(
    system: InjectedSystem, ticker: str, bundle: object, exchange: str = "NAS",
) -> float:
    """H-6: 브로커 API 우선 → 지표 폴백 체인으로 현재가를 조회한다.

    우선순위: 브로커 실시간가 → EMA20 → VWAP → POC
    """
    # 1순위: 브로커 API 실시간 현재가 (가장 정확함)
    broker_price = await _get_broker_price(system, ticker, exchange)
    if broker_price > 0:
        return broker_price
    # 2순위: 지표 기반 폴백 (후행 지표이지만 부재보다 나음)
    indicator_price = _get_current_price(bundle)
    if indicator_price > 0:
        logger.debug("브로커 가격 미확보, 지표 폴백 사용: %s = %.4f", ticker, indicator_price)
    return indicator_price


async def _check_iteration_safety(system: InjectedSystem) -> bool:
    """반복 시작 전 안전 조건을 검사한다.

    EmergencyProtocol 중단 상태 또는 CapitalGuard 손실 한도 도달 시 False를 반환한다.
    안전 모듈 자체에서 예외 발생 시 경고만 기록하고 True(fail-open)를 반환한다.
    """
    try:
        ep = system.features.get("emergency_protocol")
        if ep is not None and ep.is_halted():  # type: ignore[union-attr]
            logger.warning("[반복안전] EmergencyProtocol 매매 중단 상태 -- 이번 반복 건너뜀")
            await _record_alert(
                system, "emergency", "긴급 프로토콜 매매 중단",
                "EmergencyProtocol이 매매를 중단했습니다. 안전 조건 충족 전까지 매매가 차단됩니다.",
                severity="critical",
            )
            return False
    except Exception as exc:
        logger.warning("[반복안전] EmergencyProtocol 검사 실패 (통과 처리): %s", exc)

    try:
        cg = system.features.get("capital_guard")
        if cg is not None:
            if cg.is_daily_limit_reached():  # type: ignore[union-attr]
                logger.warning("[반복안전] CapitalGuard 일일 손실 한도 도달 -- 이번 반복 건너뜀")
                await _record_alert(
                    system, "risk", "일일 손실 한도 도달",
                    "CapitalGuard 일일 손실 한도에 도달하여 매매가 차단되었습니다.",
                    severity="warning",
                )
                return False
            if cg.is_weekly_limit_reached():  # type: ignore[union-attr]
                logger.warning("[반복안전] CapitalGuard 주간 손실 한도 도달 -- 이번 반복 건너뜀")
                await _record_alert(
                    system, "risk", "주간 손실 한도 도달",
                    "CapitalGuard 주간 손실 한도에 도달하여 매매가 차단되었습니다.",
                    severity="warning",
                )
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

def is_winding_down(time_info: TimeInfo) -> bool:
    """05:30 KST 이후 매매 마무리 모드인지 판별한다.

    마무리 모드: 신규 진입/피라미딩 차단, 청산만 허용 (스톱로스 등 급한 것만).
    """
    kst = time_info.now_kst
    kst_minutes = kst.hour * 60 + kst.minute
    return _WINDING_DOWN_MINUTES <= kst_minutes < _AUTO_STOP_MINUTES


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

async def _record_alert(
    system: InjectedSystem,
    alert_type: str,
    title: str,
    message: str,
    severity: str = "info",
) -> None:
    """알림을 캐시 alerts:list에 기록한다.

    트레이딩 루프에 영향을 주지 않도록 모든 예외를 흡수한다.
    최대 100건을 유지하며 초과 시 가장 오래된 항목을 제거한다.

    Args:
        system: DI 시스템 인스턴스
        alert_type: 알림 유형 (safety, emergency, risk, trade, system)
        title: 한국어 제목
        message: 한국어 상세 메시지
        severity: 심각도 (info, warning, error, critical)
    """
    try:
        cache = system.components.cache
        alert_entry: dict = {
            "id": str(uuid.uuid4()),
            "type": alert_type,
            "title": title,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": None,
        }
        # 기존 알림 목록을 읽고 새 알림을 추가한다
        existing: list[dict] = await cache.read_json("alerts:list") or []
        existing.append(alert_entry)
        # 최대 100건 유지 (오래된 항목부터 제거)
        if len(existing) > 100:
            existing = existing[-100:]
        await cache.write_json("alerts:list", existing, ttl=86400)
    except Exception as exc:
        logger.debug("알림 기록 실패 (무시): %s", exc)


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
    """체결된 거래를 캐시(trades:today)에 기록하고 텔레그램 알림을 발송한다.

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

        # pnl:daily 캐시를 갱신한다 -- EOD 시퀀스가 읽어 DB 저장/차트 데이터에 활용한다
        await _update_pnl_daily_cache(system, trades_list)
    except Exception as exc:
        logger.warning("거래 기록 실패 (무시): %s", exc)

    # 텔레그램 알림 발송 (기록 실패와 독립적으로 실행)
    await _notify_trade_telegram(system, ticker, side, quantity, price, reason, pnl_pct)


async def _update_pnl_daily_cache(
    system: InjectedSystem,
    trades_list: list[dict],
) -> None:
    """trades:today 전체에서 PnL을 집계하여 pnl:daily 캐시를 갱신한다.

    EOD 시퀀스(_s2, _s2_1, _s2_5)가 pnl:daily를 읽어
    DB 저장, 차트 갱신, 텔레그램 보고에 활용한다.
    기록 구조: {total_pnl, total_pnl_pct, trades_count, equity, updated_at}
    """
    try:
        cache = system.components.cache
        total_pnl: float = 0.0
        sell_count: int = 0
        buy_investment: float = 0.0

        for t in trades_list:
            if not isinstance(t, dict):
                continue
            side = t.get("side", "")
            if side == "sell":
                pnl = t.get("pnl")
                if pnl is not None and isinstance(pnl, (int, float)):
                    total_pnl += pnl
                sell_count += 1
            elif side == "buy":
                p = t.get("price", 0)
                q = t.get("quantity", 0)
                if isinstance(p, (int, float)) and isinstance(q, (int, float)):
                    buy_investment += p * q

        # 포지션 미실현 PnL을 포함한 equity 추정
        equity: float = 0.0
        try:
            pm = system.features.get("position_monitor")
            if pm is not None:
                equity = pm.get_total_value()  # type: ignore[union-attr]
        except Exception:
            pass

        # PnL % 계산: 매수 총액 대비 실현 PnL
        total_pnl_pct: float = 0.0
        if buy_investment > 0:
            total_pnl_pct = round(total_pnl / buy_investment * 100, 4)

        await cache.write_json("pnl:daily", {
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": total_pnl_pct,
            "trades_count": len(trades_list),
            "equity": round(equity, 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, ttl=86400)
    except Exception as exc:
        logger.debug("pnl:daily 캐시 갱신 실패 (무시): %s", exc)


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
        # C-1: 실제 볼륨 비율을 캐시 체결 데이터에서 계산한다
        volume_ratio = 1.0
        try:
            cache = system.components.cache
            of_raw = await cache.read_json(f"order_flow:raw:{ticker}")
            if of_raw and isinstance(of_raw, dict):
                trades_data = of_raw.get("trades", [])
                if len(trades_data) >= 10:
                    # 최근 50건 체결량 평균 vs 전체 평균으로 볼륨 비율을 계산한다
                    all_volumes = [float(t.get("volume", 0)) for t in trades_data if t.get("volume", 0) > 0]
                    if all_volumes:
                        total_avg = sum(all_volumes) / len(all_volumes)
                        recent = all_volumes[-50:] if len(all_volumes) > 50 else all_volumes
                        recent_avg = sum(recent) / len(recent)
                        if total_avg > 0:
                            volume_ratio = recent_avg / total_avg
            if volume_ratio == 1.0:
                logger.debug("Beast 볼륨비율 폴백: %s (체결 데이터 부족, 기본값 1.0)", ticker)
        except Exception as exc:
            logger.debug("Beast 볼륨비율 계산 실패 (%s): %s (기본값 1.0)", ticker, exc)
        whale_alignment = (bun.whale.total_score > 0.3) if bun.whale else False

        # 일일 Beast Mode 카운트와 마지막 실패 시각을 캐시에서 읽는다
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

        # H-6: 브로커 API 우선 → 지표 폴백으로 현재가를 조회한다
        exchange = reg.get_exchange_code(ticker) if reg.has_ticker(ticker) else "NAS"
        price = await _get_current_price_with_broker(system, ticker, bundle, exchange)
        if price <= 0:
            logger.warning("Beast 진입차단: %s 현재가 미확보", ticker)
            return 0
        # H-15: bd.position_size_pct에 conviction이 이미 적용되어 있다.
        # combined_mult를 중복 적용하지 않고 base * conviction만 사용한다.
        beast_pct = min(
            params.default_position_size_pct * bd.conviction_multiplier,
            params.max_position_pct,
        )
        q = _pct_to_shares(beast_pct, balance.total_equity, price)  # type: ignore[union-attr]
        if q <= 0:
            return 0

        # SafetyChecker → HardSafety 안전 검사
        if not _check_buy_safety(
            system, ticker, q, regime.regime_type, vix_val, balance,  # type: ignore[union-attr]
        ):
            logger.info("Beast 진입차단(안전): %s", ticker)
            await _record_alert(
                system, "safety", "Beast 매수 차단",
                f"안전 검사에 의해 {ticker} Beast Mode 매수가 차단되었습니다.",
                severity="warning",
            )
            return 0

        r = await om.execute_buy(ticker, q, exchange, expected_price=price)  # type: ignore[union-attr]
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

            # C-11: Beast 포지션 플래그를 캐시에 기록한다 (48h 안전 TTL)
            try:
                await cache.write(f"beast_positions:{ticker}", "1", ttl=172800)
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
        await _record_alert(
            system, "trade", "Beast 주문 실패",
            f"{ticker} Beast Mode 매수 주문이 거부되었습니다: {r.message}",
            severity="error",
        )
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
            # C-4: 실제 포트폴리오 리스크와 종목 집중도를 계산한다
            portfolio_risk_pct = 0.0
            ticker_concentration_pct = 0.0
            try:
                total_eq = balance.total_equity if hasattr(balance, "total_equity") else 0.0  # type: ignore[union-attr]
                # 모든 포지션 미실현 PnL 합산 → 포트폴리오 리스크(%)
                for _pp in pos_items:
                    portfolio_risk_pct += getattr(_pp, "unrealized_pnl_pct", 0.0)
                # 해당 종목 포지션 가치 / 총 자산 → 종목 집중도(%)
                if total_eq > 0:
                    pos_val = getattr(p, "quantity", 0) * getattr(p, "current_price", 0.0)
                    ticker_concentration_pct = (pos_val / total_eq) * 100.0
            except Exception:
                pass
            market_state = {
                "regime_type": regime.regime_type,  # type: ignore[union-attr]
                "vix": vix_val,
                "portfolio_risk_pct": portfolio_risk_pct,
                "ticker_concentration_pct": ticker_concentration_pct,
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
            r = await om.execute_buy(p.ticker, q, exchange, expected_price=pyr_price)  # type: ignore[union-attr]
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

                # C-11: 피라미딩 레벨을 캐시에 기록한다 (48h 안전 TTL)
                try:
                    cache = system.components.cache
                    await cache.write(
                        f"pyramid_level:{p.ticker}",  # type: ignore[union-attr]
                        str(pd_decision.level),
                        ttl=172800,
                    )
                except Exception:
                    pass

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
                await _record_alert(
                    system, "trade", "피라미딩 주문 실패",
                    f"{p.ticker} 피라미딩 매수 주문이 거부되었습니다: {r.message}",  # type: ignore[union-attr]
                    severity="error",
                )
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
    자동으로 반응한다. 판단 결과는 캐시에 저장하여 추적 가능하도록 한다.
    """
    from src.agents.status_writer import (
        record_agent_complete,
        record_agent_error,
        record_agent_start,
    )

    try:
        dm = system.features.get("decision_maker")
        if dm is None:
            return

        # 사전 분석 보고서를 캐시에서 읽는다 (정기 분석 또는 센티넬 긴급)
        # 긴급 보고서가 있으면 우선 사용한다 (센티넬 emergency 대응)
        report_data = await cache.read_json("analysis:emergency_report")  # type: ignore[union-attr]
        if report_data:
            logger.info("[DecisionMaker] 센티넬 긴급 보고서 사용")
            # 사용 후 삭제하여 중복 처리 방지
            try:
                await cache.delete("analysis:emergency_report")  # type: ignore[union-attr]
            except Exception:
                pass
        else:
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
            logger.warning("[DecisionMaker] 타임스탬프 파싱 실패 — 보고서 무시: %s", exc)
            return
        report = ComprehensiveReport(**report_data)
        portfolio = PortfolioState(
            positions=[v.model_dump() if hasattr(v, "model_dump") else v for v in pos.values()] if pos else [],
            cash_available=getattr(balance, "available_cash", 0.0) if balance else 0.0,
            total_value=getattr(balance, "total_equity", 0.0) if balance else 0.0,
        )
        t0 = time.monotonic()
        await record_agent_start(cache, "decision_maker", "매매 판단 생성")
        decision = await dm.decide(report, portfolio)  # type: ignore[union-attr]
        await record_agent_complete(
            cache, "decision_maker",
            f"{decision.action} {decision.ticker} (conf={decision.confidence:.2f})",
            time.monotonic() - t0,
        )
        logger.info(
            "[DecisionMaker] 판단: %s %s (conf=%.2f)",
            decision.action, decision.ticker, decision.confidence,
        )
    except Exception as exc:
        logger.warning("[DecisionMaker] 판단 실패 (무시): %s", exc)
        await record_agent_error(cache, "decision_maker", str(exc))


async def _run_micro_regime_gate(
    system: InjectedSystem,
    ticker: str,
    builder: object,
) -> tuple[bool, str, float]:
    """MicroRegime으로 미시 레짐을 평가한다.

    M-8: 레짐별 동적 파라미터 조정 정보도 함께 반환한다.
    - trending: 진입 허용, 배수 1.0 (와이드 트레일링은 ExitStrategy에서 처리)
    - mean_reverting: 진입 허용, 배수 0.9 (타이트 목표)
    - volatile: 진입 차단 (변동성 과다)
    - quiet: 진입 차단 (기회 부재)

    Returns:
        (진입 허용 여부, 레짐 이름, 포지션 사이즈 배수)
    """
    try:
        micro = system.features.get("micro_regime")
        if micro is None:
            return True, "unknown", 1.0  # 미등록 시 통과

        # 5분봉 캔들이 IndicatorBundleBuilder에 있는지 확인한다
        if builder is None:
            return True, "unknown", 1.0

        # IndicatorBundleBuilder에서 5분봉 캔들을 조회한다
        candles = None
        try:
            candles = await builder.get_candles_5m(ticker)  # type: ignore[union-attr]
        except AttributeError:
            # get_candles_5m 미구현 시 통과 처리한다
            return True, "unknown", 1.0

        if candles is None or len(candles) < 10:
            return True, "unknown", 1.0  # 데이터 부족 시 통과

        result = micro.evaluate(candles)  # type: ignore[union-attr]

        # M-8: 레짐별 동적 조정을 반환한다
        if result.regime == "trending":
            return True, "trending", 1.0
        elif result.regime == "mean_reverting":
            return True, "mean_reverting", 0.9
        elif result.regime == "volatile":
            logger.info(
                "MicroRegime 차단(변동성): %s regime=%s score=%.4f -- 와이드 스톱 필요",
                ticker, result.regime, result.score,
            )
            return False, "volatile", 0.7
        else:  # quiet
            logger.info(
                "MicroRegime 차단(정적): %s regime=%s score=%.4f -- 기회 부재",
                ticker, result.regime, result.score,
            )
            return False, "quiet", 0.5
    except Exception as exc:
        logger.warning("MicroRegime 평가 실패 (통과 처리): %s %s", ticker, exc)
        return True, "unknown", 1.0


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
            await _record_alert(
                system, "safety", "Wick 매수 차단",
                f"안전 검사에 의해 {ticker} WickCatcher 매수가 차단되었습니다.",
                severity="warning",
            )
            return 0

        exchange = reg.get_exchange_code(ticker) if reg.has_ticker(ticker) else "NAS"
        r = await om.execute_buy(ticker, q, exchange, expected_price=wick_price)  # type: ignore[union-attr]
        if r.status == "filled":
            logger.info("WickCatcher 진입: %s %d주 @%.2f", ticker, q, wick_price)
            await _record_trade(
                system, ticker, "buy", q, wick_price, "wick_catch", None,
                reason="급락 윅(Wick) 반등 포착 진입",
            )
            return 1
        logger.warning("Wick 진입X: %s %s", ticker, r.message)
        await _record_alert(
            system, "trade", "Wick 주문 실패",
            f"{ticker} WickCatcher 매수 주문이 거부되었습니다: {r.message}",
            severity="error",
        )
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

        # 페어 가격을 캐시에서 읽는다 (가격 업데이트 모듈이 별도 저장한다)
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


async def _fetch_news_context(system: InjectedSystem) -> list[dict] | None:
    """캐시에서 최근 고영향 뉴스 리스트를 읽는다.

    뉴스 파이프라인이 저장한 고영향 뉴스 요약 전체를 반환한다.
    preparation.py는 "items" 키를, news_pipeline.py는 "high_impact_articles" 키를 사용한다.
    """
    try:
        cached = await system.components.cache.read_json("news:latest_summary")
        if not cached or not isinstance(cached, dict):
            return None
        # 두 캐시 형식을 모두 지원한다
        items = cached.get("high_impact_articles") or cached.get("items") or []
        return items if items else None
    except Exception:
        return None


def _pick_highest_impact(news_list: list[dict]) -> dict | None:
    """뉴스 리스트에서 impact_score가 가장 높은 기사를 반환한다.

    빈 리스트인 경우 None을 반환하여 ValueError를 방지한다.
    """
    if not news_list:
        return None
    if len(news_list) == 1:
        return news_list[0]
    return max(news_list, key=lambda n: n.get("impact_score", 0.0))


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


async def _prepare_session_context(
    system: InjectedSystem,
) -> tuple[dict, object, float, object, object, bool] | None:
    """세션 컨텍스트를 준비한다: 포지션 동기화, 레짐 감지, 전략 파라미터, 잔고 조회.

    Returns:
        (pos, regime, vix_val, sp, balance, winding_down) 튜플.
        준비 실패 시(PositionMonitor 미등록, 동기화 실패, 레짐 미확보) None을 반환한다.
    """
    from src.common.broker_gateway import BalanceData
    from src.strategy.models import StrategyParams

    f = system.features

    # 05:30 KST 이후 매매 마무리 모드 판별 — 신규 진입/피라미딩 차단
    time_info = system.components.clock.get_time_info()
    winding_down = is_winding_down(time_info)
    if winding_down:
        logger.info("[마무리모드] 05:30 KST 이후 — 청산만 허용, 신규 진입/피라미딩 차단")

    pm = f.get("position_monitor")
    if not pm:
        logger.warning("PositionMonitor 미등록")
        return None
    try:
        pos = await pm.sync_positions()  # type: ignore[union-attr]
    except Exception as e:
        logger.error("동기화 실패: %s", e)
        return None

    # 레짐 감지 + VIX 조회
    regime = None
    vix_val = 20.0
    try:
        d = f.get("regime_detector")
        if d:
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
        logger.warning("레짐 미확보")
        return None

    # --- 콘탱고 상태를 레짐 판별 직후 1회 조회한다 (진입 컨텍스트 보강) ---
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

    # 전략 파라미터 로드
    sp: StrategyParams = StrategyParams()
    try:
        m = f.get("strategy_params")
        if m:
            sp = m.load()  # type: ignore[union-attr]
    except Exception as e:
        logger.warning("파라미터 실패: %s", e)

    # HardSafety.check()에 잔고 데이터가 필요하므로 브로커에서 1회 조회한다
    balance: BalanceData = BalanceData(total_equity=0.0, available_cash=0.0, positions=[])
    try:
        balance = await system.components.broker.get_balance()
    except Exception as exc:
        logger.warning("잔고 조회 실패 -- HardSafety 비중 검사 불가 (폴백 사용): %s", exc)

    return pos, regime, vix_val, sp, balance, winding_down


async def _compute_position_multipliers(
    system: InjectedSystem,
    pos: dict,
    balance: object,
    daily_loss_limiter: object,
) -> dict[str, float | bool]:
    """포지션 사이즈에 적용할 승수들을 계산한다.

    유동성, 하우스머니, 연속손절, VaR 배수와 틸트 차단 여부를 반환한다.
    DailyLossLimit 재구축과 ProfitTarget 확인도 이 단계에서 수행한다.

    Returns:
        liquidity, house_money, streak, var 배수와 tilt_blocked 불리언을 포함한 딕셔너리.
    """
    f = system.features
    _cache = system.components.cache

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
                await _record_alert(
                    system, "risk", "틸트 감지 - 매매 잠금",
                    f"감정적 매매 감지로 진입이 차단되었습니다. 사유: {tilt_status.reason}, "
                    f"연속손실: {tilt_status.consecutive_losses}회",
                    severity="warning",
                )
    except Exception as exc:
        logger.warning("[틸트] 감지 실패 (통과 처리): %s", exc)

    # --- H-4: DailyLossLimit 기존 거래 이력 반영 (C-2: 인스턴스는 루프 밖에서 생성) ---
    # C-2: 매 반복마다 리셋 후 trades:today에서 재구축한다.
    # 인스턴스가 루프 밖에 있으므로 캐시 조회 실패 시에도 이전 반복의 상태가 보존된다.
    daily_loss_limiter.reset()  # type: ignore[union-attr]
    try:
        _prev_trades = await _cache.read_json("trades:today") or []
        for _pt in _prev_trades:
            if isinstance(_pt, dict) and _pt.get("side") == "sell":
                _realized = _pt.get("pnl")
                if _realized is not None and isinstance(_realized, (int, float)):
                    if balance.total_equity > 0:  # type: ignore[union-attr]
                        daily_loss_limiter.record_trade((_realized / balance.total_equity) * 100.0)  # type: ignore[union-attr]
    except Exception as exc:
        logger.debug("[일일손실한도] 기존 거래 반영 실패 (이전 반복 상태 유지): %s", exc)

    # --- HouseMoney: 일일 PnL 기반 포지션 배수 조회 ---
    house_money_mult: float = 1.0
    daily_pnl_pct: float = 0.0
    try:
        from src.risk.house_money.house_money import calculate_multiplier as _calc_hm
        # H-2: 미실현 PnL + 오늘 실현 PnL을 합산하여 정확한 일일 PnL을 계산한다
        # 1) 보유 포지션의 미실현 PnL 합산 (PositionData.pnl_pct 사용)
        if pos:
            for _pd in pos.values():
                daily_pnl_pct += getattr(_pd, "pnl_pct", 0.0)
        # 2) 오늘 완료된 거래의 실현 PnL 합산 (trades:today에서 조회)
        try:
            trades_today = await _cache.read_json("trades:today") or []
            for _tr in trades_today:
                if isinstance(_tr, dict) and _tr.get("side") == "sell":
                    realized = _tr.get("pnl")
                    if realized is not None and isinstance(realized, (int, float)):
                        if balance.total_equity > 0:  # type: ignore[union-attr]
                            daily_pnl_pct += (realized / balance.total_equity) * 100.0  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("[HouseMoney] trades:today 파싱 실패: %s", exc)
        hm_result = _calc_hm(daily_pnl_pct)
        house_money_mult = hm_result.multiplier
        if house_money_mult != 1.0:
            logger.info("[하우스머니] PnL=%.2f%% (미실현+실현) multiplier=%.2f", daily_pnl_pct, house_money_mult)
    except Exception as exc:
        logger.warning("[하우스머니] 평가 실패 (무시): %s", exc)

    # --- LosingStreak: 연속 손절 감지 시 포지션 축소 ---
    streak_mult: float = 1.0
    try:
        ls = f.get("losing_streak")
        if ls is not None:
            cache = system.components.cache
            trades_raw = await cache.read_json("trades:today") if cache else None
            trade_list = trades_raw if isinstance(trades_raw, list) else []
            ls_result = ls.update(trade_list)  # type: ignore[union-attr]
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

    # --- L-1: SimpleVaR 권고성 포지션 축소 배수 ---
    var_mult: float = 1.0
    try:
        from src.risk.gates.simple_var import get_var_position_multiplier
        returns_raw = await _cache.read_json("portfolio:daily_returns")
        if isinstance(returns_raw, list) and len(returns_raw) >= 5:
            var_mult = get_var_position_multiplier(
                balance.total_equity, returns_raw,  # type: ignore[union-attr]
            )
    except Exception as exc:
        logger.debug("[SimpleVaR] 배수 조회 실패 (무시): %s", exc)

    # --- L-3: ProfitTarget 일일 목표 달성 로그 (advisory) ---
    try:
        pt = f.get("profit_target")
        if pt is not None and balance.total_equity > 0 and daily_pnl_pct:  # type: ignore[union-attr]
            daily_pnl_usd = balance.total_equity * daily_pnl_pct / 100.0  # type: ignore[union-attr]
            pt.check_daily_target_reached(daily_pnl_usd)  # type: ignore[union-attr]
    except Exception as exc:
        logger.debug("[수익목표] 확인 실패 (무시): %s", exc)

    return {
        "liquidity": liquidity_multiplier,
        "house_money": house_money_mult,
        "streak": streak_mult,
        "var": var_mult,
        "tilt_blocked": tilt_blocked,
    }


async def _run_exit_stage(
    system: InjectedSystem,
    pos: dict,
    regime: object,
    sp: object,
    balance: object,
    daily_loss_limiter: object,
    stat_arb_signals: list | None,
    news_context: list[dict] | None,
    es: object,
    om: object,
    builder: object,
    _cache: object,
    _P: object,
) -> tuple[int, dict]:
    """청산 단계: 보유 포지션을 순회하며 청산 평가 및 매도 주문을 실행한다.

    Returns:
        (체결 건수, 갱신된 pos 딕셔너리) 튜플.
    """
    from src.indicators.models import IndicatorBundle

    f = system.features
    reg = system.components.registry
    trades = 0

    # --- 청산 전 포지션 검증: 캐시 수량과 실잔고 불일치 감지 ---
    pm = f.get("position_monitor")
    if pm and pos:
        try:
            mismatches = await pm.verify_and_sync()  # type: ignore[union-attr]
            if mismatches:
                pos = pm.get_all_positions()  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("포지션 검증 실패 (기존 캐시 사용): %s", exc)

    # --- 청산 단계 ---
    if es and om and pos:
        for tk, pd in pos.items():
            try:
                bun = await builder.build(tk) if builder else IndicatorBundle()  # type: ignore[union-attr]
                p = await _P(pd)  # type: ignore[misc]
                # 가격 스파이크 정보: current_price vs avg_price 변동률을 간이 계산한다
                price_spike = _estimate_price_spike(p)
                dec = es.evaluate(  # type: ignore[union-attr]
                    p, bun, regime, sp,
                    stat_arb_signals=stat_arb_signals,
                    news_context=_pick_highest_impact(news_context) if news_context else None,
                    price_spike=price_spike,
                )
                if not dec.should_exit:
                    continue
                q = p.quantity if dec.exit_pct >= 100.0 else max(1, int(p.quantity * dec.exit_pct / 100.0))
                ex = reg.get_exchange_code(tk) if reg.has_ticker(tk) else "NAS"
                r = await om.execute_sell(tk, q, ex, expected_price=p.current_price)  # type: ignore[union-attr]
                if r.status == "filled":
                    trades += 1
                    logger.info("청산: %s %d주 (%s)", tk, q, dec.exit_type)
                    await _record_trade(
                        system, tk, "sell", q, p.current_price, dec.exit_type, p.unrealized_pnl_pct,
                        reason=dec.reason or dec.exit_type,
                    )

                    # H-4: 매도 체결 PnL을 DailyLossLimit에 기록한다
                    try:
                        daily_loss_limiter.record_trade(p.unrealized_pnl_pct)  # type: ignore[union-attr]
                    except Exception:
                        pass

                    # 분할 청산 단계를 실행 완료로 표시한다
                    if dec.exit_type == "scaled_exit" and dec.exit_level is not None:
                        es.mark_scale_executed(tk, dec.exit_level)  # type: ignore[union-attr]

                    # 100% 청산 시 ExitStrategy 상태를 초기화한다
                    if dec.exit_pct >= 100.0:
                        es.clear_position(tk)  # type: ignore[union-attr]
                        # C-5: 완전 청산 시 beast/pyramid 캐시 키를 삭제한다
                        try:
                            await _cache.delete(f"beast_positions:{tk}")  # type: ignore[union-attr]
                            await _cache.delete(f"pyramid_level:{tk}")  # type: ignore[union-attr]
                        except Exception as exc:
                            logger.error("캐시 상태 삭제 실패 (세션 종료 시 재정리 필요): %s %s", tk, exc)

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
                    await _record_alert(
                        system, "trade", "매도 주문 실패",
                        f"{tk} 매도 주문이 거부되었습니다: {r.message}",
                        severity="error",
                    )
            except Exception as e:
                logger.error("청산E (%s): %s", tk, e)

    return trades, pos


async def _run_entry_stage(
    system: InjectedSystem,
    pos: dict,
    regime: object,
    vix_val: float,
    sp: object,
    balance: object,
    daily_loss_limiter: object,
    tilt_blocked: bool,
    winding_down: bool,
    news_context: list[dict] | None,
    en: object,
    om: object,
    builder: object,
    _cache: object,
    _P: object,
    multipliers: dict[str, float | bool],
) -> int:
    """진입 단계: 유니버스를 순회하며 진입 평가 및 매수 주문을 실행한다.

    Beast Mode, MicroRegime, WickCatcher, 일반 진입을 순차 평가한다.
    마무리 모드, 일일 손실 한도, 틸트 차단 시 진입을 건너뛴다.

    Returns:
        체결 건수.
    """
    from src.indicators.models import IndicatorBundle

    f = system.features
    reg = system.components.registry
    trades = 0

    held = set(pos.keys()) if pos else set()
    # H-4: 일일 손실 한도 도달 시 신규 진입 전체를 차단한다
    daily_loss_blocked = daily_loss_limiter.is_limit_reached()  # type: ignore[union-attr]
    if daily_loss_blocked:
        _cumulative_pnl = daily_loss_limiter.get_cumulative_pnl()  # type: ignore[union-attr]
        logger.warning(
            "[일일손실한도] 한도 도달 (누적=%.2f%%) -- 신규 진입 차단",
            _cumulative_pnl,
        )
        await _record_alert(
            system, "risk", "일일 손실 한도 도달",
            f"일일 누적 손실이 {_cumulative_pnl:.2f}%에 도달하여 신규 진입이 차단되었습니다.",
            severity="warning",
        )
    if winding_down:
        logger.debug("[마무리모드] 신규 진입 건너뜀")
        return 0
    if daily_loss_blocked:
        logger.info("[일일손실한도] 진입 단계 전체 건너뜀")
        return 0
    if not en or not om:
        return 0
    if tilt_blocked:
        logger.info("[틸트] 진입 단계 전체 건너뜀 (감정적 매매 방지)")
        return 0

    pl = [await _P(v) for v in pos.values()] if pos else []  # type: ignore[misc]

    # M-6: 섹터 로테이션 신호를 조회하여 진입 확신도에 반영한다
    rotation = _get_sector_rotation_signal(system)
    avoid_sectors: set[str] = set()
    prefer_sectors: set[str] = set()
    if rotation is not None:
        avoid_sectors = set(getattr(rotation, "bottom2_avoid", []))
        prefer_sectors = set(getattr(rotation, "top3_prefer", []))

    # 승수 값 추출
    liquidity_multiplier = float(multipliers["liquidity"])
    house_money_mult = float(multipliers["house_money"])
    streak_mult = float(multipliers["streak"])
    var_mult = float(multipliers["var"])

    for mt in reg.get_universe():
        if mt.ticker in held:
            continue

        # M-6: 섹터 로테이션 배수 -- 회피 섹터는 페널티(-10%), 선호 섹터는 보너스(+5%)
        sector_rotation_mult: float = 1.0
        if hasattr(mt, "sector") and mt.sector:
            mapped = _SECTOR_TO_ROTATION.get(mt.sector, "")
            if mapped and mapped in avoid_sectors:
                sector_rotation_mult = 0.90  # -10% 페널티
                logger.debug("섹터 로테이션 페널티: %s (sector=%s→%s)", mt.ticker, mt.sector, mapped)
            elif mapped and mapped in prefer_sectors:
                sector_rotation_mult = 1.05  # +5% 보너스
                logger.debug("섹터 로테이션 보너스: %s (sector=%s→%s)", mt.ticker, mt.sector, mapped)

        try:
            bun = await builder.build(mt.ticker) if builder else IndicatorBundle()  # type: ignore[union-attr]

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
                        gap_result = grp.evaluate(pre_close, cur_price, ticker=mt.ticker)  # type: ignore[union-attr]
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

            # M-8: MicroRegime 게이트 -- 레짐별 동적 배수를 적용한다
            micro_ok, micro_regime, micro_mult = await _run_micro_regime_gate(
                system, mt.ticker, builder,
            )
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
            # H-7: 인버스 ETF는 페이드 방향을 반전한다 (short→long, long→short)
            fade_skip = False
            try:
                nf = f.get("news_fading")
                if nf is not None and sp.news_fading_enabled:  # type: ignore[union-attr]
                    spike = _estimate_price_spike_from_bundle(bun)
                    _top_news = _pick_highest_impact(news_context) if news_context else None
                    if spike is not None and _top_news is not None:
                        fade_signal = nf.evaluate(spike, _top_news)  # type: ignore[union-attr]
                        if fade_signal.should_fade:
                            fade_dir = fade_signal.direction
                            # H-7: 인버스 ETF는 방향을 반전한다
                            if reg.has_ticker(mt.ticker) and reg.is_inverse(mt.ticker):
                                fade_dir = "long" if fade_dir == "short" else "short"
                                logger.debug(
                                    "[뉴스페이딩] 인버스 ETF 방향 반전: %s %s→%s",
                                    mt.ticker, fade_signal.direction, fade_dir,
                                )
                            if fade_dir == "short":
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

            # 최종 배수 = 유동성 × 갭 × NAV × 디케이 × 하우스머니 × 연속손절 × 섹터 × 미시레짐 × VaR
            combined_mult = (
                liquidity_multiplier * gap_size_mult * nav_size_mult
                * decay_mult * house_money_mult * streak_mult
                * sector_rotation_mult * micro_mult * var_mult
            )
            logger.info(
                "[포지션 승수] %s: liquidity=%.2f gap=%.2f nav=%.2f decay=%.2f "
                "house=%.2f streak=%.2f sector=%.2f micro=%.2f var=%.2f → combined=%.2f",
                mt.ticker, liquidity_multiplier, gap_size_mult, nav_size_mult,
                decay_mult, house_money_mult, streak_mult, sector_rotation_mult,
                micro_mult, var_mult, combined_mult,
            )
            # 최종 포지션 퍼센트에 배수를 적용한다
            final_pct = ed.position_size_pct * combined_mult

            # M-3: Kelly Criterion 어드바이저리 캡 -- 최적 비율을 초과하면 축소한다
            try:
                from src.risk.gates.risk_budget import calculate_position_size as _kelly_calc
                _t_today = await _cache.read_json("trades:today") or []  # type: ignore[union-attr]
                _sell_trades = [t for t in _t_today if isinstance(t, dict) and t.get("side") == "sell"]
                if len(_sell_trades) >= 3:
                    _wins = [t for t in _sell_trades if (t.get("pnl") or 0) > 0]
                    _losses = [t for t in _sell_trades if (t.get("pnl") or 0) <= 0]
                    # 손실 거래가 없으면 Kelly 계산을 건너뛴다 (avg_loss=0 → 비현실적 결과)
                    if len(_losses) == 0:
                        logger.debug("[Kelly] 손실 거래 없음 -- Kelly 계산 건너뜀")
                    elif len(_wins) == 0:
                        logger.debug("[Kelly] 승리 거래 없음 -- Kelly 계산 건너뜀")
                    else:
                        _win_rate = len(_wins) / len(_sell_trades)
                        _avg_win = sum(abs(t.get("pnl", 0)) for t in _wins) / len(_wins)
                        _avg_loss = sum(abs(t.get("pnl", 0)) for t in _losses) / len(_losses)
                        if _avg_win > 0 and _avg_loss > 0 and balance.total_equity > 0:  # type: ignore[union-attr]
                            _kelly_result = _kelly_calc(_win_rate, _avg_win, _avg_loss, balance.total_equity)  # type: ignore[union-attr]
                            # 비현실적 값(0 이하 또는 25% 초과) 거부한다
                            if 0 < _kelly_result.adjusted_pct <= 25.0 and final_pct > _kelly_result.adjusted_pct:
                                logger.info(
                                    "[Kelly] 포지션 캡 적용: %s %.1f%% -> %.1f%% (Kelly=%.1f%%)",
                                    mt.ticker, final_pct, _kelly_result.adjusted_pct, _kelly_result.kelly_pct,
                                )
                                final_pct = _kelly_result.adjusted_pct
            except Exception as exc:
                logger.debug("[Kelly] 계산 실패 (무시): %s", exc)

            # H-6: 브로커 API 우선 → 지표 폴백으로 현재가를 조회한다
            entry_price = await _get_current_price_with_broker(
                system, mt.ticker, bun, mt.exchange,
            )
            if entry_price <= 0:
                logger.info("진입 건너뜀: %s 현재가 미확보 (브로커+지표 모두 실패)", mt.ticker)
                continue
            q = _pct_to_shares(final_pct, balance.total_equity, entry_price)  # type: ignore[union-attr]
            if q <= 0:
                continue

            # SafetyChecker → HardSafety 순서로 매수 전 안전 검사를 실행한다
            if not _check_buy_safety(
                system, mt.ticker, q, regime.regime_type, vix_val, balance,  # type: ignore[union-attr]
            ):
                logger.info("진입차단(안전): %s", mt.ticker)
                await _record_alert(
                    system, "safety", "매수 차단",
                    f"안전 검사에 의해 {mt.ticker} 매수가 차단되었습니다.",
                    severity="warning",
                )
                continue

            r = await om.execute_buy(mt.ticker, q, mt.exchange, expected_price=entry_price)  # type: ignore[union-attr]
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
                await _record_alert(
                    system, "trade", "매수 주문 실패",
                    f"{mt.ticker} 매수 주문이 거부되었습니다: {r.message}",
                    severity="error",
                )
        except Exception as e:
            logger.error("진입E (%s): %s", mt.ticker, e)

    return trades


async def _run_regular_session(system: InjectedSystem, daily_loss_limiter: object) -> int:
    """정규 세션: 동기화 + 청산 + 진입을 수행한다. 체결 건수를 반환한다.

    청산 우선순위: emergency -> hard_stop(ATR동적) -> news_fade -> stat_arb -> take_profit -> trailing
    진입 우선순위: Beast Mode (A+ 셋업) -> MicroRegime 게이트 -> WickCatcher -> 일반 진입
    포지션 관리: Pyramiding (추가 진입)
    """
    from src.strategy.models import Position

    # 1단계: 세션 컨텍스트 준비 (포지션 동기화, 레짐, 파라미터, 잔고)
    ctx = await _prepare_session_context(system)
    if ctx is None:
        return 0
    pos, regime, vix_val, sp, balance, winding_down = ctx

    # C-2/C-3: 캐시에서 beast 플래그와 pyramid 레벨을 읽어 Position을 생성한다
    _cache = system.components.cache
    f, reg = system.features, system.components.registry

    async def _P(d: object) -> Position:
        """PositionData → Position 변환 시 캐시에서 beast/pyramid 상태를 복원한다."""
        ticker = d.ticker  # type: ignore[union-attr]
        is_beast = False
        pyramid_level = 0
        try:
            beast_flag = await _cache.read(f"beast_positions:{ticker}")
            if beast_flag is not None:
                is_beast = True
        except Exception:
            pass
        try:
            pyr_raw = await _cache.read(f"pyramid_level:{ticker}")
            if pyr_raw is not None:
                pyramid_level = int(pyr_raw)
        except Exception:
            pass
        return Position(
            ticker=ticker,
            quantity=d.quantity,  # type: ignore[union-attr]
            avg_price=d.avg_price,  # type: ignore[union-attr]
            current_price=d.current_price,  # type: ignore[union-attr]
            unrealized_pnl_pct=d.pnl_pct,  # type: ignore[union-attr]
            is_beast=is_beast,
            pyramid_level=pyramid_level,
        )

    # 2단계: 포지션 승수 계산 (유동성, 하우스머니, 연속손절, VaR, 틸트)
    multipliers = await _compute_position_multipliers(system, pos, balance, daily_loss_limiter)
    tilt_blocked = bool(multipliers["tilt_blocked"])

    # 종합 분석 보고서 기반 DecisionMaker를 실행한다 (이벤트 발행용)
    await _run_decision_maker(system, regime, pos, _cache, balance)

    es, en, om = f.get("exit_strategy"), f.get("entry_strategy"), f.get("order_manager")
    builder = f.get("indicator_bundle_builder") or f.get("indicator_builder")

    # StatArb 신호를 한 번만 조회하여 모든 포지션에 재사용한다 (API 절약)
    stat_arb_signals = await _fetch_stat_arb_signals(system)
    # 최신 뉴스 컨텍스트를 캐시에서 읽어 뉴스 페이딩 청산에 활용한다
    news_context = await _fetch_news_context(system)

    trades = 0

    # 3단계: 청산
    exit_trades, pos = await _run_exit_stage(
        system, pos, regime, sp, balance, daily_loss_limiter,
        stat_arb_signals, news_context, es, om, builder, _cache, _P,
    )
    trades += exit_trades

    # 4단계: 피라미딩 (마무리 모드 제외)
    if pos and om and not winding_down:
        pos_list = [await _P(v) for v in pos.values()]
        pyr_trades = await _run_pyramiding(system, pos_list, regime, vix_val, balance, sp, om, reg)
        trades += pyr_trades

    # 5단계: 진입
    entry_trades = await _run_entry_stage(
        system, pos, regime, vix_val, sp, balance, daily_loss_limiter,
        tilt_blocked, winding_down, news_context,
        en, om, builder, _cache, _P, multipliers,
    )
    trades += entry_trades

    logger.info("정규 세션: %d건 체결", trades)
    return trades

async def _update_ws_cache(
    system: InjectedSystem,
    session_type: str,
    trades_executed: int,
) -> None:
    """WebSocket 채널용 캐시를 갱신한다.

    ws:positions, ws:dashboard, ws:trades, ws:alerts, ws:orderflow 키에
    최신 데이터를 기록하여 WebSocketManager가 클라이언트에 실시간
    데이터를 전달할 수 있게 한다.
    트레이딩 루프에 영향을 주지 않도록 모든 예외를 흡수한다.
    """
    try:
        cache = system.components.cache
        pos_monitor = system.features.get("position_monitor")
        if pos_monitor is None:
            return

        # ws:positions -- 포지션 목록 (Dart Position.fromJson 호환 키로 변환)
        all_positions = pos_monitor.get_all_positions()
        position_list: list[dict] = []
        for p in all_positions.values():
            d = p.model_dump()
            # pnl_pct → unrealized_pnl_pct 키 변환
            if "pnl_pct" in d:
                d["unrealized_pnl_pct"] = d.pop("pnl_pct")
            # pnl_amount → unrealized_pnl 키 변환
            if "pnl_amount" in d:
                d["unrealized_pnl"] = d.pop("pnl_amount")
            # 미실현 손익 계산 (필드 누락 시)
            d.setdefault("unrealized_pnl_pct", 0.0)
            d.setdefault("unrealized_pnl",
                         (d.get("current_price", 0) - d.get("avg_price", 0)) * d.get("quantity", 0))
            d.setdefault("hold_days", 0)
            d.setdefault("entry_time", "")
            d.setdefault("strategy", "")
            position_list.append(d)
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

        # ws:trades -- 오늘의 거래 기록 (Dart Trade.fromJson 호환 키로 변환)
        raw_trades: list[dict] = await cache.read_json("trades:today") or []
        trades_data: list[dict] = []
        for idx, tr in enumerate(raw_trades):
            if not isinstance(tr, dict):
                continue
            converted: dict = dict(tr)
            # side → action 키 변환
            if "side" in converted and "action" not in converted:
                converted["action"] = converted.pop("side")
            # id 필드 보충 (Dart에서 int 기대)
            converted.setdefault("id", idx + 1)
            # pnl_pct 계산 (없으면 pnl / (price * quantity) * 100)
            if "pnl_pct" not in converted:
                pnl = converted.get("pnl")
                price = converted.get("price", 0)
                qty = converted.get("quantity", 0)
                if pnl is not None and price > 0 and qty > 0:
                    converted["pnl_pct"] = (pnl / (price * qty)) * 100.0
                else:
                    converted["pnl_pct"] = 0.0
            # pnl 기본값 보충
            converted.setdefault("pnl", 0.0)
            converted.setdefault("reason", "")
            trades_data.append(converted)
        await cache.write_json("ws:trades", {
            "channel": "trades",
            "data": trades_data,
            "count": len(trades_data),
        }, ttl=30)

        # ws:alerts -- 알림 목록 (alerts:list → 프론트엔드 AlertNotification 형식으로 변환)
        try:
            raw_alerts: list[dict] = await cache.read_json("alerts:list") or []
            if raw_alerts:
                # 읽음 처리된 alert_id 집합을 로드한다
                read_ids_raw = await cache.read_json("alerts:read")
                read_ids: set[str] = set(read_ids_raw) if isinstance(read_ids_raw, list) else set()

                # 최신순 정렬 후 최대 50건만 전송한다
                sorted_alerts = sorted(
                    raw_alerts,
                    key=lambda a: str(a.get("timestamp", "")),
                    reverse=True,
                )[:50]

                # 프론트엔드 AlertNotification.fromJson이 기대하는 키로 매핑한다
                alert_items: list[dict] = []
                for raw in sorted_alerts:
                    alert_id = str(raw.get("id", ""))
                    alert_items.append({
                        "id": alert_id,
                        "alert_type": str(raw.get("type", raw.get("alert_type", "system"))),
                        "title": str(raw.get("title", raw.get("message", "")[:30])),
                        "message": str(raw.get("message", "")),
                        "severity": str(raw.get("severity", "info")).lower(),
                        "data": raw.get("data"),
                        "created_at": str(raw.get("timestamp", raw.get("created_at", ""))),
                        "read": alert_id in read_ids,
                    })

                await cache.write_json("ws:alerts", {
                    "channel": "alerts",
                    "data": alert_items,
                    "count": len(alert_items),
                }, ttl=30)
            else:
                await cache.write_json("ws:alerts", {
                    "channel": "alerts",
                    "data": [],
                    "count": 0,
                }, ttl=30)
        except Exception:
            pass  # alerts 갱신 실패는 무시한다

        # ws:orderflow -- 스캘퍼 테이프용 오더플로우 데이터 (분석 지표 포함)
        try:
            from src.indicators.misc.order_flow_aggregator import OrderFlowAggregator

            of_snapshots: list[dict] = []
            aggregator = OrderFlowAggregator(cache)
            for ticker in list(all_positions.keys()):
                snapshot = await aggregator.aggregate(ticker)
                if snapshot is None:
                    continue
                # raw 데이터에서 last_price, last_volume, spread 추출
                raw = await cache.read_json(f"order_flow:raw:{ticker}")
                last_price = 0.0
                last_volume = 0
                spread_bps = 0.0
                if raw and isinstance(raw, dict):
                    trades = raw.get("trades", [])
                    if trades:
                        last_t = trades[-1]
                        last_price = float(last_t.get("price", 0))
                        last_volume = int(last_t.get("volume", 0))
                    bids = raw.get("bids", [])
                    asks = raw.get("asks", [])
                    if bids and asks:
                        best_bid = float(bids[0].get("price", 0))
                        best_ask = float(asks[0].get("price", 0))
                        mid = (best_bid + best_ask) / 2
                        if mid > 0:
                            spread_bps = round((best_ask - best_bid) / mid * 10000, 2)
                # Flutter ScalperTapeData.fromJson 호환 형식으로 변환
                obi_val = snapshot.obi
                of_snapshots.append({
                    "ticker": ticker,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "obi": {
                        "value": obi_val,
                        "smoothed": obi_val,
                        "signal": _obi_signal(obi_val),
                    },
                    "cvd": {"cumulative": snapshot.cvd, "divergence": None},
                    "vpin": {
                        "value": snapshot.vpin,
                        "level": _vpin_level(snapshot.vpin),
                    },
                    "execution_strength": {
                        "current": snapshot.execution_strength,
                        "trend": "stable",
                        "is_surge": snapshot.execution_strength > 0.8,
                    },
                    "spread_bps": spread_bps,
                    "last_price": last_price,
                    "last_volume": last_volume,
                    "toxicity": None,
                    "time_stop": None,
                })
            await cache.write_json("ws:orderflow", {
                "channel": "orderflow",
                "data": of_snapshots if of_snapshots else None,
                "count": len(of_snapshots),
            }, ttl=30)

            # orderflow REST 엔드포인트용 스냅샷을 저장한다
            # order_flow.py의 get_orderflow_snapshot()이 이 캐시를 1차 조회한다
            if of_snapshots:
                tickers_dict = {item["ticker"]: item for item in of_snapshots}
                await cache.write_json("orderflow:snapshot", {
                    "tickers": tickers_dict,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "message": "실시간 주문 흐름 데이터",
                }, ttl=30)

                # 슬라이딩 윈도우 히스토리 누적 (6시간 = 360개 1분 스냅샷)
                await _accumulate_orderflow_history(cache, of_snapshots)

                # 고래 활동 탐지 → orderflow:whale 캐시에 기록한다
                from src.indicators.misc.whale_detector import detect_whale_events
                await detect_whale_events(cache, of_snapshots)
        except Exception:
            pass  # orderflow 갱신 실패는 무시한다

        # indicators:latest — 보유 종목의 지표 스냅샷을 집약 캐시한다
        # continuous_analysis.py와 analysis.py의 엔드포인트가 조회한다
        try:
            builder = system.features.get("indicator_bundle_builder") or system.features.get("indicator_builder")
            if builder is not None and all_positions:
                ind_snapshot: dict[str, dict] = {}
                for ticker in list(all_positions.keys()):
                    try:
                        bun = await builder.build(ticker)  # type: ignore[union-attr]
                        bun_dict = bun.model_dump() if hasattr(bun, "model_dump") else {}
                        # 핵심 지표만 추출하여 간결한 스냅샷을 구성한다
                        tech = bun_dict.get("technical") or {}
                        ind_snapshot[ticker] = {
                            "rsi": tech.get("rsi_14"),
                            "macd": tech.get("macd"),
                            "macd_signal": tech.get("macd_signal"),
                            "ema_20": tech.get("ema_20"),
                            "ema_50": tech.get("ema_50"),
                            "atr": tech.get("atr_14"),
                            "bb_upper": tech.get("bb_upper"),
                            "bb_lower": tech.get("bb_lower"),
                        }
                    except Exception:
                        pass  # 개별 종목 실패는 무시한다
                if ind_snapshot:
                    await cache.write_json("indicators:latest", ind_snapshot, ttl=300)
        except Exception:
            pass  # indicators 캐시 갱신 실패는 무시한다
    except Exception as exc:
        logger.debug("WS 캐시 갱신 실패 (무시): %s", exc)


async def _execute_iteration(
    system: InjectedSystem,
    time_info: TimeInfo,
    session_type: str,
    daily_loss_limiter: object,
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
            trades = await _run_regular_session(system, daily_loss_limiter)
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
    daily_loss_limiter: object,
) -> bool:
    """루프 1회 실행 후 계속 여부를 반환한다. False면 루프 종료이다."""
    time_info = system.components.clock.get_time_info()
    if await check_shutdown(time_info, shutdown_event):
        return False
    session = determine_session(time_info)
    interval = calculate_interval(session)
    result = await _execute_iteration(system, time_info, session, daily_loss_limiter)
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
    # C-2: DailyLossLimit을 루프 밖에서 1회 생성하여 반복 간 누적 상태를 보존한다
    from src.risk.gates.daily_loss_limit import DailyLossLimit
    daily_loss_limiter = DailyLossLimit()
    iteration = 0
    logger.info("=== 매매 루프 시작 ===")
    await _record_alert(
        system, "system", "매매 루프 시작",
        "자동매매 루프가 시작되었습니다.",
        severity="info",
    )
    while not shutdown_event.is_set():
        iteration += 1
        should_continue = await _run_single_iteration(
            system, shutdown_event, iteration, daily_loss_limiter,
        )
        if not should_continue:
            break
    logger.info("=== 매매 루프 종료 (총 %d회 반복) ===", iteration)
    await _record_alert(
        system, "system", "매매 루프 종료",
        f"자동매매 루프가 종료되었습니다. 총 {iteration}회 반복 실행.",
        severity="info",
    )
