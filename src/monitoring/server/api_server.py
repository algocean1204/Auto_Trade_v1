"""F7.1 ApiServer -- FastAPI 앱을 생성하고 라우터를 등록한다.

CORS, 글로벌 예외 핸들러, 모든 도메인 라우터를 설정한다.
InjectedSystem 주입 후 uvicorn으로 서빙한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.common.error_handler import register_exception_handlers
from src.common.logger import get_logger
from src.monitoring.endpoints.agents import (
    agents_router,
    set_agents_deps,
)
from src.monitoring.endpoints.alerts import alerts_router, set_alerts_deps
from src.monitoring.endpoints.charts import charts_router, set_charts_deps
from src.monitoring.endpoints.crawl_control import (
    crawl_control_router,
    set_crawl_control_deps,
)
from src.monitoring.endpoints.feedback import (
    feedback_router,
    set_feedback_deps,
)
from src.monitoring.endpoints.reports import reports_router, set_reports_deps
from src.monitoring.endpoints.strategy import set_strategy_deps, strategy_router
from src.monitoring.endpoints.analysis import analysis_router, set_analysis_deps
from src.monitoring.endpoints.benchmark import benchmark_router, set_benchmark_deps
from src.monitoring.endpoints.dashboard import (
    dashboard_router,
    set_dashboard_deps,
)
from src.monitoring.endpoints.emergency import emergency_router, set_emergency_deps
from src.monitoring.endpoints.indicator_crawler import (
    indicator_crawler_router,
    set_indicator_crawler_deps,
)
from src.monitoring.endpoints.indicators import (
    indicators_router,
    set_indicators_deps,
)
from src.monitoring.endpoints.macro import macro_router, set_macro_deps
from src.monitoring.endpoints.manual_trade import (
    manual_trade_router,
    set_manual_trade_deps,
)
from src.monitoring.endpoints.news import news_router, set_news_deps
from src.monitoring.endpoints.order_flow import (
    order_flow_router,
    set_order_flow_deps,
)
from src.monitoring.endpoints.performance import (
    performance_router,
    set_performance_deps,
)
from src.monitoring.endpoints.principles import (
    principles_router,
    set_principles_deps,
)
from src.monitoring.endpoints.system import (
    set_system_deps,
    system_router,
)
from src.monitoring.endpoints.trade_reasoning import (
    set_trade_reasoning_deps,
    trade_reasoning_router,
)
from src.monitoring.endpoints.trading_control import (
    set_trading_control_deps,
    trading_control_router,
)
from src.monitoring.endpoints.universe import (
    set_universe_deps,
    universe_router,
)
from src.monitoring.endpoints.tax import set_tax_deps, tax_router
from src.monitoring.endpoints.fx import set_fx_deps, fx_router
from src.monitoring.endpoints.slippage import set_slippage_deps, slippage_router
from src.monitoring.endpoints.profit_target import (
    set_profit_target_deps,
    profit_target_router,
)
from src.monitoring.endpoints.risk import set_risk_deps, risk_router
from src.monitoring.schedulers.fx_scheduler import FxScheduler
from src.monitoring.websocket.ws_manager import set_ws_deps, ws_router

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# 모듈 레벨 스케줄러 레퍼런스 -- inject_system()에서 생성, startup 이벤트에서 시작한다
_fx_scheduler: FxScheduler | None = None


def _configure_cors(app: FastAPI) -> None:
    """CORS 미들웨어를 설정한다. 개발 편의를 위해 전체 허용한다."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _register_routes(app: FastAPI) -> None:
    """모든 도메인 라우터를 앱에 등록한다."""
    routers = [
        dashboard_router,
        trading_control_router,
        system_router,
        analysis_router,
        macro_router,
        news_router,
        universe_router,
        emergency_router,
        benchmark_router,
        trade_reasoning_router,
        indicators_router,
        manual_trade_router,
        principles_router,
        agents_router,
        performance_router,
        order_flow_router,
        indicator_crawler_router,
        strategy_router,           # /api/strategy/* (전략 파라미터)
        feedback_router,           # /api/feedback/* (일별/주별/최신 피드백)
        charts_router,             # /api/dashboard/charts/* (차트 데이터)
        alerts_router,             # /api/alerts/* (알림 목록/읽음 처리)
        crawl_control_router,      # /api/crawl/* (뉴스 수동 크롤링)
        reports_router,            # /api/reports/* (일별 거래 리포트)
        tax_router,                # /api/tax/* (세금 현황/리포트/손실수확)
        fx_router,                 # /api/fx/* (환율 현황/이력)
        slippage_router,           # /api/slippage/* (슬리피지 통계/최적시간)
        profit_target_router,      # /api/target/* (수익 목표 현황/이력/추정)
        risk_router,               # /api/risk/* (리스크 대시보드)
        ws_router,
    ]
    for router in routers:
        app.include_router(router)
    _logger.info("라우터 등록 완료 (%d개)", len(routers))


def create_app() -> FastAPI:
    """FastAPI 앱을 생성한다. 미들웨어와 라우터를 설정한다."""
    app = FastAPI(
        title="Stock Trading AI System V2",
        version="2.0.0",
        description="AI 자동매매 시스템 모니터링 API",
    )
    _configure_cors(app)
    register_exception_handlers(app)
    _register_routes(app)
    _logger.info("FastAPI 앱 생성 완료")
    return app


def inject_system(app: FastAPI, system: InjectedSystem) -> None:
    """InjectedSystem을 모든 엔드포인트에 주입한다.

    create_app() 이후, start_server() 이전에 호출해야 한다.
    """
    # 기존 3개 엔드포인트
    set_dashboard_deps(system)
    set_trading_control_deps(system)
    set_system_deps(system)
    # 신규 13개 엔드포인트 + WebSocket
    set_analysis_deps(system)
    set_macro_deps(system)
    set_news_deps(system)
    set_universe_deps(system)
    set_emergency_deps(system)
    set_benchmark_deps(system)
    set_trade_reasoning_deps(system)
    set_indicators_deps(system)
    set_manual_trade_deps(system)
    set_principles_deps(system)
    set_agents_deps(system)
    set_performance_deps(system)
    set_order_flow_deps(system)
    set_indicator_crawler_deps(system)
    # 신규 4개 엔드포인트 모듈
    set_strategy_deps(system)
    set_feedback_deps(system)
    set_charts_deps(system)
    # 배치2: 알림 / 크롤링 제어 / 리포트
    set_alerts_deps(system)
    set_crawl_control_deps(system)
    set_reports_deps(system)
    # 배치1 신규 5개 엔드포인트 (Tax / FX / Slippage / ProfitTarget / Risk)
    set_tax_deps(system)
    set_fx_deps(system)
    set_slippage_deps(system)
    set_profit_target_deps(system)
    set_risk_deps(system)
    set_ws_deps(system)
    _logger.info("모든 엔드포인트에 InjectedSystem 주입 완료 (30개)")

    # 백그라운드 스케줄러 등록 -- 서버 startup 이벤트에서 시작한다
    global _fx_scheduler
    _fx_scheduler = FxScheduler(system)

    @app.on_event("startup")
    async def _start_background_schedulers() -> None:
        """서버 시작 시 백그라운드 스케줄러와 FRED 캐시를 초기화한다."""
        if _fx_scheduler is not None:
            _fx_scheduler.start()
            _logger.info("FxScheduler 백그라운드 태스크 등록 완료")

        # FRED 거시지표 캐시가 비어 있으면 채운다 (대시보드 즉시 표시용)
        try:
            from src.indicators.misc.fred_fetcher import (
                is_fred_cache_populated,
                populate_fred_cache,
            )
            cache = system.components.cache
            if not await is_fred_cache_populated(cache):
                http = system.components.http
                vault = system.components.vault
                count = await populate_fred_cache(http, vault, cache)
                _logger.info("FRED 거시지표 캐시 초기화: %d건", count)
            else:
                _logger.info("FRED 캐시 이미 존재 -- 건너뜀")
        except Exception as exc:
            _logger.warning("FRED 캐시 초기화 실패 (무시): %s", exc)

    @app.on_event("shutdown")
    async def _stop_background_schedulers() -> None:
        """서버 종료 시 백그라운드 스케줄러를 정리한다."""
        if _fx_scheduler is not None:
            await _fx_scheduler.stop()
            _logger.info("FxScheduler 백그라운드 태스크 정리 완료")


_ALLOWED_PORTS: list[int] = [9500, 9501, 9502, 9503, 9504, 9505]
_PORT_FILE: str = "data/server_port.txt"


def _is_port_available(port: int) -> bool:
    """포트가 사용 가능한지 확인한다."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _find_available_port() -> int | None:
    """9500-9505 범위에서 사용 가능한 첫 번째 포트를 반환한다. 없으면 None이다."""
    for port in _ALLOWED_PORTS:
        if _is_port_available(port):
            return port
    return None


def _write_port_file(port: int) -> None:
    """서버 포트를 파일에 기록한다. Flutter에서 읽어 접속한다."""
    from pathlib import Path
    Path(_PORT_FILE).parent.mkdir(exist_ok=True)
    Path(_PORT_FILE).write_text(str(port))
    _logger.info("포트 파일 기록: %s → %d", _PORT_FILE, port)


def _remove_port_file() -> None:
    """서버 종료 시 포트 파일을 삭제한다."""
    from pathlib import Path
    try:
        Path(_PORT_FILE).unlink(missing_ok=True)
    except Exception:
        pass


async def start_server(
    app: FastAPI,
    host: str = "0.0.0.0",
    port: int | None = None,
) -> None:
    """API 서버를 시작한다. 9500-9505 범위에서 빈 포트를 자동 탐색한다.

    port를 명시하면 해당 포트만 시도한다.
    port가 None이면 9500-9505 범위에서 사용 가능한 첫 포트를 선택한다.
    선택된 포트를 data/server_port.txt에 기록하여 Flutter가 접속할 수 있게 한다.
    """
    import uvicorn

    if port is not None:
        # 명시적 포트 지정 시 해당 포트만 사용한다
        if port not in _ALLOWED_PORTS:
            _logger.warning("포트 %d는 허용 범위(9500-9505) 밖이다. 그래도 시도한다.", port)
        selected_port = port
    else:
        selected_port = _find_available_port()
        if selected_port is None:
            _logger.error(
                "포트 9500-9505 모두 사용 중이다. 서버를 시작할 수 없다.",
            )
            raise SystemExit(1)

    _logger.info("API 서버 시작: http://%s:%d", host, selected_port)
    _write_port_file(selected_port)

    config = uvicorn.Config(
        app,
        host=host,
        port=selected_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        _remove_port_file()
