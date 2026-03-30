"""F9.2 DependencyInjector -- Feature 매니저에 Common 인프라를 주입한다.

SystemComponents를 받아 InjectedSystem을 조립한다.
F1~F10 Feature 인스턴스를 생성하고 등록한다. (F10 = Self-Healing)
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.common.logger import get_logger
from src.orchestration.init.system_initializer import SystemComponents

logger = get_logger(__name__)


class InjectedSystem(BaseModel):
    """의존성 주입이 완료된 시스템이다."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    components: SystemComponents
    # Feature 매니저를 동적으로 등록한다
    features: dict[str, object] = {}
    # 실행 상태
    running: bool = False
    trading_task: object | None = None  # asyncio.Task


def _register_feature(
    system: InjectedSystem,
    name: str,
    instance: object,
) -> None:
    """Feature 매니저를 시스템에 등록한다.

    Args:
        system: 주입 대상 시스템
        name: Feature 식별 키 (예: "crawler", "safety")
        instance: Feature 매니저 인스턴스
    """
    if name in system.features:
        logger.warning("Feature '%s' 중복 등록 -- 기존 인스턴스를 덮어쓴다", name)
    system.features[name] = instance
    logger.info("Feature 등록 완료: %s", name)


def _inject_f1_crawl(system: InjectedSystem) -> None:
    """F1 크롤링 파이프라인을 초기화하고 등록한다."""
    try:
        from src.crawlers.dedup.article_dedup import ArticleDeduplicator
        from src.crawlers.engine.crawl_engine import CrawlEngine
        from src.crawlers.scheduler.crawl_scheduler import CrawlScheduler
        from src.crawlers.sources.api_crawler import ApiCrawler
        from src.crawlers.sources.rss_crawler import RssCrawler
        from src.crawlers.verifier.crawl_verifier import CrawlVerifier

        c = system.components
        rss = RssCrawler(c.http)
        api = ApiCrawler(c.http, c.vault)
        verifier = CrawlVerifier()
        dedup = ArticleDeduplicator(c.cache)
        engine = CrawlEngine([rss, api], verifier, dedup, c.event_bus)
        scheduler = CrawlScheduler(c.clock)

        _register_feature(system, "crawl_engine", engine)
        _register_feature(system, "crawl_scheduler", scheduler)
        _register_feature(system, "article_deduplicator", dedup)
    except Exception as exc:
        logger.warning("F1 CrawlEngine 초기화 실패 (건너뜀): %s", exc)


def _inject_f2_analysis(system: InjectedSystem) -> None:
    """F2 AI 분석 모듈을 초기화하고 등록한다."""
    try:
        from src.analysis.classifier.key_news_filter import KeyNewsFilter
        from src.analysis.classifier.news_classifier import NewsClassifier
        from src.analysis.decision.decision_maker import DecisionMaker
        from src.analysis.decision.overnight_judge import OvernightJudge
        from src.analysis.regime.regime_detector import RegimeDetector
        from src.analysis.team.comprehensive_team import ComprehensiveTeam

        c = system.components
        _register_feature(system, "news_classifier", NewsClassifier(c.ai))
        _register_feature(system, "regime_detector", RegimeDetector())
        _register_feature(system, "comprehensive_team", ComprehensiveTeam(c.ai))
        _register_feature(system, "decision_maker", DecisionMaker(c.event_bus))
        _register_feature(system, "overnight_judge", OvernightJudge())
        _register_feature(system, "key_news_filter", KeyNewsFilter())

        from src.analysis.feedback.eod_feedback_report import EODFeedbackReport
        _register_feature(system, "eod_feedback", EODFeedbackReport(c.ai))

        # 반복 테마 감지 -- 캐시에 카테고리+방향 빈도를 누적한다
        from src.analysis.classifier.news_theme_tracker import NewsThemeTracker
        _register_feature(system, "news_theme_tracker", NewsThemeTracker(c.cache))

        # 진행 상황 추적 -- 장기 지속 이슈 타임라인을 캐시에 관리한다
        from src.analysis.classifier.situation_tracker import OngoingSituationTracker
        _register_feature(system, "situation_tracker", OngoingSituationTracker(c.cache, c.ai))

        # 뉴스 번역기 -- MLX 로컬 모델로 제목을 한국어 번역한다
        from src.analysis.classifier.news_translator import NewsTranslator
        _register_feature(system, "news_translator", NewsTranslator(c.ai))
    except Exception as exc:
        logger.warning("F2 Analysis 초기화 실패 (건너뜀): %s", exc)


def _inject_f3_indicators(system: InjectedSystem) -> None:
    """F3 지표 모듈을 초기화하고 등록한다."""
    # C1 수정: 엔드포인트가 기대하는 키명 "indicator_bundle_builder"로 정확히 등록한다
    try:
        from src.indicators.price.price_data_fetcher import PriceDataFetcher

        c = system.components
        _register_feature(system, "price_fetcher", PriceDataFetcher(c.broker))

        from src.indicators.bundle_builder import IndicatorBundleBuilder
        _finnhub_key = c.vault.get_secret_or_none("FINNHUB_API_KEY")
        builder = IndicatorBundleBuilder(
            c.broker, c.cache, system.components.registry,
            http=c.http, finnhub_api_key=_finnhub_key,
        )
        # indicators.py 엔드포인트가 "indicator_bundle_builder" 키를 조회하므로 일치시킨다
        _register_feature(system, "indicator_bundle_builder", builder)
    except Exception as exc:
        logger.warning("F3 Indicators 초기화 실패 (건너뜀): %s", exc)

    try:
        from src.indicators.misc.vix_fetcher import VixFetcher

        c = system.components
        vix_fetcher = VixFetcher(c.cache, c.http, c.vault)
        _register_feature(system, "vix_fetcher", vix_fetcher)
    except Exception as exc:
        logger.warning("F3 VixFetcher 초기화 실패 (건너뜀): %s", exc)

    # 고래 트래커 -- 블록 거래와 아이스버그 주문을 감지한다
    try:
        from src.indicators.whale.whale_tracker import WhaleTracker

        c = system.components
        _register_feature(system, "whale_tracker", WhaleTracker(c.cache))
    except ImportError as exc:
        logger.warning("F3 WhaleTracker 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F3 WhaleTracker 초기화 실패 (건너뜀): %s", exc)

    # 볼륨 프로파일 -- POC + Value Area 70%를 계산한다
    try:
        from src.indicators.volume_profile.volume_profile import VolumeProfile

        _register_feature(system, "volume_profile", VolumeProfile())
    except ImportError as exc:
        logger.warning("F3 VolumeProfile 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F3 VolumeProfile 초기화 실패 (건너뜀): %s", exc)

    # 콘탱고 감지기 -- VIX 기간구조 + 레버리지 드래그를 분석한다
    try:
        from src.indicators.misc.contango_detector import ContangoDetector

        c = system.components
        _register_feature(system, "contango_detector", ContangoDetector(c.cache, c.broker))
    except ImportError as exc:
        logger.warning("F3 ContangoDetector 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F3 ContangoDetector 초기화 실패 (건너뜀): %s", exc)

    # NAV 프리미엄 트래커 -- 레버리지 ETF의 프리미엄/디스카운트를 추적한다
    try:
        from src.indicators.misc.nav_premium_tracker import NAVPremiumTracker

        c = system.components
        _register_feature(system, "nav_premium_tracker", NAVPremiumTracker(c.broker))
    except ImportError as exc:
        logger.warning("F3 NAVPremiumTracker 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F3 NAVPremiumTracker 초기화 실패 (건너뜀): %s", exc)

    # 레버리지 디케이 계산기 -- 변동성 드래그를 정량화한다
    try:
        from src.indicators.misc.leverage_decay import LeverageDecay

        _register_feature(system, "leverage_decay", LeverageDecay())
    except ImportError as exc:
        logger.warning("F3 LeverageDecay 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F3 LeverageDecay 초기화 실패 (건너뜀): %s", exc)

    # 주문 흐름 집계기 -- WebSocket 체결 데이터로 OBI/CVD/VPIN을 계산한다
    try:
        from src.indicators.misc.order_flow_aggregator import OrderFlowAggregator

        c = system.components
        _register_feature(system, "order_flow_aggregator", OrderFlowAggregator(c.cache))
    except ImportError as exc:
        logger.warning("F3 OrderFlowAggregator 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F3 OrderFlowAggregator 초기화 실패 (건너뜀): %s", exc)

    # -- 외부 데이터 소스 (F3-ext) --
    _inject_f3_external(system)


def _inject_f3_external(system: InjectedSystem) -> None:
    """F3-ext 외부 데이터 수집기를 초기화하고 등록한다.

    Polymarket, Trading Economics, ETFdb, Macrotrends, TipRanks, Dataroma
    6개 소스를 등록한다. 개별 실패 시 해당 소스만 건너뛴다.
    """
    c = system.components

    # Polymarket 예측시장 확률 수집기이다
    try:
        from src.indicators.external.polymarket_fetcher import PolymarketFetcher
        _register_feature(system, "polymarket_fetcher", PolymarketFetcher(c.cache, c.http))
    except Exception as exc:
        logger.warning("F3-ext Polymarket 초기화 실패 (건너뜀): %s", exc)

    # Trading Economics 경제 캘린더 수집기이다
    try:
        from src.indicators.external.tradingeconomics_fetcher import TradingEconomicsFetcher
        _register_feature(
            system, "tradingeconomics_fetcher", TradingEconomicsFetcher(c.cache, c.http),
        )
    except Exception as exc:
        logger.warning("F3-ext TradingEconomics 초기화 실패 (건너뜀): %s", exc)

    # ETFdb 자금 유출입 수집기이다
    try:
        from src.indicators.external.etf_flow_fetcher import EtfFlowFetcher
        _register_feature(system, "etf_flow_fetcher", EtfFlowFetcher(c.cache, c.http))
    except Exception as exc:
        logger.warning("F3-ext EtfFlowFetcher 초기화 실패 (건너뜀): %s", exc)

    # Macrotrends 밸류에이션 수집기이다
    try:
        from src.indicators.external.macrotrends_fetcher import MacrotrendsFetcher
        _register_feature(system, "macrotrends_fetcher", MacrotrendsFetcher(c.cache, c.http))
    except Exception as exc:
        logger.warning("F3-ext Macrotrends 초기화 실패 (건너뜀): %s", exc)

    # TipRanks 애널리스트 컨센서스 수집기이다
    try:
        from src.indicators.external.tipranks_fetcher import TipRanksFetcher
        _register_feature(system, "tipranks_fetcher", TipRanksFetcher(c.cache, c.http))
    except Exception as exc:
        logger.warning("F3-ext TipRanks 초기화 실패 (건너뜀): %s", exc)

    # Dataroma 슈퍼인베스터 포트폴리오 추적기이다
    try:
        from src.indicators.external.dataroma_fetcher import DataromaFetcher
        _register_feature(system, "dataroma_fetcher", DataromaFetcher(c.cache, c.http))
    except Exception as exc:
        logger.warning("F3-ext Dataroma 초기화 실패 (건너뜀): %s", exc)


def _inject_f4_strategy(system: InjectedSystem) -> None:
    """F4 전략 모듈을 초기화하고 등록한다."""
    try:
        from src.strategy.entry.entry_strategy import EntryStrategy
        from src.strategy.exit.exit_strategy import ExitStrategy
        from src.strategy.params.strategy_params import StrategyParamsManager

        _register_feature(system, "entry_strategy", EntryStrategy())
        c = system.components
        _register_feature(system, "exit_strategy", ExitStrategy(cache=c.cache))
        _register_feature(system, "strategy_params", StrategyParamsManager())

        from src.strategy.params.profit_target import ProfitTarget
        _register_feature(system, "profit_target", ProfitTarget())
    except Exception as exc:
        logger.warning("F4 Strategy 초기화 실패 (건너뜀): %s", exc)

    # Beast Mode -- A+ 셋업 고확신 매매 판단기이다
    try:
        from src.strategy.beast_mode.beast_mode import BeastMode

        _register_feature(system, "beast_mode", BeastMode())
    except ImportError as exc:
        logger.warning("F4 BeastMode 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F4 BeastMode 초기화 실패 (건너뜀): %s", exc)

    # StatArb -- Z-Score 기반 통계적 차익거래 신호를 생성한다
    try:
        from src.strategy.stat_arb.stat_arb import StatArb

        _register_feature(system, "stat_arb", StatArb())
    except ImportError as exc:
        logger.warning("F4 StatArb 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F4 StatArb 초기화 실패 (건너뜀): %s", exc)

    # MicroRegime -- 5분봉 기반 미시 레짐 분류기이다
    try:
        from src.strategy.micro_regime.micro_regime import MicroRegime

        _register_feature(system, "micro_regime", MicroRegime())
    except ImportError as exc:
        logger.warning("F4 MicroRegime 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F4 MicroRegime 초기화 실패 (건너뜀): %s", exc)

    # NewsFading -- 뉴스 스파이크 역방향 페이딩 신호를 생성한다
    try:
        from src.strategy.news_fading.news_fading import NewsFading

        _register_feature(system, "news_fading", NewsFading())
    except ImportError as exc:
        logger.warning("F4 NewsFading 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F4 NewsFading 초기화 실패 (건너뜀): %s", exc)

    # Pyramiding -- 3단계 추가 진입 판단기이다
    try:
        from src.strategy.pyramiding.pyramiding import Pyramiding

        _register_feature(system, "pyramiding", Pyramiding())
    except ImportError as exc:
        logger.warning("F4 Pyramiding 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F4 Pyramiding 초기화 실패 (건너뜀): %s", exc)

    # SectorRotation -- 7개 섹터 상대강도를 분석한다
    try:
        from src.strategy.sector_rotation.sector_rotation import SectorRotation

        _register_feature(system, "sector_rotation", SectorRotation())
    except ImportError as exc:
        logger.warning("F4 SectorRotation 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F4 SectorRotation 초기화 실패 (건너뜀): %s", exc)

    # WickCatcher -- 하방 윅 역방향 진입 판단기이다
    try:
        from src.strategy.wick_catcher.wick_catcher import WickCatcher

        _register_feature(system, "wick_catcher", WickCatcher())
    except ImportError as exc:
        logger.warning("F4 WickCatcher 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F4 WickCatcher 초기화 실패 (건너뜀): %s", exc)


def _inject_f5_executor(system: InjectedSystem) -> None:
    """F5 주문 실행 모듈을 초기화하고 등록한다."""
    try:
        from src.executor.order.order_manager import OrderManager
        from src.executor.position.position_monitor import PositionMonitor

        c = system.components
        order_mgr = OrderManager(c.broker, cache=c.cache)
        pos_monitor = PositionMonitor(c.broker)

        _register_feature(system, "order_manager", order_mgr)
        _register_feature(system, "position_monitor", pos_monitor)
    except Exception as exc:
        logger.warning("F5 Executor 초기화 실패 (건너뜀): %s", exc)


def _inject_f6_safety(system: InjectedSystem) -> None:
    """F6 안전 장치 모듈을 초기화하고 등록한다."""
    try:
        from src.safety.emergency.emergency_protocol import EmergencyProtocol
        from src.safety.guards.capital_guard import CapitalGuard
        from src.safety.hard_safety.hard_safety import HardSafety
        from src.safety.hard_safety.safety_checker import SafetyChecker

        _register_feature(system, "hard_safety", HardSafety())
        _register_feature(system, "safety_checker", SafetyChecker())
        _register_feature(system, "emergency_protocol", EmergencyProtocol())
        _register_feature(system, "capital_guard", CapitalGuard())
    except Exception as exc:
        logger.warning("F6 Safety 초기화 실패 (건너뜀): %s", exc)

    # TiltDetector -- 감정적 매매를 방지하는 심리 보호기이다
    try:
        from src.risk.psychology.tilt_detector import TiltDetector

        _register_feature(system, "tilt_detector", TiltDetector())
    except ImportError as exc:
        logger.warning("F6 TiltDetector 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F6 TiltDetector 초기화 실패 (건너뜀): %s", exc)

    # GapRiskProtector -- 갭 리스크를 4단계로 분류하는 보호기이다
    try:
        from src.risk.gates.gap_risk import GapRiskProtector

        _register_feature(system, "gap_risk_protector", GapRiskProtector())
    except ImportError as exc:
        logger.warning("F6 GapRiskProtector 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F6 GapRiskProtector 초기화 실패 (건너뜀): %s", exc)

    # StopLossManager -- ATR 동적 손절가 + 트레일링을 관리한다
    try:
        from src.risk.gates.stop_loss import StopLossManager
        _register_feature(system, "stop_loss", StopLossManager())
    except ImportError as exc:
        logger.warning("F6 StopLossManager 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F6 StopLossManager 초기화 실패 (건너뜀): %s", exc)

    # LosingStreakDetector -- 연속 손실을 추적하는 감지기이다
    try:
        from src.risk.gates.losing_streak import LosingStreakDetector
        _register_feature(system, "losing_streak", LosingStreakDetector())
    except ImportError as exc:
        logger.warning("F6 LosingStreakDetector 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F6 LosingStreakDetector 초기화 실패 (건너뜀): %s", exc)

    # NetLiquidityTracker -- FRED 기반 순유동성 바이어스를 추적한다
    try:
        from src.risk.macro.net_liquidity import NetLiquidityTracker

        c = system.components
        # FRED API 키가 없으면 초기화를 건너뛴다
        fred_api_key = c.vault.get_secret_or_none("FRED_API_KEY") or ""
        if fred_api_key:
            _register_feature(
                system,
                "net_liquidity_tracker",
                NetLiquidityTracker(c.cache, fred_api_key),
            )
        else:
            logger.warning("F6 NetLiquidityTracker: FRED_API_KEY 미설정, 건너뜀")
    except ImportError as exc:
        logger.warning("F6 NetLiquidityTracker 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F6 NetLiquidityTracker 초기화 실패 (건너뜀): %s", exc)


def _inject_f7_telegram(system: InjectedSystem) -> None:
    """F7 텔레그램 알림 모듈을 초기화하고 등록한다."""
    try:
        from src.monitoring.telegram.telegram_notifier import TelegramNotifier

        notifier = TelegramNotifier(system.components.telegram)
        _register_feature(system, "telegram_notifier", notifier)
    except Exception as exc:
        logger.warning("F7 Telegram 초기화 실패 (건너뜀): %s", exc)


def _inject_f8_tax(system: InjectedSystem) -> None:
    """F8 세금/환율/슬리피지 모듈을 초기화하고 등록한다."""
    # C2 수정: FxManager -- fx.py 엔드포인트가 "fx_manager" 키를 조회한다
    try:
        from src.tax.fx_manager import FxManager

        c = system.components
        _register_feature(system, "fx_manager", FxManager(c.broker))
    except ImportError as exc:
        logger.warning("F8 FxManager 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F8 FxManager 초기화 실패 (건너뜀): %s", exc)

    # C2 수정: SlippageTracker -- slippage.py 엔드포인트가 "slippage_tracker" 키를 조회한다
    # OrderManager에도 주입하여 체결 시 슬리피지를 자동 측정한다
    try:
        from src.tax.slippage_tracker import SlippageTracker

        tracker = SlippageTracker()
        _register_feature(system, "slippage_tracker", tracker)
        # F5에서 생성된 OrderManager에 SlippageTracker를 후속 주입한다
        om = system.features.get("order_manager")
        if om is not None:
            from src.executor.order.order_manager import OrderManager
            if isinstance(om, OrderManager):
                om.set_slippage_tracker(tracker)
    except ImportError as exc:
        logger.warning("F8 SlippageTracker 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F8 SlippageTracker 초기화 실패 (건너뜀): %s", exc)


def _inject_f9_optimization(system: InjectedSystem) -> None:
    """F9 최적화 모듈을 초기화하고 등록한다."""
    try:
        from src.optimization.param_tuner.execution_optimizer import ExecutionOptimizer
        c = system.components
        _register_feature(system, "execution_optimizer", ExecutionOptimizer(c.cache))
    except ImportError as exc:
        logger.warning("F9 ExecutionOptimizer 임포트 실패 (건너뜀): %s", exc)
    except Exception as exc:
        logger.warning("F9 ExecutionOptimizer 초기화 실패 (건너뜀): %s", exc)


def _inject_f10_healing(system: InjectedSystem) -> None:
    """F10 Self-Healing 모듈을 초기화하고 등록한다."""
    try:
        from src.healing import ErrorMonitor, TradeWatchdog

        _register_feature(system, "error_monitor", ErrorMonitor(system))
        _register_feature(system, "trade_watchdog", TradeWatchdog(system))
    except Exception as exc:
        logger.warning("F10 Healing 초기화 실패 (건너뜀): %s", exc)


def inject_dependencies(components: SystemComponents) -> InjectedSystem:
    """SystemComponents에 Feature 매니저를 조립하고 의존성을 주입한다.

    F1~F10 Feature 인스턴스를 생성하여 등록한다.
    개별 Feature 초기화 실패 시 해당 Feature만 건너뛴다.
    """
    system = InjectedSystem(components=components, running=False)

    _inject_f1_crawl(system)
    _inject_f2_analysis(system)
    _inject_f3_indicators(system)
    _inject_f4_strategy(system)
    _inject_f5_executor(system)
    _inject_f6_safety(system)
    _inject_f7_telegram(system)
    _inject_f8_tax(system)
    _inject_f9_optimization(system)
    _inject_f10_healing(system)

    # Universe DB 영속화 -- 부팅 시 DB에서 유니버스를 로드하기 위한 persister이다
    try:
        from src.common.universe_persister import UniversePersister

        persister = UniversePersister(system.components.db)
        _register_feature(system, "universe_persister", persister)
    except Exception as exc:
        logger.warning("UniversePersister 초기화 실패 (건너뜀): %s", exc)

    # DI 결과 요약 — 로드 성공/실패 feature 목록을 기록한다
    loaded = list(system.features.keys())
    logger.info("DI 완료: %d개 feature 로드", len(loaded))
    # 필수 feature 누락 시 error 레벨로 경고한다
    critical = {"position_monitor", "order_manager", "entry_strategy", "exit_strategy"}
    missing_critical = critical - set(loaded)
    if missing_critical:
        logger.error("필수 feature 로드 실패: %s", ", ".join(missing_critical))

    return system
