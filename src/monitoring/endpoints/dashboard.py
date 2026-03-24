"""F7.3 DashboardEndpoints -- 대시보드 요약 데이터를 제공하는 API이다.

포지션, PnL, 세션 상태 등을 집계하여 대시보드 프론트엔드에 전달한다.
InjectedSystem은 DI로 주입받는다.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from src.monitoring.server.auth import verify_api_key
from pydantic import BaseModel, ConfigDict, Field

from src.common.logger import get_logger
from src.common.market_clock import get_market_clock
from src.monitoring.schemas.response_models import DashboardSummaryResponse

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# InjectedSystem 레퍼런스 (DI)
_system: InjectedSystem | None = None


class PositionItem(BaseModel):
    """포지션 항목 응답 모델이다. Flutter Position.fromJson 호환."""

    ticker: str
    quantity: int
    avg_price: float
    current_price: float
    unrealized_pnl_pct: float
    unrealized_pnl: float
    current_value: float
    name: str
    exchange: str
    hold_days: int = 0
    entry_time: str = ""
    strategy: str = ""


class PositionsResponse(BaseModel):
    """포지션 목록 응답 모델이다."""

    positions: list[PositionItem] = Field(default_factory=list)
    count: int = 0


class AccountBalanceItem(BaseModel):
    """개별 계좌 잔고 응답 항목이다."""

    account_number: str = ""
    total_asset: float = 0.0
    cash: float = 0.0
    positions_count: int = 0


class AccountsResponse(BaseModel):
    """모의투자 + 실전투자 계좌 잔고 응답 모델이다."""

    virtual: AccountBalanceItem = Field(default_factory=AccountBalanceItem)
    real: AccountBalanceItem = Field(default_factory=AccountBalanceItem)


class RecentTradeItem(BaseModel):
    """개별 거래 항목 응답 모델이다. Flutter Trade.fromJson 호환."""

    model_config = ConfigDict(extra="allow")  # 추가 필드 허용

    ticker: str = ""
    action: str = ""       # buy / sell
    quantity: int = 0
    price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    reason: str = ""
    timestamp: str = ""


class RecentTradesResponse(BaseModel):
    """최근 거래 목록 응답 모델이다."""

    trades: list[RecentTradeItem] = Field(default_factory=list)
    count: int = 0


def _convert_position_dict(d: dict) -> dict:
    """PositionData.model_dump() 결과를 Flutter Position.fromJson 호환 키로 변환한다.

    pnl_pct → unrealized_pnl_pct, pnl_amount → unrealized_pnl 로 매핑하고
    hold_days, entry_time, strategy 기본값을 추가한다.
    """
    out = dict(d)
    # pnl_pct → unrealized_pnl_pct (기존 키 제거)
    if "pnl_pct" in out:
        out["unrealized_pnl_pct"] = out.pop("pnl_pct")
    # pnl_amount → unrealized_pnl (기존 키 제거)
    if "pnl_amount" in out:
        out["unrealized_pnl"] = out.pop("pnl_amount")
    # 누락 필드 기본값 보완
    out.setdefault("unrealized_pnl_pct", 0.0)
    out.setdefault("unrealized_pnl", 0.0)
    out.setdefault("hold_days", 0)
    out.setdefault("entry_time", "")
    out.setdefault("strategy", "")
    return out


def set_dashboard_deps(system: InjectedSystem) -> None:
    """InjectedSystem을 주입한다. API 서버 시작 시 호출된다."""
    global _system
    _system = system
    _logger.info("DashboardEndpoints 의존성 주입 완료")


def _build_initializing_response() -> DashboardSummaryResponse:
    """시스템 미초기화 상태의 기본 응답을 생성한다."""
    clock = get_market_clock()
    time_info = clock.get_time_info()
    kst = ZoneInfo("Asia/Seoul")
    return DashboardSummaryResponse(
        system_status="initializing",
        session_type=time_info.session_type,
        is_trading_window=time_info.is_trading_window,
        current_kst=time_info.now_kst.isoformat(),
        timestamp=datetime.now(kst).isoformat(),
    )


async def _build_summary_response(system: InjectedSystem) -> DashboardSummaryResponse:
    """시스템 상태 기반 대시보드 요약 응답을 생성한다.

    PositionMonitor에서 실시간 포지션을 조회하고, 브로커에서 잔고를 가져온다.
    Flutter DashboardSummary.fromJson이 기대하는 모든 필드를 채운다.
    외부 호출 실패 시 빈 데이터로 폴백한다.
    """
    from src.executor.broker.kis_api import fetch_balance, fetch_buy_power

    time_info = system.components.clock.get_time_info()
    status = "running" if system.running else "stopped"

    positions: list[dict] = []
    daily_pnl: float = 0.0
    total_equity: float = 0.0
    cash: float = 0.0
    positions_value: float = 0.0
    active_positions: int = 0
    account_number: str = ""
    buying_power: float = 0.0

    # 포지션 데이터 조회
    try:
        pos_monitor = system.features.get("position_monitor")
        if pos_monitor is not None:
            all_positions = pos_monitor.get_all_positions()
            positions = [_convert_position_dict(p.model_dump()) for p in all_positions.values()]
            active_positions = len(all_positions)
            daily_pnl = sum(
                (p.current_price - p.avg_price) * p.quantity
                for p in all_positions.values()
            )
            positions_value = pos_monitor.get_total_value()
    except Exception as exc:
        _logger.warning("포지션 데이터 조회 실패: %s", exc)

    # 브로커 잔고에서 현금 및 총자산을 조회한다
    broker = system.components.broker
    http = getattr(broker, "_http", None)
    try:
        if http is not None:
            balance = await fetch_balance(broker.virtual_auth, http)
            cash = balance.available_cash
            total_equity = balance.total_equity
            account_str = getattr(broker.virtual_auth, "_account", "")
            account_number = (
                f"****{account_str[4:]}" if len(account_str) > 4 else account_str
            )
            # 가용현금 0이면 매수가능금액 API(캐시)로 보완한다
            if cash <= 0:
                try:
                    cached_bp = await system.components.cache.read("dashboard:buy_power")
                    if cached_bp is not None:
                        cash = float(cached_bp)
                    else:
                        cash = await fetch_buy_power(broker.virtual_auth, http)
                        await system.components.cache.write(
                            "dashboard:buy_power", str(cash), ttl=60,
                        )
                except Exception:
                    _logger.debug("매수가능금액 조회 실패 (무시)")
            buying_power = cash

            # PositionMonitor가 비어있으면 브로커 잔고의 포지션 데이터를 사용한다
            if active_positions == 0 and balance.positions:
                active_positions = len(balance.positions)
                positions = [_convert_position_dict(p.model_dump()) for p in balance.positions]
                daily_pnl = sum(
                    (p.current_price - p.avg_price) * p.quantity
                    for p in balance.positions
                )
                positions_value = sum(
                    p.current_price * p.quantity for p in balance.positions
                )
        else:
            # http가 없으면 포지션 평가액만 사용한다
            total_equity = positions_value
    except Exception as exc:
        _logger.warning("브로커 잔고 조회 실패: %s", exc)
        total_equity = positions_value

    # today_pnl_pct 계산: 총 자산 대비 일일 수익률
    today_pnl_pct: float = 0.0
    if total_equity != 0 and daily_pnl != 0:
        base = total_equity - daily_pnl
        if base > 0:
            today_pnl_pct = (daily_pnl / base) * 100

    # 미실현 손익 (보유 포지션 합산)
    unrealized_pnl: float = daily_pnl  # 현재 일일 PnL = 미실현 손익
    unrealized_pnl_pct: float = today_pnl_pct

    # 초기 자본 추정: 총 자산 - 미실현 손익
    initial_capital: float = max(total_equity - unrealized_pnl, 0.0)

    # 전체 수익 = 누적 실현 + 미실현 (현재는 미실현만)
    total_pnl: float = unrealized_pnl
    total_pnl_pct: float = (
        (total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0
    )

    kst = ZoneInfo("Asia/Seoul")
    return DashboardSummaryResponse(
        system_status=status,
        session_type=time_info.session_type,
        is_trading_window=time_info.is_trading_window,
        current_kst=time_info.now_kst.isoformat(),
        timestamp=datetime.now(kst).isoformat(),
        positions=positions,
        daily_pnl=daily_pnl,
        total_equity=total_equity,
        # Flutter 호환 필드
        total_asset=total_equity,
        cash=cash,
        today_pnl=daily_pnl,
        today_pnl_pct=round(today_pnl_pct, 4),
        cumulative_return=0.0,
        active_positions=active_positions,
        account_number=account_number,
        positions_value=positions_value,
        buying_power=buying_power,
        # Flutter DashboardSummary 추가 필드
        unrealized_pnl=round(unrealized_pnl, 2),
        unrealized_pnl_pct=round(unrealized_pnl_pct, 4),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl_pct, 4),
        initial_capital=round(initial_capital, 2),
        currency="USD",
    )


@dashboard_router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(_auth: str = Depends(verify_api_key)) -> DashboardSummaryResponse:
    """대시보드 요약 데이터를 반환한다."""
    if _system is None:
        _logger.debug("시스템 미초기화 -- 기본 응답 반환")
        return _build_initializing_response()

    return await _build_summary_response(_system)


@dashboard_router.get("/positions", response_model=PositionsResponse)
async def get_positions(mode: str | None = None, _auth: str = Depends(verify_api_key)) -> PositionsResponse:
    """현재 보유 포지션 목록을 반환한다.

    1차: PositionMonitor(인메모리)에서 실시간 포지션을 가져온다.
    2차: 비어있으면 브로커 잔고 API(fetch_balance)에서 직접 조회한다.
    mode 파라미터는 향후 virtual/real 전환 지원을 위해 수신하지만
    현재는 단일 모드로 동작한다.
    """
    if _system is None:
        _logger.debug("시스템 미초기화 -- 빈 포지션 반환")
        return PositionsResponse(positions=[], count=0)
    try:
        items: list[PositionItem] = []

        # 1차: PositionMonitor에서 실시간 포지션을 가져온다
        pos_monitor = _system.features.get("position_monitor")
        if pos_monitor is not None:
            all_positions = pos_monitor.get_all_positions()
            for ticker, pos in all_positions.items():
                try:
                    pos_data = (
                        pos.model_dump() if hasattr(pos, "model_dump") else dict(pos)
                    )
                    avg = float(pos_data.get("avg_price", 0.0))
                    qty = int(pos_data.get("quantity", 0))
                    current = float(pos_data.get("current_price", avg))
                    pnl_amount = (current - avg) * qty
                    pnl_pct = ((current - avg) / avg * 100) if avg > 0 else 0.0
                    items.append(
                        PositionItem(
                            ticker=ticker,
                            quantity=qty,
                            avg_price=avg,
                            current_price=current,
                            unrealized_pnl_pct=round(pnl_pct, 4),
                            unrealized_pnl=round(pnl_amount, 2),
                            current_value=round(current * qty, 2),
                            name=pos_data.get("name", ticker),
                            exchange=pos_data.get("exchange", ""),
                        )
                    )
                except Exception as exc:
                    _logger.warning("포지션 변환 실패 (%s): %s", ticker, exc)

        # 2차: PositionMonitor가 비어있으면 브로커 API에서 직접 조회한다
        if not items:
            items = await _fetch_positions_from_broker()

        return PositionsResponse(positions=items, count=len(items))
    except Exception:
        _logger.exception("포지션 목록 조회 실패")
        raise HTTPException(status_code=500, detail="포지션 조회 실패") from None


async def _fetch_positions_from_broker() -> list[PositionItem]:
    """브로커 잔고 API에서 포지션 목록을 직접 조회한다.

    PositionMonitor가 비활성(대시보드 전용 모드)일 때 폴백으로 사용한다.
    fetch_balance의 PositionData를 PositionItem으로 변환한다.
    """
    if _system is None:
        return []
    from src.executor.broker.kis_api import fetch_balance

    broker = _system.components.broker
    http = getattr(broker, "_http", None)
    if http is None:
        return []

    items: list[PositionItem] = []
    try:
        balance = await fetch_balance(broker.virtual_auth, http)
        for pos in balance.positions:
            avg = pos.avg_price
            qty = pos.quantity
            current = pos.current_price
            pnl_amount = (current - avg) * qty
            pnl_pct = ((current - avg) / avg * 100) if avg > 0 else 0.0
            items.append(
                PositionItem(
                    ticker=pos.ticker,
                    quantity=qty,
                    avg_price=avg,
                    current_price=current,
                    unrealized_pnl_pct=round(pnl_pct, 4),
                    unrealized_pnl=round(pnl_amount, 2),
                    current_value=round(current * qty, 2),
                    name=pos.ticker,
                    exchange="NASD",
                )
            )
        _logger.info("브로커 API에서 포지션 %d개 직접 조회 성공", len(items))
    except Exception as exc:
        _logger.warning("브로커 포지션 직접 조회 실패: %s", exc)
    return items


@dashboard_router.get("/accounts", response_model=AccountsResponse)
async def get_accounts_summary(_auth: str = Depends(verify_api_key)) -> AccountsResponse:
    """모의투자와 실전투자 두 계좌의 잔고 요약을 반환한다.

    브로커의 virtual_auth / real_auth로 각각 잔고를 조회하여
    Flutter 대시보드의 듀얼 계좌 카드에 필요한 데이터를 제공한다.
    한쪽 계좌 조회 실패 시 해당 계좌만 기본값으로 반환한다.
    """
    if _system is None:
        _logger.warning("시스템 미초기화 -- 빈 계좌 응답 반환 (DI 주입 확인 필요)")
        raise HTTPException(status_code=503, detail="시스템 초기화 중")

    from src.executor.broker.kis_api import fetch_balance, fetch_buy_power

    broker = _system.components.broker
    http = getattr(broker, "_http", None)

    if http is None:
        _logger.error(
            "BrokerClient._http가 None이다. "
            "broker 타입=%s, hasattr(_http)=%s",
            type(broker).__name__,
            hasattr(broker, "_http"),
        )
        raise HTTPException(
            status_code=503,
            detail="HTTP 클라이언트 미초기화 (broker._http is None)",
        )

    # 가상 계좌 잔고 조회
    virtual_item = AccountBalanceItem()
    try:
        account_str = getattr(broker.virtual_auth, "_account", "")
        # 계좌번호 마스킹: 앞 4자리 숨김 (예: ****7255-01)
        masked = f"****{account_str[4:]}" if len(account_str) > 4 else account_str
        balance = await fetch_balance(broker.virtual_auth, http)
        cash = balance.available_cash
        # 가상 계좌에서 가용현금 0이면 매수가능금액 API(캐시)로 보완 시도한다
        if cash <= 0:
            try:
                cached_bp = await _system.components.cache.read("dashboard:buy_power")
                if cached_bp is not None:
                    cash = float(cached_bp)
                else:
                    cash = await fetch_buy_power(broker.virtual_auth, http)
                    await _system.components.cache.write(
                        "dashboard:buy_power", str(cash), ttl=60,
                    )
            except Exception as bp_err:
                _logger.debug(
                    "가상 매수가능금액 조회 실패 (무시): %s",
                    getattr(bp_err, "detail", str(bp_err)),
                )
        virtual_item = AccountBalanceItem(
            account_number=masked,
            total_asset=balance.total_equity,
            cash=cash,
            positions_count=len(balance.positions),
        )
        _logger.info(
            "가상 계좌 잔고 조회 성공: total=%.2f, cash=%.2f, pos=%d",
            balance.total_equity,
            cash,
            len(balance.positions),
        )
    except Exception as e:
        detail = getattr(e, "detail", None) or str(e)
        _logger.exception("가상 계좌 잔고 조회 실패: %s", detail)

    # 실전 계좌 잔고 조회
    real_item = AccountBalanceItem()
    try:
        account_str = getattr(broker.real_auth, "_account", "")
        masked = f"****{account_str[4:]}" if len(account_str) > 4 else account_str
        balance = await fetch_balance(broker.real_auth, http)
        real_item = AccountBalanceItem(
            account_number=masked,
            total_asset=balance.total_equity,
            cash=balance.available_cash,
            positions_count=len(balance.positions),
        )
        _logger.info(
            "실전 계좌 잔고 조회 성공: total=%.2f, cash=%.2f, pos=%d",
            balance.total_equity,
            balance.available_cash,
            len(balance.positions),
        )
    except Exception:
        _logger.exception("실전 계좌 잔고 조회 실패 (스택 트레이스 포함)")

    return AccountsResponse(virtual=virtual_item, real=real_item)


@dashboard_router.get("/trades/recent", response_model=RecentTradesResponse)
async def get_recent_trades(limit: int = Query(default=10, ge=1, le=100), _auth: str = Depends(verify_api_key)) -> RecentTradesResponse:
    """최근 체결 거래 목록을 반환한다.

    trades:today에서 당일 거래를 읽어 Dart Trade.fromJson 호환 키로 변환한다.
    """
    if _system is None:
        return RecentTradesResponse(trades=[], count=0)
    try:
        cache = _system.components.cache
        raw = await cache.read_json("trades:today")
        raw_list: list = raw if isinstance(raw, list) else []
        # 최신순 정렬 후 limit 적용
        sorted_list = sorted(
            raw_list,
            key=lambda t: str(t.get("timestamp", "")) if isinstance(t, dict) else "",
            reverse=True,
        )[:limit]
        # Dart Trade.fromJson 호환 키로 변환하여 RecentTradeItem을 생성한다
        trades: list[RecentTradeItem] = []
        for idx, tr in enumerate(sorted_list):
            if not isinstance(tr, dict):
                continue
            d: dict = dict(tr)
            # side → action 키 변환
            if "side" in d and "action" not in d:
                d["action"] = d.pop("side")
            d.setdefault("id", idx + 1)
            # pnl_pct 역산: avg = price - pnl/qty, pnl_pct = pnl/(avg*qty)*100
            if "pnl_pct" not in d:
                pnl = d.get("pnl")
                price = d.get("price", 0)
                qty = d.get("quantity", 0)
                if pnl is not None and price > 0 and qty > 0:
                    cost_basis = price * qty - pnl
                    d["pnl_pct"] = (pnl / cost_basis) * 100.0 if abs(cost_basis) > 1e-9 else 0.0
                else:
                    d["pnl_pct"] = 0.0
            d.setdefault("pnl", 0.0)
            d.setdefault("reason", "")
            d.setdefault("timestamp", "")
            trades.append(RecentTradeItem(**d))
        return RecentTradesResponse(trades=trades, count=len(trades))
    except Exception:
        _logger.exception("최근 거래 조회 실패")
        raise HTTPException(status_code=500, detail="거래 조회 실패") from None
