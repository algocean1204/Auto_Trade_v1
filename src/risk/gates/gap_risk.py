"""GapRiskProtector (F6.14) -- 갭 리스크를 4단계로 분류한다.

시장 개장 시 전일 종가 대비 갭 크기에 따라
포지션 사이즈 조절, 스톱 확대, 매매 차단 등을 결정한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel

from src.common.logger import get_logger

_logger = get_logger(__name__)

# -- 갭 레벨 임계값 (절대값 기준, %) --
_MEDIUM_THRESHOLD: float = 1.0
_LARGE_THRESHOLD: float = 3.0
_EXTREME_THRESHOLD: float = 5.0
_EXTREME_BLOCK_MINUTES: int = 30


class GapLevel(str, Enum):
    """갭 리스크 레벨이다."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    EXTREME = "extreme"


# 레벨별 사이즈 조절 배수
_SIZE_MULTIPLIERS: dict[GapLevel, float] = {
    GapLevel.SMALL: 1.0,
    GapLevel.MEDIUM: 0.7,
    GapLevel.LARGE: 0.5,
    GapLevel.EXTREME: 0.0,
}


class GapRiskResult(BaseModel):
    """갭 리스크 결과이다."""

    level: GapLevel
    gap_pct: float
    size_multiplier: float = 1.0
    blocked: bool = False
    block_until: datetime | None = None


class GapRiskProtector:
    """갭 리스크 보호기이다.

    전일 종가와 현재가를 비교하여 갭 크기를 4단계로 분류하고
    적절한 포지션 사이즈 배수를 반환한다.
    """

    def __init__(self) -> None:
        """초기화한다."""
        self._block_until: datetime | None = None

    def evaluate(
        self,
        pre_close: float,
        current_price: float,
    ) -> GapRiskResult:
        """갭 리스크를 평가한다.

        Args:
            pre_close: 전일 종가.
            current_price: 현재가.

        Returns:
            갭 레벨, 갭 비율, 사이즈 배수, 차단 여부.
        """
        # 아직 블록 상태인지 먼저 확인
        if self._is_blocked():
            return GapRiskResult(
                level=GapLevel.EXTREME,
                gap_pct=0.0,
                size_multiplier=0.0,
                blocked=True,
                block_until=self._block_until,
            )

        if pre_close <= 0:
            return GapRiskResult(
                level=GapLevel.SMALL, gap_pct=0.0,
            )

        gap_pct = _calculate_gap_pct(pre_close, current_price)
        abs_gap = abs(gap_pct)
        level = _classify_gap(abs_gap)
        multiplier = _SIZE_MULTIPLIERS[level]

        # EXTREME이면 30분 블록 설정
        blocked = False
        block_until: datetime | None = None
        if level == GapLevel.EXTREME:
            blocked = True
            now = datetime.now(tz=timezone.utc)
            self._block_until = now + timedelta(
                minutes=_EXTREME_BLOCK_MINUTES,
            )
            block_until = self._block_until
            _logger.warning(
                "갭 EXTREME: %.2f%% -> %d분 블록 설정",
                gap_pct, _EXTREME_BLOCK_MINUTES,
            )

        if level != GapLevel.SMALL:
            _logger.info(
                "갭 리스크: %.2f%% -> %s (배수=%.2f)",
                gap_pct, level.value, multiplier,
            )

        return GapRiskResult(
            level=level,
            gap_pct=gap_pct,
            size_multiplier=multiplier,
            blocked=blocked,
            block_until=block_until,
        )

    def is_blocked(self) -> bool:
        """현재 블록 상태인지 외부에서 확인한다."""
        return self._is_blocked()

    def reset(self) -> None:
        """일일 리셋한다."""
        self._block_until = None
        _logger.info("GapRiskProtector 리셋 완료")

    def _is_blocked(self) -> bool:
        """블록 상태를 내부적으로 확인한다."""
        if self._block_until is None:
            return False
        now = datetime.now(tz=timezone.utc)
        if now >= self._block_until:
            self._block_until = None
            return False
        return True


def _calculate_gap_pct(
    pre_close: float, current_price: float,
) -> float:
    """갭 비율(%)을 계산한다."""
    return ((current_price - pre_close) / pre_close) * 100


def _classify_gap(abs_gap: float) -> GapLevel:
    """절대값 기준으로 갭 레벨을 분류한다."""
    if abs_gap >= _EXTREME_THRESHOLD:
        return GapLevel.EXTREME
    if abs_gap >= _LARGE_THRESHOLD:
        return GapLevel.LARGE
    if abs_gap >= _MEDIUM_THRESHOLD:
        return GapLevel.MEDIUM
    return GapLevel.SMALL
