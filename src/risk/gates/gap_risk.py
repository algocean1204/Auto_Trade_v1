"""GapRiskProtector (F6.14) -- 갭 리스크를 4단계로 분류한다.

시장 개장 시 전일 종가 대비 갭 크기에 따라
포지션 사이즈 조절, 스톱 확대, 매매 차단 등을 결정한다.

M-5: _block_until을 캐시에 영속하여 프로세스 재시작 시 보호 상태를 유지한다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient

_logger = get_logger(__name__)

# 캐시 키 접두사 및 TTL
_CACHE_KEY_PREFIX = "gap_block:"

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

    cache가 주입되면 블록 상태를 캐시에 영속하여 프로세스 재시작 시에도
    보호 상태를 유지한다. cache가 없으면 메모리 전용으로 동작한다.
    """

    def __init__(self, cache: CacheClient | None = None) -> None:
        """초기화한다.

        Args:
            cache: CacheClient 인스턴스. None이면 메모리 전용 모드이다.
        """
        self._cache = cache
        # 티커별 블록 종료 시각을 관리한다 (M-5: 다중 종목 동시 블록 지원)
        self._block_until: dict[str, datetime] = {}

    async def load_state(self) -> None:
        """캐시에서 기존 갭 블록 상태를 복원한다. 초기화 직후 호출한다."""
        if self._cache is None:
            return
        try:
            data = await self._cache.read_json("gap_block:all")
            if isinstance(data, dict):
                now = datetime.now(tz=timezone.utc)
                for ticker, ts_str in data.items():
                    try:
                        block_dt = datetime.fromisoformat(ts_str)
                        if block_dt.tzinfo is None:
                            block_dt = block_dt.replace(tzinfo=timezone.utc)
                        if block_dt > now:
                            self._block_until[ticker] = block_dt
                    except (ValueError, TypeError):
                        pass
                if self._block_until:
                    _logger.info("캐시에서 갭 블록 상태 복원: %d건", len(self._block_until))
        except Exception as exc:
            _logger.warning("갭 블록 캐시 복원 실패 (메모리 전용으로 계속): %s", exc)

    def _save_blocks(self) -> None:
        """블록 상태를 캐시에 비동기로 저장한다."""
        if self._cache is None:
            return
        serializable = {t: dt.isoformat() for t, dt in self._block_until.items()}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _safe() -> None:
            try:
                await self._cache.write_json(
                    "gap_block:all", serializable,
                    ttl=_EXTREME_BLOCK_MINUTES * 60 + 60,
                )
            except Exception:
                _logger.warning("갭 블록 캐시 저장 실패 (매매 로직에 영향 없음)")

        loop.create_task(_safe())

    def evaluate(
        self,
        pre_close: float,
        current_price: float,
        ticker: str = "",
    ) -> GapRiskResult:
        """갭 리스크를 평가한다.

        Args:
            pre_close: 전일 종가.
            current_price: 현재가.
            ticker: 종목 코드 (블록 상태 영속화에 사용한다).

        Returns:
            갭 레벨, 갭 비율, 사이즈 배수, 차단 여부.
        """
        # 아직 블록 상태인지 먼저 확인한다
        if self._is_blocked(ticker):
            return GapRiskResult(
                level=GapLevel.EXTREME,
                gap_pct=0.0,
                size_multiplier=0.0,
                blocked=True,
                block_until=self._block_until.get(ticker),
            )

        if pre_close <= 0:
            return GapRiskResult(
                level=GapLevel.SMALL, gap_pct=0.0,
            )

        gap_pct = _calculate_gap_pct(pre_close, current_price)
        abs_gap = abs(gap_pct)
        level = _classify_gap(abs_gap)
        multiplier = _SIZE_MULTIPLIERS[level]

        # EXTREME이면 30분 블록 설정한다
        blocked = False
        block_until: datetime | None = None
        if level == GapLevel.EXTREME:
            blocked = True
            now = datetime.now(tz=timezone.utc)
            block_dt = now + timedelta(minutes=_EXTREME_BLOCK_MINUTES)
            if ticker:
                self._block_until[ticker] = block_dt
            else:
                self._block_until["_global"] = block_dt
            block_until = block_dt
            self._save_blocks()
            _logger.warning(
                "갭 EXTREME: %s %.2f%% -> %d분 블록 설정",
                ticker or "global", gap_pct, _EXTREME_BLOCK_MINUTES,
            )

        if level != GapLevel.SMALL:
            _logger.info(
                "갭 리스크: %s %.2f%% -> %s (배수=%.2f)",
                ticker or "?", gap_pct, level.value, multiplier,
            )

        return GapRiskResult(
            level=level,
            gap_pct=gap_pct,
            size_multiplier=multiplier,
            blocked=blocked,
            block_until=block_until,
        )

    def is_blocked(self, ticker: str = "") -> bool:
        """현재 블록 상태인지 외부에서 확인한다."""
        return self._is_blocked(ticker)

    def reset(self) -> None:
        """일일 리셋한다."""
        self._block_until.clear()
        self._save_blocks()
        _logger.info("GapRiskProtector 리셋 완료")

    def _is_blocked(self, ticker: str = "") -> bool:
        """블록 상태를 내부적으로 확인한다. 글로벌 블록 → 티커별 블록 순으로 검사한다.

        H-13: 글로벌 블록은 티커 유무와 관계없이 항상 확인한다.
        만료된 블록은 즉시 제거하여 메모리 누수를 방지한다.
        """
        now = datetime.now(tz=timezone.utc)
        # 글로벌 블록 항상 확인
        global_block = self._block_until.get("_global")
        if global_block is not None:
            if now < global_block:
                return True
            del self._block_until["_global"]
        # 티커별 블록 확인
        if ticker:
            ticker_block = self._block_until.get(ticker)
            if ticker_block is not None:
                if now < ticker_block:
                    return True
                del self._block_until[ticker]
        return False


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
