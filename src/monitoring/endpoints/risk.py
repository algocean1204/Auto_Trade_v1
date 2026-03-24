"""RiskEndpoints -- 포트폴리오 리스크 대시보드 API이다.

포트폴리오 VaR, 최대 낙폭, 포지션 집중도, 레짐, VIX, 리스크 스코어,
경고 목록을 통합하여 제공한다.

데이터 소스:
  - regime_detector: 현재 시장 레짐
  - position_monitor: 포지션 집중도 및 낙폭
  - vix_fetcher: 현재 VIX
  - capital_guard: 일일/주간 손실 현황
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException

from src.monitoring.server.auth import verify_api_key

from src.common.logger import get_logger
from src.monitoring.schemas.risk_schemas import (
    ConcentrationData,
    GateEntry,
    PositionConcentrationEntry,
    RiskBudgetData,
    RiskDashboardResponse,
    StreakData,
    TrailingStopData,
    VarData,
)

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

risk_router = APIRouter(prefix="/api/risk", tags=["risk"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None

# VIX 구간별 리스크 스코어 임계값이다
_VIX_LOW: float = 15.0
_VIX_MID: float = 25.0
_VIX_HIGH: float = 35.0

# 집중도 경고 임계값이다 (포트폴리오 대비 단일 종목 비중)
_CONCENTRATION_WARN_PCT: float = 30.0
_CONCENTRATION_CRIT_PCT: float = 50.0


def set_risk_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("RiskEndpoints 의존성 주입 완료")


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def _calc_risk_score(
    vix: float,
    daily_pnl_pct: float,
    concentration_pct: float,
    regime: str,
) -> float:
    """VIX, 일일 손익, 집중도, 레짐 기반으로 종합 리스크 스코어를 산출한다.

    0.0(최저) ~ 10.0(최고) 범위를 반환한다.
    """
    # VIX 기여도 (0~4점)
    if vix < _VIX_LOW:
        vix_score = 1.0
    elif vix < _VIX_MID:
        vix_score = 2.5
    elif vix < _VIX_HIGH:
        vix_score = 3.5
    else:
        vix_score = 4.0

    # 일일 손실 기여도 (0~3점) -- 음수 손실일수록 점수 증가
    loss_pct = max(0.0, -daily_pnl_pct)
    loss_score = min(3.0, loss_pct * 1.0)

    # 집중도 기여도 (0~2점)
    if concentration_pct >= _CONCENTRATION_CRIT_PCT:
        conc_score = 2.0
    elif concentration_pct >= _CONCENTRATION_WARN_PCT:
        conc_score = 1.0
    else:
        conc_score = 0.0

    # 레짐 기여도 (0~1점)
    regime_scores: dict[str, float] = {
        "strong_bull": 0.0,
        "mild_bull": 0.2,
        "sideways": 0.5,
        "mild_bear": 0.8,
        "crash": 1.0,
    }
    regime_score = regime_scores.get(regime, 0.5)

    total = vix_score + loss_score + conc_score + regime_score
    return round(min(10.0, total), 2)


def _build_warnings(
    vix: float,
    daily_pnl_pct: float,
    weekly_pnl_pct: float,
    concentration_pct: float,
    regime: str,
    daily_limit_reached: bool,
    weekly_limit_reached: bool,
) -> list[str]:
    """리스크 조건별 경고 메시지 목록을 생성한다."""
    warnings: list[str] = []

    if daily_limit_reached:
        warnings.append(f"일일 손실 한도 도달: {daily_pnl_pct:.2f}%")
    if weekly_limit_reached:
        warnings.append(f"주간 손실 한도 도달: {weekly_pnl_pct:.2f}%")
    if vix >= _VIX_HIGH:
        warnings.append(f"VIX 극단적 공포 구간: {vix:.1f}")
    elif vix >= _VIX_MID:
        warnings.append(f"VIX 상승 주의: {vix:.1f}")
    if concentration_pct >= _CONCENTRATION_CRIT_PCT:
        warnings.append(f"포지션 집중도 위험: {concentration_pct:.1f}%")
    elif concentration_pct >= _CONCENTRATION_WARN_PCT:
        warnings.append(f"포지션 집중도 경고: {concentration_pct:.1f}%")
    if regime in ("mild_bear", "crash"):
        warnings.append(f"방어적 레짐 활성화: {regime}")

    return warnings


# ---------------------------------------------------------------------------
# 엔드포인트 구현
# ---------------------------------------------------------------------------

@risk_router.get("/dashboard", response_model=RiskDashboardResponse)
async def get_risk_dashboard(_auth: str = Depends(verify_api_key)) -> RiskDashboardResponse:
    """포트폴리오 리스크 대시보드 종합 데이터를 반환한다.

    regime_detector, position_monitor, vix_fetcher, capital_guard를
    모두 조회하여 통합 리스크 현황을 반환한다.
    각 피처가 없으면 안전한 기본값으로 폴백한다.

    플랫 필드(하위 호환) + 중첩 구조(Flutter 대시보드용)를 모두 반환한다.
    """
    if _system is None:
        return RiskDashboardResponse(
            portfolio_var=0.0,
            max_drawdown_pct=0.0,
            current_drawdown_pct=0.0,
            position_concentration=0.0,
            regime="unknown",
            vix_current=19.0,
            risk_score=0.0,
            warnings=[],
            updated_at=datetime.now(tz=timezone.utc).isoformat(),
        )
    try:
        features = _system.features

        # --- VIX 조회 ---
        vix_current: float = 19.0
        vix_fetcher = features.get("vix_fetcher")
        if vix_fetcher is not None:
            try:
                vix_current = await vix_fetcher.get_vix()
            except Exception:
                _logger.debug("VIX 조회 실패 -- 기본값 사용")

        # --- 레짐 탐지 ---
        regime: str = "unknown"
        regime_detector = features.get("regime_detector")
        if regime_detector is not None:
            try:
                market_regime = regime_detector.detect(vix_current)
                regime = str(market_regime.regime_type)
            except Exception:
                _logger.debug("레짐 탐지 실패 -- 기본값 사용")

        # --- 포지션 집중도 및 낙폭 계산 ---
        position_concentration: float = 0.0
        current_drawdown_pct: float = 0.0
        portfolio_var: float = 0.0
        total_position_value: float = 0.0
        all_positions: dict[str, Any] | None = None

        pos_monitor = features.get("position_monitor")
        if pos_monitor is not None:
            try:
                all_positions = pos_monitor.get_all_positions()
                # 폴백: position_monitor 캐시가 비어있으면 broker에서 직접 조회한다
                if not all_positions:
                    try:
                        from src.executor.broker.kis_api import fetch_balance

                        broker = _system.components.broker
                        balance = await fetch_balance(
                            broker.virtual_auth, broker._http,  # type: ignore[attr-defined]
                        )
                        all_positions = {
                            p.ticker: p for p in balance.positions
                        }
                        _logger.info(
                            "브로커 잔고 직접 조회 폴백 성공: %d개 포지션",
                            len(all_positions),
                        )
                    except Exception as exc:
                        _logger.warning("브로커 잔고 직접 조회 폴백 실패: %s", exc)
                if all_positions:
                    position_values = [
                        float(p.current_price) * float(p.quantity)
                        for p in all_positions.values()
                    ]
                    total_position_value = sum(position_values)
                    if total_position_value > 0:
                        max_pos_value = max(position_values)
                        position_concentration = round(
                            max_pos_value / total_position_value * 100, 2
                        )
                    # 현재 낙폭 추정: 모든 포지션의 평균 미실현 PnL(%)이다
                    pnl_pcts = []
                    for pos in all_positions.values():
                        avg = float(pos.avg_price)
                        cur = float(pos.current_price)
                        if avg > 0:
                            pnl_pcts.append((cur - avg) / avg * 100)
                    if pnl_pcts:
                        current_drawdown_pct = round(
                            min(0.0, sum(pnl_pcts) / len(pnl_pcts)), 2
                        )
                    # VaR 추정: 포지션 총 가치의 2% (단순 추정)
                    portfolio_var = round(total_position_value * 0.02, 2)
            except Exception:
                _logger.debug("포지션 데이터 조회 실패 -- 기본값 사용")

        # --- CapitalGuard 일일/주간 손실 현황 ---
        daily_pnl_pct: float = 0.0
        weekly_pnl_pct: float = 0.0
        daily_limit_reached: bool = False
        weekly_limit_reached: bool = False

        capital_guard = features.get("capital_guard")
        if capital_guard is not None:
            try:
                daily_pnl_pct = float(capital_guard.get_daily_pnl())
                weekly_pnl_pct = float(capital_guard.get_weekly_pnl())
                daily_limit_reached = bool(capital_guard.is_daily_limit_reached())
                weekly_limit_reached = bool(capital_guard.is_weekly_limit_reached())
            except Exception:
                _logger.debug("CapitalGuard 조회 실패 -- 기본값 사용")

        # --- 최대 낙폭은 캐시에서 읽는다 ---
        max_drawdown_pct: float = 0.0
        try:
            cache = _system.components.cache
            dd_cached = await cache.read("risk:max_drawdown")
            if dd_cached is not None:
                max_drawdown_pct = float(dd_cached)
        except Exception:
            _logger.debug("최대 낙폭 캐시 읽기 실패 -- 기본값 사용")

        # --- 종합 리스크 스코어 계산 ---
        risk_score = _calc_risk_score(
            vix_current, daily_pnl_pct, position_concentration, regime
        )

        # --- 경고 목록 생성 ---
        warnings = _build_warnings(
            vix_current,
            daily_pnl_pct,
            weekly_pnl_pct,
            position_concentration,
            regime,
            daily_limit_reached,
            weekly_limit_reached,
        )

        # ---------------------------------------------------------------
        # 중첩 구조 데이터 구성 (Flutter 대시보드용)
        # ---------------------------------------------------------------

        # --- 게이트 목록 생성 ---
        gates = _build_gates(
            capital_guard=capital_guard,
            daily_pnl_pct=daily_pnl_pct,
            weekly_pnl_pct=weekly_pnl_pct,
            daily_limit_reached=daily_limit_reached,
            weekly_limit_reached=weekly_limit_reached,
            vix_current=vix_current,
            position_concentration=position_concentration,
            regime=regime,
        )

        # --- 리스크 예산 구성 ---
        risk_budget_data = _build_risk_budget(
            capital_guard=capital_guard,
            daily_pnl_pct=daily_pnl_pct,
        )

        # --- VaR 지표 구성 ---
        var_data = VarData(
            var_pct=round(
                portfolio_var / max(1.0, total_position_value) * 100, 2,
            ) if total_position_value > 0 else 0.0,
            confidence=0.95,
            risk_level=(
                "low" if risk_score < 3
                else "medium" if risk_score < 7
                else "high"
            ),
            max_var_pct=5.0,
        )

        # --- 포지션 집중도 목록 구성 ---
        concentrations_data = _build_concentrations(all_positions)

        # --- 트레일링 스톱 구성 ---
        trailing_data = _build_trailing_stop(features)

        # --- 연승/연패 카운터 구성 ---
        streak_data = await _build_streak(features, _system)

        return RiskDashboardResponse(
            # 기존 플랫 필드
            portfolio_var=portfolio_var,
            max_drawdown_pct=max_drawdown_pct,
            current_drawdown_pct=current_drawdown_pct,
            position_concentration=position_concentration,
            regime=regime,
            vix_current=vix_current,
            risk_score=risk_score,
            warnings=warnings,
            # 중첩 구조 필드
            updated_at=datetime.now(tz=timezone.utc).isoformat(),
            gates=gates,
            risk_budget=risk_budget_data,
            var_indicator=var_data,
            streak_counter=streak_data,
            concentrations=concentrations_data,
            trailing_stop=trailing_data,
        )
    except Exception:
        _logger.exception("리스크 대시보드 조회 실패")
        raise HTTPException(
            status_code=500,
            detail="리스크 데이터 조회 중 오류가 발생했다",
        ) from None


# ---------------------------------------------------------------------------
# 중첩 구조 빌더 헬퍼
# ---------------------------------------------------------------------------


def _build_gates(
    *,
    capital_guard: Any,
    daily_pnl_pct: float,
    weekly_pnl_pct: float,
    daily_limit_reached: bool,
    weekly_limit_reached: bool,
    vix_current: float,
    position_concentration: float,
    regime: str,
) -> list[GateEntry]:
    """리스크 게이트 상태 목록을 생성한다."""
    gates: list[GateEntry] = []

    # 일일 손실 한도 게이트
    if capital_guard is not None:
        gates.append(GateEntry(
            gate_name="daily_loss_limit",
            passed=not daily_limit_reached,
            action="block" if daily_limit_reached else "allow",
            message=f"일일 손실 {daily_pnl_pct:.2f}%",
            details={"current_value": daily_pnl_pct},
        ))
        # 주간 손실 한도 게이트
        gates.append(GateEntry(
            gate_name="weekly_loss_limit",
            passed=not weekly_limit_reached,
            action="block" if weekly_limit_reached else "allow",
            message=f"주간 손실 {weekly_pnl_pct:.2f}%",
            details={"current_value": weekly_pnl_pct},
        ))

    # VIX 임계값 게이트
    gates.append(GateEntry(
        gate_name="vix_threshold",
        passed=vix_current < _VIX_HIGH,
        action=(
            "block" if vix_current >= _VIX_HIGH
            else "reduce" if vix_current >= _VIX_MID
            else "allow"
        ),
        message=f"VIX {vix_current:.1f}",
        details={"current_value": vix_current, "threshold": _VIX_HIGH},
    ))

    # 집중도 게이트
    gates.append(GateEntry(
        gate_name="concentration",
        passed=position_concentration < _CONCENTRATION_WARN_PCT,
        action=(
            "block" if position_concentration >= _CONCENTRATION_CRIT_PCT
            else "warn" if position_concentration >= _CONCENTRATION_WARN_PCT
            else "allow"
        ),
        message=f"집중도 {position_concentration:.1f}%",
        details={
            "current_value": position_concentration,
            "threshold": _CONCENTRATION_WARN_PCT,
        },
    ))

    # 레짐 게이트
    gates.append(GateEntry(
        gate_name="regime",
        passed=regime not in ("crash",),
        action=(
            "block" if regime == "crash"
            else "reduce" if regime == "mild_bear"
            else "allow"
        ),
        message=f"시장 레짐: {regime}",
        details={"regime": regime},
    ))

    return gates


def _build_risk_budget(
    *,
    capital_guard: Any,
    daily_pnl_pct: float,
) -> RiskBudgetData:
    """리스크 예산 데이터를 구성한다."""
    if capital_guard is None:
        return RiskBudgetData()

    try:
        budget_pct = abs(float(getattr(capital_guard, "_daily_limit_pct", -3.0)))
        daily_limit_pct = budget_pct
        daily_used_pct = abs(min(0.0, daily_pnl_pct))
        consumption = (
            daily_used_pct / budget_pct * 100 if budget_pct > 0 else 0.0
        )
        return RiskBudgetData(
            budget_pct=budget_pct,
            consumption_pct=round(consumption, 2),
            daily_limit_pct=daily_limit_pct,
            daily_used_pct=round(daily_used_pct, 2),
        )
    except Exception:
        _logger.debug("리스크 예산 구성 실패 -- 기본값 사용")
        return RiskBudgetData()


def _build_concentrations(
    all_positions: dict[str, Any] | None,
) -> ConcentrationData:
    """포지션 집중도 목록을 구성한다."""
    entries: list[PositionConcentrationEntry] = []
    if not all_positions:
        return ConcentrationData(positions=entries)

    try:
        total_value = sum(
            float(p.current_price) * float(p.quantity)
            for p in all_positions.values()
        )
        for ticker, pos in all_positions.items():
            mv = float(pos.current_price) * float(pos.quantity)
            weight = (mv / total_value * 100) if total_value > 0 else 0.0
            entries.append(PositionConcentrationEntry(
                ticker=ticker,
                market_value=round(mv, 2),
                weight_pct=round(weight, 2),
            ))
    except Exception:
        _logger.debug("집중도 목록 구성 실패 -- 빈 목록 사용")

    return ConcentrationData(positions=entries)


def _build_trailing_stop(features: dict[str, Any]) -> TrailingStopData:
    """트레일링 스톱 현황을 구성한다.

    stop_loss 설정값과 position_monitor의 보유 포지션을 결합하여
    활성 상태 및 종목별 스톱 정보를 반환한다.
    """
    stop_loss = features.get("stop_loss")
    if stop_loss is None:
        return TrailingStopData()

    try:
        initial_pct = float(getattr(stop_loss, "initial_stop_pct", 3.0))
        trailing_pct = float(getattr(stop_loss, "trailing_stop_pct", 5.0))

        # 보유 포지션에서 트레일링 스톱 적용 종목 정보를 구성한다
        positions_info: dict[str, Any] = {}
        pos_monitor = features.get("position_monitor")
        if pos_monitor is not None:
            all_positions = pos_monitor.get_all_positions()
            for ticker, pos in all_positions.items():
                avg = float(pos.avg_price)
                cur = float(pos.current_price)
                pnl_pct = ((cur - avg) / avg * 100) if avg > 0 else 0.0
                # 트레일링 손절가: 현재가 기준으로 trailing_pct만큼 아래
                trailing_stop_price = round(cur * (1 - trailing_pct / 100), 4)
                # Flutter TrailingStopPosition.fromJson이 기대하는 키:
                # high_price, current_price, drawdown_pct, stop_price
                # high_price는 트레일링 기준 고가이므로 현재가를 사용한다
                drawdown_pct = round(min(0.0, pnl_pct), 2)
                positions_info[ticker] = {
                    "entry_price": avg,
                    "high_price": cur,
                    "current_price": cur,
                    "pnl_pct": round(pnl_pct, 2),
                    "drawdown_pct": drawdown_pct,
                    "stop_price": trailing_stop_price,
                    "trailing_stop_price": trailing_stop_price,
                }

        tracked = len(positions_info)
        return TrailingStopData(
            active=tracked > 0,
            initial_stop_pct=initial_pct,
            trailing_stop_pct=trailing_pct,
            tracked_positions=tracked,
            positions=positions_info,
        )
    except Exception:
        _logger.debug("트레일링 스톱 구성 실패 -- 기본값 사용")
        return TrailingStopData()


async def _build_streak(
    features: dict[str, Any],
    system: InjectedSystem | None,
) -> StreakData:
    """연승/연패 카운터를 구성한다.

    losing_streak 피처의 현재 값과 캐시의 거래 이력을 결합하여
    역대 최대 연승/연패를 계산한다.
    """
    losing_streak = features.get("losing_streak")
    current = 0
    if losing_streak is not None:
        try:
            current = int(getattr(losing_streak, "current_streak", 0))
        except Exception:
            _logger.debug("현재 연패 값 읽기 실패")

    # 캐시에서 당일 거래 이력을 읽어 최대 연승/연패를 계산한다
    max_win: int = 0
    max_loss: int = 0
    if system is not None:
        try:
            cache = system.components.cache
            trades: list[dict] = await cache.read_json("trades:today") or []
            if trades:
                win_run = 0
                loss_run = 0
                for trade in trades:
                    # 매수 거래(pnl 없음)는 스트릭 계산에서 제외한다
                    if trade.get("side") == "buy":
                        continue
                    pnl = float(trade.get("pnl") or 0.0)
                    if pnl > 0:
                        win_run += 1
                        loss_run = 0
                        max_win = max(max_win, win_run)
                    elif pnl < 0:
                        loss_run += 1
                        win_run = 0
                        max_loss = max(max_loss, loss_run)
                    else:
                        # pnl == 0: 무승부는 스트릭을 끊지 않는다
                        pass
        except Exception:
            _logger.debug("거래 이력에서 최대 스트릭 계산 실패")

    # losing_streak 피처에 누적된 역대 max_streak도 반영한다
    if losing_streak is not None:
        try:
            feature_max = int(getattr(losing_streak, "max_streak", 0))
            max_loss = max(max_loss, feature_max)
        except Exception as exc:
            _logger.debug("LosingStreak max_streak 조회 실패 (무시): %s", exc)

    try:
        return StreakData(
            current_streak=current,
            max_win_streak=max_win,
            max_loss_streak=max_loss,
        )
    except Exception:
        _logger.debug("연패 카운터 구성 실패 -- 기본값 사용")
        return StreakData()
