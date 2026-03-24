"""F9.1 SystemInitializer -- 전체 시스템을 초기화한다.

Common 모듈을 의존 순서대로 생성하여 SystemComponents에 담아 반환한다.
Feature 인스턴스(F1~F8)는 여기서 생성하지 않는다.
setup_mode=True이면 ai, broker, telegram을 NoOp 더미로 대체하여
API 키 없이도 서버를 부팅할 수 있다 (noop_components.py 참조).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.common.ai_gateway import AiClient, get_ai_client
from src.common.broker_gateway import BrokerClient, get_broker_client
from src.common.cache_gateway import CacheClient, get_cache_client
from src.common.database_gateway import SessionFactory, get_session_factory
from src.common.event_bus import EventBus, get_event_bus
from src.common.http_client import AsyncHttpClient, get_http_client
from src.common.logger import get_logger
from src.common.market_clock import MarketClock, get_market_clock
from src.common.secret_vault import SecretProvider, get_vault
from src.common.telegram_gateway import TelegramSender, get_telegram_sender
from src.common.ticker_registry import TickerRegistry, get_ticker_registry
from src.orchestration.init.noop_components import (
    NoOpAiClient,
    NoOpBrokerClient,
    NoOpTelegramSender,
)

logger = get_logger(__name__)


class SystemComponents(BaseModel):
    """초기화된 시스템 컴포넌트 집합이다."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    vault: SecretProvider
    db: SessionFactory
    cache: CacheClient
    http: AsyncHttpClient
    ai: AiClient
    broker: BrokerClient
    telegram: TelegramSender
    event_bus: EventBus
    clock: MarketClock
    registry: TickerRegistry


def _init_vault(setup_mode: bool = False) -> SecretProvider:
    """SecretVault를 최우선으로 초기화한다."""
    vault = get_vault(setup_mode=setup_mode)
    loaded = vault.list_loaded_keys()
    logger.info("SecretVault 초기화 완료 (%d개 키 로드)", len(loaded))
    return vault


def _init_infra(vault: SecretProvider) -> tuple[SessionFactory, CacheClient, AsyncHttpClient]:
    """DB, Cache, HTTP 인프라 계층을 초기화한다."""
    db = get_session_factory(database_url=vault.get_secret("DATABASE_URL"))
    cache = get_cache_client()
    http = get_http_client()
    logger.info("인프라 계층 초기화 완료 (DB, Cache, HTTP)")
    return db, cache, http


def _init_ai(vault: SecretProvider) -> AiClient:
    """AI 클라이언트를 초기화한다. CLAUDE_MODE에 따라 모드를 결정한다."""
    mode = vault.get_secret_or_none("CLAUDE_MODE") or "local"
    api_key = vault.get_secret_or_none("ANTHROPIC_API_KEY") or ""
    ai = get_ai_client(api_key=api_key, mode=mode)
    logger.info("AI 클라이언트 초기화 완료 (mode=%s)", mode)
    return ai


def _init_broker(vault: SecretProvider) -> BrokerClient:
    """KIS 브로커 클라이언트를 듀얼 인증으로 초기화한다.

    가상/실전 키 쌍 중 하나만 있어도 초기화 가능하다.
    누락된 키 쌍은 get_secret_or_none으로 None을 전달하고,
    get_broker_client가 처리한다.
    """
    broker = get_broker_client(
        app_key=vault.get_secret_or_none("KIS_VIRTUAL_APP_KEY"),
        app_secret=vault.get_secret_or_none("KIS_VIRTUAL_APP_SECRET"),
        virtual_account=vault.get_secret_or_none("KIS_VIRTUAL_ACCOUNT"),
        real_app_key=vault.get_secret_or_none("KIS_REAL_APP_KEY"),
        real_app_secret=vault.get_secret_or_none("KIS_REAL_APP_SECRET"),
        real_account=vault.get_secret_or_none("KIS_REAL_ACCOUNT"),
    )
    logger.info("BrokerClient 초기화 완료")
    return broker


def _init_telegram(vault: SecretProvider) -> TelegramSender:
    """텔레그램 발송 클라이언트를 초기화한다. 최대 5명의 수신자를 지원한다."""
    recipients: list[tuple[str, str]] = []
    # 1차 수신자 (접미사 없음)
    t1 = vault.get_secret_or_none("TELEGRAM_BOT_TOKEN")
    c1 = vault.get_secret_or_none("TELEGRAM_CHAT_ID")
    if t1 and c1:
        recipients.append((t1, c1))
    # 2~5차 수신자
    for i in range(2, 6):
        ti = vault.get_secret_or_none(f"TELEGRAM_BOT_TOKEN_{i}")
        ci = vault.get_secret_or_none(f"TELEGRAM_CHAT_ID_{i}")
        if ti and ci:
            recipients.append((ti, ci))
    telegram = get_telegram_sender(recipients=recipients)
    logger.info("TelegramSender 초기화 완료 (수신자=%d명)", len(recipients))
    return telegram


def _init_utilities() -> tuple[EventBus, MarketClock, TickerRegistry]:
    """EventBus, MarketClock, TickerRegistry 유틸리티를 초기화한다."""
    event_bus = get_event_bus()
    clock = get_market_clock()
    registry = get_ticker_registry()
    logger.info("유틸리티 초기화 완료 (EventBus, MarketClock, TickerRegistry)")
    return event_bus, clock, registry


def _assemble_components(
    vault: SecretProvider,
    db: SessionFactory,
    cache: CacheClient,
    http: AsyncHttpClient,
    ai: AiClient,
    broker: BrokerClient,
    telegram: TelegramSender,
    event_bus: EventBus,
    clock: MarketClock,
    registry: TickerRegistry,
) -> SystemComponents:
    """개별 컴포넌트를 SystemComponents로 조립한다."""
    return SystemComponents(
        vault=vault, db=db, cache=cache, http=http,
        ai=ai, broker=broker, telegram=telegram,
        event_bus=event_bus, clock=clock, registry=registry,
    )


async def initialize_system(setup_mode: bool = False) -> SystemComponents:
    """전체 시스템을 초기화한다. Common 모듈을 순서대로 생성한다.

    Args:
        setup_mode: True이면 ai, broker, telegram을 NoOp 더미로 대체한다.
                    첫 설치 시 API 키 없이 서버를 부팅할 때 사용한다.
    """
    mode_label = "셋업 모드" if setup_mode else "일반 모드"
    logger.info("=== 시스템 초기화 시작 (%s) ===", mode_label)

    vault = _init_vault(setup_mode=setup_mode)
    db, cache, http = _init_infra(vault)

    if setup_mode:
        # setup_mode: 외부 서비스 연결 없이 NoOp 더미를 사용한다
        ai: AiClient = NoOpAiClient()
        broker: BrokerClient = NoOpBrokerClient()
        telegram: TelegramSender = NoOpTelegramSender()
        logger.info("setup_mode: ai/broker/telegram을 NoOp 더미로 초기화")
    else:
        ai = _init_ai(vault)
        broker = _init_broker(vault)
        telegram = _init_telegram(vault)

    event_bus, clock, registry = _init_utilities()

    components = _assemble_components(
        vault, db, cache, http, ai, broker, telegram,
        event_bus, clock, registry,
    )
    logger.info("=== 시스템 초기화 완료 (10개 컴포넌트, %s) ===", mode_label)
    return components
