"""F7.22 ResponseModels -- API 응답 Pydantic 모델을 정의한다.

모든 엔드포인트는 이 모듈의 모델로 응답 타입을 고정하여
프론트엔드와 계약을 유지한다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TradingStatusResponse(BaseModel):
    """매매 상태 응답이다."""

    is_trading: bool
    running: bool
    task_done: bool
    is_trading_window: bool
    session_type: str
    current_kst: str


class TradingActionResponse(BaseModel):
    """매매 시작/중지 응답이다."""

    status: str  # started, stopped, already_running, not_running


class DashboardSummaryResponse(BaseModel):
    """대시보드 요약 응답이다.

    Flutter DashboardSummary.fromJson이 기대하는 필드를 모두 포함한다.
    total_asset, cash, today_pnl 등은 accounts 데이터에서 집계하여 채운다.
    """

    status: str
    session_type: str
    is_trading_window: bool
    current_kst: str
    positions: list[dict] = Field(default_factory=list)
    daily_pnl: float = 0.0
    total_equity: float = 0.0
    # Flutter 호환 필드 (DashboardSummary.fromJson 기대값)
    total_asset: float = 0.0
    cash: float = 0.0
    today_pnl: float = 0.0
    today_pnl_pct: float = 0.0
    cumulative_return: float = 0.0
    active_positions: int = 0
    account_number: str = ""
    positions_value: float = 0.0
    buying_power: float = 0.0


class ServiceHealthItem(BaseModel):
    """개별 서비스 상태 항목이다."""

    ok: bool = False
    status: str = "OFFLINE"
    connected: bool = False


class SystemStatusResponse(BaseModel):
    """종합 시스템 상태 응답이다.

    Flutter SystemStatus.fromJson이 기대하는 claude/kis/database/redis 필드를 포함한다.
    """

    claude: ServiceHealthItem = Field(default_factory=ServiceHealthItem)
    kis: ServiceHealthItem = Field(default_factory=ServiceHealthItem)
    database: ServiceHealthItem = Field(default_factory=ServiceHealthItem)
    redis: ServiceHealthItem = Field(default_factory=ServiceHealthItem)
    fallback: bool = False
    timestamp: str = ""


class HealthResponse(BaseModel):
    """헬스체크 응답이다."""

    status: str
    version: str


class SystemInfoResponse(BaseModel):
    """시스템 정보 응답이다."""

    version: str
    python_version: str
    uptime_seconds: float
    components_loaded: int
    features_registered: int


class ErrorDetail(BaseModel):
    """에러 상세 응답이다. JSONResponse content로 사용한다."""

    detail: str
    error_code: str
