"""
공통 모듈 (C0) -- 모든 Feature가 의존하는 기초 인프라이다.
"""

from src.common.cache_gateway import CacheClient, get_cache_client, reset_cache_client
from src.common.database_gateway import (
    Base,
    SessionFactory,
    get_session_factory,
    reset_session_factory,
)
from src.common.error_handler import (
    AiError,
    BrokerError,
    DataError,
    ErrorResponse,
    SafetyError,
    TradingError,
    register_exception_handlers,
    to_error_response,
)
from src.common.event_bus import (
    EventBus,
    EventDeliveryResult,
    EventType,
    get_event_bus,
    reset_event_bus,
)
from src.common.http_client import (
    AsyncHttpClient,
    HttpClientError,
    HttpResponse,
    TimeoutConfig,
    get_http_client,
    reset_http_client,
)
from src.common.logger import get_logger
from src.common.secret_vault import SecretProvider, get_vault, reset_vault

__all__ = [
    # C0.1 SecretVault
    "SecretProvider",
    "get_vault",
    "reset_vault",
    # C0.2 DatabaseGateway
    "Base",
    "SessionFactory",
    "get_session_factory",
    "reset_session_factory",
    # C0.3 CacheGateway
    "CacheClient",
    "get_cache_client",
    "reset_cache_client",
    # C0.4 HttpClient
    "AsyncHttpClient",
    "HttpClientError",
    "HttpResponse",
    "TimeoutConfig",
    "get_http_client",
    "reset_http_client",
    # C0.8 Logger
    "get_logger",
    # C0.9 ErrorHandler
    "ErrorResponse",
    "TradingError",
    "BrokerError",
    "AiError",
    "DataError",
    "SafetyError",
    "to_error_response",
    "register_exception_handlers",
    # C0.10 EventBus
    "EventBus",
    "EventDeliveryResult",
    "EventType",
    "get_event_bus",
    "reset_event_bus",
]
