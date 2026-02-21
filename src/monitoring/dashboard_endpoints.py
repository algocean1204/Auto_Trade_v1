"""
Flutter 대시보드용 대시보드/차트/전략/알림/세금/환율/슬리피지/리포트 API 엔드포인트.

대시보드 요약, 차트 데이터(일간 수익, 누적 수익, 히트맵, 드로우다운),
알림, 일간 리포트, 전략 파라미터, 슬리피지, 세금/환율 엔드포인트를 제공한다.

시스템 상태는 system_endpoints.py, 에이전트 관리는 agent_endpoints.py에 분리.

엔드포인트 목록:
  GET  /dashboard/summary                     - 메인 대시보드 요약
  GET  /dashboard/positions                   - 현재 보유 포지션 목록
  GET  /dashboard/trades/recent               - 최근 완료 거래 목록
  GET  /dashboard/charts/daily-returns         - 일간 PnL 차트
  GET  /dashboard/charts/cumulative            - 누적 PnL 차트
  GET  /dashboard/charts/heatmap/ticker        - 티커별 히트맵
  GET  /dashboard/charts/heatmap/hourly        - 시간대별 히트맵
  GET  /dashboard/charts/drawdown              - 드로우다운 차트
  GET  /alerts                                 - 알림 목록
  GET  /alerts/unread-count                    - 미읽은 알림 수
  POST /alerts/{alert_id}/read                 - 알림 읽음 처리
  GET  /strategy/params                        - 전략 파라미터 조회
  POST /strategy/params                        - 전략 파라미터 수정
  GET  /tax/status                             - 세금 현황
  GET  /tax/report/{year}                      - 연간 세금 보고서
  GET  /tax/harvest-suggestions                - 세금 손실 확정 매도 후보
  GET  /fx/status                              - 환율 정보
  GET  /fx/effective-return/{trade_id}         - 환율 포함 실질수익률
  GET  /fx/history                             - 환율 이력
  GET  /slippage/stats                         - 슬리피지 통계
  GET  /slippage/optimal-hours                 - 최적 체결 시간대
  GET  /reports/daily                          - 일간 리포트
  GET  /reports/daily/list                     - 리포트 날짜 목록
  GET  /strategy/ticker-params                 - 전체 종목별 파라미터 요약
  GET  /strategy/ticker-params/{ticker}        - 단일 종목 상세 파라미터
  POST /strategy/ticker-params/{ticker}/override - 유저 오버라이드 설정
  DELETE /strategy/ticker-params/{ticker}/override - 유저 오버라이드 제거
  POST /strategy/ticker-params/ai-optimize     - AI 재분석 트리거
"""

from __future__ import annotations

import asyncio
import json
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select

from src.db.connection import get_session
from src.db.models import FeedbackReport, Trade
from src.monitoring.alert import AlertManager
from src.monitoring.auth import verify_api_key
from src.monitoring.daily_report import DailyReportGenerator
from src.monitoring.schemas import (
    DashboardSummary,
    StrategyParamsUpdateRequest,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 프로젝트 루트의 strategy_params.json 절대 경로
_STRATEGY_PARAMS_PATH: Path = Path(__file__).resolve().parents[2] / "strategy_params.json"

# 백그라운드 태스크 참조 집합 — GC 방지를 위해 태스크를 보관한다.
_background_tasks: set[asyncio.Task] = set()

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# api_server.py 가 startup 시 set_dashboard_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}

# 싱글턴 헬퍼
_alert_manager = AlertManager()
_report_generator = DailyReportGenerator()


def set_dashboard_deps(
    position_monitor: Any = None,
    strategy_params: Any = None,
    safety_checker: Any = None,
    fallback_router: Any = None,
    kis_client: Any = None,
    tax_tracker: Any = None,
    fx_manager: Any = None,
    slippage_tracker: Any = None,
    startup_time: float = 0.0,
    virtual_kis_client: Any = None,
    real_kis_client: Any = None,
    position_monitors: dict | None = None,
    ticker_params_manager: Any = None,
    historical_team: Any = None,
) -> None:
    """런타임 의존성을 주입한다.

    api_server.py 의 set_dependencies() 호출 시 함께 호출되어야 한다.

    Args:
        position_monitor: 기본 모드 포지션 모니터 인스턴스.
        strategy_params: 전략 파라미터 인스턴스.
        safety_checker: 안전 체커 인스턴스.
        fallback_router: 폴백 라우터 인스턴스.
        kis_client: 기본 모드 KIS API 클라이언트 인스턴스.
        tax_tracker: 세금 추적기 인스턴스.
        fx_manager: 환율 관리자 인스턴스.
        slippage_tracker: 슬리피지 추적기 인스턴스.
        startup_time: 서버 시작 시각 (monotonic). system_endpoints에도 전달한다.
        virtual_kis_client: 모의투자 전용 KIS 클라이언트.
        real_kis_client: 실전투자 전용 KIS 클라이언트.
        position_monitors: 모드별 포지션 모니터 딕셔너리 {"virtual": ..., "real": ...}.
        ticker_params_manager: 종목별 AI 최적화 파라미터 관리자 인스턴스.
        historical_team: 과거분석팀/종목분석팀 인스턴스.
    """
    _deps.update({
        "position_monitor": position_monitor,
        "strategy_params": strategy_params,
        "safety_checker": safety_checker,
        "fallback_router": fallback_router,
        "kis_client": kis_client,
        "tax_tracker": tax_tracker,
        "fx_manager": fx_manager,
        "slippage_tracker": slippage_tracker,
        "virtual_kis_client": virtual_kis_client,
        "real_kis_client": real_kis_client,
        "position_monitors": position_monitors or {},
        "ticker_params_manager": ticker_params_manager,
        "historical_team": historical_team,
    })
    # system_endpoints 의존성도 함께 주입한다
    from src.monitoring.system_endpoints import set_system_deps
    set_system_deps(
        safety_checker=safety_checker,
        fallback_router=fallback_router,
        kis_client=kis_client,
        startup_time=startup_time,
    )


def _get(name: str) -> Any:
    """의존성을 조회한다. 없으면 503을 반환한다."""
    dep = _deps.get(name)
    if dep is None:
        raise HTTPException(
            status_code=503,
            detail=f"Service '{name}' is not available",
        )
    return dep


def _try_get(name: str) -> Any | None:
    """의존성을 조회한다. 없으면 None을 반환한다 (503 대신)."""
    return _deps.get(name)


def _get_monitor(mode: str | None = None) -> Any | None:
    """mode에 해당하는 PositionMonitor를 반환한다.

    mode가 None이면 KIS_MODE 환경변수(기본 모드)를 사용한다.
    해당 모드의 모니터가 없으면 기본 모니터(position_monitor)를 반환한다.

    Args:
        mode: "virtual" 또는 "real". None이면 기본 설정 모드를 사용한다.

    Returns:
        PositionMonitor 인스턴스 또는 None.
    """
    if mode is None:
        from src.utils.config import get_settings
        mode = get_settings().kis_mode

    monitors: dict = _deps.get("position_monitors") or {}
    monitor = monitors.get(mode)
    if monitor is not None:
        return monitor

    # 명시적 모드 모니터가 없으면 기본 모니터를 반환한다.
    return _deps.get("position_monitor")


def _get_kis_client(mode: str | None = None) -> Any | None:
    """mode에 해당하는 KISClient를 반환한다.

    mode가 None이면 KIS_MODE 환경변수(기본 모드)를 사용한다.

    Args:
        mode: "virtual" 또는 "real". None이면 기본 설정 모드를 사용한다.

    Returns:
        KISClient 인스턴스 또는 None.
    """
    if mode is None:
        from src.utils.config import get_settings
        mode = get_settings().kis_mode

    if mode == "virtual":
        client = _deps.get("virtual_kis_client")
    else:
        client = _deps.get("real_kis_client")

    if client is not None:
        return client

    # 명시적 모드 클라이언트가 없으면 기본 클라이언트를 반환한다.
    return _deps.get("kis_client")


def _mask_account(raw_account: str | None) -> str:
    """계좌번호를 마스킹하여 반환한다.

    "50167255-01" -> "****7255-01" 형태로 변환한다.

    Args:
        raw_account: 원본 계좌번호 문자열.

    Returns:
        마스킹된 계좌번호. 유효하지 않으면 "****0000-01" 반환.
    """
    if not raw_account or not isinstance(raw_account, str) or "-" not in raw_account:
        return "****0000-01"
    number_part, product_part = raw_account.split("-", 1)
    masked = f"****{number_part[-4:]}"
    return f"{masked}-{product_part}"


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

dashboard_router = APIRouter(tags=["dashboard"])


# ===================================================================
# Dashboard endpoints
# ===================================================================


@dashboard_router.get("/dashboard/accounts")
async def get_accounts() -> dict:
    """모의투자 + 실전투자 계좌 잔액을 한번에 반환한다.

    각 모드의 잔고를 동시에 조회하여 통합 계좌 현황을 반환한다.
    모드별 KISClient가 없으면 해당 항목은 None으로 반환된다.

    Returns:
        모드별 잔액 정보::

            {
                "virtual": {
                    "total_asset": float,
                    "cash": float,
                    "positions_count": int,
                    "account_number": str,
                },
                "real": {
                    "total_asset": float,
                    "cash": float,
                    "positions_count": int,
                    "account_number": str,
                },
                "default_mode": str,
            }
    """
    from src.utils.config import get_settings
    settings = get_settings()

    async def _fetch_account_info(mode: str) -> dict | None:
        """특정 모드의 계좌 정보를 조회한다.

        Args:
            mode: "virtual" 또는 "real".

        Returns:
            계좌 정보 딕셔너리 또는 None (클라이언트 없음).
        """
        monitor = _get_monitor(mode)
        kis = _get_kis_client(mode)
        if monitor is None and kis is None:
            return None

        # 계좌번호 마스킹
        account_number = "****0000-01"
        try:
            if kis is not None:
                auth_obj = getattr(kis, "auth", None)
                raw_account = getattr(auth_obj, "account", None) if auth_obj is not None else None
                account_number = _mask_account(raw_account)
        except Exception as acc_exc:
            logger.debug("계좌번호 마스킹 실패 (mode=%s): %s", mode, acc_exc)

        # 포트폴리오 요약 조회
        total_asset = 0.0
        cash = 0.0
        positions_count = 0

        if monitor is not None:
            try:
                portfolio = await monitor.get_portfolio_summary()
                total_asset = portfolio.get("total_value", 0.0)
                cash = portfolio.get("cash", 0.0)
                positions_count = portfolio.get("position_count", 0)
            except Exception as exc:
                logger.warning("포트폴리오 조회 실패 (mode=%s): %s", mode, exc)

        return {
            "total_asset": round(total_asset, 2),
            "cash": round(cash, 2),
            "positions_count": positions_count,
            "account_number": account_number,
        }

    import asyncio
    virtual_info, real_info = await asyncio.gather(
        _fetch_account_info("virtual"),
        _fetch_account_info("real"),
        return_exceptions=False,
    )

    return {
        "virtual": virtual_info,
        "real": real_info,
        "default_mode": settings.kis_mode,
    }


@dashboard_router.get("/dashboard/summary", response_model=DashboardSummary)
async def get_summary(
    mode: str | None = Query(default=None, description="계좌 모드: 'virtual' 또는 'real'. 미지정 시 기본 모드(KIS_MODE) 사용."),
) -> DashboardSummary:
    """메인 대시보드 요약 데이터를 반환한다.

    총자산, 당일 PnL, 누적 수익, 활성 포지션 수, 시스템 상태를 포함한다.

    Args:
        mode: 계좌 모드. "virtual"(모의투자) 또는 "real"(실전투자).
              미지정 시 KIS_MODE 환경변수 기준 기본 모드를 사용한다.
    """
    monitor = _get_monitor(mode)
    safety = _try_get("safety_checker")

    if monitor is not None:
        try:
            portfolio = await monitor.get_portfolio_summary()
        except Exception as exc:
            logger.warning("포트폴리오 요약 조회 실패 (mode=%s): %s", mode, exc)
            portfolio = {"total_value": 0.0, "cash": 0.0, "position_count": 0}
    else:
        portfolio = {"total_value": 0.0, "cash": 0.0, "position_count": 0}

    # Today's PnL from trades
    today_pnl = 0.0
    today_pnl_pct = 0.0
    try:
        async with get_session() as session:
            today_start = datetime.now(tz=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            stmt = select(
                func.coalesce(func.sum(Trade.pnl_amount), 0.0),
            ).where(
                and_(
                    Trade.exit_at >= today_start,
                    Trade.exit_price.isnot(None),
                )
            )
            result = await session.execute(stmt)
            today_pnl = float(result.scalar_one())
    except Exception as exc:
        logger.warning("Failed to compute today PnL: %s", exc)

    total_asset = portfolio.get("total_value", 0.0)
    if total_asset > 0:
        today_pnl_pct = round((today_pnl / total_asset) * 100, 2)

    # Cumulative return from all closed trades
    cumulative_return = 0.0
    try:
        async with get_session() as session:
            stmt = select(
                func.coalesce(func.sum(Trade.pnl_amount), 0.0)
            ).where(Trade.exit_price.isnot(None))
            result = await session.execute(stmt)
            cumulative_return = float(result.scalar_one())
    except Exception as exc:
        logger.warning("Failed to compute cumulative return: %s", exc)

    system_status = "NORMAL"
    if safety is not None:
        status = safety.get_safety_status()
        system_status = status.get("grade", "NORMAL")

    cash = portfolio.get("cash", 0.0)
    positions_value = max(total_asset - cash, 0.0)

    # 모드에 맞는 KIS 클라이언트에서 계좌번호를 조회한다.
    account_number = "****0000-01"
    try:
        kis = _get_kis_client(mode)
        if kis is not None:
            auth_obj = getattr(kis, "auth", None)
            raw_account = getattr(auth_obj, "account", None) if auth_obj is not None else None
            account_number = _mask_account(raw_account)
    except Exception as acc_exc:
        logger.debug("계좌번호 마스킹 실패: %s", acc_exc)

    return DashboardSummary(
        total_asset=total_asset,
        cash=cash,
        today_pnl=today_pnl,
        today_pnl_pct=today_pnl_pct,
        cumulative_return=cumulative_return,
        active_positions=portfolio.get("position_count", 0),
        system_status=system_status,
        timestamp=datetime.now(tz=timezone.utc),
        positions_value=round(positions_value, 2),
        buying_power=round(cash, 2),
        currency="USD",
        account_number=account_number,
    )


@dashboard_router.get("/dashboard/positions")
async def get_positions(
    mode: str | None = Query(default=None, description="계좌 모드: 'virtual' 또는 'real'. 미지정 시 기본 모드(KIS_MODE) 사용."),
) -> list[dict]:
    """현재 보유 중인 포지션 목록을 반환한다.

    1) 인메모리 모니터에서 포지션을 조회한다.
    2) 포지션이 비어 있으면 KIS 잔고 API에서 직접 조회한다.
    3) 그것도 실패하거나 없으면 DB에서 미청산 거래(exit_price IS NULL)를 조회한다.

    Args:
        mode: 계좌 모드. "virtual"(모의투자) 또는 "real"(실전투자).
              미지정 시 KIS_MODE 환경변수 기준 기본 모드를 사용한다.
    """
    # 1. 인메모리 포지션 시도
    monitor = _get_monitor(mode)
    if monitor is not None:
        positions = monitor.get_all_positions()
        if positions:
            return positions

    # 2. KIS 잔고 API에서 포지션 조회 시도
    kis = _get_kis_client(mode)
    if kis is not None:
        try:
            balance = await kis.get_balance()
            kis_positions = balance.get("positions", [])
            if kis_positions:
                for pos in kis_positions:
                    pos["current_value"] = round(
                        pos.get("current_price", 0) * pos.get("quantity", 0), 2
                    )
                return kis_positions
        except Exception as exc:
            logger.warning("KIS 잔고 조회 실패 (mode=%s): %s", mode, exc)

    # 3. Fallback: DB에서 미청산 거래를 조회한다.
    try:
        async with get_session() as session:
            stmt = (
                select(Trade)
                .where(Trade.exit_price.is_(None))
                .order_by(Trade.entry_at.desc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": row.id,
                    "ticker": row.ticker,
                    "direction": row.direction,
                    "entry_price": row.entry_price,
                    "entry_at": row.entry_at.isoformat() if row.entry_at else None,
                    "ai_confidence": row.ai_confidence,
                    "market_regime": row.market_regime,
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get positions: %s", exc)
        return []


@dashboard_router.get("/dashboard/trades/recent")
async def get_recent_trades(
    limit: int = Query(default=10, ge=1, le=100),
) -> list[dict]:
    """최근 완료된 거래 목록을 반환한다.

    청산 완료된 거래(exit_price IS NOT NULL)를 최근 순으로 조회한다.
    """
    try:
        async with get_session() as session:
            stmt = (
                select(Trade)
                .where(Trade.exit_price.isnot(None))
                .order_by(Trade.exit_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": row.id,
                    "ticker": row.ticker,
                    "direction": row.direction,
                    "entry_price": row.entry_price,
                    "exit_price": row.exit_price,
                    "entry_at": row.entry_at.isoformat() if row.entry_at else None,
                    "exit_at": row.exit_at.isoformat() if row.exit_at else None,
                    "pnl_pct": round(float(row.pnl_pct), 4) if row.pnl_pct is not None else None,
                    "pnl_amount": round(float(row.pnl_amount), 2) if row.pnl_amount is not None else None,
                    "hold_minutes": row.hold_minutes,
                    "exit_reason": row.exit_reason,
                    "ai_confidence": row.ai_confidence,
                    "market_regime": row.market_regime,
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get recent trades: %s", exc)
        return []


@dashboard_router.get("/dashboard/charts/daily-returns")
async def get_daily_returns(days: int = Query(default=30, ge=1, le=365)) -> list[dict]:
    """일간 PnL 차트 데이터를 반환한다."""
    try:
        async with get_session() as session:
            since = datetime.now(tz=timezone.utc) - timedelta(days=days)
            stmt = (
                select(
                    func.date(Trade.exit_at).label("trade_date"),
                    func.coalesce(func.sum(Trade.pnl_amount), 0.0).label("pnl_amount"),
                    func.coalesce(func.avg(Trade.pnl_pct), 0.0).label("pnl_pct"),
                    func.count(Trade.id).label("trade_count"),
                )
                .where(
                    and_(
                        Trade.exit_at >= since,
                        Trade.exit_price.isnot(None),
                    )
                )
                .group_by(func.date(Trade.exit_at))
                .order_by(func.date(Trade.exit_at))
            )
            result = await session.execute(stmt)
            rows = result.all()

            return [
                {
                    "date": str(row.trade_date),
                    "pnl_amount": round(float(row.pnl_amount), 2),
                    "pnl_pct": round(float(row.pnl_pct), 4),
                    "trade_count": int(row.trade_count),
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get daily returns: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/dashboard/charts/cumulative")
async def get_cumulative() -> list[dict]:
    """누적 PnL 곡선을 반환한다."""
    try:
        async with get_session() as session:
            # 초기 자본금 조회: RiskConfig 테이블 참조, 실패 시 10,000 USD 기본값 사용
            from src.db.models import RiskConfig
            initial_capital = 10_000.0
            try:
                from sqlalchemy import select as sa_select
                stmt_capital = sa_select(RiskConfig).where(
                    RiskConfig.param_key == "initial_capital"
                )
                result_capital = await session.execute(stmt_capital)
                config = result_capital.scalar_one_or_none()
                if config:
                    initial_capital = float(config.param_value)
            except Exception as cap_exc:
                logger.debug("초기 자본금 조회 실패, 기본값 사용: %s", cap_exc)

            stmt = (
                select(
                    func.date(Trade.exit_at).label("trade_date"),
                    func.coalesce(func.sum(Trade.pnl_amount), 0.0).label("daily_pnl"),
                )
                .where(Trade.exit_price.isnot(None))
                .group_by(func.date(Trade.exit_at))
                .order_by(func.date(Trade.exit_at))
            )
            result = await session.execute(stmt)
            rows = result.all()

            cumulative = 0.0
            data: list[dict] = []
            for row in rows:
                cumulative += float(row.daily_pnl)
                cumulative_pct = (cumulative / initial_capital * 100) if initial_capital > 0 else 0.0
                data.append({
                    "date": str(row.trade_date),
                    "cumulative_pnl": round(cumulative, 2),
                    "cumulative_pct": round(cumulative_pct, 2),
                })
            return data
    except Exception as exc:
        logger.error("Failed to get cumulative chart: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/dashboard/charts/heatmap/ticker")
async def get_ticker_heatmap(
    days: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    """티커별 PnL 히트맵 데이터를 반환한다 (X: 날짜, Y: 티커, color: pnl_pct)."""
    try:
        async with get_session() as session:
            since = datetime.now(tz=timezone.utc) - timedelta(days=days)
            stmt = (
                select(
                    func.date(Trade.exit_at).label("trade_date"),
                    Trade.ticker,
                    func.coalesce(func.avg(Trade.pnl_pct), 0.0).label("avg_pnl_pct"),
                )
                .where(
                    and_(
                        Trade.exit_at >= since,
                        Trade.exit_price.isnot(None),
                    )
                )
                .group_by(func.date(Trade.exit_at), Trade.ticker)
                .order_by(func.date(Trade.exit_at))
            )
            result = await session.execute(stmt)
            rows = result.all()

            return [
                {
                    "x": str(row.trade_date),
                    "y": row.ticker,
                    "value": round(float(row.avg_pnl_pct), 4),
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get ticker heatmap: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/dashboard/charts/heatmap/hourly")
async def get_hourly_heatmap() -> list[dict]:
    """시간대별 성과 히트맵을 반환한다 (X: 시간, Y: 요일, color: avg pnl_pct)."""
    try:
        async with get_session() as session:
            stmt = (
                select(
                    func.extract("hour", Trade.exit_at).label("hour"),
                    func.extract("dow", Trade.exit_at).label("dow"),
                    func.coalesce(func.avg(Trade.pnl_pct), 0.0).label("avg_pnl_pct"),
                )
                .where(Trade.exit_price.isnot(None))
                .group_by(
                    func.extract("hour", Trade.exit_at),
                    func.extract("dow", Trade.exit_at),
                )
            )
            result = await session.execute(stmt)
            rows = result.all()

            weekday_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            return [
                {
                    "x": f"{int(row.hour):02d}:00",
                    "y": weekday_names[int(row.dow)],
                    "value": round(float(row.avg_pnl_pct), 4),
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get hourly heatmap: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/dashboard/charts/drawdown")
async def get_drawdown() -> list[dict]:
    """드로우다운 차트 데이터를 반환한다 (최대 고점 대비 하락)."""
    try:
        async with get_session() as session:
            stmt = (
                select(
                    func.date(Trade.exit_at).label("trade_date"),
                    func.coalesce(func.sum(Trade.pnl_amount), 0.0).label("daily_pnl"),
                )
                .where(Trade.exit_price.isnot(None))
                .group_by(func.date(Trade.exit_at))
                .order_by(func.date(Trade.exit_at))
            )
            result = await session.execute(stmt)
            rows = result.all()

            cumulative = 0.0
            peak = 0.0
            data: list[dict] = []
            for row in rows:
                cumulative += float(row.daily_pnl)
                if cumulative > peak:
                    peak = cumulative
                dd = peak - cumulative
                dd_pct = (dd / peak * 100) if peak > 0 else 0.0
                data.append({
                    "date": str(row.trade_date),
                    "peak": round(peak, 2),
                    "current": round(cumulative, 2),
                    "drawdown_pct": round(dd_pct, 2),
                })
            return data
    except Exception as exc:
        logger.error("Failed to get drawdown chart: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ===================================================================
# Strategy endpoints
# ===================================================================


async def _read_strategy_file() -> dict:
    """strategy_params.json 파일을 비동기로 읽는다.

    블로킹 파일 I/O를 asyncio.to_thread로 감싸 이벤트 루프를 차단하지 않는다.

    Returns:
        파싱된 전략 파라미터 딕셔너리. 파일 읽기 실패 시 빈 딕셔너리를 반환한다.
    """
    def _read() -> dict:
        with open(_STRATEGY_PARAMS_PATH, "r") as f:
            return json.load(f)

    try:
        return await asyncio.to_thread(_read)
    except Exception as exc:
        logger.debug("strategy_params.json 파일 로드 실패 (%s): %s", _STRATEGY_PARAMS_PATH, exc)
        return {}


@dashboard_router.get("/strategy/params")
async def get_strategy_params() -> dict:
    """현재 전략 파라미터와 레짐 설정을 반환한다."""
    sp = _try_get("strategy_params")
    if sp is None:
        params = await _read_strategy_file()
        return {"params": params, "regimes": {}}
    from src.strategy.params import REGIMES
    return {
        "params": sp.to_dict(),
        "regimes": REGIMES,
    }


@dashboard_router.post("/strategy/params")
async def update_strategy_params(
    body: StrategyParamsUpdateRequest,
    _: None = Depends(verify_api_key),
) -> dict:
    """전략 파라미터를 업데이트한다."""
    sp = _get("strategy_params")
    errors: list[str] = []
    updated: dict[str, Any] = {}

    for name, value in body.params.items():
        try:
            sp.set_param(name, value)
            updated[name] = value
        except KeyError as exc:
            errors.append(str(exc))

    if errors:
        raise HTTPException(
            status_code=400,
            detail=f"Parameter errors: {'; '.join(errors)}",
        )
    return {"status": "ok", "updated": updated, "params": sp.to_dict()}


# ===================================================================
# Alert endpoints
# ===================================================================


@dashboard_router.get("/alerts")
async def get_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    alert_type: str | None = None,
    severity: str | None = None,
) -> list[dict]:
    """최근 알림 목록을 반환한다. 타입/심각도 필터링을 지원한다."""
    return await _alert_manager.get_recent_alerts(
        limit=limit, alert_type=alert_type, severity=severity
    )


@dashboard_router.get("/alerts/unread-count")
async def get_unread_count() -> dict:
    """미읽은 알림 수를 반환한다."""
    count = await _alert_manager.get_unread_count()
    return {"unread_count": count}


@dashboard_router.post("/alerts/{alert_id}/read")
async def mark_alert_read(
    alert_id: str,
    _: None = Depends(verify_api_key),
) -> dict:
    """특정 알림을 읽음으로 표시한다."""
    success = await _alert_manager.mark_as_read(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "ok"}


# ===================================================================
# Tax endpoints
# ===================================================================


@dashboard_router.get("/tax/status")
async def get_tax_status() -> dict:
    """현재 연도 세금 현황을 반환한다."""
    tracker = _try_get("tax_tracker")
    if tracker is None:
        return {
            "year": _date.today().year,
            "summary": {},
            "remaining_exemption": {
                "exemption_krw": 2_500_000,
                "used_krw": 0.0,
                "remaining_krw": 2_500_000,
                "utilization_pct": 0.0,
            },
        }
    try:
        year = _date.today().year
        summary = await tracker.get_yearly_summary(year)
        remaining = await tracker.get_remaining_exemption(year)
        return {
            "year": year,
            "summary": summary,
            "remaining_exemption": remaining,
        }
    except Exception as exc:
        logger.error("Failed to get tax status: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/tax/report/{year}")
async def get_tax_report(year: int) -> dict:
    """연간 세금 보고서를 반환한다."""
    tracker = _get("tax_tracker")
    try:
        summary = await tracker.get_yearly_summary(year)
        remaining = await tracker.get_remaining_exemption(year)
        return {
            "year": year,
            "summary": summary,
            "remaining_exemption": remaining,
        }
    except Exception as exc:
        logger.error("Failed to get tax report for %d: %s", year, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/tax/harvest-suggestions")
async def get_tax_harvest_suggestions() -> list[dict]:
    """세금 손실 확정 매도 후보 포지션을 반환한다."""
    tracker = _get("tax_tracker")
    monitor = _get("position_monitor")
    try:
        portfolio = await monitor.get_portfolio_summary()
        positions = portfolio.get("positions", [])
        suggestions = await tracker.suggest_tax_loss_harvest(positions)
        return suggestions
    except Exception as exc:
        logger.error("Failed to get tax harvest suggestions: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ===================================================================
# FX endpoints
# ===================================================================


@dashboard_router.get("/fx/status")
async def get_fx_status() -> dict:
    """현재 환율 정보를 반환한다."""
    fm = _try_get("fx_manager")
    if fm is None:
        return {"usd_krw_rate": 0.0, "timestamp": datetime.now(tz=timezone.utc).isoformat()}
    try:
        rate = await fm.fetch_current_rate()
        return {
            "usd_krw_rate": rate,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Failed to get FX status: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/fx/effective-return/{trade_id}")
async def get_fx_effective_return(trade_id: str) -> dict:
    """특정 거래의 환율 포함 실질수익률을 반환한다."""
    fm = _get("fx_manager")
    try:
        result = await fm.get_effective_return(trade_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to get effective return for %s: %s", trade_id, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/fx/history")
async def get_fx_history(
    days: int = Query(default=30, ge=1, le=365),
) -> list[dict]:
    """환율 이력을 반환한다."""
    fm = _get("fx_manager")
    try:
        history = await fm.get_fx_history(days=days)
        return history
    except Exception as exc:
        logger.error("Failed to get FX history: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ===================================================================
# Slippage endpoints
# ===================================================================


@dashboard_router.get("/slippage/stats")
async def get_slippage_stats(
    ticker: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """슬리피지 통계를 반환한다."""
    st = _try_get("slippage_tracker")
    if st is None:
        return {"avg_slippage_pct": 0.0, "total_trades": 0, "stats_by_ticker": {}}
    try:
        stats = await st.get_stats(ticker=ticker, days=days)
        return stats
    except Exception as exc:
        logger.error("Failed to get slippage stats: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/slippage/optimal-hours")
async def get_slippage_optimal_hours(
    ticker: str = Query(..., min_length=1, max_length=10),
) -> dict:
    """특정 종목의 최적 체결 시간대를 반환한다."""
    st = _try_get("slippage_tracker")
    if st is None:
        return {"ticker": ticker, "optimal_hours": [], "data_points": 0}
    try:
        result = await st.get_optimal_execution_time(ticker)
        return result
    except Exception as exc:
        logger.error("Failed to get optimal hours for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ===================================================================
# Daily report endpoint
# ===================================================================


@dashboard_router.get("/reports/daily")
async def get_daily_report(
    date_str: str | None = Query(default=None, alias="date"),
) -> dict:
    """일간 성과 리포트를 생성하거나 조회한다."""
    return await _report_generator.generate(target_date=date_str)


@dashboard_router.get("/reports/daily/list")
async def list_report_dates(limit: int = Query(default=30, ge=1, le=365)) -> dict:
    """날짜별 일간 리포트 목록을 반환한다."""
    try:
        async with get_session() as session:
            stmt = (
                select(FeedbackReport.report_date, FeedbackReport.id)
                .where(FeedbackReport.report_type == "daily_performance")
                .order_by(FeedbackReport.report_date.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            dates = [
                {"date": str(row.report_date), "id": str(row.id)}
                for row in result
            ]
        return {"dates": dates}
    except Exception as exc:
        logger.error("Failed to list report dates: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


# ===================================================================
# Ticker-level strategy params endpoints
# ===================================================================


@dashboard_router.get("/strategy/ticker-params")
async def get_all_ticker_params() -> dict:
    """전체 종목별 파라미터 요약을 반환한다.

    각 종목의 유효 파라미터, AI 추천 여부, 유저 오버라이드 여부,
    리스크 등급, 섹터 정보를 포함한다.
    """
    tpm = _try_get("ticker_params_manager")
    if tpm is None:
        return {"tickers": {}, "total_count": 0, "with_ai": 0, "with_override": 0}
    try:
        return tpm.get_all_ticker_params()
    except Exception as exc:
        logger.error("Failed to get all ticker params: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.get("/strategy/ticker-params/{ticker}")
async def get_ticker_params_detail(ticker: str) -> dict:
    """단일 종목의 상세 파라미터를 반환한다.

    AI 분석 결과, 추천 파라미터, 유저 오버라이드, 글로벌 기본값,
    각 파라미터의 출처(source)를 포함한다.

    Args:
        ticker: 종목 티커 심볼.
    """
    tpm = _try_get("ticker_params_manager")
    if tpm is None:
        raise HTTPException(
            status_code=503,
            detail="TickerParamsManager가 초기화되지 않았습니다.",
        )
    try:
        return tpm.get_ticker_detail(ticker.upper())
    except Exception as exc:
        logger.error("Failed to get ticker params for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.post("/strategy/ticker-params/{ticker}/override")
async def set_ticker_override(
    ticker: str,
    body: dict,
    _: None = Depends(verify_api_key),
) -> dict:
    """유저가 특정 종목의 파라미터를 오버라이드한다.

    body에 오버라이드할 파라미터를 딕셔너리로 전달한다.
    허용 키: take_profit_pct, stop_loss_pct, trailing_stop_pct,
    min_confidence, max_position_pct, max_hold_days, eod_close.

    Args:
        ticker: 종목 티커 심볼.
        body: 오버라이드할 파라미터 딕셔너리.
    """
    tpm = _try_get("ticker_params_manager")
    if tpm is None:
        raise HTTPException(
            status_code=503,
            detail="TickerParamsManager가 초기화되지 않았습니다.",
        )
    try:
        effective = tpm.set_user_override(ticker.upper(), body)
        return {
            "status": "ok",
            "ticker": ticker.upper(),
            "effective": effective,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to set ticker override for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.delete("/strategy/ticker-params/{ticker}/override")
async def clear_ticker_override(
    ticker: str,
    param_name: str | None = Query(default=None, description="특정 파라미터 키. 미지정 시 전체 오버라이드 제거."),
    _: None = Depends(verify_api_key),
) -> dict:
    """유저 오버라이드를 제거한다 (AI 추천값으로 복귀).

    param_name이 지정되면 해당 키만 제거하고,
    미지정이면 전체 오버라이드를 제거한다.

    Args:
        ticker: 종목 티커 심볼.
        param_name: 특정 파라미터 키 (선택).
    """
    tpm = _try_get("ticker_params_manager")
    if tpm is None:
        raise HTTPException(
            status_code=503,
            detail="TickerParamsManager가 초기화되지 않았습니다.",
        )
    try:
        effective = tpm.clear_user_override(ticker.upper(), param_name)
        return {
            "status": "ok",
            "ticker": ticker.upper(),
            "cleared_param": param_name or "all",
            "effective": effective,
        }
    except Exception as exc:
        logger.error("Failed to clear ticker override for %s: %s", ticker, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@dashboard_router.post("/strategy/ticker-params/ai-optimize")
async def trigger_ai_optimization(
    _: None = Depends(verify_api_key),
) -> dict:
    """AI 재분석을 수동으로 트리거한다.

    전체 활성 유니버스 종목을 대상으로 AI 파라미터 최적화를 실행한다.
    비동기로 실행되며 즉시 응답 후 백그라운드에서 완료된다.
    """
    tpm = _try_get("ticker_params_manager")
    if tpm is None:
        raise HTTPException(
            status_code=503,
            detail="TickerParamsManager가 초기화되지 않았습니다.",
        )

    kis = _get_kis_client()
    if kis is None:
        raise HTTPException(
            status_code=503,
            detail="KIS 클라이언트가 초기화되지 않았습니다.",
        )

    async def _run_optimization() -> None:
        """백그라운드에서 AI 최적화를 실행한다."""
        try:
            await tpm.ai_optimize_all(kis)
        except Exception as exc:
            logger.error("AI 종목별 최적화 백그라운드 실행 실패: %s", exc)

    # 태스크 참조를 보관하여 GC에 의한 조기 소멸을 방지한다.
    task = asyncio.create_task(_run_optimization())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {
        "status": "started",
        "message": "AI 종목별 파라미터 최적화가 백그라운드에서 시작되었습니다.",
    }


# ═══════════════════════════════════════════════════════════════════
# 과거분석팀 / 종목분석팀 엔드포인트
# ═══════════════════════════════════════════════════════════════════


@dashboard_router.get(
    "/analysis/historical/progress",
    responses={503: {"description": "과거분석팀이 초기화되지 않음"}},
)
async def get_historical_progress() -> dict:
    """과거 분석 진행 상태를 조회한다.

    Returns:
        진행 상태 (모드, 완료 주 수, 진행률, 현재 분석 중인 주간 등).
    """
    team = _deps.get("historical_team")
    if team is None:
        # 의존성 미주입 시에도 DB에서 직접 조회 시도
        try:
            from src.db.models import HistoricalAnalysisProgress
            from sqlalchemy import desc, select, func

            async with get_session() as session:
                stmt = (
                    select(HistoricalAnalysisProgress)
                    .order_by(desc(HistoricalAnalysisProgress.updated_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                progress = result.scalar_one_or_none()

                # 분석된 총 레코드 수 조회
                from src.db.models import HistoricalAnalysis
                count_stmt = select(func.count()).select_from(HistoricalAnalysis)
                count_result = await session.execute(count_stmt)
                total_records = count_result.scalar() or 0

                if progress:
                    from datetime import date as _d
                    _start = _d(2021, 1, 4)
                    _today = _d.today()
                    total_weeks = max(1, (_today - _start).days // 7)
                    analyzed = progress.total_weeks_analyzed
                    pct = min(100.0, round((analyzed / total_weeks) * 100, 1))
                    return {
                        "mode": progress.mode,
                        "running": False,
                        "current_week": None,
                        "last_completed_week": progress.last_completed_week.isoformat(),
                        "total_weeks_analyzed": analyzed,
                        "total_weeks_needed": total_weeks,
                        "progress_pct": pct,
                        "status": progress.status,
                        "start_date": _start.isoformat(),
                        "total_records": total_records,
                    }
                return {
                    "mode": "historical",
                    "running": False,
                    "status": "not_started",
                    "total_weeks_analyzed": 0,
                    "progress_pct": 0.0,
                    "total_records": total_records,
                }
        except Exception as exc:
            logger.warning("과거분석 진행 상태 직접 조회 실패: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="과거분석팀이 초기화되지 않았습니다.",
            )

    return await team.get_progress()


@dashboard_router.get(
    "/analysis/historical/timeline/{ticker}",
    responses={503: {"description": "과거분석팀이 초기화되지 않음"}},
)
async def get_ticker_timeline(
    ticker: str,
    weeks: int = Query(default=12, ge=1, le=52, description="조회할 주 수"),
) -> dict:
    """종목의 과거 분석 타임라인을 조회한다.

    Args:
        ticker: 종목 티커 심볼.
        weeks: 조회할 최근 주 수 (기본 12주, 최대 52주).

    Returns:
        해당 종목의 주간별 분석 결과 목록.
    """
    team = _deps.get("historical_team")
    if team is None:
        # 의존성 미주입 시 DB에서 직접 조회
        try:
            from src.db.models import HistoricalAnalysis
            from sqlalchemy import desc, select

            async with get_session() as session:
                stmt = (
                    select(HistoricalAnalysis)
                    .where(HistoricalAnalysis.ticker == ticker.upper())
                    .order_by(desc(HistoricalAnalysis.week_start))
                    .limit(weeks)
                )
                result = await session.execute(stmt)
                analyses = result.scalars().all()

                timeline = [
                    {
                        "week_start": a.week_start.isoformat(),
                        "week_end": a.week_end.isoformat(),
                        "sector": a.sector,
                        "timeline_events": a.timeline_events,
                        "market_context": a.market_context,
                        "analyst_notes": a.analyst_notes,
                        "analysis_quality": a.analysis_quality,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                    }
                    for a in reversed(analyses)
                ]
                return {"ticker": ticker.upper(), "weeks": weeks, "timeline": timeline}
        except Exception as exc:
            logger.warning("종목 타임라인 직접 조회 실패: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="과거분석팀이 초기화되지 않았습니다.",
            )

    timeline = await team.get_ticker_timeline(ticker.upper(), weeks)
    return {"ticker": ticker.upper(), "weeks": weeks, "timeline": timeline}


