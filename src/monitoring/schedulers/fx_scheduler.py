"""FxScheduler -- 10분 주기로 USD/KRW 환율을 갱신하고 Redis에 캐싱한다.

3단계 폴백 체인으로 환율을 조회한다:
  1차: KIS API (FxManager.get_rate())
  2차: 네이버 금융 크롤링
  3차: 구글 Finance 크롤링
결과를 fx:current (현재 환율)와 fx:history (롤링 이력)에 저장한다.
최대 720개 이력을 유지한다 (10분 간격 x 5일).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.common.logger import get_logger

if TYPE_CHECKING:
    from src.orchestration.init.dependency_injector import InjectedSystem

_logger = get_logger(__name__)

# 갱신 주기 (초) -- 10분이다
_INTERVAL_SEC: int = 600

# 이력 최대 보관 건수 -- 5일 x 144회/일 = 720건이다
_MAX_HISTORY: int = 720

# 폴백 환율이다
_FALLBACK_RATE: float = 1350.0


class FxScheduler:
    """10분 주기 환율 갱신 스케줄러이다.

    3단계 폴백 체인 (KIS → 네이버 → 구글)으로 환율을 조회한다.
    asyncio.create_task로 백그라운드 루프를 실행한다.
    start()로 시작하고 stop()으로 중지한다.
    """

    def __init__(self, system: InjectedSystem) -> None:
        """InjectedSystem을 주입받는다."""
        self._system = system
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False
        _logger.info(
            "FxScheduler 초기화 완료 (주기=%d초, 최대이력=%d건, 폴백=KIS→네이버→구글)",
            _INTERVAL_SEC,
            _MAX_HISTORY,
        )

    @property
    def is_running(self) -> bool:
        """스케줄러 실행 상태를 반환한다."""
        return self._running

    def start(self) -> None:
        """백그라운드 갱신 루프를 시작한다.

        이미 실행 중이면 무시한다.
        """
        if self._running:
            _logger.warning("FxScheduler가 이미 실행 중이다")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        _logger.info("FxScheduler 백그라운드 루프 시작")

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
        # 시작 직후 첫 갱신을 즉시 실행한다
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
                _logger.exception("FxScheduler 루프 예외 발생, 다음 주기에 재시도한다")

    async def _tick(self) -> None:
        """환율 1회 갱신을 수행한다.

        3단계 폴백 체인으로 환율을 조회한다:
          1차: KIS API (FxManager)
          2차: 네이버 금융 크롤링
          3차: 구글 Finance 크롤링
        모두 실패 시 폴백 환율(1350.0)을 사용한다.
        fx:current와 fx:history를 업데이트한다.
        """
        try:
            rate_value, source = await self._fetch_rate_with_fallback()
            now = datetime.now(tz=timezone.utc)

            cache = self._system.components.cache

            # 이전 환율을 읽어 변동률을 계산한다
            change_pct = await self._calc_change_pct(cache, rate_value)

            # fx:current 갱신
            current_data: dict[str, object] = {
                "usd_krw_rate": rate_value,
                "change_pct": change_pct,
                "updated_at": now.isoformat(),
                "source": source,
            }
            await cache.write_json("fx:current", current_data)

            # fx:history 롤링 이력 추가
            entry: dict[str, object] = {
                "date": now.strftime("%Y-%m-%d %H:%M"),
                "rate": rate_value,
                "change_pct": change_pct,
            }
            await self._append_history(cache, entry)

            _logger.info(
                "환율 갱신 완료: %.2f 원/달러 (변동 %.2f%%, 소스=%s)",
                rate_value,
                change_pct,
                source,
            )
        except Exception:
            _logger.exception("환율 갱신 실패")

    async def _fetch_rate_with_fallback(self) -> tuple[float, str]:
        """3단계 폴백 체인으로 환율을 조회한다.

        반환값: (환율, 소스명) 튜플이다.
        순서: KIS API → 네이버 크롤링 → 구글 크롤링 → 폴백 상수
        """
        # 1차: KIS API (FxManager)
        rate = await self._try_kis_rate()
        if rate is not None:
            return rate, "KIS"

        # 2차: 네이버 금융 크롤링
        rate = await self._try_naver_rate()
        if rate is not None:
            return rate, "Naver"

        # 3차: 구글 Finance 크롤링
        rate = await self._try_google_rate()
        if rate is not None:
            return rate, "Google"

        # 모두 실패: 폴백 상수 사용
        _logger.warning(
            "환율 조회 3단계 모두 실패, 폴백 환율 사용: %.0f", _FALLBACK_RATE
        )
        return _FALLBACK_RATE, "fallback"

    async def _try_kis_rate(self) -> float | None:
        """1차: KIS API로 환율을 조회한다."""
        try:
            fx_manager = self._system.features.get("fx_manager")
            if fx_manager is None:
                _logger.debug("FxManager 미등록, KIS 환율 조회 스킵")
                return None

            fx_rate = await fx_manager.get_rate()
            rate_value = float(fx_rate.usd_krw)

            # 폴백값(1350.0)이 아닌 실제 조회 값인지 확인한다
            # FxManager 내부에서 이미 폴백 처리가 되므로, 소스를 판별한다
            if rate_value == _FALLBACK_RATE:
                _logger.debug("KIS API 환율이 폴백값과 동일, 크롤링으로 전환한다")
                return None

            if 900 < rate_value < 2000:
                _logger.info("KIS API 환율 조회 성공: %.2f", rate_value)
                return rate_value

            _logger.warning("KIS API 환율 범위 이탈: %.2f", rate_value)
            return None
        except Exception:
            _logger.warning("KIS API 환율 조회 실패, 다음 소스로 전환", exc_info=True)
            return None

    async def _try_naver_rate(self) -> float | None:
        """2차: 네이버 금융에서 환율을 크롤링한다."""
        try:
            from src.monitoring.crawlers.naver_fx import fetch_naver_usd_krw

            rate = await fetch_naver_usd_krw()
            if rate is not None:
                _logger.info("네이버 환율 크롤링 성공: %.2f", rate)
            return rate
        except Exception:
            _logger.warning("네이버 환율 크롤링 실패", exc_info=True)
            return None

    async def _try_google_rate(self) -> float | None:
        """3차: 구글 Finance에서 환율을 크롤링한다."""
        try:
            from src.monitoring.crawlers.google_fx import fetch_google_usd_krw

            rate = await fetch_google_usd_krw()
            if rate is not None:
                _logger.info("구글 환율 크롤링 성공: %.2f", rate)
            return rate
        except Exception:
            _logger.warning("구글 환율 크롤링 실패", exc_info=True)
            return None

    async def _calc_change_pct(
        self,
        cache: object,
        current_rate: float,
    ) -> float:
        """이전 캐시 대비 변동률을 계산한다.

        이전 데이터가 없으면 0.0을 반환한다.
        """
        try:
            prev = await cache.read_json("fx:current")  # type: ignore[union-attr]
            if prev and isinstance(prev, dict):
                prev_rate = float(prev.get("usd_krw_rate", 0))
                if prev_rate > 0:
                    return round((current_rate - prev_rate) / prev_rate * 100, 4)
        except Exception:
            pass
        return 0.0

    async def _append_history(
        self,
        cache: object,
        entry: dict[str, object],
    ) -> None:
        """fx:history 리스트에 새 항목을 추가한다. 최대 _MAX_HISTORY 건을 유지한다."""
        try:
            history = await cache.read_json("fx:history")  # type: ignore[union-attr]
            if not isinstance(history, list):
                history = []

            # 최신 항목을 앞에 추가한다
            history.insert(0, entry)

            # 최대 건수를 초과하면 오래된 항목을 제거한다
            if len(history) > _MAX_HISTORY:
                history = history[:_MAX_HISTORY]

            await cache.write_json("fx:history", history)  # type: ignore[union-attr]
        except Exception:
            _logger.exception("환율 이력 저장 실패")
