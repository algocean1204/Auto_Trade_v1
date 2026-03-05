"""F4 전략 -- 공용 Pydantic 모델이다."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Position(BaseModel):
    """보유 포지션이다."""

    ticker: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl_pct: float = 0.0
    entry_time: datetime | None = None
    is_beast: bool = False
    pyramid_level: int = 0


class EntryDecision(BaseModel):
    """진입 판단 결과이다."""

    should_enter: bool
    confidence: float
    position_size_pct: float
    blocked_by: str | None = None
    gate_results: dict[str, bool] = {}
    ticker: str
    direction: str = "bull"


class ExitDecision(BaseModel):
    """청산 판단 결과이다."""

    should_exit: bool
    exit_type: str
    exit_pct: float
    priority: float
    reason: str
    ticker: str
    estimated_pnl_pct: float = 0.0


class BeastDecision(BaseModel):
    """Beast Mode 판단이다."""

    activated: bool
    conviction_multiplier: float = 1.0
    ego_type: str | None = None
    position_size_pct: float = 0.0
    rejection_reason: str | None = None
    composite_score: float = 0.0


class PyramidDecision(BaseModel):
    """피라미딩 판단이다."""

    should_add: bool
    level: int = 0
    add_size_pct: float = 0.0
    ratchet_stop: float = 0.0
    reason: str = ""


class StatArbSignal(BaseModel):
    """통계적 차익거래 신호이다."""

    pair: str
    z_score: float
    direction: str
    signal_type: str


class MicroRegimeResult(BaseModel):
    """미시 레짐 결과이다."""

    regime: str  # trending / mean_reverting / volatile / quiet
    score: float
    weights: dict[str, float] = {}


class FadeSignal(BaseModel):
    """뉴스 페이딩 신호이다."""

    should_fade: bool
    direction: str = ""
    decay_estimate: float = 0.0
    entry_price: float = 0.0


class WickDecision(BaseModel):
    """윅 캐처 판단이다."""

    should_catch: bool
    entry_prices: list[float] = []
    bounce_exit_pct: float = 2.0


class RotationSignal(BaseModel):
    """섹터 로테이션 신호이다."""

    top3_prefer: list[str] = []
    bottom2_avoid: list[str] = []
    scores: dict[str, float] = {}


class StrategyParams(BaseModel):
    """전략 파라미터 종합이다."""

    # 기능 토글
    beast_mode_enabled: bool = True
    pyramiding_enabled: bool = True
    stat_arb_enabled: bool = True
    news_fading_enabled: bool = True
    wick_catcher_enabled: bool = True
    # Beast Mode
    beast_min_confidence: float = 0.9
    beast_min_obi: float = 0.4
    beast_max_daily: int = 5
    beast_cooldown_seconds: int = 300
    # Pyramiding
    pyramid_level1_pct: float = 1.0
    pyramid_level2_pct: float = 2.0
    pyramid_level3_pct: float = 3.0
    # 일반
    default_position_size_pct: float = 5.0
    max_position_pct: float = 15.0
    obi_threshold: float = 0.3
    ml_threshold: float = 0.6
    friction_hurdle: float = 0.5


class TargetStatus(BaseModel):
    """수익 목표 상태이다."""

    current_pnl: float
    target_pnl: float = 300.0
    on_track: bool
    days_remaining: int
    daily_target: float
