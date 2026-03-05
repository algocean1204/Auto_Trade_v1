"""QuotaGuard (F6.19) -- KIS API 속도 제한을 관리한다.

Redis 기반 슬라이딩 윈도우 카운터로 요청 수를 추적하여
초과 시 요청을 차단한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.common.cache_gateway import CacheClient
from src.common.logger import get_logger
from src.risk.models import QuotaResult

_logger = get_logger(__name__)

# -- 상수 --
_DEFAULT_WINDOW_SECONDS: int = 60
_DEFAULT_MAX_REQUESTS: int = 20
_REDIS_KEY_PREFIX: str = "quota:kis_api"


class QuotaGuard:
    """KIS API 쿼터 관리기이다.

    Redis 키에 현재 윈도우 내 요청 수를 기록하고,
    최대 허용 수 초과 시 차단 신호를 반환한다.
    """

    def __init__(
        self,
        cache: CacheClient,
        window_seconds: int = _DEFAULT_WINDOW_SECONDS,
        max_requests: int = _DEFAULT_MAX_REQUESTS,
    ) -> None:
        """초기화한다.

        Args:
            cache: Redis 캐시 클라이언트.
            window_seconds: 쿼터 윈도우(초). 기본 60.
            max_requests: 윈도우 내 최대 요청 수. 기본 20.
        """
        self._cache = cache
        self._window = window_seconds
        self._max = max_requests

    async def check_quota(self) -> QuotaResult:
        """현재 쿼터 상태를 확인한다.

        Returns:
            allowed=True이면 요청 가능.
        """
        count = await self._get_current_count()
        remaining = max(self._max - count, 0)
        allowed = count < self._max

        if not allowed:
            _logger.warning(
                "API 쿼터 초과: %d/%d (%ds 윈도우)",
                count, self._max, self._window,
            )

        return QuotaResult(
            allowed=allowed,
            remaining=remaining,
            reset_at=self._estimate_reset_time(),
        )

    async def record_request(self) -> None:
        """API 요청 1건을 기록한다."""
        key = self._build_key()
        raw = await self._cache.read(key)
        count = int(raw) if raw else 0
        await self._cache.write(
            key, str(count + 1), ttl=self._window,
        )

    async def _get_current_count(self) -> int:
        """현재 윈도우 내 요청 수를 조회한다."""
        raw = await self._cache.read(self._build_key())
        return int(raw) if raw else 0

    def _build_key(self) -> str:
        """Redis 키를 생성한다. 윈도우 단위로 키가 변경된다."""
        now = int(datetime.now(tz=timezone.utc).timestamp())
        window_id = now // self._window
        return f"{_REDIS_KEY_PREFIX}:{window_id}"

    def _estimate_reset_time(self) -> datetime:
        """현재 윈도우 종료 시점을 추정한다."""
        now = int(datetime.now(tz=timezone.utc).timestamp())
        window_id = now // self._window
        next_window = (window_id + 1) * self._window
        return datetime.fromtimestamp(
            next_window, tz=timezone.utc,
        )
