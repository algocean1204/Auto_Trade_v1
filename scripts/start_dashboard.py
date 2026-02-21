#!/usr/bin/env python3
"""
대시보드 전용 서버 시작 스크립트.

전체 TradingSystem을 기동하지 않고, 대시보드에 필요한 최소 의존성만
초기화한 뒤 set_dependencies()를 호출하여 uvicorn을 시작한다.

uvicorn의 lifespan 이벤트 내에서 의존성을 초기화하므로,
DB 커넥션 풀이 동일한 이벤트 루프 내에서 올바르게 작동한다.

사용법:
    .venv/bin/python scripts/start_dashboard.py
    # 또는 포트 변경:
    API_PORT=8080 .venv/bin/python scripts/start_dashboard.py
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가한다.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
os.chdir(_PROJECT_ROOT)

from dotenv import load_dotenv

# 호스트에서 직접 실행하므로 항상 .env 파일을 로드한다.
load_dotenv()

import uvicorn
from fastapi import FastAPI

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _load_or_create_auth(
    app_key: str,
    app_secret: str,
    account: str,
    virtual: bool,
    token_path: Path,
) -> "KISAuth":
    """캐시된 토큰이 유효하면 복원하고, 없으면 새 인스턴스를 생성한다."""
    from src.executor.kis_auth import KISAuth

    try:
        auth = KISAuth.from_token_cache(
            app_key=app_key,
            app_secret=app_secret,
            account=account,
            virtual=virtual,
            path=token_path,
        )
        if auth.access_token:
            logger.info("  KIS token restored from cache: %s", token_path.name)
        return auth
    except Exception as exc:
        logger.warning("  KIS token load failed, creating new instance: %s", exc)
        return KISAuth(
            app_key=app_key,
            app_secret=app_secret,
            account=account,
            virtual=virtual,
        )


async def _init_dependencies() -> None:
    """대시보드에 필요한 최소 의존성을 초기화하고 set_dependencies()를 호출한다.

    각 컴포넌트는 독립적인 try/except로 감싸져 있어,
    일부 모듈 실패 시에도 나머지 기능은 정상 동작한다 (graceful degradation).

    이 함수는 반드시 uvicorn의 이벤트 루프 내에서 호출되어야 한다.
    """
    settings = get_settings()

    # ------------------------------------------------------------------
    # 1. Database (필수 -- 대부분의 엔드포인트가 DB를 조회한다)
    # ------------------------------------------------------------------
    logger.info("[1/10] Initializing database...")
    from src.db.connection import init_db
    await init_db()
    logger.info("  Database connection established.")

    # ------------------------------------------------------------------
    # 2. KIS Client (듀얼 모드: 모의투자 + 실전투자 동시 지원)
    # ------------------------------------------------------------------
    kis_client = None          # 기존 호환성 유지용 (기본 모드 클라이언트)
    virtual_kis_client = None  # 모의투자 전용 클라이언트
    real_kis_client = None     # 실전투자 전용 클라이언트
    try:
        logger.info("[2/10] Initializing KIS API clients (dual mode)...")
        from src.executor.kis_auth import KISAuth
        from src.executor.kis_client import KISClient

        token_dir = _PROJECT_ROOT / "data"
        token_dir.mkdir(parents=True, exist_ok=True)
        virtual_token_path = token_dir / "kis_token.json"
        real_token_path = token_dir / "kis_real_token.json"

        # ------------------------------------------------------------------
        # 2-A. 실전 인증 (시세 조회 및 실전 거래 공용)
        # ------------------------------------------------------------------
        real_auth = None
        if settings.kis_real_app_key and settings.kis_real_account:
            logger.info("  Initializing real KIS auth...")
            real_auth = _load_or_create_auth(
                app_key=settings.kis_real_app_key,
                app_secret=settings.kis_real_app_secret,
                account=settings.kis_real_account,
                virtual=False,
                token_path=real_token_path,
            )
            await real_auth.get_token()
            real_auth.save_credentials(real_token_path)
            logger.info("  Real KIS auth initialized (account=%s).", settings.kis_real_account[:4] + "****")

        # ------------------------------------------------------------------
        # 2-B. 모의투자 클라이언트 (virtual 계좌 거래 + real_auth로 시세 조회)
        # ------------------------------------------------------------------
        if settings.kis_virtual_app_key and settings.kis_virtual_account:
            virtual_auth = _load_or_create_auth(
                app_key=settings.kis_virtual_app_key,
                app_secret=settings.kis_virtual_app_secret,
                account=settings.kis_virtual_account,
                virtual=True,
                token_path=virtual_token_path,
            )
            await virtual_auth.get_token()
            virtual_auth.save_credentials(virtual_token_path)
            # 모의투자 클라이언트: 거래는 virtual auth, 시세는 real_auth 사용
            virtual_kis_client = KISClient(virtual_auth, real_auth=real_auth)
            logger.info("  Virtual KIS client initialized (account=%s).", settings.kis_virtual_account[:4] + "****")

        # ------------------------------------------------------------------
        # 2-C. 실전투자 클라이언트 (real 계좌 거래 + 시세 동일 auth)
        # ------------------------------------------------------------------
        if real_auth is not None:
            real_kis_client = KISClient(real_auth)
            logger.info("  Real KIS client initialized (account=%s).", settings.kis_real_account[:4] + "****")

        # ------------------------------------------------------------------
        # 2-D. 기본 모드 클라이언트 (기존 코드 호환성 유지)
        # ------------------------------------------------------------------
        if settings.kis_mode == "virtual" and virtual_kis_client is not None:
            kis_client = virtual_kis_client
        elif settings.kis_mode == "real" and real_kis_client is not None:
            kis_client = real_kis_client
        elif virtual_kis_client is not None:
            kis_client = virtual_kis_client
        elif real_kis_client is not None:
            kis_client = real_kis_client

        logger.info(
            "  KIS clients initialized (mode=%s, virtual=%s, real=%s).",
            settings.kis_mode,
            "OK" if virtual_kis_client is not None else "N/A",
            "OK" if real_kis_client is not None else "N/A",
        )
    except Exception as exc:
        logger.warning("  KIS client init failed (price/analysis endpoints will be unavailable): %s", exc)

    # ------------------------------------------------------------------
    # 3. Claude Client
    # 호스트에서 직접 실행하므로 항상 설정값(CLAUDE_MODE)을 그대로 사용한다.
    # ------------------------------------------------------------------
    claude_client = None
    try:
        logger.info("[3/10] Initializing Claude client...")
        from src.analysis.claude_client import ClaudeClient

        effective_mode = settings.claude_mode
        claude_client = ClaudeClient(
            mode=effective_mode,
            api_key=settings.anthropic_api_key or None,
        )
        logger.info("  Claude client initialized (mode=%s).", effective_mode)
    except Exception as exc:
        logger.warning("  Claude client init failed (AI analysis will be unavailable): %s", exc)

    # ------------------------------------------------------------------
    # 4. Crawl Engine
    # ------------------------------------------------------------------
    crawl_engine = None
    try:
        logger.info("[4/10] Initializing crawl engine...")
        from src.crawler.crawl_engine import CrawlEngine

        crawl_engine = CrawlEngine()
        logger.info("  Crawl engine initialized.")
    except Exception as exc:
        logger.warning("  Crawl engine init failed (manual crawling will be unavailable): %s", exc)

    # ------------------------------------------------------------------
    # 5. Universe / Weights / Strategy
    # ------------------------------------------------------------------
    universe_manager = None
    weights_manager = None
    strategy_params = None
    try:
        logger.info("[5/10] Initializing universe, weights, strategy params...")
        from src.executor.universe_manager import UniverseManager
        from src.indicators.weights import WeightsManager
        from src.strategy.params import StrategyParams

        universe_manager = UniverseManager()
        weights_manager = WeightsManager()
        strategy_params = StrategyParams()
        logger.info("  Universe, weights, strategy params initialized.")
    except Exception as exc:
        logger.warning("  Universe/weights/strategy init failed: %s", exc)

    # ------------------------------------------------------------------
    # 6. Safety modules
    # ------------------------------------------------------------------
    safety_checker = None
    fallback_router = None
    try:
        logger.info("[6/10] Initializing safety modules...")
        from src.safety.hard_safety import HardSafety
        from src.safety.quota_guard import QuotaGuard
        from src.safety.safety_checker import SafetyChecker

        if claude_client is not None:
            quota_guard = QuotaGuard(claude_client)
            hard_safety = HardSafety()
            safety_checker = SafetyChecker(quota_guard, hard_safety)

            from src.fallback.fallback_router import FallbackRouter
            fallback_router = FallbackRouter(claude_client, quota_guard)
            logger.info("  Safety checker + fallback router initialized.")
        else:
            logger.info("  Safety modules skipped (Claude client not available).")
    except Exception as exc:
        logger.warning("  Safety modules init failed: %s", exc)

    # ------------------------------------------------------------------
    # 7. Emergency / Capital Guard / Account Safety
    # ------------------------------------------------------------------
    emergency_protocol = None
    capital_guard = None
    account_safety = None
    try:
        logger.info("[7/10] Initializing emergency/capital/account safety...")
        from src.safety.emergency_protocol import EmergencyProtocol
        from src.safety.capital_guard import CapitalGuard
        from src.safety.account_safety import AccountSafetyChecker

        emergency_protocol = EmergencyProtocol()
        capital_guard = CapitalGuard()
        account_safety = AccountSafetyChecker(kis_client=kis_client)
        logger.info("  Emergency/capital/account safety initialized.")
    except Exception as exc:
        logger.warning("  Emergency/capital/account safety init failed: %s", exc)

    # ------------------------------------------------------------------
    # 8. Tax / FX / Slippage
    # ------------------------------------------------------------------
    tax_tracker = None
    fx_manager = None
    slippage_tracker = None
    try:
        logger.info("[8/10] Initializing tax/fx/slippage...")
        from src.tax.tax_tracker import TaxTracker
        from src.tax.fx_manager import FXManager
        from src.tax.slippage_tracker import SlippageTracker

        tax_tracker = TaxTracker()
        fx_manager = FXManager(kis_client)
        slippage_tracker = SlippageTracker()
        logger.info("  Tax/FX/slippage initialized.")
    except Exception as exc:
        logger.warning("  Tax/fx/slippage init failed: %s", exc)

    # ------------------------------------------------------------------
    # 9. Benchmark / Telegram / Profit Target
    # ------------------------------------------------------------------
    benchmark_comparison = None
    telegram_notifier = None
    profit_target_manager = None
    try:
        logger.info("[9/10] Initializing benchmark/telegram/profit target...")
        from src.monitoring.benchmark import BenchmarkComparison
        from src.monitoring.telegram_notifier import TelegramNotifier
        from src.strategy.profit_target import ProfitTargetManager

        if kis_client is not None:
            benchmark_comparison = BenchmarkComparison(kis_client)
        telegram_notifier = TelegramNotifier()
        profit_target_manager = ProfitTargetManager()
        try:
            await profit_target_manager.get_monthly_target_from_db()
        except Exception as ptm_exc:
            logger.warning("  Profit target DB load failed (defaults used): %s", ptm_exc)
        logger.info("  Benchmark/telegram/profit target initialized.")
    except Exception as exc:
        logger.warning("  Benchmark/telegram/profit target init failed: %s", exc)

    # ------------------------------------------------------------------
    # 10a. PositionMonitor 듀얼 초기화 (모의투자 + 실전투자 각각 읽기 전용)
    # ------------------------------------------------------------------
    position_monitor = None       # 기존 호환성 유지용 (기본 모드)
    virtual_monitor = None        # 모의투자 전용 모니터
    real_monitor = None           # 실전투자 전용 모니터
    position_monitors: dict = {}  # 모드별 모니터 딕셔너리

    try:
        logger.info("[10a] Initializing PositionMonitor (dual read-only)...")
        from src.executor.position_monitor import PositionMonitor

        if virtual_kis_client is not None:
            virtual_monitor = PositionMonitor.create_readonly(virtual_kis_client)
            position_monitors["virtual"] = virtual_monitor
            logger.info("  Virtual PositionMonitor initialized.")

        if real_kis_client is not None:
            real_monitor = PositionMonitor.create_readonly(real_kis_client)
            position_monitors["real"] = real_monitor
            logger.info("  Real PositionMonitor initialized.")

        # 기본 모드 모니터 선택 (기존 코드 호환성)
        if settings.kis_mode == "virtual" and virtual_monitor is not None:
            position_monitor = virtual_monitor
        elif settings.kis_mode == "real" and real_monitor is not None:
            position_monitor = real_monitor
        elif virtual_monitor is not None:
            position_monitor = virtual_monitor
        elif real_monitor is not None:
            position_monitor = real_monitor

        if position_monitor is not None:
            logger.info(
                "  PositionMonitor (dual read-only) initialized "
                "(virtual=%s, real=%s, default=%s).",
                "OK" if virtual_monitor is not None else "N/A",
                "OK" if real_monitor is not None else "N/A",
                settings.kis_mode,
            )
        else:
            logger.info("[10a] PositionMonitor skipped (KIS clients not available).")
    except Exception as exc:
        logger.warning("  PositionMonitor init failed (portfolio summary will return zeros): %s", exc)

    # ------------------------------------------------------------------
    # 10b. Indicator Crawler (매크로 지표 1시간 자동 크롤링)
    # ------------------------------------------------------------------
    indicator_crawler = None
    try:
        logger.info("[10b] Initializing indicator crawler...")
        from src.monitoring.indicator_crawler import IndicatorCrawler

        indicator_crawler = IndicatorCrawler(claude_client=claude_client)
        logger.info("  IndicatorCrawler initialized (claude_client=%s).", "있음" if claude_client else "없음")
    except Exception as exc:
        logger.warning("  IndicatorCrawler init failed (auto macro crawling unavailable): %s", exc)

    # ------------------------------------------------------------------
    # 10. Risk modules (Addendum 26)
    # ------------------------------------------------------------------
    risk_gate_pipeline = None
    risk_budget = None
    risk_backtester = None
    try:
        logger.info("[10/10] Initializing risk modules...")
        from src.risk.risk_gate import RiskGatePipeline
        from src.risk.daily_loss_limit import DailyLossLimiter
        from src.risk.concentration import ConcentrationLimiter
        from src.risk.losing_streak import LosingStreakDetector
        from src.risk.simple_var import SimpleVaR
        from src.risk.risk_budget import RiskBudget
        from src.risk.stop_loss import TrailingStopLoss
        from src.risk.risk_backtester import RiskBacktester

        daily_loss_limiter = DailyLossLimiter()
        concentration_limiter = ConcentrationLimiter()
        losing_streak_detector = LosingStreakDetector()
        simple_var = SimpleVaR()
        risk_budget = RiskBudget()
        trailing_stop_loss = TrailingStopLoss()
        risk_backtester = RiskBacktester()
        risk_gate_pipeline = RiskGatePipeline(
            daily_loss_limiter=daily_loss_limiter,
            concentration_limiter=concentration_limiter,
            losing_streak_detector=losing_streak_detector,
            simple_var=simple_var,
            risk_budget=risk_budget,
            trailing_stop_loss=trailing_stop_loss,
        )
        logger.info("  Risk modules initialized.")
    except Exception as exc:
        logger.warning("  Risk modules init failed: %s", exc)

    # ------------------------------------------------------------------
    # Inject all dependencies into the API server
    # ------------------------------------------------------------------
    logger.info("Injecting dependencies into API server...")
    from src.monitoring.api_server import set_dependencies

    set_dependencies(
        position_monitor=position_monitor,
        universe_manager=universe_manager,
        weights_manager=weights_manager,
        strategy_params=strategy_params,
        safety_checker=safety_checker,
        fallback_router=fallback_router,
        crawl_engine=crawl_engine,
        kis_client=kis_client,
        claude_client=claude_client,
        emergency_protocol=emergency_protocol,
        capital_guard=capital_guard,
        account_safety=account_safety,
        tax_tracker=tax_tracker,
        fx_manager=fx_manager,
        slippage_tracker=slippage_tracker,
        benchmark_comparison=benchmark_comparison,
        telegram_notifier=telegram_notifier,
        profit_target_manager=profit_target_manager,
        risk_gate_pipeline=risk_gate_pipeline,
        risk_budget=risk_budget,
        risk_backtester=risk_backtester,
        indicator_crawler=indicator_crawler,
        # 듀얼 모드 클라이언트 및 모니터 추가
        virtual_kis_client=virtual_kis_client,
        real_kis_client=real_kis_client,
        position_monitors=position_monitors,
    )
    logger.info("All dependencies injected. Dashboard server is ready.")


def main() -> None:
    """대시보드 전용 서버를 시작한다."""
    settings = get_settings()
    port = settings.api_port

    # 원본 api_server.app의 lifespan을 래핑하여 의존성 초기화를 추가한다.
    from src.monitoring.api_server import app as api_app

    original_lifespan = api_app.router.lifespan_context

    @asynccontextmanager
    async def dashboard_lifespan(app: FastAPI):
        """의존성 초기화 + 원본 lifespan을 합친 라이프사이클 핸들러이다."""
        # 먼저 의존성을 초기화한다 (DB init이 여기서 수행된다).
        await _init_dependencies()
        # 원본 lifespan 실행 (init_db 중복 호출은 무해하다).
        async with original_lifespan(app):
            yield

    # 원본 앱의 lifespan을 교체한다.
    api_app.router.lifespan_context = dashboard_lifespan

    logger.info("=" * 60)
    logger.info("  Dashboard-Only Server Starting (Host Mode)")
    logger.info("  Port: %d", port)
    logger.info("  KIS Mode: %s", settings.kis_mode)
    logger.info("  Claude Mode: %s", settings.claude_mode)
    logger.info("  DB Host: %s", os.environ.get("DB_HOST", "localhost"))
    logger.info("  Redis Host: %s", os.environ.get("REDIS_HOST", "localhost"))
    logger.info("=" * 60)

    # uvicorn에 app 객체를 직접 전달한다 (import 문자열 대신).
    uvicorn.run(
        api_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
