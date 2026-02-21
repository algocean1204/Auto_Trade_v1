"""
Pydantic request/response models for the monitoring API.

Defines typed schemas for all REST endpoints ensuring input validation
and consistent response formatting.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Unified error response."""

    detail: str
    error_code: str = "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardSummary(BaseModel):
    """Main dashboard summary response."""

    total_asset: float
    cash: float
    today_pnl: float
    today_pnl_pct: float
    cumulative_return: float
    active_positions: int
    system_status: str  # "NORMAL" | "WARNING" | "SHUTDOWN"
    timestamp: datetime

    # 상세 계좌 정보 (선택적 필드, 구버전 호환)
    positions_value: float = 0.0          # 보유 포지션 평가금액 (total_asset - cash)
    buying_power: float = 0.0             # 매수 가능 금액 (= cash)
    currency: str = "USD"                 # 통화 단위
    account_number: str = "****0000-01"   # 마스킹된 계좌번호


class DailyReturnItem(BaseModel):
    """Single day return data point."""

    date: str
    pnl_amount: float
    pnl_pct: float
    trade_count: int


class CumulativeReturnItem(BaseModel):
    """Cumulative return data point."""

    date: str
    cumulative_pnl: float
    cumulative_pct: float


class HeatmapCell(BaseModel):
    """Generic heatmap cell."""

    x: str
    y: str
    value: float


class DrawdownItem(BaseModel):
    """Drawdown chart data point."""

    date: str
    peak: float
    current: float
    drawdown_pct: float


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

class WeightsResponse(BaseModel):
    """Indicator weights response."""

    weights: dict[str, int]
    presets: list[str]


class WeightsUpdateRequest(BaseModel):
    """Indicator weights update request."""

    weights: dict[str, int] = Field(
        ...,
        description="Indicator name -> weight (0-100). Sum must equal 100.",
    )


class RealtimeIndicatorResponse(BaseModel):
    """Realtime indicator data for a ticker."""

    ticker: str
    indicators: dict[str, Any]
    history: list[dict[str, Any]]
    updated_at: datetime


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class StrategyParamsResponse(BaseModel):
    """Strategy parameters response."""

    params: dict[str, Any]
    regimes: dict[str, Any]


class StrategyParamsUpdateRequest(BaseModel):
    """Strategy parameters update request."""

    params: dict[str, Any] = Field(
        ...,
        description="Parameter name -> new value.",
    )


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackReportResponse(BaseModel):
    """Feedback report response."""

    report_type: str
    report_date: str
    content: dict[str, Any]
    created_at: datetime


class PendingAdjustmentResponse(BaseModel):
    """Pending parameter adjustment."""

    id: str
    param_name: str
    current_value: float
    proposed_value: float
    change_pct: float
    reason: str | None
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------

class UniverseTickerResponse(BaseModel):
    """Single ticker in universe."""

    ticker: str
    name: str
    direction: str
    enabled: bool
    underlying: str | None = None
    expense_ratio: float | None = None
    avg_daily_volume: int | None = None


class AddTickerRequest(BaseModel):
    """Request to add a ticker to the universe."""

    ticker: str = Field(..., min_length=1, max_length=10)
    direction: str = Field(..., pattern="^(bull|bear)$")
    name: str = Field(..., min_length=1, max_length=100)
    underlying: str = ""
    expense_ratio: float = 0.95
    avg_daily_volume: int = 0
    enabled: bool = True


class ToggleTickerRequest(BaseModel):
    """Request to toggle a ticker on/off."""

    ticker: str = Field(..., min_length=1, max_length=10)
    enabled: bool


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

class ManualCrawlResponse(BaseModel):
    """Manual crawl trigger response."""

    task_id: str
    status: str
    message: str


class CrawlStatusResponse(BaseModel):
    """Crawl task status (simple, for backward compatibility)."""

    task_id: str
    status: str
    data: dict[str, Any] | None = None


class CrawlerStatusItem(BaseModel):
    """단일 크롤러의 현재 상태."""

    name: str
    key: str
    index: int
    status: str  # "pending" | "running" | "completed" | "failed"
    articles_count: int = 0
    message: str = ""
    timestamp: str = ""


class CrawlDetailedStatusResponse(BaseModel):
    """크롤링 태스크의 상세 진행 상황 응답.

    GET /crawl/status/{task_id} 가 반환하는 상세 버전으로,
    각 크롤러의 개별 상태와 전체 진행률을 포함한다.
    """

    task_id: str
    status: str  # "started" | "running" | "completed" | "failed"
    total_crawlers: int = 0
    completed_crawlers: int = 0
    progress_pct: float = 0.0
    crawler_statuses: list[CrawlerStatusItem] = Field(default_factory=list)
    data: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

class SystemStatusResponse(BaseModel):
    """System-wide status."""

    claude: dict[str, Any]
    kis: dict[str, Any]
    database: dict[str, Any]
    fallback: dict[str, Any]
    quota: dict[str, Any]
    safety: dict[str, Any]
    timestamp: datetime


class UsageStatsResponse(BaseModel):
    """API usage statistics."""

    claude_calls_today: int
    kis_calls_today: int
    trades_today: int
    crawl_articles_today: int
    fallback_count: int
    uptime_seconds: float


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class AlertItem(BaseModel):
    """Single alert entry."""

    id: str
    alert_type: str
    title: str
    message: str
    severity: str  # "info" | "warning" | "critical"
    data: dict[str, Any] | None = None
    created_at: datetime
    read: bool = False


# ---------------------------------------------------------------------------
# Trading Control
# ---------------------------------------------------------------------------

class TradingStatusResponse(BaseModel):
    """자동매매 실행 상태 응답."""

    is_trading: bool
    running: bool
    task_done: bool = False

    # 운영 윈도우 / 시간 정보
    is_trading_window: bool = False       # 현재 자동매매 운영 윈도우 내인지 여부
    is_trading_day: bool = True           # 오늘이 거래일인지 여부
    session_type: str | None = None       # 현재 미국 시장 세션 타입
    next_window_start: str | None = None  # 다음 운영 윈도우 시작 시각 (ISO, KST)
    current_kst: str = ""                 # 현재 KST 시각 (ISO 형식)


class TradingActionResponse(BaseModel):
    """자동매매 시작/중지 액션 응답."""

    status: str
