"""센티넬 이상 감지 모델이다."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel


class AnomalySignal(BaseModel):
    """단일 이상 신호이다."""

    rule: str                    # "price_crash", "vix_spike", "volume_surge", "position_danger", "news_urgent"
    level: Literal["urgent", "watch", "normal"]
    detail: str                  # 사람이 읽을 수 있는 설명
    value: float                 # 감지된 수치 (change_pct, vix_delta 등)
    threshold: float             # 임계값
    ticker: str = ""             # 관련 티커 (없으면 빈 문자열)


class AnomalyResult(BaseModel):
    """센티넬 1회 스캔 결과이다."""

    timestamp: datetime
    signals: list[AnomalySignal] = []
    highest_level: Literal["urgent", "watch", "normal"] = "normal"
    news_headlines_scanned: int = 0

    @property
    def has_anomaly(self) -> bool:
        """urgent 또는 watch 신호가 있는지 반환한다."""
        return self.highest_level != "normal"


class EscalationResult(BaseModel):
    """Sonnet 에스컬레이션 평가 결과이다."""

    action_needed: bool
    urgency: Literal["emergency", "next_cycle", "ignore"]
    reasoning: str
    suggested_action: str = ""   # "sell SOXL", "buy SQQQ" 등
    ticker: str = ""


_MAX_SEEN_HEADLINES: int = 500  # 해시 집합 크기 상한 (메모리 누수 방지)


class SentinelState(BaseModel):
    """센티넬 루프 상태이다."""

    iterations: int = 0
    anomalies_detected: int = 0
    escalations_triggered: int = 0
    emergencies_triggered: int = 0
    last_vix: float | None = None  # 이전 VIX 값 (급변 감지용)
    last_prices: dict[str, float] = {}  # 이전 가격 (스캔 간 변동 감지용)
    seen_headline_hashes: list[str] = []  # 이미 분류한 헤드라인 해시 (FIFO 순서 보존)
    errors: list[str] = []

    model_config = {"arbitrary_types_allowed": True}

    def add_seen_hash(self, h: str) -> None:
        """헤드라인 해시를 추가한다. 상한 초과 시 가장 오래된 항목부터 제거한다."""
        if h in self.seen_headline_hashes:
            return
        self.seen_headline_hashes.append(h)
        if len(self.seen_headline_hashes) > _MAX_SEEN_HEADLINES:
            # FIFO: 앞쪽(오래된)을 절반 제거하여 최근 해시를 보존한다
            trim_count = len(self.seen_headline_hashes) - _MAX_SEEN_HEADLINES // 2
            self.seen_headline_hashes = self.seen_headline_hashes[trim_count:]
