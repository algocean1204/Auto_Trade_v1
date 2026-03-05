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
    agents_compat_router,
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
    feedback_compat_router,
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
        agents_compat_router,      # Flutter /agents/* 하드코딩 경로 호환
        performance_router,
        order_flow_router,
        indicator_crawler_router,
        strategy_router,           # /api/strategy/* (전략 파라미터)
        feedback_router,           # /api/feedback/* (일별/최신 피드백)
        feedback_compat_router,    # /feedback/* (주별/pending Flutter TODO 경로)
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
        """서버 시작 시 백그라운드 스케줄러를 기동한다."""
        if _fx_scheduler is not None:
            _fx_scheduler.start()
            _logger.info("FxScheduler 백그라운드 태스크 등록 완료")

    @app.on_event("shutdown")
    async def _stop_background_schedulers() -> None:
        """서버 종료 시 백그라운드 스케줄러를 정리한다."""
        if _fx_scheduler is not None:
            await _fx_scheduler.stop()
            _logger.info("FxScheduler 백그라운드 태스크 정리 완료")


async def start_server(
    app: FastAPI,
    host: str = "0.0.0.0",
    port: int = 9501,
    max_retries: int = 5,
) -> None:
    """API 서버를 시작한다. 포트 충돌 시 재시도한다.

    LaunchAgent KeepAlive 환경에서 이전 프로세스의 포트 해제가
    지연될 수 있으므로 EADDRINUSE 발생 시 대기 후 재시도한다.
    """
    import asyncio

    import uvicorn

    for attempt in range(1, max_retries + 1):
        _logger.info(
            "API 서버 시작 시도 %d/%d: http://%s:%d",
            attempt, max_retries, host, port,
        )
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        try:
            await server.serve()
            return  # 정상 종료 (shutdown_event에 의한 종료)
        except SystemExit as exc:
            # uvicorn이 포트 바인드 실패 시 SystemExit(1)을 발생시킨다
            if attempt < max_retries:
                wait_sec = attempt * 3
                _logger.warning(
                    "포트 %d 바인드 실패 (시도 %d/%d). %d초 후 재시도한다.",
                    port, attempt, max_retries, wait_sec,
                )
                await asyncio.sleep(wait_sec)
            else:
                _logger.error(
                    "포트 %d 바인드 실패 -- %d회 재시도 모두 실패. 서버를 시작할 수 없다.",
                    port, max_retries,
                )
                raise
