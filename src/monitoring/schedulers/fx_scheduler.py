"""FxScheduler -- 10분 주기로 USD/KRW 환율을 갱신하고 인메모리 캐시에 저장한다.

10단계 폴백 체인(fx_chain.py)으로 환율을 조회한다:
  1차: KIS API → 2차: 구글 Finance → 3차: 구글 Search
  4차: 네이버 모바일 → 5차: 네이버 PC → 6차: FRED DEXKOUS
  7차: 한국은행 ECOS → 8차: ExchangeRate-API → 9차: Yahoo Finance
  10차: 캐시된 최종 성공값
결과를 캐시 키 fx:current와 fx:history에 저장한다.
최대 720개 이력을 유지한다 (10분 간격 x 5일).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.common.cache_gateway import CacheClient
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# 갱신 주기 (초) -- 10분이다
_INTERVAL_SEC: int = 600
# 마지막 성공 환율 캐시 TTL (초) -- 7일이다
_LAST_SUCCESS_TTL: int = 604800

# 이력 최대 보관 건수 -- 5일 x 144회/일 = 720건이다
_MAX_HISTORY: int = 720


class FxScheduler:
    """10분 주기 환율 갱신 스케줄러이다.

    10단계 폴백 체인으로 환율을 조회한다.
    start()로 시작하고 stop()으로 중지한다.
    """

    def __init__(self, system: InjectedSystem) -> None:
        """InjectedSystem을 주입받는다."""
        self._system = system
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False
        _logger.info(
            "FxScheduler 초기화 완료 (주기=%d초, 최대이력=%d건)",
            _INTERVAL_SEC,
            _MAX_HISTORY,
        )

    @property
    def is_running(self) -> bool:
        """스케줄러 실행 상태를 반환한다."""
        return self._running

    def start(self) -> None:
        """백그라운드 갱신 루프를 시작한다. 이미 실행 중이면 무시한다."""
        if self._running:
            _logger.warning("FxScheduler가 이미 실행 중이다")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        self._task.add_done_callback(self._on_task_done)
        _logger.info("FxScheduler 백그라운드 루프 시작")

    @staticmethod
    def _on_task_done(task: asyncio.Task) -> None:  # type: ignore[type-arg]
        """태스크 완료 콜백 -- 예외가 있으면 로그로 기록한다."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _logger.error("FxScheduler 루프 비정상 종료: %s", exc)

    async def stop(self) -> None:
        """백그라운드 갱신 루프를 중지한다."""
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        _logger.info("FxScheduler 백그라운드 루프 중지")

    async def _loop(self) -> None:
        """주기적으로 환율을 갱신하는 메인 루프이다."""
        await self._tick()
        while self._running:
            try:
                await asyncio.sleep(_INTERVAL_SEC)
                if not self._running:
                    break
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                _logger.exception("FxScheduler 루프 예외, 다음 주기 재시도")

    async def _tick(self) -> None:
        """환율 1회 갱신을 수행한다."""
        try:
            from src.monitoring.crawlers.fx_chain import (
                run_fallback_chain,
            )

            result = await run_fallback_chain(self._system)
            if result is None:
                _logger.error("환율 조회 10단계 모두 실패 -- 조회불가")
                return

            rate_value, source = result
            now = datetime.now(tz=timezone.utc)
            cache = self._system.components.cache

            await self._save_last_success(cache, rate_value)
            change_pct = await self._calc_change_pct(cache, rate_value)

            current_data: dict[str, object] = {
                "usd_krw_rate": rate_value,
                "change_pct": change_pct,
                "updated_at": now.isoformat(),
                "source": source,
            }
            await cache.write_json("fx:current", current_data)

            entry: dict[str, object] = {
                "date": now.strftime("%Y-%m-%d %H:%M"),
                "rate": rate_value,
                "change_pct": change_pct,
            }
            await self._append_history(cache, entry)

            _logger.info(
                "환율 갱신: %.2f 원/달러 (변동 %.2f%%, 소스=%s)",
                rate_value,
                change_pct,
                source,
            )
        except Exception:
            _logger.exception("환율 갱신 실패")

    async def _save_last_success(
        self, cache: CacheClient, rate: float,
    ) -> None:
        """성공한 환율을 fx:last_success 캐시에 저장한다."""
        try:
            data = {
                "rate": rate,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            await cache.write_json(  # type: ignore[union-attr]
                "fx:last_success", data, ttl=_LAST_SUCCESS_TTL,
            )
        except Exception:
            _logger.debug("fx:last_success 저장 실패", exc_info=True)

    async def _calc_change_pct(
        self, cache: CacheClient, current_rate: float,
    ) -> float:
        """이전 캐시 대비 변동률(%)을 계산한다."""
        try:
            prev = await cache.read_json("fx:current")  # type: ignore[union-attr]
            if prev and isinstance(prev, dict):
                prev_rate = float(prev.get("usd_krw_rate", 0))
                if prev_rate > 0:
                    return round(
                        (current_rate - prev_rate) / prev_rate * 100, 4,
                    )
        except Exception as exc:
            _logger.debug("이전 환율 캐시 조회 실패 (무시): %s", exc)
        return 0.0

    async def _append_history(
        self, cache: CacheClient, entry: dict[str, float | str],
    ) -> None:
        """fx:history 리스트에 항목을 원자적으로 추가한다. 최대 _MAX_HISTORY 건이다.

        atomic_list_append를 사용하여 read→insert→write 사이에
        다른 코루틴이 이력을 덮어쓰는 경합을 방지한다.
        """
        try:
            await cache.atomic_list_append(  # type: ignore[union-attr]
                "fx:history", [entry], max_size=_MAX_HISTORY,
            )
        except Exception:
            _logger.exception("환율 이력 저장 실패")
