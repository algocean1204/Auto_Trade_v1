"""
FastAPI monitoring backend for AI Trading System V2.

Provides REST endpoints for the Flutter dashboard (charts, indicators,
strategy configuration, feedback, universe management, crawling, system
status) and WebSocket channels for real-time position/trade/crawl updates.

Based on Thinking.md Addendum 3.5 + 9.3 + 11.3.

이 모듈은 FastAPI 앱 인스턴스, 라이프사이클, 미들웨어, WebSocket 엔드포인트,
의존성 주입 허브만 담당한다. 모든 REST 엔드포인트는 개별 라우터 모듈에
분산되어 있다.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    FastAPI,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.db.connection import close_db, get_redis, init_db
from src.monitoring.alert import AlertManager
from src.monitoring.agent_endpoints import agent_router
from src.monitoring.analysis_endpoints import router as analysis_router
from src.monitoring.analysis_endpoints import set_analysis_deps
from src.monitoring.benchmark_endpoints import benchmark_router, set_benchmark_deps
from src.monitoring.dashboard_endpoints import dashboard_router, set_dashboard_deps
from src.monitoring.emergency_endpoints import emergency_router, set_emergency_deps
from src.monitoring.indicator_endpoints import indicator_router, set_indicator_deps
from src.monitoring.macro_endpoints import router as macro_router, set_macro_deps
from src.monitoring.news_collect_endpoints import news_collect_router, set_news_collect_deps
from src.monitoring.news_endpoints import router as news_router
from src.monitoring.principles_endpoints import principles_router
from src.monitoring.schemas import ErrorResponse
from src.monitoring.system_endpoints import system_router
from src.monitoring.trade_endpoints import trade_router, set_trade_deps
from src.monitoring.trade_reasoning_endpoints import trade_reasoning_router
from src.monitoring.trading_control_endpoints import trading_control_router
from src.monitoring.trading_control_endpoints import set_trading_control_deps
from src.monitoring.universe_endpoints import universe_router, set_universe_deps
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

_HEALTH_CHECK_SLEEP: float = 2.0

# WebSocket Redis Pub/Sub 메시지 수신 타임아웃 (초)
_PUBSUB_TIMEOUT: float = 1.0

# WebSocket Redis Pub/Sub 폴링 딜레이 (초)
_PUBSUB_POLL_SLEEP: float = 0.1

# WebSocket 크롤 진행 상황 폴링 딜레이 (초)
_WS_CRAWL_POLL_SLEEP: float = 0.2

# WebSocket 지표 스트림 폴링 딜레이 (초)
_WS_INDICATOR_POLL_SLEEP: float = 0.1

# ---------------------------------------------------------------------------
# Global service registry -- populated at startup via set_dependencies()
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}


def set_dependencies(
    position_monitor: Any = None,
    universe_manager: Any = None,
    weights_manager: Any = None,
    strategy_params: Any = None,
    safety_checker: Any = None,
    fallback_router: Any = None,
    crawl_engine: Any = None,
    kis_client: Any = None,
    claude_client: Any = None,
    classifier: Any = None,
    emergency_protocol: Any = None,
    capital_guard: Any = None,
    account_safety: Any = None,
    tax_tracker: Any = None,
    fx_manager: Any = None,
    slippage_tracker: Any = None,
    benchmark_comparison: Any = None,
    telegram_notifier: Any = None,
    profit_target_manager: Any = None,
    risk_gate_pipeline: Any = None,
    risk_budget: Any = None,
    risk_backtester: Any = None,
    indicator_crawler: Any = None,
    virtual_kis_client: Any = None,
    real_kis_client: Any = None,
    position_monitors: dict | None = None,
    trading_system: Any = None,
    account_mode_manager: Any = None,
    ticker_params_manager: Any = None,
    historical_team: Any = None,
) -> None:
    """Inject runtime dependencies from the main application.

    Must be called before the app starts serving requests. All parameters
    are optional -- missing dependencies will cause the corresponding
    endpoints to return 503.

    Args:
        position_monitor: 기본 모드 포지션 모니터 (기존 호환성 유지).
        virtual_kis_client: 모의투자 전용 KIS 클라이언트.
        real_kis_client: 실전투자 전용 KIS 클라이언트.
        position_monitors: 모드별 포지션 모니터 딕셔너리 {"virtual": ..., "real": ...}.
        trading_system: TradingSystem 인스턴스 (자동매매 시작/중지 제어용).
        account_mode_manager: AccountModeManager 인스턴스 (듀얼 모드 계정 관리).
        ticker_params_manager: 종목별 AI 최적화 파라미터 관리자 인스턴스.
        historical_team: 과거분석팀/종목분석팀 인스턴스.
    """
    _deps.update({
        "position_monitor": position_monitor,
        "universe_manager": universe_manager,
        "weights_manager": weights_manager,
        "strategy_params": strategy_params,
        "safety_checker": safety_checker,
        "fallback_router": fallback_router,
        "crawl_engine": crawl_engine,
        "kis_client": kis_client,
        "claude_client": claude_client,
        "classifier": classifier,
        "emergency_protocol": emergency_protocol,
        "capital_guard": capital_guard,
        "account_safety": account_safety,
        "tax_tracker": tax_tracker,
        "fx_manager": fx_manager,
        "slippage_tracker": slippage_tracker,
        "benchmark_comparison": benchmark_comparison,
        "telegram_notifier": telegram_notifier,
        "profit_target_manager": profit_target_manager,
        "risk_gate_pipeline": risk_gate_pipeline,
        "risk_budget": risk_budget,
        "risk_backtester": risk_backtester,
        "indicator_crawler": indicator_crawler,
        # 듀얼 모드 의존성
        "virtual_kis_client": virtual_kis_client,
        "real_kis_client": real_kis_client,
        "position_monitors": position_monitors or {},
        "account_mode_manager": account_mode_manager,
        # 자동매매 제어 의존성
        "trading_system": trading_system,
        # 종목별 파라미터
        "ticker_params_manager": ticker_params_manager,
        # 과거분석팀
        "historical_team": historical_team,
    })

    # 각 라우터 모듈에 필요한 의존성을 전달한다.
    set_analysis_deps(kis_client=kis_client, claude_client=claude_client)
    set_indicator_deps(weights_manager=weights_manager, kis_client=kis_client)
    set_benchmark_deps(
        benchmark_comparison=benchmark_comparison,
        profit_target_manager=profit_target_manager,
    )
    set_dashboard_deps(
        position_monitor=position_monitor,
        strategy_params=strategy_params,
        safety_checker=safety_checker,
        fallback_router=fallback_router,
        kis_client=kis_client,
        tax_tracker=tax_tracker,
        fx_manager=fx_manager,
        slippage_tracker=slippage_tracker,
        startup_time=_startup_time,
        virtual_kis_client=virtual_kis_client,
        real_kis_client=real_kis_client,
        position_monitors=position_monitors or {},
        ticker_params_manager=ticker_params_manager,
        historical_team=historical_team,
    )
    set_universe_deps(
        universe_manager=universe_manager,
        crawl_engine=crawl_engine,
        claude_client=claude_client,
        classifier=classifier,
    )
    set_emergency_deps(
        emergency_protocol=emergency_protocol,
        position_monitor=position_monitor,
        risk_gate_pipeline=risk_gate_pipeline,
        risk_budget=risk_budget,
        risk_backtester=risk_backtester,
    )
    set_trade_deps(
        strategy_params=strategy_params,
    )
    set_macro_deps(indicator_crawler=indicator_crawler)
    set_trading_control_deps(trading_system=trading_system)
    set_news_collect_deps(
        crawl_engine=crawl_engine,
        classifier=classifier,
        claude_client=claude_client,
        telegram_notifier=telegram_notifier,
    )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_startup_time: float = 0.0

# Active WebSocket connections
_ws_position_clients: set[WebSocket] = set()
_ws_trade_clients: set[WebSocket] = set()
_ws_crawl_clients: dict[str, set[WebSocket]] = {}


def _verify_ws_token(token: str | None) -> bool:
    """WebSocket 연결용 API 키를 검증한다.

    API_SECRET_KEY가 설정되지 않은 경우(개발 환경) 모든 연결을 허용한다.
    설정된 경우 token이 일치해야 True를 반환한다.

    Args:
        token: 클라이언트가 전달한 API 키 (query param 또는 첫 메시지).

    Returns:
        인증 성공 여부.
    """
    settings = get_settings()
    secret_key = settings.api_secret_key
    if not secret_key:
        # API_SECRET_KEY 미설정: 인증 비활성화 (개발 환경)
        return True
    if token is None:
        return False
    return token == secret_key


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Startup / shutdown lifecycle handler.

    시작 시 DB 초기화와 환율 주기 갱신 태스크를 시작한다.
    종료 시 환율 주기 갱신 태스크를 중단하고 DB 연결을 닫는다.
    """
    global _startup_time
    _startup_time = time.monotonic()
    logger.info("Monitoring API server starting up")

    # DB 초기화
    try:
        await init_db()
        logger.info("Database connection verified")
    except Exception as exc:
        logger.error("Database init failed: %s", exc)

    # 환율 주기 갱신 태스크 시작
    # set_dependencies()가 lifespan 이전에 호출되는 경우를 대비해
    # _deps에서 fx_manager를 참조한다.
    fx_manager = _deps.get("fx_manager")
    if fx_manager is not None:
        try:
            fx_manager.start_periodic_update()
            logger.info("환율 주기 업데이트 태스크 등록 완료 (1시간 주기)")
        except Exception as exc:
            logger.warning("환율 주기 업데이트 태스크 등록 실패: %s", exc)
    else:
        logger.debug("fx_manager 미주입 -- 환율 주기 업데이트 건너뜀")

    # 매크로 지표 자동 크롤러 시작
    indicator_crawler = _deps.get("indicator_crawler")
    if indicator_crawler is not None:
        try:
            await indicator_crawler.start()
            logger.info("IndicatorCrawler 시작 완료 (1시간 주기 자동 크롤링)")
        except Exception as exc:
            logger.warning("IndicatorCrawler 시작 실패: %s", exc)
    else:
        logger.debug("indicator_crawler 미주입 -- 매크로 자동 크롤링 건너뜀")

    yield

    # 종료 시 매크로 지표 크롤러 중단
    indicator_crawler = _deps.get("indicator_crawler")
    if indicator_crawler is not None:
        try:
            await indicator_crawler.stop()
            logger.info("IndicatorCrawler 중단 완료")
        except Exception as exc:
            logger.warning("IndicatorCrawler 중단 실패: %s", exc)

    # 종료 시 환율 태스크 중단
    fx_manager = _deps.get("fx_manager")
    if fx_manager is not None:
        try:
            fx_manager.stop_periodic_update()
            logger.info("환율 주기 업데이트 태스크 중단 완료")
        except Exception as exc:
            logger.warning("환율 주기 업데이트 태스크 중단 실패: %s", exc)

    logger.info("Monitoring API server shutting down")
    await close_db()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Trading System V2 API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Flutter 대시보드가 다양한 포트에서 접속할 수 있으므로 모든 origin 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Router 등록
# ---------------------------------------------------------------------------

app.include_router(agent_router)
app.include_router(analysis_router)
app.include_router(benchmark_router)
app.include_router(dashboard_router)
app.include_router(emergency_router)
app.include_router(indicator_router)
app.include_router(macro_router)
app.include_router(news_collect_router)
app.include_router(news_router)
app.include_router(principles_router)
app.include_router(system_router)
app.include_router(trade_router)
app.include_router(trade_reasoning_router)
app.include_router(trading_control_router)
app.include_router(universe_router)


# ---------------------------------------------------------------------------
# Middleware: request logging
# ---------------------------------------------------------------------------

@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """금융 데이터 캐싱을 방지하는 Cache-Control 헤더를 추가한다."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Log every HTTP request and its response time."""
    start = time.monotonic()
    response = await call_next(request)
    elapsed = (time.monotonic() - start) * 1000
    logger.debug(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a unified error response."""
    logger.error(
        "Unhandled error on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            detail="내부 서버 오류가 발생했습니다. 서버 로그를 확인하세요.",
            error_code="INTERNAL_ERROR",
        ).model_dump(),
    )


# ===================================================================
# WebSocket endpoints (with authentication)
# ===================================================================


@app.websocket("/ws/positions")
async def ws_positions(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Real-time position updates (every 2 seconds).

    인증: query parameter ?token=<API_SECRET_KEY> 로 API 키를 전달한다.
    API_SECRET_KEY가 미설정인 개발 환경에서는 인증을 건너뛴다.
    """
    if not _verify_ws_token(token):
        await websocket.close(code=4001, reason="인증 실패: 유효한 API 키가 필요합니다.")
        return

    await websocket.accept()
    _ws_position_clients.add(websocket)
    logger.info("WebSocket /ws/positions connected (total=%d)", len(_ws_position_clients))

    try:
        while True:
            monitor = _deps.get("position_monitor")
            if monitor is not None:
                positions = monitor.get_all_positions()
                await websocket.send_json({
                    "type": "positions",
                    "data": positions,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                })
            await asyncio.sleep(_HEALTH_CHECK_SLEEP)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket /ws/positions error: %s", exc)
    finally:
        _ws_position_clients.discard(websocket)
        logger.info(
            "WebSocket /ws/positions disconnected (remaining=%d)",
            len(_ws_position_clients),
        )


@app.websocket("/ws/trades")
async def ws_trades(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Real-time trade execution notifications via Redis Pub/Sub.

    인증: query parameter ?token=<API_SECRET_KEY> 로 API 키를 전달한다.
    """
    if not _verify_ws_token(token):
        await websocket.close(code=4001, reason="인증 실패: 유효한 API 키가 필요합니다.")
        return

    await websocket.accept()
    _ws_trade_clients.add(websocket)
    logger.info("WebSocket /ws/trades connected (total=%d)", len(_ws_trade_clients))

    try:
        redis = get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe("monitoring:alerts:stream")

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_PUBSUB_TIMEOUT
            )
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                alert_type = data.get("alert_type", "")
                if alert_type in (
                    AlertManager.TYPE_TRADE_ENTRY,
                    AlertManager.TYPE_TRADE_EXIT,
                    AlertManager.TYPE_STOP_LOSS,
                    AlertManager.TYPE_TAKE_PROFIT,
                    AlertManager.TYPE_TRAILING_STOP,
                ):
                    await websocket.send_json({
                        "type": "trade_alert",
                        "data": data,
                    })
            await asyncio.sleep(_PUBSUB_POLL_SLEEP)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket /ws/trades error: %s", exc)
    finally:
        _ws_trade_clients.discard(websocket)
        try:
            await pubsub.unsubscribe("monitoring:alerts:stream")
            await pubsub.close()
        except Exception as exc:
            logger.debug("WebSocket /ws/trades pubsub 정리 실패: %s", exc)
        logger.info(
            "WebSocket /ws/trades disconnected (remaining=%d)",
            len(_ws_trade_clients),
        )


@app.websocket("/ws/crawl/{task_id}")
async def ws_crawl_progress(
    websocket: WebSocket,
    task_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Real-time crawl progress for a specific task via Redis Pub/Sub.

    인증: query parameter ?token=<API_SECRET_KEY> 로 API 키를 전달한다.
    """
    if not _verify_ws_token(token):
        await websocket.close(code=4001, reason="인증 실패: 유효한 API 키가 필요합니다.")
        return

    await websocket.accept()
    if task_id not in _ws_crawl_clients:
        _ws_crawl_clients[task_id] = set()
    _ws_crawl_clients[task_id].add(websocket)
    logger.info("WebSocket /ws/crawl/%s connected", task_id)

    try:
        redis = get_redis()
        pubsub = redis.pubsub()
        channel = f"crawl:progress:{task_id}"
        await pubsub.subscribe(channel)

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_PUBSUB_TIMEOUT
            )
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                await websocket.send_json({
                    "type": "crawl_progress",
                    "data": data,
                })
                # Close when crawl is done
                if data.get("status") in ("completed", "failed"):
                    break
            await asyncio.sleep(_WS_CRAWL_POLL_SLEEP)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket /ws/crawl/%s error: %s", task_id, exc)
    finally:
        if task_id in _ws_crawl_clients:
            _ws_crawl_clients[task_id].discard(websocket)
            if not _ws_crawl_clients[task_id]:
                del _ws_crawl_clients[task_id]
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception as exc:
            logger.debug("WebSocket /ws/crawl/%s pubsub 정리 실패: %s", task_id, exc)
        logger.info("WebSocket /ws/crawl/%s disconnected", task_id)


@app.websocket("/ws/alerts")
async def ws_alerts(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Real-time alert stream. Forwards all alerts via Redis Pub/Sub.

    인증: query parameter ?token=<API_SECRET_KEY> 로 API 키를 전달한다.
    """
    if not _verify_ws_token(token):
        await websocket.close(code=4001, reason="인증 실패: 유효한 API 키가 필요합니다.")
        return

    await websocket.accept()
    logger.info("WebSocket /ws/alerts connected")

    try:
        redis = get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe("monitoring:alerts:stream")

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_PUBSUB_TIMEOUT
            )
            if message and message["type"] == "message":
                data = json.loads(message["data"])
                await websocket.send_json({
                    "type": "alert",
                    "data": data,
                })
            await asyncio.sleep(_WS_INDICATOR_POLL_SLEEP)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket /ws/alerts error: %s", exc)
    finally:
        try:
            await pubsub.unsubscribe("monitoring:alerts:stream")
            await pubsub.close()
        except Exception as exc:
            logger.debug("WebSocket /ws/alerts pubsub 정리 실패: %s", exc)
        logger.info("WebSocket /ws/alerts disconnected")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check() -> dict:
    """Simple health check endpoint."""
    return {"status": "ok", "uptime": round(time.monotonic() - _startup_time, 1)}
