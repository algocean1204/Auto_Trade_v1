"""
AI Auto-Trading System V2 - Main Entry Point

이 파일은 전체 시스템의 중앙 오케스트레이터로서 모든 모듈을 통합하고 실행한다.

주요 기능:
- 인프라 초기화 (DB, Redis, KIS API)
- 15분 주기 매매 루프 (크롤링 → 분류 → 분석 → 판단 → 실행 → 모니터링)
- Pre-market 준비 단계 (23:00 KST)
- EOD 정리 단계 (장 마감 후)
- FastAPI 모니터링 서버 백그라운드 실행
- 주간 분석 (일요일)
- Graceful shutdown 처리
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# .env 값을 os.environ에 로드 (크롤러의 os.environ.get() 호환)
load_dotenv()

import uvicorn

from src.analysis.claude_client import ClaudeClient
from src.analysis.classifier import NewsClassifier
from src.analysis.comprehensive_team import ComprehensiveAnalysisTeam
from src.analysis.decision_maker import DecisionMaker
from src.analysis.overnight_judge import OvernightJudge
from src.analysis.regime_detector import RegimeDetector
from src.crawler.crawl_engine import CrawlEngine
from src.crawler.crawl_verifier import CrawlVerifier
from src.db.connection import close_db, get_redis, get_session_factory, init_db
from src.executor.forced_liquidator import ForcedLiquidator
from src.executor.kis_auth import KISAuth
from src.executor.kis_client import KISClient
from src.executor.order_manager import OrderManager
from src.executor.position_monitor import PositionMonitor
from src.executor.universe_manager import UniverseManager
from src.fallback.fallback_router import FallbackRouter
from src.feedback.daily_feedback import DailyFeedback
from src.feedback.param_adjuster import ParamAdjuster
from src.feedback.rag_doc_updater import RAGDocUpdater
from src.feedback.weekly_analysis import WeeklyAnalysis
from src.indicators.aggregator import IndicatorAggregator
from src.indicators.calculator import TechnicalCalculator
from src.indicators.data_fetcher import PriceDataFetcher
from src.indicators.history_analyzer import TickerHistoryAnalyzer
from src.indicators.weights import WeightsManager
from src.monitoring.account_mode import AccountModeManager
from src.monitoring.alert import AlertManager
from src.monitoring.api_server import app as api_app
from src.monitoring.api_server import set_dependencies
from src.rag.embedder import BGEEmbedder
from src.rag.retriever import RAGRetriever
from src.safety.account_safety import AccountSafetyChecker
from src.safety.capital_guard import CapitalGuard
from src.safety.emergency_protocol import EmergencyProtocol
from src.safety.hard_safety import HardSafety
from src.safety.quota_guard import QuotaGuard
from src.safety.safety_checker import SafetyChecker
from src.tax.fx_manager import FXManager
from src.tax.slippage_tracker import SlippageTracker
from src.tax.tax_tracker import TaxTracker
from src.monitoring.benchmark import BenchmarkComparison
from src.monitoring.live_readiness import LiveReadinessChecker
from src.monitoring.telegram_notifier import TelegramNotifier
from src.telegram.bot_handler import TelegramBotHandler
from src.ai.mlx_classifier import MLXClassifier
from src.ai.knowledge_manager import KnowledgeManager
from src.strategy.entry_strategy import EntryStrategy
from src.strategy.exit_strategy import ExitStrategy
from src.strategy.params import StrategyParams
from src.strategy.profit_target import ProfitTargetManager
from src.strategy.ticker_params import TickerParamsManager
from src.risk.risk_gate import RiskGatePipeline
from src.risk.daily_loss_limit import DailyLossLimiter
from src.risk.concentration import ConcentrationLimiter
from src.risk.losing_streak import LosingStreakDetector
from src.risk.simple_var import SimpleVaR
from src.risk.risk_budget import RiskBudget
from src.risk.stop_loss import TrailingStopLoss
from src.risk.risk_backtester import RiskBacktester
from src.analysis.historical_team import HistoricalAnalysisTeam
from src.utils.config import get_settings
from src.utils.logger import get_logger
from src.utils.market_hours import MarketHours

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 상수
# ---------------------------------------------------------------------------

# 메인 루프 타이밍 상수
_PREP_CHECK_INTERVAL: int = 3600        # 준비 단계 재확인 간격 (초) — 1시간
_EOD_SLEEP_INTERVAL: int = 60           # 오류 후 재시도 대기 시간 (초)
_SHUTDOWN_GRACE_PERIOD: float = 2.0     # API 서버 시작 대기 시간 (초)
_SHUTDOWN_TIMEOUT: float = 15.0         # 시스템 종료 최대 대기 시간 (초)

# 매매 루프 타이밍 상수
_TRADING_LOOP_SLEEP: int = 15 * 60      # 정규 매매 루프 주기 (초) — 15분
_POSITION_MONITOR_SLEEP: int = 5 * 60   # 정규장 포지션 모니터링 주기 (초) — 5분
_MONITOR_ONLY_SLEEP: int = 30 * 60      # 비정규 세션 모니터링 주기 (초) — 30분
_CONTINUOUS_ANALYSIS_INTERVAL: int = 30 * 60  # 연속 분석 주기 (초) — 30분

# 연속 분석 윈도우 (KST) 경계값
_CA_WINDOW_HOUR_START: int = 23         # 연속 분석 시작 시각 (23:00 KST)
_CA_WINDOW_HOUR_END: int = 6            # 연속 분석 종료 시각 (06:30 KST)
_CA_WINDOW_MINUTE_END: int = 30         # 연속 분석 종료 분 (xx:30 KST)

# 주간 분석 요일 (0=월요일, 6=일요일)
_WEEKDAY_SUNDAY: int = 6

# 가격 데이터 조회 기간
_PRICE_HISTORY_DAYS: int = 200          # 기술적 지표 계산용 기간 (영업일 기준)

# VIX 기반 레짐 임계값
_VIX_STRONG_BULL: float = 15.0          # strong_bull 상단 경계 (VIX < 15)
_VIX_MILD_BULL: float = 20.0            # mild_bull 상단 경계 (VIX < 20)
_VIX_SIDEWAYS: float = 25.0             # sideways 상단 경계 (VIX < 25)
_VIX_MILD_BEAR: float = 30.0            # mild_bear 상단 경계 (VIX < 30)
_VIX_DEFAULT_FALLBACK: float = 20.0     # VIX 조회 실패 시 보수적 기본값

# 레짐 캐시 TTL
_REGIME_CACHE_TTL: int = 300            # Redis 레짐 캐시 만료 시간 (초) — 5분

# 인프라 체크 타임아웃
_DOCKER_CHECK_TIMEOUT: float = 5.0      # Docker 상태 확인 타임아웃 (초)

# 텔레그램/보고서 표시 제한
_MAX_OVERNIGHT_DISPLAY: int = 5         # 보고서 포지션 최대 표시 건수
_MAX_SUMMARY_CHARS: int = 200           # 텔레그램 요약 최대 문자 수
_MAX_REASON_CHARS_TELEGRAM: int = 40    # 텔레그램 사유 문자열 최대 길이
_MAX_REASON_CHARS_MARKDOWN: int = 80    # 마크다운 테이블 사유 문자열 최대 길이

# EOD 단계에서 사용하는 최신 기사 조회 건수
_EOD_ARTICLE_LIMIT: int = 10


class TradingSystem:
    """AI Auto-Trading System V2의 메인 시스템 클래스.

    모든 모듈을 초기화하고 통합하여 15분 주기 매매 루프를 실행한다.

    실행 단계:
        1. Pre-market 준비 (23:00 KST): 전체 크롤링, 분류, 분석, 안전 체크
        2. Regular market (00:00 또는 22:30/23:30 KST): 15분 루프 (delta crawl → decide → execute → monitor)
        3. EOD 정리 (장 마감 후): overnight 판단, daily feedback, forced liquidation
        4. Weekly 분석 (일요일): 주간 성과 분석 및 파라미터 조정 제안
    """

    def __init__(self) -> None:
        """시스템 초기화. 모든 모듈 인스턴스를 생성한다."""
        logger.info("========== Trading System V2 Initializing ==========")

        self.settings = get_settings()
        self.market_hours = MarketHours()

        # Infrastructure
        self.redis = None  # Initialized in startup()

        # KIS (Broker)
        self.kis_auth: KISAuth | None = None
        self.kis_client: KISClient | None = None

        # 듀얼 모드 계정 관리 (virtual/real)
        self.account_mode_manager: AccountModeManager | None = None

        # Crawling
        self.crawl_engine: CrawlEngine | None = None
        self.crawl_verifier: CrawlVerifier | None = None

        # Analysis
        self.claude_client: ClaudeClient | None = None
        self.classifier: NewsClassifier | None = None
        self.regime_detector: RegimeDetector | None = None
        self.decision_maker: DecisionMaker | None = None
        self.overnight_judge: OvernightJudge | None = None
        self.comprehensive_team: ComprehensiveAnalysisTeam | None = None

        # RAG
        self.embedder: BGEEmbedder | None = None
        self.rag_retriever: RAGRetriever | None = None

        # Indicators
        self.data_fetcher: PriceDataFetcher | None = None
        self.technical_calculator: TechnicalCalculator | None = None
        self.history_analyzer: TickerHistoryAnalyzer | None = None
        self.indicator_aggregator: IndicatorAggregator | None = None

        # Strategy
        self.strategy_params: StrategyParams | None = None
        self.entry_strategy: EntryStrategy | None = None
        self.exit_strategy: ExitStrategy | None = None
        self.ticker_params_manager: TickerParamsManager | None = None

        # Execution
        self.universe_manager: UniverseManager | None = None
        self.weights_manager: WeightsManager | None = None
        self.order_manager: OrderManager | None = None
        self.position_monitor: PositionMonitor | None = None
        self.forced_liquidator: ForcedLiquidator | None = None

        # Safety
        self.quota_guard: QuotaGuard | None = None
        self.hard_safety: HardSafety | None = None
        self.safety_checker: SafetyChecker | None = None

        # Fallback
        self.fallback_router: FallbackRouter | None = None

        # Feedback
        self.rag_doc_updater: RAGDocUpdater | None = None
        self.daily_feedback: DailyFeedback | None = None
        self.weekly_analysis: WeeklyAnalysis | None = None
        self.param_adjuster: ParamAdjuster | None = None

        # Monitoring
        self.alert_manager: AlertManager | None = None

        # Safety (new)
        self.emergency_protocol: EmergencyProtocol | None = None
        self.capital_guard: CapitalGuard | None = None
        self.account_safety: AccountSafetyChecker | None = None

        # Tax/FX
        self.tax_tracker: TaxTracker | None = None
        self.fx_manager: FXManager | None = None
        self.slippage_tracker: SlippageTracker | None = None

        # Monitoring (new)
        self.benchmark_comparison: BenchmarkComparison | None = None
        self.telegram_notifier: TelegramNotifier | None = None
        self.live_readiness_checker: LiveReadinessChecker | None = None

        # Telegram bidirectional bot
        self.telegram_bot: TelegramBotHandler | None = None

        # AI (local)
        self.mlx_classifier: MLXClassifier | None = None
        self.knowledge_manager: KnowledgeManager | None = None

        # Profit Target (Addendum 25)
        self.profit_target_manager: ProfitTargetManager | None = None

        # Risk (Addendum 26)
        self.daily_loss_limiter: DailyLossLimiter | None = None
        self.concentration_limiter: ConcentrationLimiter | None = None
        self.losing_streak_detector: LosingStreakDetector | None = None
        self.simple_var: SimpleVaR | None = None
        self.risk_budget: RiskBudget | None = None
        self.trailing_stop_loss: TrailingStopLoss | None = None
        self.risk_backtester: RiskBacktester | None = None
        self.risk_gate_pipeline: RiskGatePipeline | None = None

        # Historical Analysis Team (과거분석팀 / 종목분석팀)
        self.historical_team: HistoricalAnalysisTeam | None = None
        self._historical_task: asyncio.Task | None = None

        # Runtime state
        self.running: bool = False
        self.api_server_task: asyncio.Task | None = None
        self._trading_task: asyncio.Task | None = None
        self._auto_stop_triggered: bool = False
        self._control_lock: asyncio.Lock = asyncio.Lock()

        # Last execution timestamps
        self.last_prep_date: datetime | None = None
        self.last_daily_feedback_date: datetime | None = None
        self.last_weekly_analysis_date: datetime | None = None

        # 연속 크롤링 분석 상태 (23:00~06:30 KST, 30분 단위)
        self._continuous_analysis_iteration: int = 0
        self._continuous_analysis_previous_issues: str = ""
        self._continuous_analysis_last_run: datetime | None = None

        # 일일 보고서용 누적 데이터 (세션 시작 시 초기화)
        self._session_start_time: datetime | None = None
        self._trading_loop_count: int = 0
        self._continuous_analysis_count: int = 0
        self._risk_gate_blocks: list[dict[str, Any]] = []
        self._today_decisions: list[dict[str, Any]] = []

        # 종합분석팀 분석 결과 (세션 시작 전 분석, 세션 내 참조용)
        self._comprehensive_analysis: dict[str, Any] | None = None

    async def initialize(self) -> None:
        """모든 모듈을 초기화한다."""
        logger.info("Initializing all modules...")

        # Infrastructure
        await init_db()
        self.redis = get_redis()

        # KIS (Broker) — 토큰은 24시간 유효, 1일 1회 발급 원칙.
        # 저장된 토큰이 유효하면 재사용하고, 만료 시에만 새로 발급한다.
        logger.info("Initializing KIS API...")
        token_dir = Path(__file__).resolve().parents[1] / "data"
        token_dir.mkdir(parents=True, exist_ok=True)
        trading_token_path = token_dir / "kis_token.json"
        real_token_path = token_dir / "kis_real_token.json"

        self.kis_auth = self._load_or_create_auth(
            app_key=self.settings.kis_app_key,
            app_secret=self.settings.kis_app_secret,
            account=self.settings.kis_active_account,
            virtual=self.settings.kis_virtual,
            token_path=trading_token_path,
        )
        await self.kis_auth.get_token()
        self.kis_auth.save_credentials(trading_token_path)

        # 모의투자 모드일 때 시세 조회용 실전 인증을 별도 생성한다.
        # 모의투자 서버에는 시세 API가 없으므로 실전 API로 시세를 조회해야 한다.
        real_auth = None
        if self.settings.kis_virtual and self.settings.kis_real_app_key:
            logger.info("Initializing real KIS auth for price queries...")
            real_auth = self._load_or_create_auth(
                app_key=self.settings.kis_real_app_key,
                app_secret=self.settings.kis_real_app_secret,
                account=self.settings.kis_real_account,
                virtual=False,
                token_path=real_token_path,
            )
            await real_auth.get_token()
            real_auth.save_credentials(real_token_path)

        self.kis_client = KISClient(self.kis_auth, real_auth=real_auth)

        # ------------------------------------------------------------------
        # 듀얼 모드 계정 관리 (virtual/real) 초기화
        # 대시보드에서 모드별 독립 잔고/포지션을 조회하기 위해
        # 각 모드에 전용 KISClient + PositionMonitor를 등록한다.
        #
        # Virtual 모드: kis_client만 등록한다.
        #   PositionMonitor는 나중에 생성되는 거래용 position_monitor를
        #   기본 폴백으로 사용하므로 여기서 별도 등록하지 않는다.
        #
        # Real 모드: 실전 전용 KISClient + readonly PositionMonitor를 등록한다.
        # ------------------------------------------------------------------
        logger.info("Initializing dual-mode account manager...")
        self.account_mode_manager = AccountModeManager()

        # Virtual 모드: 기존 kis_client 등록 (거래 + 대시보드 공용)
        # position_monitor는 뒤에서 생성 후 별도 등록한다.
        self.account_mode_manager.register(
            mode="virtual",
            kis_client=self.kis_client,
            position_monitor=None,  # 거래용 monitor 생성 후 업데이트
        )

        # Real 모드: 실전 인증 전용 KISClient (대시보드 잔고 조회 전용)
        # real_auth가 있으면 독립 클라이언트를 생성하고, 없으면 건너뛴다.
        if real_auth is not None:
            real_kis_client = KISClient(real_auth, real_auth=None)
            real_monitor = PositionMonitor.create_readonly(real_kis_client)
            self.account_mode_manager.register(
                mode="real",
                kis_client=real_kis_client,
                position_monitor=real_monitor,
            )
            logger.info("Real-mode KIS client registered for dashboard viewing")
        else:
            logger.info("Real KIS auth not available -- real mode dashboard disabled")

        # Crawling
        logger.info("Initializing crawl engine...")
        self.crawl_engine = CrawlEngine()
        self.crawl_verifier = CrawlVerifier()

        # Claude client (initialize before QuotaGuard -- QuotaGuard가 모드를 참조한다)
        logger.info("Initializing Claude client and analysis modules...")
        self.claude_client = ClaudeClient(
            mode=self.settings.claude_mode,
            api_key=self.settings.anthropic_api_key or None,
        )

        # Safety
        logger.info("Initializing safety modules...")
        self.quota_guard = QuotaGuard(self.claude_client)
        self.hard_safety = HardSafety()
        self.safety_checker = SafetyChecker(self.quota_guard, self.hard_safety)

        # Analysis (continued)
        self.fallback_router = FallbackRouter(self.claude_client, self.quota_guard)
        self.classifier = NewsClassifier(self.claude_client)
        self.regime_detector = RegimeDetector(self.claude_client)
        self.comprehensive_team = ComprehensiveAnalysisTeam(self.claude_client)

        # RAG
        logger.info("Initializing RAG modules...")
        self.embedder = BGEEmbedder()
        rag_session = get_session_factory()()
        self.rag_retriever = RAGRetriever(rag_session, self.embedder)

        # Indicators
        logger.info("Initializing indicator modules...")
        self.data_fetcher = PriceDataFetcher(self.kis_client)
        self.technical_calculator = TechnicalCalculator()
        self.history_analyzer = TickerHistoryAnalyzer()
        self.indicator_aggregator = IndicatorAggregator(
            self.technical_calculator, self.history_analyzer
        )

        # Strategy
        logger.info("Initializing strategy modules...")
        self.strategy_params = StrategyParams()
        self.entry_strategy = EntryStrategy(self.strategy_params, self.market_hours)
        self.exit_strategy = ExitStrategy(self.strategy_params, self.market_hours)

        # Ticker-level params (종목별 AI 최적화 파라미터)
        logger.info("Initializing ticker params manager...")
        self.ticker_params_manager = TickerParamsManager(
            claude_client=self.claude_client,
            strategy_params=self.strategy_params,
            indicator_calculator=self.technical_calculator,
        )
        # 종목별 파라미터를 entry/exit 전략에 주입
        self.entry_strategy.set_ticker_params_manager(self.ticker_params_manager)
        self.exit_strategy.set_ticker_params_manager(self.ticker_params_manager)

        # Tax/FX (Execution 모듈보다 먼저 초기화: OrderManager에 주입된다)
        logger.info("Initializing tax/fx modules...")
        self.tax_tracker = TaxTracker()
        self.fx_manager = FXManager(self.kis_client)
        self.slippage_tracker = SlippageTracker()

        # Execution
        logger.info("Initializing execution modules...")
        self.universe_manager = UniverseManager()
        self.weights_manager = WeightsManager()
        self.order_manager = OrderManager(
            self.kis_client,
            self.safety_checker,
            tax_tracker=self.tax_tracker,
            slippage_tracker=self.slippage_tracker,
        )
        self.position_monitor = PositionMonitor(
            self.kis_client,
            self.exit_strategy,
            self.order_manager,
            self.hard_safety,
        )
        # 듀얼 모드: virtual 모드의 포지션 모니터를 거래용 인스턴스로 업데이트한다.
        # 이전에 None으로 등록했던 virtual 모니터를 실제 거래 모니터로 교체한다.
        if self.account_mode_manager is not None:
            self.account_mode_manager.register(
                mode="virtual",
                kis_client=self.kis_client,
                position_monitor=self.position_monitor,
            )
        self.forced_liquidator = ForcedLiquidator(self.order_manager)

        # Decision (depends on RAG + indicators)
        logger.info("Initializing decision maker...")
        self.decision_maker = DecisionMaker(
            self.claude_client,
            self.rag_retriever,
            self.indicator_aggregator,
        )
        self.overnight_judge = OvernightJudge(self.claude_client)

        # Feedback
        logger.info("Initializing feedback modules...")
        self.rag_doc_updater = RAGDocUpdater()
        self.daily_feedback = DailyFeedback(self.claude_client, self.rag_doc_updater)
        self.param_adjuster = ParamAdjuster(self.strategy_params)
        self.weekly_analysis = WeeklyAnalysis(self.claude_client, self.param_adjuster)

        # Monitoring
        logger.info("Initializing monitoring...")
        self.alert_manager = AlertManager()

        # Safety (new modules)
        logger.info("Initializing new safety modules...")
        self.emergency_protocol = EmergencyProtocol()
        self.capital_guard = CapitalGuard()
        self.account_safety = AccountSafetyChecker(kis_client=self.kis_client)

        # Monitoring (new)
        logger.info("Initializing benchmark and telegram...")
        self.benchmark_comparison = BenchmarkComparison(self.kis_client)
        self.telegram_notifier = TelegramNotifier()
        self.telegram_bot = TelegramBotHandler(self.telegram_notifier)
        self.telegram_bot.set_trading_system(self)
        self.live_readiness_checker = LiveReadinessChecker(self.telegram_notifier)

        # AI (local)
        logger.info("Initializing local AI modules...")
        self.mlx_classifier = MLXClassifier()
        self.knowledge_manager = KnowledgeManager(self.claude_client, self.embedder)

        # Profit Target (Addendum 25)
        logger.info("Initializing profit target manager...")
        self.profit_target_manager = ProfitTargetManager()
        await self.profit_target_manager.get_monthly_target_from_db()

        # Risk (Addendum 26)
        logger.info("Initializing risk modules...")
        self.daily_loss_limiter = DailyLossLimiter()
        self.concentration_limiter = ConcentrationLimiter()
        self.losing_streak_detector = LosingStreakDetector()
        self.simple_var = SimpleVaR()
        self.risk_budget = RiskBudget()
        self.trailing_stop_loss = TrailingStopLoss()
        self.risk_backtester = RiskBacktester()
        self.risk_gate_pipeline = RiskGatePipeline(
            daily_loss_limiter=self.daily_loss_limiter,
            concentration_limiter=self.concentration_limiter,
            losing_streak_detector=self.losing_streak_detector,
            simple_var=self.simple_var,
            risk_budget=self.risk_budget,
            trailing_stop_loss=self.trailing_stop_loss,
        )

        # Historical Analysis Team (과거분석팀 / 종목분석팀)
        logger.info("Initializing historical analysis team...")
        self.historical_team = HistoricalAnalysisTeam(self.claude_client)

        # Inject dependencies into FastAPI monitoring server
        # 듀얼 모드: AccountModeManager에서 모드별 클라이언트/모니터를 꺼내 전달한다.
        _amm = self.account_mode_manager
        set_dependencies(
            position_monitor=self.position_monitor,
            universe_manager=self.universe_manager,
            weights_manager=self.weights_manager,
            strategy_params=self.strategy_params,
            safety_checker=self.safety_checker,
            fallback_router=self.fallback_router,
            crawl_engine=self.crawl_engine,
            kis_client=self.kis_client,
            claude_client=self.claude_client,
            classifier=self.classifier,
            emergency_protocol=self.emergency_protocol,
            capital_guard=self.capital_guard,
            account_safety=self.account_safety,
            tax_tracker=self.tax_tracker,
            fx_manager=self.fx_manager,
            slippage_tracker=self.slippage_tracker,
            benchmark_comparison=self.benchmark_comparison,
            telegram_notifier=self.telegram_notifier,
            profit_target_manager=self.profit_target_manager,
            risk_gate_pipeline=self.risk_gate_pipeline,
            risk_budget=self.risk_budget,
            risk_backtester=self.risk_backtester,
            trading_system=self,
            ticker_params_manager=self.ticker_params_manager,
            virtual_kis_client=_amm.get_kis_client("virtual") if _amm else None,
            real_kis_client=_amm.get_kis_client("real") if _amm else None,
            position_monitors={
                mode: _amm.get_position_monitor(mode)
                for mode in (_amm.registered_modes if _amm else [])
            },
            account_mode_manager=_amm,
            historical_team=self.historical_team,
        )

        logger.info("All modules initialized successfully.")

    async def shutdown(self) -> None:
        """시스템을 안전하게 종료한다."""
        logger.info("========== Trading System V2 Shutting Down ==========")
        self.running = False

        # 시스템 종료 텔레그램 알림 (봇 중단 전에 발송)
        if self.telegram_notifier:
            try:
                from zoneinfo import ZoneInfo
                kst = ZoneInfo("Asia/Seoul")
                shutdown_time_kst = datetime.now(tz=kst).strftime("%H:%M KST")

                shutdown_lines = [
                    f"종료 시각: {shutdown_time_kst}",
                    f"종료 유형: 정상 종료",
                ]

                # 일일 PnL 요약 (가능한 경우)
                if self.daily_feedback:
                    try:
                        today = datetime.now(timezone.utc).date()
                        # Redis에서 오늘 매매 요약 조회 시도
                        if self.redis:
                            import json as _json_shutdown
                            daily_key = f"trading:daily_summary:{today.isoformat()}"
                            daily_raw = await self.redis.get(daily_key)
                            if daily_raw:
                                daily_data = _json_shutdown.loads(daily_raw)
                                trade_count = daily_data.get("trade_count", 0)
                                pnl = daily_data.get("total_pnl_usd", 0.0)
                                shutdown_lines.append(
                                    f"오늘 매매: {trade_count}건, 일일 PnL: ${pnl:+.2f}"
                                )
                    except Exception as _exc:
                        logger.debug("종료 시 일일 요약 조회 실패 (무시): %s", _exc)

                await self.telegram_notifier.send_message(
                    title="[시스템 종료] 자동매매 시스템 정상 종료",
                    message="\n".join(shutdown_lines),
                    severity="info",
                )
            except Exception as exc:
                logger.debug("시스템 종료 텔레그램 알림 실패: %s", exc)

        # Stop Telegram bot handler
        if self.telegram_bot:
            try:
                await self.telegram_bot.stop()
            except Exception as exc:
                logger.warning("텔레그램 봇 종료 실패: %s", exc)

        # Stop API server
        if self.api_server_task and not self.api_server_task.done():
            logger.info("Stopping API server...")
            self.api_server_task.cancel()
            try:
                await self.api_server_task
            except asyncio.CancelledError:
                pass

        # Close KIS HTTP client (aiohttp 세션 종료로 Unclosed session 경고 방지)
        if self.kis_client:
            try:
                await self.kis_client.close()
                logger.info("KIS 클라이언트 세션 종료 완료 (거래용)")
            except Exception as exc:
                logger.warning("KIS 클라이언트 종료 실패 (거래용): %s", exc)

        # 듀얼 모드 대시보드 전용 real KIS 클라이언트 종료
        if self.account_mode_manager:
            real_client = self.account_mode_manager.get_kis_client("real")
            if real_client is not None and real_client is not self.kis_client:
                try:
                    await real_client.close()
                    logger.info("KIS 클라이언트 세션 종료 완료 (real 대시보드 전용)")
                except Exception as exc:
                    logger.warning("KIS 클라이언트 종료 실패 (real 대시보드 전용): %s", exc)

        # Close database connections
        await close_db()

        # Close Redis
        if self.redis:
            await self.redis.aclose()

        logger.info("System shutdown complete.")

    def _on_trading_task_done(self, task: asyncio.Task) -> None:
        """매매 태스크 완료/실패 시 콜백.

        태스크가 취소되거나 예외로 종료된 경우 상태를 기록하고 running 플래그를 해제한다.
        """
        if task.cancelled():
            logger.info("Trading task cancelled")
        elif exc := task.exception():
            logger.error("Trading task crashed: %s", exc)
        self.running = False

    def get_trading_status(self) -> dict[str, Any]:
        """현재 자동매매 실행 상태를 반환한다.

        외부 모듈(엔드포인트 등)에서 private 속성에 직접 접근하지 않도록 공개 메서드로 제공한다.
        운영 윈도우 정보, 거래일 여부, 현재 세션 타입, 현재 KST 시각을 함께 반환한다.

        Returns:
            is_trading: 매매 루프가 실제로 실행 중인지 여부.
            running: running 플래그 값.
            task_done: 매매 태스크가 완료(종료)되었는지 여부.
            is_trading_window: 현재 운영 윈도우 내인지 여부.
            is_trading_day: 오늘이 거래일인지 여부.
            session_type: 현재 미국 시장 세션 타입.
            next_window_start: 다음 운영 윈도우 시작 시각 (ISO, KST).
            current_kst: 현재 KST 시각 (ISO 형식).
        """
        task = self._trading_task
        task_active = task is not None and not task.done()

        # 운영 윈도우 정보 수집 (실패 시 기본값 사용)
        is_trading_window = False
        is_trading_day = True
        session_type = None
        next_window_start = None
        current_kst = ""
        try:
            window_info = self.market_hours.get_operating_window_info()
            is_trading_window = window_info.get("is_active", False)
            is_trading_day = window_info.get("is_trading_day", True)
            next_window_start = window_info.get("next_window_start_kst")
            current_kst = window_info.get("current_kst", "")
            session_type = self.market_hours.get_session_type()
        except Exception as exc:
            logger.warning("운영 윈도우 정보 조회 실패 (기본값 사용): %s", exc)

        return {
            "is_trading": self.running and task_active,
            "running": self.running,
            "task_done": task.done() if task else True,
            "is_trading_window": is_trading_window,
            "is_trading_day": is_trading_day,
            "session_type": session_type,
            "next_window_start": next_window_start,
            "current_kst": current_kst,
        }

    async def start_trading(self, force: bool = False) -> dict[str, Any]:
        """API 호출로 자동매매 루프를 시작한다.

        이미 실행 중인 경우 즉시 반환한다. 동시 호출 보호를 위해 _control_lock을 사용한다.
        force=False(기본값)이면 운영 윈도우 및 거래일 시간 검증을 수행한다.
        force=True이면 시간 검증을 우회하여 강제 시작한다 (긴급 수동 오버라이드 용도).

        Args:
            force: True이면 시간 검증을 건너뛴다.

        Returns:
            status: "started", "already_running", "outside_trading_hours", "not_trading_day".
        """
        if not force:
            try:
                if not self.market_hours.is_trading_day():
                    logger.info("자동매매 시작 거부: 오늘은 거래일이 아닙니다.")
                    return {
                        "status": "not_trading_day",
                        "message": "오늘은 매매일이 아닙니다 (주말 또는 미국 공휴일)",
                    }
                if not self.market_hours.is_operating_window():
                    window_info = self.market_hours.get_operating_window_info()
                    next_window = window_info.get("next_window_start_kst", "")
                    logger.info(
                        "자동매매 시작 거부: 운영 윈도우 밖입니다. 다음 윈도우: %s",
                        next_window,
                    )
                    return {
                        "status": "outside_trading_hours",
                        "message": "매매 가능 시간이 아닙니다",
                        "next_window": next_window,
                    }
            except Exception as exc:
                logger.warning("운영 윈도우 검증 중 오류 (무시하고 진행): %s", exc)

        async with self._control_lock:
            if self._trading_task and not self._trading_task.done():
                logger.info("자동매매 루프가 이미 실행 중입니다.")
                return {"status": "already_running"}

            logger.info("자동매매 루프 시작 (API 호출, force=%s)", force)
            self.running = True
            self._auto_stop_triggered = False
            self._trading_task = asyncio.create_task(self.main_loop())
            self._trading_task.add_done_callback(self._on_trading_task_done)
            return {"status": "started"}

    async def stop_trading(self, run_eod: bool = True) -> dict[str, Any]:
        """API 호출로 자동매매 루프를 중지한다.

        run_eod=True인 경우 EOD 시퀀스(EOD 단계 → 일일 보고서 → Telegram)를 실행한다.
        실행 중이 아닌 경우 즉시 반환한다. 동시 호출 보호를 위해 _control_lock을 사용한다.

        Args:
            run_eod: True이면 EOD 종료 시퀀스를 실행한다 (기본값: True).

        Returns:
            status: "stopped" 또는 "not_running".
        """
        async with self._control_lock:
            if not self.running:
                logger.info("자동매매 루프가 실행 중이 아닙니다.")
                if self._trading_task and self._trading_task.done():
                    self._trading_task = None
                return {"status": "not_running"}

            logger.info("자동매매 루프 중지 시작 (run_eod=%s)", run_eod)
            self.running = False

            if self._trading_task:
                try:
                    await asyncio.wait_for(self._trading_task, timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("자동매매 루프 태스크 종료 대기 시간 초과, 취소합니다.")
                    self._trading_task.cancel()
                    try:
                        await self._trading_task
                    except (asyncio.CancelledError, Exception):
                        pass
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.warning("자동매매 루프 태스크 대기 중 오류: %s", exc)
                finally:
                    self._trading_task = None

        if run_eod:
            await self._run_shutdown_sequence()

        logger.info("자동매매 루프 중지 완료")
        return {"status": "stopped"}

    async def _run_shutdown_sequence(self) -> None:
        """EOD 종료 시퀀스를 실행한다.

        오늘 EOD를 아직 실행하지 않은 경우에만 EOD 단계를 수행하고,
        이후 Telegram으로 종료 알림을 발송한다.

        이 메서드는 자동 종료(6:00 AM KST) 및 API 수동 중지 시 호출된다.
        """
        logger.info("EOD 종료 시퀀스 시작")
        try:
            today = datetime.now(timezone.utc).date()
            if self.last_daily_feedback_date != today:
                logger.info("오늘 EOD 미실행 — EOD 단계를 실행합니다.")
                await self.run_eod_phase()
            else:
                logger.info("오늘 EOD 이미 실행됨 — EOD 단계를 건너뜁니다.")
        except Exception as exc:
            logger.exception("EOD 종료 시퀀스 중 오류: %s", exc)
        finally:
            logger.info("EOD 종료 시퀀스 완료")

    async def start_api_server(self) -> None:
        """FastAPI 모니터링 서버를 백그라운드에서 실행한다."""
        import socket as _socket

        api_port = self.settings.api_port
        config = uvicorn.Config(
            api_app,
            host="0.0.0.0",
            port=api_port,
            log_level="info",
        )

        class _ReuseAddrServer(uvicorn.Server):
            """SO_REUSEADDR를 소켓에 강제 설정하여 재시작 시 포트를 즉시 재사용한다."""

            async def startup(self, sockets=None):  # type: ignore[override]
                if sockets is None:
                    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                    sock.bind(("0.0.0.0", self.config.port))
                    sock.set_inheritable(True)
                    sockets = [sock]
                await super().startup(sockets=sockets)

        server = _ReuseAddrServer(config)

        logger.info("Starting FastAPI monitoring server on port %d...", api_port)
        await server.serve()

    async def run_preparation_phase(self) -> dict[str, Any]:
        """Pre-market 준비 단계를 실행한다 (23:00 KST).

        실제 로직은 src.orchestration.preparation 모듈에 위임한다.

        Returns:
            준비 단계 실행 결과.
        """
        from src.orchestration.preparation import run_preparation_phase
        return await run_preparation_phase(self)

    async def run_trading_loop_iteration(self) -> dict[str, Any]:
        """15분 매매 루프의 1회 반복을 실행한다.

        실제 로직은 src.orchestration.trading_loop 모듈에 위임한다.

        Returns:
            루프 반복 실행 결과.
        """
        from src.orchestration.trading_loop import run_trading_loop_iteration
        return await run_trading_loop_iteration(self)

    async def run_eod_phase(self) -> dict[str, Any]:
        """EOD (End of Day) 정리 단계를 실행한다 (장 마감 후).

        Returns:
            EOD 단계 실행 결과.
        """
        logger.info("========== EOD PHASE START ==========")
        results = {}

        try:
            # 1. Overnight judgment
            logger.info("[1/9] Overnight judgment...")
            positions_dict = await self.position_monitor.sync_positions()
            positions = list(positions_dict.values())
            signals = await self._fetch_latest_articles(limit=_EOD_ARTICLE_LIMIT)
            regime = await self._get_current_regime()
            overnight_decisions = await self.overnight_judge.judge(positions, signals, regime)
            results["overnight_decisions"] = overnight_decisions
            logger.info("Overnight decisions: %d positions evaluated", len(overnight_decisions))

            # Execute overnight sells if needed
            for decision in overnight_decisions:
                if decision.get("action") == "sell":
                    await self._execute_overnight_sell(decision)

            # 2. Daily feedback
            logger.info("[2/9] Generating daily feedback...")
            today = datetime.now(timezone.utc).date()
            feedback = None
            if self.last_daily_feedback_date != today:
                feedback = await self.daily_feedback.generate(today)
                results["daily_feedback"] = feedback
                self.last_daily_feedback_date = today
                logger.info("Daily feedback generated")
            else:
                logger.info("Daily feedback already generated today")

            # 3. 벤치마크 스냅샷 기록
            logger.info("[3/9] Benchmark daily snapshot...")
            try:
                await self.benchmark_comparison.record_daily_snapshot(
                    ai_return_pct=feedback.get("summary", {}).get("total_pnl_pct", 0.0) if feedback else 0.0,
                    spy_return_pct=await self.benchmark_comparison.calculate_spy_return(today, today),
                    sso_return_pct=await self.benchmark_comparison.calculate_sso_return(today, today),
                )
            except Exception as e:
                logger.warning("벤치마크 스냅샷 실패: %s", e)

            # 4. Telegram 최종 종합 보고서
            logger.info("[4/9] Telegram final comprehensive report...")
            try:
                await self._send_final_daily_report(results, feedback)
            except Exception as e:
                logger.warning("Telegram 최종 보고서 발송 실패: %s", e)

            # 4-1. 종합분석팀 EOD 보고서
            logger.info("[4-1] Comprehensive Analysis Team EOD report...")
            try:
                if (
                    self.comprehensive_team is not None
                    and self._comprehensive_analysis is not None
                ):
                    _fb_summary_eod = feedback.get("summary", {}) if feedback else {}
                    eod_report = await self.comprehensive_team.generate_eod_report(
                        today_analysis=self._comprehensive_analysis,
                        today_decisions=self._today_decisions,
                        today_results=_fb_summary_eod,
                        positions=positions,
                        risk_gate_blocks=self._risk_gate_blocks,
                    )
                    results["comprehensive_eod_report"] = eod_report

                    # Redis에 EOD 보고서 저장
                    try:
                        import json as _json_eod
                        await self.redis.set(
                            f"comprehensive_analysis:eod:{today}",
                            eod_report,
                            ex=86400 * 7,  # 7일 보존
                        )
                    except Exception as redis_exc:
                        logger.debug("종합분석 EOD Redis 저장 실패: %s", redis_exc)

                    # 텔레그램 전송
                    if self.telegram_notifier and eod_report:
                        await self.telegram_notifier.send_eod_analysis_report(
                            eod_report
                        )
                    logger.info("종합분석팀 EOD 보고서 생성 및 발송 완료")
                else:
                    logger.debug(
                        "종합분석팀 EOD 보고서 건너뜀 (team=%s, analysis=%s)",
                        "있음" if self.comprehensive_team else "없음",
                        "있음" if self._comprehensive_analysis else "없음",
                    )
            except Exception as e:
                logger.warning("종합분석팀 EOD 보고서 실패: %s", e)

            # 5. Daily PnL log + Profit target update (Addendum 25)
            logger.info("[5/9] Daily PnL log and profit target update...")
            try:
                _fb_summary = feedback.get("summary", {}) if feedback else {}
                today_pnl = _fb_summary.get("total_pnl_amount", 0.0)
                trade_count = _fb_summary.get("total_trades", 0)
                await self.profit_target_manager.log_daily_pnl(
                    trade_date=today,
                    realized_pnl=today_pnl,
                    trade_count=trade_count,
                )
                await self.profit_target_manager.update_aggression()
            except Exception as e:
                logger.warning("일일 PnL/수익목표 업데이트 실패: %s", e)

            # 6. Risk budget update (Addendum 26)
            logger.info("[6/9] Risk budget update...")
            try:
                await self.risk_budget.update_budget()
            except Exception as e:
                logger.warning("리스크 예산 업데이트 실패: %s", e)

            # 7. Reset daily risk counters
            logger.info("[7/9] Reset daily risk counters...")
            try:
                self.daily_loss_limiter.reset_daily()
            except Exception as e:
                logger.warning("일일 리스크 카운터 리셋 실패: %s", e)

            # 8. Forced liquidation check (day 3+)
            logger.info("[8/9] Forced liquidation check...")
            liquidation_results = await self.forced_liquidator.check_and_liquidate(positions)
            results["forced_liquidation"] = liquidation_results
            logger.info("Forced liquidation: %d positions checked", len(liquidation_results))

            # 9. Cleanup
            logger.info("[9/9] Cleanup...")
            # QuotaGuard는 슬라이딩 윈도우 방식이므로 별도 리셋 불필요
            self.quota_guard.cleanup()

            # 10. 실전전환 준비도 체크 (모든 기준 충족 시 Telegram 1회 발송)
            logger.info("[10/10] Live trading readiness check...")
            readiness_result = await self._check_live_readiness()
            results["live_readiness"] = readiness_result
            if readiness_result.get("notified"):
                logger.info("실전전환 준비 완료 알림 발송")
            elif readiness_result.get("ready") and not readiness_result.get("notified"):
                logger.info("실전전환 준비 완료 (알림 이미 발송됨)")

            logger.info("========== EOD PHASE COMPLETE ==========")

        except Exception as e:
            logger.exception("EOD phase failed: %s", e)
            await self.alert_manager.send_alert(
                "system", "EOD phase exception", str(e), "error",
            )
            results["error"] = str(e)

        return results

    async def run_weekly_analysis(self) -> dict[str, Any]:
        """주간 분석을 실행한다 (일요일).

        Returns:
            주간 분석 결과.
        """
        logger.info("========== WEEKLY ANALYSIS START ==========")
        results = {}

        try:
            # Determine week start date (previous Monday)
            today = datetime.now().date()
            week_start = today - timedelta(days=today.weekday())

            analysis = None
            if self.last_weekly_analysis_date != week_start:
                analysis = await self.weekly_analysis.generate(week_start)
                results["weekly_analysis"] = analysis
                self.last_weekly_analysis_date = week_start
                logger.info("Weekly analysis generated")

                # Alert user about parameter adjustment suggestions
                if analysis.get("param_adjustments"):
                    await self.alert_manager.send_alert(
                        "strategy", "Weekly param adjustment ready", str(analysis.get("param_adjustments", {})),
                    )
            else:
                logger.info("Weekly analysis already generated this week")

            # 벤치마크 언더퍼포먼스 체크
            try:
                await self.benchmark_comparison.check_underperformance()
            except Exception as e:
                logger.warning("벤치마크 체크 실패: %s", e)

            # Telegram 주간 리포트
            if analysis:
                try:
                    await self.telegram_notifier.send_weekly_report(analysis)
                except Exception as e:
                    logger.warning("Telegram 주간 리포트 실패: %s", e)

            logger.info("========== WEEKLY ANALYSIS COMPLETE ==========")

        except Exception as e:
            logger.exception("Weekly analysis failed: %s", e)
            await self.alert_manager.send_alert(
                "system", "Weekly analysis exception", str(e), "error",
            )
            results["error"] = str(e)

        return results

    async def _check_live_readiness(self) -> dict[str, Any]:
        """모의투자 실전전환 준비도를 체크하고 조건 충족 시 Telegram 알림을 발송한다.

        7가지 기준을 평가한다:
            1. 최소 5거래일 완료
            2. 시스템 가동률 > 95%
            3. 누적 수익률 >= 0% (손실 없음)
            4. 최대 낙폭 < 10%
            5. 성공 거래 3건 이상
            6. 안전 시스템 일관적 통과
            7. 비상 이벤트 0건

        Redis 플래그(`live_trading_recommended`)로 중복 알림을 방지한다.

        Returns:
            평가 결과 딕셔너리.
        """
        try:
            if self.live_readiness_checker is None:
                logger.warning("LiveReadinessChecker 미초기화. 체크 건너뜀.")
                return {"evaluated": False, "reason": "checker not initialized"}
            return await self.live_readiness_checker.check_and_notify()
        except Exception as exc:
            logger.error("실전전환 준비도 체크 실패: %s", exc)
            return {"evaluated": False, "error": str(exc)}

    def _is_continuous_analysis_window(self) -> bool:
        """현재 시각이 연속 크롤링 분석 윈도우 안인지 확인한다.

        서머타임(EDT) 적용 중이면 22:00~06:30 KST,
        비서머타임(EST)이면 23:00~06:30 KST를 윈도우로 사용한다.
        """
        from zoneinfo import ZoneInfo
        kst = ZoneInfo("Asia/Seoul")
        now_kst = datetime.now(tz=kst)
        hour = now_kst.hour
        minute = now_kst.minute

        # DST 여부에 따라 시작 시각 결정 (서머타임: 22시, 비서머타임: 23시)
        try:
            window_start_hour = self.market_hours._get_window_start_hour(now_kst)
        except Exception:
            window_start_hour = _CA_WINDOW_HOUR_START  # 기본값 23

        # window_start_hour:00 ~ 23:59 (당일)
        if hour >= window_start_hour:
            return True
        # 00:00 ~ 06:29 (다음날 새벽)
        if hour < _CA_WINDOW_HOUR_END:
            return True
        # 06:00 ~ 06:30
        if hour == _CA_WINDOW_HOUR_END and minute <= _CA_WINDOW_MINUTE_END:
            return True
        return False

    def _should_run_continuous_analysis(self) -> bool:
        """연속 분석을 실행할 시점인지 확인한다 (30분 간격)."""
        if not self._is_continuous_analysis_window():
            return False
        if self._continuous_analysis_last_run is None:
            return True
        elapsed = (datetime.now(tz=timezone.utc) - self._continuous_analysis_last_run).total_seconds()
        return elapsed >= _CONTINUOUS_ANALYSIS_INTERVAL

    async def main_loop(self) -> None:
        """메인 루프를 실행한다. 시장 시간에 따라 적절한 단계를 실행한다.

        start_trading() 호출로 시작되며, running 플래그가 False가 되거나
        KST 06:00에 자동 종료된다.
        """
        logger.info("========== MAIN LOOP START ==========")

        # 세션 시작 시각 기록 및 일일 추적 데이터 초기화
        self._session_start_time = datetime.now(tz=timezone.utc)
        self._trading_loop_count = 0
        self._continuous_analysis_count = 0
        self._risk_gate_blocks = []
        self._today_decisions = []

        # 텔레그램 양방향 봇 시작
        if self.telegram_bot:
            try:
                await self.telegram_bot.start()
                logger.info("텔레그램 양방향 봇 시작 완료")
            except Exception as exc:
                logger.warning("텔레그램 양방향 봇 시작 실패: %s", exc)

        # 시스템 시작 텔레그램 알림
        try:
            from zoneinfo import ZoneInfo
            kst = ZoneInfo("Asia/Seoul")
            start_time_kst = datetime.now(tz=kst).strftime("%Y-%m-%d %H:%M KST")
            trading_mode = "모의투자" if self.settings.kis_virtual else "실전투자"
            account_no = self.settings.kis_active_account or "미설정"
            session_type = self.market_hours.get_session_type()
            session_kr_map = {
                "regular": "정규장",
                "pre_market": "프리마켓",
                "after_market": "애프터마켓",
                "closed": "장 외",
            }
            session_kr = session_kr_map.get(session_type, session_type)
            startup_lines = [
                f"시작 시각: {start_time_kst}",
                f"매매 모드: {trading_mode}",
                f"계좌 번호: {account_no}",
                f"Claude 모드: {self.settings.claude_mode}",
                f"현재 시장: {session_kr}",
            ]
            await self.telegram_notifier.send_message(
                title="[시스템 시작] 자동매매 시스템 가동",
                message="\n".join(startup_lines),
                severity="info",
            )
        except Exception as exc:
            logger.debug("시스템 시작 텔레그램 알림 실패: %s", exc)

        # 과거분석팀 백그라운드 태스크 시작
        if self.historical_team:
            try:
                self._historical_task = asyncio.create_task(
                    self.historical_team.start_background_analysis()
                )
                logger.info("과거분석팀 백그라운드 태스크 시작 완료")
            except Exception as exc:
                logger.warning("과거분석팀 백그라운드 태스크 시작 실패: %s", exc)

        while self.running:
            try:
                now = datetime.now(tz=timezone.utc)
                session_type = self.market_hours.get_session_type()

                # 06:00 KST 자동 종료 체크 — LaunchAgent 없이 API 서버 단독 운영 시 사용한다.
                try:
                    from zoneinfo import ZoneInfo
                    _kst = ZoneInfo("Asia/Seoul")
                    _now_kst = datetime.now(tz=_kst)
                    # 06:30 KST 이후이면 자동 종료한다. 플래그로 중복 트리거를 방지한다.
                    if not self._auto_stop_triggered and (
                        _now_kst.hour > 6
                        or (_now_kst.hour == 6 and _now_kst.minute >= 30)
                    ):
                        logger.info("06:30 KST 자동 종료 시간 도달. 시스템을 안전하게 종료한다.")
                        self._auto_stop_triggered = True
                        self.running = False
                        await self._run_shutdown_sequence()
                        break
                except Exception as _auto_stop_exc:
                    logger.debug("자동 종료 시각 체크 실패 (무시): %s", _auto_stop_exc)

                # Check if it's Sunday (weekly analysis)
                if now.weekday() == _WEEKDAY_SUNDAY:
                    await self.run_weekly_analysis()
                    # Sleep until Monday
                    await asyncio.sleep(_PREP_CHECK_INTERVAL)  # 1 hour
                    continue

                # Check if preparation phase is needed (23:00 KST)
                prep_time = self.market_hours.get_preparation_start_time()
                today_date = now.date()

                if (
                    now >= prep_time
                    and self.last_prep_date != today_date
                    and session_type == "closed"
                ):
                    # 연속 분석 상태 초기화 (새 날 시작)
                    self._continuous_analysis_iteration = 0
                    self._continuous_analysis_previous_issues = ""
                    self._continuous_analysis_last_run = None

                    # 일일 보고서용 누적 데이터 초기화 (새 날)
                    self._trading_loop_count = 0
                    self._continuous_analysis_count = 0
                    self._risk_gate_blocks = []
                    self._today_decisions = []

                    await self.run_preparation_phase()
                    self.last_prep_date = today_date

                    # 준비 단계 완료 후 첫 연속 분석 즉시 실행
                    self._continuous_analysis_last_run = datetime.now(tz=timezone.utc)

                # 연속 크롤링 분석 (23:00~06:30 KST, 30분 단위)
                if self._should_run_continuous_analysis():
                    await self.run_continuous_crawl_analysis()

                # Regular market session: run 15-minute trading loop
                # 트레이딩 루프는 15분마다, 포지션 모니터링은 5분마다 실행한다.
                if session_type == "regular":
                    logger.info("Regular market session - running trading loop")
                    await self.run_trading_loop_iteration()

                    # 15분 대기 동안 5분마다 포지션 모니터링 실행 (급격한 가격 변동 대비)
                    for _monitor_tick in range(_TRADING_LOOP_SLEEP // _POSITION_MONITOR_SLEEP):
                        await asyncio.sleep(_POSITION_MONITOR_SLEEP)
                        if not self.running:
                            break
                        try:
                            await self.position_monitor.sync_positions()
                            _mon_regime = await self._get_current_regime()
                            _mon_vix = await self._fetch_vix()
                            await self.position_monitor.monitor_all(
                                regime=_mon_regime.get("regime", "sideways"),
                                vix=_mon_vix,
                            )
                            logger.info("정규장 포지션 모니터링 완료 (%d/%d)", _monitor_tick + 1, _TRADING_LOOP_SLEEP // _POSITION_MONITOR_SLEEP)
                        except Exception as e:
                            logger.warning("정규장 포지션 모니터링 실패: %s", e)

                # EOD phase (after market close, before next day preparation)
                elif session_type == "closed":
                    # Check if we need to run EOD
                    if self.last_daily_feedback_date != today_date:
                        await self.run_eod_phase()

                    # Sleep until preparation time or next check
                    sleep_seconds = min(
                        (prep_time - now).total_seconds() if now < prep_time else _PREP_CHECK_INTERVAL,
                        _PREP_CHECK_INTERVAL,
                    )
                    # 연속 분석 윈도우에서는 최대 30분만 대기
                    if self._is_continuous_analysis_window():
                        sleep_seconds = min(sleep_seconds, _CONTINUOUS_ANALYSIS_INTERVAL)
                    await asyncio.sleep(sleep_seconds)

                # Pre-market or after-market: monitor positions but no new entries
                else:
                    logger.info("Non-regular session (%s) - monitoring only", session_type)
                    await self.position_monitor.sync_positions()
                    monitor_regime = await self._get_current_regime()
                    monitor_vix = await self._fetch_vix()
                    await self.position_monitor.monitor_all(
                        regime=monitor_regime.get("regime", "sideways"),
                        vix=monitor_vix,
                    )
                    # 프리/애프터마켓: 30분 주기 모니터링 (연속 분석과 동기화)
                    await asyncio.sleep(_MONITOR_ONLY_SLEEP)

            except asyncio.CancelledError:
                logger.info("Main loop cancelled")
                break
            except Exception as e:
                logger.exception("Main loop error: %s", e)
                try:
                    await self.alert_manager.send_alert(
                        "system", "Main loop exception", str(e), "critical",
                    )
                except Exception as exc:
                    logger.debug("메인 루프 오류 알림 전송 실패: %s", exc)
                # Sleep before retry
                await asyncio.sleep(_EOD_SLEEP_INTERVAL)

        # 과거분석팀 백그라운드 태스크 중지
        if self.historical_team:
            self.historical_team.stop()
        if self._historical_task and not self._historical_task.done():
            self._historical_task.cancel()
            try:
                await self._historical_task
            except (asyncio.CancelledError, Exception):
                pass
            self._historical_task = None

        logger.info("========== MAIN LOOP END ==========")

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    async def _fetch_indicators_for_ticker(self, ticker: str) -> dict[str, Any]:
        """특정 티커의 기술적 지표를 조회한다.

        가격 데이터를 가져와 TechnicalCalculator로 전체 지표를 계산한다.
        레버리지 ETF인 경우 본주 데이터를 사용한다.

        Args:
            ticker: 종목 심볼 (예: "SOXL", "QLD").

        Returns:
            지표명을 키로, 계산 결과를 값으로 갖는 딕셔너리.
            데이터 조회/계산 실패 시 빈 딕셔너리를 반환한다.
        """
        if not ticker or self.data_fetcher is None:
            return {}

        try:
            from src.utils.ticker_mapping import get_analysis_ticker as _get_at

            analysis_ticker = _get_at(ticker)
            df = await self.data_fetcher.get_daily_prices(analysis_ticker, days=_PRICE_HISTORY_DAYS)

            if df is None or df.empty:
                # 본주 조회 실패 시 원래 티커로 재시도
                if analysis_ticker != ticker:
                    df = await self.data_fetcher.get_daily_prices(ticker, days=_PRICE_HISTORY_DAYS)

            if df is None or df.empty:
                logger.debug("지표 계산용 가격 데이터 없음: %s", ticker)
                return {}

            indicators = self.technical_calculator.calculate_all(df)
            return indicators
        except Exception as exc:
            logger.warning("티커 지표 조회 실패 (%s): %s", ticker, exc)
            return {}

    async def _check_infrastructure(self) -> dict[str, Any]:
        """인프라 상태를 확인한다 (DB, Redis, KIS API, Docker)."""
        results = {
            "docker": False,
            "db": False,
            "redis": False,
            "kis_api": False,
            "all_ok": False,
        }

        # Docker check (PostgreSQL/Redis 컨테이너 실행 확인)
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "ps", "--status", "running", "--format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_DOCKER_CHECK_TIMEOUT)
            # 출력이 있으면 실행 중인 컨테이너가 있다
            results["docker"] = proc.returncode == 0 and len(stdout.strip()) > 0
        except Exception as e:
            logger.warning("Docker 상태 확인 실패 (True로 가정): %s", e)
            # Docker 확인 실패 시에도 DB/Redis가 정상이면 문제없다
            results["docker"] = True

        try:
            # DB check
            from sqlalchemy import text
            from src.db.connection import get_session
            async with get_session() as session:
                await session.execute(text("SELECT 1"))
            results["db"] = True
        except Exception as e:
            logger.error("DB check failed: %s", e)

        try:
            # Redis check
            await self.redis.ping()
            results["redis"] = True
        except Exception as e:
            logger.error("Redis check failed: %s", e)

        try:
            # KIS API check
            await self.kis_auth.get_token()
            results["kis_api"] = True
        except Exception as e:
            logger.error("KIS API check failed: %s", e)

        results["all_ok"] = all([
            results["docker"],
            results["db"],
            results["redis"],
            results["kis_api"],
        ])

        return results

    async def _fetch_latest_articles(self, limit: int = 20) -> list[dict[str, Any]]:
        """최신 기사를 DB에서 가져온다."""
        from src.db.connection import get_session
        from src.db.models import Article
        from sqlalchemy import select

        async with get_session() as session:
            stmt = (
                select(Article)
                .order_by(Article.published_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            articles = result.scalars().all()

        return [
            {
                "id": str(a.id),
                "title": a.headline,
                "content": a.content or "",
                "source": a.source,
                "url": a.url,
                "published_at": a.published_at,
            }
            for a in articles
        ]

    async def _send_final_daily_report(
        self,
        eod_results: dict[str, Any],
        feedback: dict[str, Any] | None,
    ) -> None:
        """EOD 종합 최종 보고서를 텔레그램 및 마크다운 파일로 발송/저장한다.

        일일 수익, 세션 요약, AI 매매 판단 상세, 리스크 게이트 차단 내역,
        연속 분석 타임라인, 포지션 현황, 오버나잇 판단, 시장 레짐/지표,
        AI 사용량을 하나의 상세 종합 보고서로 정리하여 전송한다.
        """
        import json as _json
        from zoneinfo import ZoneInfo

        kst = ZoneInfo("Asia/Seoul")
        now_kst = datetime.now(tz=kst)

        # =====================================================================
        # 공통 데이터 수집
        # =====================================================================

        # 연속 분석 히스토리 (Redis)
        ca_history: list[dict[str, Any]] = []
        ca_latest: dict[str, Any] = {}
        try:
            history_raw = await self.redis.lrange("continuous_analysis:history", 0, -1)
            if history_raw:
                ca_history = [_json.loads(h) for h in history_raw]
            latest_raw = await self.redis.get("continuous_analysis:latest")
            if latest_raw:
                ca_latest = _json.loads(latest_raw)
        except Exception as exc:
            logger.debug("연속 분석 히스토리 조회 실패: %s", exc)

        # 리스크 예산
        risk_budget_status: dict[str, Any] = {}
        try:
            risk_budget_status = self.risk_budget.get_status()
        except Exception as exc:
            logger.debug("리스크 예산 상태 조회 실패: %s", exc)

        # AI 사용량
        ai_usage: dict[str, Any] = {}
        try:
            ai_usage = self.claude_client.get_usage_stats()
        except Exception as exc:
            logger.debug("AI 사용량 조회 실패: %s", exc)

        # 현재 레짐
        regime_data: dict[str, Any] = {}
        try:
            regime_data = await self._get_current_regime()
        except Exception as exc:
            logger.debug("레짐 조회 실패: %s", exc)

        # 포트폴리오 (포지션 상세 포함)
        portfolio: dict[str, Any] = {}
        try:
            portfolio = await self.position_monitor.get_portfolio_summary()
        except Exception as exc:
            logger.debug("포트폴리오 조회 실패: %s", exc)

        overnight = eod_results.get("overnight_decisions", [])
        liq = eod_results.get("forced_liquidation", [])

        # 피드백 요약
        fb_summary = feedback.get("summary", {}) if feedback else {}
        fb_analysis = feedback.get("analysis", {}) if feedback else {}

        # 세션 시간 계산
        session_start_kst = ""
        session_end_kst = now_kst.strftime("%H:%M KST")
        session_duration = ""
        if self._session_start_time:
            _start_kst = self._session_start_time.astimezone(kst)
            session_start_kst = _start_kst.strftime("%H:%M KST")
            _dur = now_kst - _start_kst
            _dur_hours = int(_dur.total_seconds() // 3600)
            _dur_mins = int((_dur.total_seconds() % 3600) // 60)
            session_duration = f"{_dur_hours}시간 {_dur_mins}분"

        total_ai_calls = ai_usage.get("total_calls", 0)
        total_tokens = (
            ai_usage.get("total_input_tokens", 0)
            + ai_usage.get("total_output_tokens", 0)
        )

        # =====================================================================
        # 1. 텔레그램 보고서 (간결하되 핵심 정보 포함)
        # =====================================================================
        tg_lines: list[str] = [
            f"날짜: {now_kst.strftime('%Y-%m-%d (%a)')}",
            f"세션: {session_start_kst} ~ {session_end_kst} ({session_duration})",
            "",
        ]

        # 수익 요약
        pnl = fb_summary.get("total_pnl_amount", 0.0)
        pnl_pct = fb_summary.get("total_pnl_pct", 0.0)
        trade_count = fb_summary.get("total_trades", 0)
        win_rate = fb_summary.get("win_rate")
        if feedback:
            tg_lines.append(f"일일 손익: ${pnl:+.2f} ({pnl_pct:+.2f}%)")
            tg_lines.append(f"거래 횟수: {trade_count}건")
            if win_rate is not None:
                tg_lines.append(f"승률: {win_rate:.1f}%")
        else:
            tg_lines.append("일일 손익: 데이터 없음")

        # 매매 미실행 사유 (거래 0건일 때)
        if trade_count == 0:
            tg_lines.append("")
            tg_lines.append("[매매 미실행 사유]")
            if self._risk_gate_blocks:
                # 게이트별 차단 횟수 집계
                gate_counts: dict[str, int] = {}
                for blk in self._risk_gate_blocks:
                    gate_name = blk.get("gate", "unknown")
                    gate_counts[gate_name] = gate_counts.get(gate_name, 0) + 1
                for gate_name, cnt in sorted(gate_counts.items(), key=lambda x: -x[1]):
                    tg_lines.append(f"  - {gate_name}: {cnt}회 차단")
            elif not self._today_decisions:
                tg_lines.append("  - AI가 매매 신호를 생성하지 않음 (조건 미충족)")
            else:
                # 판단은 있었지만 모두 hold
                hold_count = sum(
                    1 for d in self._today_decisions if d.get("action") == "hold"
                )
                if hold_count > 0:
                    tg_lines.append(f"  - AI 판단 {len(self._today_decisions)}건 중 {hold_count}건 HOLD")
                else:
                    tg_lines.append("  - 신뢰도 부족 또는 리스크 게이트 차단")

        # 리스크 게이트 요약 (차단 있을 때만)
        if self._risk_gate_blocks:
            tg_lines.append("")
            tg_lines.append(f"리스크 차단: {len(self._risk_gate_blocks)}회")
            # 최근 차단 사유 1건
            latest_block = self._risk_gate_blocks[-1]
            tg_lines.append(
                f"  최근: {latest_block.get('gate', '?')} - "
                f"{latest_block.get('reason', '')[:_MAX_REASON_CHARS_TELEGRAM]}"
            )

        # 포지션 현황
        if overnight:
            tg_lines.append("")
            tg_lines.append(f"보유 포지션: {len(overnight)}건")
            for od in overnight[:_MAX_OVERNIGHT_DISPLAY]:
                ticker = od.get("ticker", "?")
                action = od.get("action", "hold")
                reason = od.get("reason", "")[:_MAX_REASON_CHARS_TELEGRAM]
                tg_lines.append(f"  {ticker}: {action.upper()} - {reason}")

        # 강제 청산
        if liq:
            tg_lines.append("")
            tg_lines.append(f"강제 청산: {len(liq)}건")

        # 연속 분석 최신 센티먼트
        if ca_latest:
            ca_analysis = ca_latest.get("analysis", {})
            if isinstance(ca_analysis, dict):
                sentiment = ca_analysis.get("market_sentiment_shift", {})
                ca_summary = ca_analysis.get("summary", "")
                if sentiment:
                    tg_lines.append("")
                    tg_lines.append(
                        f"시장 심리: {sentiment.get('direction', '?')} "
                        f"(신뢰도 {sentiment.get('confidence', 0) * 100:.0f}%)"
                    )
                if ca_summary:
                    tg_lines.append(ca_summary[:_MAX_SUMMARY_CHARS])

        # 리스크 & AI
        if risk_budget_status:
            tg_lines.append("")
            tg_lines.append(f"리스크 예산: {risk_budget_status.get('remaining_pct', 0):.1f}% 잔여")
        tg_lines.append(
            f"AI: {total_ai_calls}회 ({total_tokens:,}토큰) | "
            f"루프 {self._trading_loop_count}회 | 연속분석 {self._continuous_analysis_count}회"
        )

        await self.telegram_notifier.send_message(
            title="[일일 보고서] 자동매매 일일 종합",
            message="\n".join(tg_lines),
            severity="info",
        )
        logger.info("Telegram 최종 종합 보고서 발송 완료")

        # =====================================================================
        # 2. 마크다운 상세 보고서 (docs/report/latest_report.md)
        # =====================================================================
        try:
            report_dir = Path(__file__).resolve().parent.parent / "docs" / "report"
            os.makedirs(report_dir, exist_ok=True)
            report_path = report_dir / "latest_report.md"

            md: list[str] = [
                "# 자동매매 일일 보고서",
                "",
                f"> 생성 시각: {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}",
                "",
                "---",
                "",
            ]

            # ---------------------------------------------------------------
            # 섹션 1: 수익 요약
            # ---------------------------------------------------------------
            md.append("## 1. 수익 요약")
            md.append("")
            if feedback:
                best_trade = fb_summary.get("best_trade")
                worst_trade = fb_summary.get("worst_trade")
                avg_conf = fb_summary.get("avg_confidence")

                md.append("| 항목 | 값 |")
                md.append("|------|-----|")
                md.append(f"| 일일 손익 (금액) | **${pnl:+.2f}** |")
                md.append(f"| 일일 손익 (%) | **{pnl_pct:+.4f}%** |")
                md.append(f"| 총 거래 건수 | {trade_count}건 |")
                if win_rate is not None:
                    md.append(f"| 승률 | {win_rate:.2f}% |")
                if avg_conf is not None:
                    md.append(f"| 평균 AI 신뢰도 | {avg_conf:.4f} |")
                if best_trade:
                    md.append(
                        f"| 최고 거래 | {best_trade.get('ticker', '?')} "
                        f"({best_trade.get('pnl_pct', 0.0):+.4f}%) |"
                    )
                if worst_trade:
                    md.append(
                        f"| 최저 거래 | {worst_trade.get('ticker', '?')} "
                        f"({worst_trade.get('pnl_pct', 0.0):+.4f}%) |"
                    )
            else:
                md.append("거래 데이터 없음 (오늘 체결된 매매 없음)")
            md.append("")

            # ---------------------------------------------------------------
            # 섹션 2: 세션 요약
            # ---------------------------------------------------------------
            md.append("## 2. 세션 요약")
            md.append("")
            md.append("| 항목 | 값 |")
            md.append("|------|-----|")
            md.append(f"| 세션 시작 | {session_start_kst or 'N/A'} |")
            md.append(f"| 세션 종료 | {session_end_kst} |")
            md.append(f"| 세션 시간 | {session_duration or 'N/A'} |")
            md.append(f"| 매매 루프 실행 | {self._trading_loop_count}회 |")
            md.append(f"| 연속 분석 실행 | {self._continuous_analysis_count}회 |")
            md.append(f"| AI 총 호출 | {total_ai_calls}회 |")
            md.append(f"| AI 총 토큰 | {total_tokens:,} |")
            md.append(f"| 리스크 게이트 차단 | {len(self._risk_gate_blocks)}회 |")
            md.append(f"| AI 매매 판단 생성 | {len(self._today_decisions)}건 |")
            md.append("")

            # ---------------------------------------------------------------
            # 섹션 3: AI 매매 판단 상세
            # ---------------------------------------------------------------
            md.append("## 3. AI 매매 판단 상세")
            md.append("")
            if self._today_decisions:
                md.append(f"총 {len(self._today_decisions)}건의 AI 매매 판단이 생성되었다.")
                md.append("")

                # 액션별 집계
                action_counts: dict[str, int] = {}
                for dec in self._today_decisions:
                    a = dec.get("action", "hold").upper()
                    action_counts[a] = action_counts.get(a, 0) + 1
                action_summary = ", ".join(
                    f"{a}: {c}건" for a, c in sorted(action_counts.items())
                )
                md.append(f"**판단 분포:** {action_summary}")
                md.append("")

                # 개별 판단 상세
                md.append("| # | 루프 | 시각 | 티커 | 판단 | 신뢰도 | 비중 | 방향 | 시간대 | TP/SL |")
                md.append("|---|------|------|------|------|--------|------|------|--------|-------|")
                for idx, dec in enumerate(self._today_decisions, 1):
                    dec_time = ""
                    try:
                        dt_obj = datetime.fromisoformat(dec.get("time", ""))
                        dec_time = dt_obj.astimezone(kst).strftime("%H:%M")
                    except Exception:
                        dec_time = "?"
                    md.append(
                        f"| {idx} "
                        f"| #{dec.get('loop', '?')} "
                        f"| {dec_time} "
                        f"| {dec.get('ticker', '?')} "
                        f"| **{dec.get('action', '?').upper()}** "
                        f"| {dec.get('confidence', 0.0):.2f} "
                        f"| {dec.get('weight_pct', 0.0):.1f}% "
                        f"| {dec.get('direction', '?')} "
                        f"| {dec.get('time_horizon', '?')} "
                        f"| +{dec.get('take_profit_pct', 0.0):.1f}% / -{dec.get('stop_loss_pct', 0.0):.1f}% |"
                    )
                md.append("")

                # 판단 사유 상세 (reason이 있는 것들)
                decisions_with_reason = [
                    d for d in self._today_decisions if d.get("reason")
                ]
                if decisions_with_reason:
                    md.append("### 판단 근거 상세")
                    md.append("")
                    for dec in decisions_with_reason:
                        ticker = dec.get("ticker", "?")
                        action = dec.get("action", "?").upper()
                        confidence = dec.get("confidence", 0.0)
                        reason = dec.get("reason", "")
                        md.append(
                            f"**{ticker} ({action}, 신뢰도 {confidence:.2f}):**"
                        )
                        md.append(f"> {reason}")
                        md.append("")
            else:
                md.append("AI 매매 판단이 생성되지 않았다.")
                md.append("")
                md.append("**가능한 원인:**")
                if self._risk_gate_blocks:
                    md.append("- 리스크 게이트가 매매 루프를 차단하여 AI 판단 단계까지 진행하지 못함")
                elif self._trading_loop_count == 0:
                    md.append("- 정규장 시간이 아니어서 매매 루프가 실행되지 않음")
                else:
                    md.append("- 뉴스 신호가 없거나 분류 결과가 없어 판단 대상이 없었음")
                    md.append("- 리스크 게이트가 사전 체크에서 매매를 차단함")
                md.append("")

            # ---------------------------------------------------------------
            # 섹션 4: 리스크 게이트 차단 내역
            # ---------------------------------------------------------------
            md.append("## 4. 리스크 게이트 차단 내역")
            md.append("")
            if self._risk_gate_blocks:
                md.append(
                    f"세션 동안 총 **{len(self._risk_gate_blocks)}회** 리스크 게이트가 "
                    f"매매를 차단했다."
                )
                md.append("")

                # 게이트별 집계
                gate_summary: dict[str, list[dict[str, Any]]] = {}
                for blk in self._risk_gate_blocks:
                    gate_name = blk.get("gate", "unknown")
                    if gate_name not in gate_summary:
                        gate_summary[gate_name] = []
                    gate_summary[gate_name].append(blk)

                md.append("### 게이트별 차단 요약")
                md.append("")
                md.append("| 게이트 | 차단 횟수 | 조치 | 최근 사유 |")
                md.append("|--------|----------|------|----------|")
                for gate_name, blocks in sorted(
                    gate_summary.items(), key=lambda x: -len(x[1])
                ):
                    latest = blocks[-1]
                    reason_text = latest.get("reason", "")[:_MAX_REASON_CHARS_MARKDOWN]
                    action_text = latest.get("action", "?")
                    md.append(
                        f"| {gate_name} | {len(blocks)}회 | {action_text} | {reason_text} |"
                    )
                md.append("")

                # 차단 타임라인
                md.append("### 차단 타임라인")
                md.append("")
                for blk in self._risk_gate_blocks:
                    blk_time = ""
                    try:
                        dt_obj = datetime.fromisoformat(blk.get("time", ""))
                        blk_time = dt_obj.astimezone(kst).strftime("%H:%M")
                    except Exception:
                        blk_time = "?"
                    ticker_info = f" ({blk['ticker']})" if blk.get("ticker") else ""
                    md.append(
                        f"- **{blk_time}** [루프 #{blk.get('loop', '?')}] "
                        f"`{blk.get('gate', '?')}`{ticker_info}: "
                        f"{blk.get('reason', 'N/A')}"
                    )
                md.append("")
            else:
                md.append("리스크 게이트 차단 없음 - 세션 동안 매매 제한이 발생하지 않았다.")
                md.append("")

            # ---------------------------------------------------------------
            # 섹션 5: 연속 분석 타임라인
            # ---------------------------------------------------------------
            md.append("## 5. 연속 분석 타임라인")
            md.append("")
            if ca_history:
                md.append(
                    f"30분 간격으로 총 **{len(ca_history)}회** 연속 분석을 수행했다."
                )
                md.append("")
                md.append("| # | 시간 범위 | 새 기사 | 센티먼트 | 신뢰도 | 핵심 이슈 수 |")
                md.append("|---|----------|--------|----------|--------|------------|")
                for ca_item in ca_history:
                    ca_iter = ca_item.get("iteration", "?")
                    ca_time = ca_item.get("time_range", "?")
                    ca_new = ca_item.get("crawl", {}).get("saved", 0)
                    ca_an = ca_item.get("analysis", {})
                    if isinstance(ca_an, dict):
                        ca_sent = ca_an.get("market_sentiment_shift", {})
                        ca_dir = ca_sent.get("direction", "?")
                        ca_conf = ca_sent.get("confidence", 0) * 100
                        ca_issues = ca_an.get("key_issues", [])
                        ca_issue_count = len(ca_issues)
                    else:
                        ca_dir = "?"
                        ca_conf = 0
                        ca_issue_count = 0
                    md.append(
                        f"| #{ca_iter} | {ca_time} | {ca_new}건 "
                        f"| {ca_dir} | {ca_conf:.0f}% | {ca_issue_count}건 |"
                    )
                md.append("")

                # 최신 분석 상세
                if ca_latest:
                    ca_an = ca_latest.get("analysis", {})
                    if isinstance(ca_an, dict):
                        ca_summary_text = ca_an.get("summary", "")
                        if ca_summary_text:
                            md.append("### 최신 분석 요약")
                            md.append("")
                            md.append(ca_summary_text)
                            md.append("")

                        key_issues = ca_an.get("key_issues", [])
                        if key_issues:
                            md.append("### 핵심 이슈 목록")
                            md.append("")
                            md.append("| 이슈 | 영향도 | 상태 | 관련 종목 |")
                            md.append("|------|--------|------|----------|")
                            for issue in key_issues:
                                i_title = issue.get("title", "?")
                                i_impact = issue.get("impact", "?").upper()
                                i_status = issue.get("status", "?")
                                i_tickers = ", ".join(
                                    issue.get("affected_tickers", [])[:5]
                                )
                                md.append(
                                    f"| {i_title} | {i_impact} | {i_status} | {i_tickers} |"
                                )
                            md.append("")

                        new_risks = ca_an.get("new_risks", [])
                        if new_risks:
                            md.append("### 신규 리스크")
                            md.append("")
                            for risk in new_risks:
                                severity = risk.get("severity", "?").upper()
                                risk_desc = risk.get("risk", "?")
                                md.append(f"- **[{severity}]** {risk_desc}")
                            md.append("")
            else:
                md.append("연속 분석 데이터 없음 (금일 연속 분석이 실행되지 않았다)")
                md.append("")

            # ---------------------------------------------------------------
            # 섹션 6: 포지션 현황
            # ---------------------------------------------------------------
            md.append("## 6. 포지션 현황")
            md.append("")
            positions_list = portfolio.get("positions", [])
            if positions_list:
                md.append(f"보유 포지션: **{len(positions_list)}건**")
                md.append(f"- 총 자산: ${portfolio.get('total_value', 0):,.2f}")
                md.append(f"- 현금: ${portfolio.get('cash', 0):,.2f}")
                md.append("")
                md.append("| 티커 | 종목명 | 수량 | 매입가 | 현재가 | 평가금액 | 손익률 | 손익금액 | 보유일 |")
                md.append("|------|--------|------|--------|--------|---------|--------|---------|--------|")
                for pos in positions_list:
                    p_ticker = pos.get("ticker", "?")
                    p_name = pos.get("name", "")[:15]
                    p_qty = pos.get("quantity", 0)
                    p_avg = pos.get("avg_price", 0.0)
                    p_cur = pos.get("current_price", 0.0)
                    p_mval = pos.get("market_value", 0.0)
                    p_pnl_pct = pos.get("pnl_pct", 0.0)
                    p_pnl_amt = pos.get("pnl_amount", 0.0)
                    p_days = pos.get("hold_days", 0)
                    md.append(
                        f"| {p_ticker} | {p_name} | {p_qty} "
                        f"| ${p_avg:.2f} | ${p_cur:.2f} "
                        f"| ${p_mval:,.2f} | {p_pnl_pct:+.2f}% "
                        f"| ${p_pnl_amt:+.2f} | {p_days}일 |"
                    )
            else:
                md.append("보유 포지션 없음")
            md.append("")

            # ---------------------------------------------------------------
            # 섹션 7: 오버나잇 판단
            # ---------------------------------------------------------------
            md.append("## 7. 오버나잇 판단")
            md.append("")
            if overnight:
                md.append(f"**{len(overnight)}건** 포지션에 대해 오버나잇 판단을 수행했다.")
                md.append("")
                md.append("| 티커 | 결정 | 신뢰도 | 리스크 | 사유 |")
                md.append("|------|------|--------|--------|------|")
                for od in overnight:
                    od_ticker = od.get("ticker", "?")
                    od_decision = od.get("decision", od.get("action", "hold")).upper()
                    od_conf = od.get("confidence", 0.0)
                    od_risk = od.get("overnight_risk", "?")
                    od_reason = od.get("reason", "")
                    md.append(
                        f"| {od_ticker} | **{od_decision}** "
                        f"| {od_conf:.2f} | {od_risk} "
                        f"| {od_reason} |"
                    )
                md.append("")

                # 판단 근거 상세 (reason이 긴 경우)
                detailed_overnight = [
                    od for od in overnight if len(od.get("reason", "")) > 80
                ]
                if detailed_overnight:
                    md.append("### 오버나잇 판단 근거 상세")
                    md.append("")
                    for od in detailed_overnight:
                        od_ticker = od.get("ticker", "?")
                        od_decision = od.get("decision", od.get("action", "hold")).upper()
                        od_risk = od.get("overnight_risk", "?")
                        md.append(
                            f"**{od_ticker} ({od_decision}, 리스크: {od_risk}):**"
                        )
                        md.append(f"> {od.get('reason', '')}")
                        md.append("")
            else:
                md.append("오버나잇 판단 대상 포지션 없음")
                md.append("")

            # ---------------------------------------------------------------
            # 섹션 8: 시장 레짐 & 지표
            # ---------------------------------------------------------------
            md.append("## 8. 시장 레짐 & 지표")
            md.append("")

            regime_name = regime_data.get("regime", "N/A")
            vix_val = regime_data.get("vix", 0.0)

            regime_kr_map = {
                "strong_bull": "강세장 (Strong Bull)",
                "mild_bull": "약세장 (Mild Bull)",
                "sideways": "횡보장 (Sideways)",
                "mild_bear": "약세장 (Mild Bear)",
                "crash": "폭락장 (Crash)",
            }
            regime_kr = regime_kr_map.get(regime_name, regime_name)

            md.append("| 지표 | 값 |")
            md.append("|------|-----|")
            md.append(f"| 시장 레짐 | **{regime_kr}** |")
            md.append(f"| VIX | {vix_val:.2f} |")

            # 연속 분석의 최신 센티먼트
            if ca_latest:
                ca_an = ca_latest.get("analysis", {})
                if isinstance(ca_an, dict):
                    ca_sent = ca_an.get("market_sentiment_shift", {})
                    if ca_sent:
                        md.append(
                            f"| 시장 심리 | {ca_sent.get('direction', '?')} "
                            f"(신뢰도 {ca_sent.get('confidence', 0) * 100:.0f}%) |"
                        )

            # 리스크 예산
            if risk_budget_status:
                md.append(
                    f"| 리스크 예산 잔여 | {risk_budget_status.get('remaining_pct', 0):.1f}% |"
                )

            md.append("")

            # ---------------------------------------------------------------
            # 섹션 9: AI 분석 요약 (피드백)
            # ---------------------------------------------------------------
            md.append("## 9. AI 분석 요약")
            md.append("")
            if feedback and isinstance(fb_analysis, dict):
                overall = fb_analysis.get("overall_assessment", "")
                market_read = fb_analysis.get("market_reading", "")
                strengths = fb_analysis.get("strengths", [])
                weaknesses = fb_analysis.get("weaknesses", [])
                if overall:
                    md.append(f"**종합 평가:** {overall}")
                    md.append("")
                if market_read:
                    md.append(f"**시장 분석:** {market_read}")
                    md.append("")
                if strengths:
                    md.append("**강점:**")
                    for s in strengths:
                        md.append(f"- {s}")
                    md.append("")
                if weaknesses:
                    md.append("**약점/개선점:**")
                    for w in weaknesses:
                        md.append(f"- {w}")
                    md.append("")
                improvements = feedback.get("improvements", [])
                if improvements:
                    md.append("**개선 사항:**")
                    for imp in improvements:
                        md.append(f"- {imp}")
                    md.append("")
            else:
                md.append("AI 분석 데이터 없음")
                md.append("")

            # ---------------------------------------------------------------
            # 섹션 10: 강제 청산
            # ---------------------------------------------------------------
            if liq:
                md.append("## 10. 강제 청산")
                md.append("")
                md.append(f"강제 청산 건수: **{len(liq)}건**")
                md.append("")
                for l_item in liq:
                    if isinstance(l_item, dict):
                        md.append(
                            f"- {l_item.get('ticker', '?')}: {l_item.get('reason', 'N/A')}"
                        )
                md.append("")

            # ---------------------------------------------------------------
            # 섹션 11: AI 사용량
            # ---------------------------------------------------------------
            md.append("## 11. AI 사용량")
            md.append("")
            md.append("| 항목 | 값 |")
            md.append("|------|-----|")
            md.append(f"| 총 호출 수 | {total_ai_calls}회 |")
            md.append(
                f"| 입력 토큰 | {ai_usage.get('total_input_tokens', 0):,} |"
            )
            md.append(
                f"| 출력 토큰 | {ai_usage.get('total_output_tokens', 0):,} |"
            )
            md.append(f"| 총 토큰 | {total_tokens:,} |")
            md.append("")

            # ---------------------------------------------------------------
            # 푸터
            # ---------------------------------------------------------------
            md.append("---")
            md.append("")
            md.append("*자동매매 시스템 V2 자동 생성*")

            report_path.write_text("\n".join(md), encoding="utf-8")
            logger.info("일일 보고서 파일 저장 완료 | path=%s", report_path)
        except Exception as report_exc:
            logger.warning("일일 보고서 파일 저장 실패: %s", report_exc)

    @staticmethod
    def _load_or_create_auth(
        app_key: str,
        app_secret: str,
        account: str,
        virtual: bool,
        token_path: Path,
    ) -> KISAuth:
        """캐시된 토큰이 유효하면 복원하고, 없으면 새 인스턴스를 생성한다.

        app_key / app_secret은 .env에서만 읽으며 파일에 저장하지 않는다.
        """
        try:
            auth = KISAuth.from_token_cache(
                app_key=app_key,
                app_secret=app_secret,
                account=account,
                virtual=virtual,
                path=token_path,
            )
            if auth.access_token:
                logger.info("KIS 토큰 복원 성공: %s", token_path.name)
            return auth
        except Exception as e:
            logger.warning("KIS 토큰 로드 실패, 새 인스턴스 생성: %s", e)
            return KISAuth(
                app_key=app_key,
                app_secret=app_secret,
                account=account,
                virtual=virtual,
            )

    async def run_continuous_crawl_analysis(self) -> dict[str, Any]:
        """30분 단위 연속 크롤링 + Opus 분석을 1회 실행한다.

        실제 로직은 src.orchestration.continuous_analysis 모듈에 위임한다.

        Returns:
            분석 결과 딕셔너리.
        """
        from src.orchestration.continuous_analysis import run_continuous_crawl_analysis
        return await run_continuous_crawl_analysis(self)

    async def _fetch_vix(self) -> float:
        """현재 VIX 지수를 가져온다. 실패 시 기본값(_VIX_DEFAULT_FALLBACK)을 반환한다."""
        try:
            vix = await self.data_fetcher.get_vix()
            if vix <= 0.0:
                logger.warning("VIX 값이 0 이하(%.2f), 기본값 %.1f 사용", vix, _VIX_DEFAULT_FALLBACK)
                return _VIX_DEFAULT_FALLBACK
            return vix
        except Exception as e:
            logger.warning("VIX 조회 실패, 기본값 %.1f 사용: %s", _VIX_DEFAULT_FALLBACK, e)
            return _VIX_DEFAULT_FALLBACK

    async def _get_current_regime(self) -> dict[str, Any]:
        """현재 시장 레짐을 가져온다 (Redis 캐시 또는 재계산).

        Redis에 캐시된 레짐이 있으면 사용하고 (5분 TTL),
        없으면 VIX 기반으로 재계산하여 캐시에 저장한다.

        Returns:
            regime, vix, timestamp 키를 포함하는 딕셔너리.
        """
        import json as _json

        cache_key = "trading:current_regime"

        # Redis 캐시 확인
        if self.redis is not None:
            try:
                cached = await self.redis.get(cache_key)
                if cached is not None:
                    return _json.loads(cached)
            except Exception as exc:
                logger.debug("레짐 캐시 조회 실패 (무시): %s", exc)

        # 캐시 미스: VIX 기반 재계산
        vix = await self._fetch_vix()
        regime_name = "sideways"
        if vix < _VIX_STRONG_BULL:
            regime_name = "strong_bull"
        elif vix < _VIX_MILD_BULL:
            regime_name = "mild_bull"
        elif vix < _VIX_SIDEWAYS:
            regime_name = "sideways"
        elif vix < _VIX_MILD_BEAR:
            regime_name = "mild_bear"
        else:
            regime_name = "crash"

        result = {
            "regime": regime_name,
            "vix": vix,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

        # Redis에 캐시 저장 (5분 TTL)
        if self.redis is not None:
            try:
                await self.redis.set(
                    cache_key,
                    _json.dumps(result, default=str),
                    ex=_REGIME_CACHE_TTL,
                )
            except Exception as exc:
                logger.debug("레짐 캐시 저장 실패 (무시): %s", exc)

        return result

    async def _execute_decisions(
        self,
        decisions: list[dict[str, Any]],
        portfolio: dict[str, Any],
        vix: float,
    ) -> list[dict[str, Any]]:
        """트레이딩 결정을 실행한다."""
        results = []

        for decision in decisions:
            try:
                action = decision.get("action")

                # 주문 단위 리스크 게이트 체크 (Addendum 26.14 step 4)
                if action in ("buy", "sell"):
                    order_gate = await self.risk_gate_pipeline.check_order(
                        order=decision,
                        portfolio=portfolio,
                    )
                    if not order_gate.passed:
                        logger.warning(
                            "주문 리스크 검증 실패: ticker=%s action=%s | %s",
                            decision.get("ticker"), action, order_gate.message,
                        )
                        results.append({
                            "decision": decision,
                            "skipped": True,
                            "reason": order_gate.message,
                            "success": False,
                        })
                        continue

                if action == "buy":
                    # Evaluate entry via entry strategy
                    entry_signals = [decision]
                    indicators = await self._fetch_indicators_for_ticker(
                        decision.get("ticker", "")
                    )
                    regime_dict = await self._get_current_regime()

                    # _get_current_regime()는 dict를 반환한다.
                    # evaluate_entry()는 str 타입의 regime과 float 타입의 vix를 요구한다.
                    regime_str = (
                        regime_dict.get("regime", "sideways")
                        if isinstance(regime_dict, dict)
                        else str(regime_dict)
                    )
                    vix_val = (
                        regime_dict.get("vix", vix)
                        if isinstance(regime_dict, dict)
                        else vix
                    )

                    entry_evaluations = self.entry_strategy.evaluate_entry(
                        entry_signals,
                        indicators,
                        regime_str,
                        portfolio,
                        vix_val,
                    )

                    # Execute approved entries
                    for evaluation in entry_evaluations:
                        if evaluation.get("approved", False):
                            result = await self.order_manager.execute_entry(
                                evaluation,
                                portfolio,
                                vix,
                            )
                            # AI 매매 결정을 결과에 첨부하여 텔레그램 알림에 활용
                            if result is not None:
                                result["_ai_decision"] = decision
                            results.append(result)

                elif action == "sell":
                    # Find position and execute exit
                    # portfolio["positions"] is a list[dict], not a dict keyed by ticker.
                    ticker = decision.get("ticker")
                    positions_list = portfolio.get("positions", [])
                    position = next(
                        (p for p in positions_list if p.get("ticker") == ticker),
                        None,
                    )
                    if position:
                        result = await self.order_manager.execute_exit(
                            decision,
                            position,
                        )
                        # AI 매매 결정을 결과에 첨부하여 텔레그램 알림에 활용
                        if result is not None:
                            result["_ai_decision"] = decision
                        results.append(result)

            except Exception as e:
                logger.error("Failed to execute decision %s: %s", decision, e)
                results.append({
                    "decision": decision,
                    "error": str(e),
                    "success": False,
                })

        return results

    async def _execute_overnight_sell(self, decision: dict[str, Any]) -> None:
        """Overnight 판단에 따라 매도를 실행한다."""
        try:
            ticker = decision.get("ticker")
            portfolio = await self.position_monitor.get_portfolio_summary()
            # portfolio["positions"] is a list[dict], not a dict keyed by ticker.
            positions_list = portfolio.get("positions", [])
            position = next(
                (p for p in positions_list if p.get("ticker") == ticker),
                None,
            )

            if position:
                await self.order_manager.execute_exit(decision, position)
                logger.info("Overnight sell executed: %s", ticker)
        except Exception as e:
            logger.error("Failed to execute overnight sell %s: %s", decision, e)


async def main() -> None:
    """메인 진입점.

    API 서버를 시작하고 종료 신호를 기다린다.
    자동매매 루프는 API 엔드포인트(/api/trading/start)를 통해 시작한다.
    """
    system = TradingSystem()
    _shutdown_event = asyncio.Event()

    # 종료 신호 핸들러 — SIGINT / SIGTERM 수신 시 매매를 중단하고 이벤트를 설정한다.
    def signal_handler(sig: signal.Signals) -> None:
        logger.info("Received signal %s, initiating graceful shutdown...", sig)
        system.running = False
        _shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    try:
        # 모든 모듈 초기화
        await system.initialize()

        # FastAPI 모니터링 서버를 백그라운드에서 시작한다.
        system.api_server_task = asyncio.create_task(system.start_api_server())

        # 서버가 요청을 수락할 때까지 잠시 대기한다.
        await asyncio.sleep(_SHUTDOWN_GRACE_PERIOD)

        logger.info(
            "API 서버 준비 완료. 자동매매 시작 명령을 기다립니다. "
            "(POST /api/trading/start)"
        )

        # 종료 신호가 올 때까지 대기한다. 매매 루프는 API 호출로 시작/중지된다.
        await _shutdown_event.wait()

    except Exception as e:
        logger.exception("Fatal error in main: %s", e)
        if system.alert_manager:
            try:
                await system.alert_manager.send_alert(
                    "system", "Fatal error", str(e), "critical",
                )
            except Exception as exc:
                logger.debug("치명적 오류 알림 전송 실패: %s", exc)
    finally:
        # 아직 실행 중인 매매 루프가 있으면 EOD 없이 즉시 중단한다.
        if system.running:
            await system.stop_trading(run_eod=False)

        logger.info("Running shutdown sequence (timeout=%.0fs)...", _SHUTDOWN_TIMEOUT)
        try:
            await asyncio.wait_for(system.shutdown(), timeout=_SHUTDOWN_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning(
                "Shutdown timed out after %.0f seconds, forcing exit.", _SHUTDOWN_TIMEOUT
            )
        except Exception as exc:
            logger.error("Error during shutdown: %s", exc)
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
