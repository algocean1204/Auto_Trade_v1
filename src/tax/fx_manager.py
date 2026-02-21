"""
USD/KRW 환율 관리 모듈.

KIS API 또는 외부 무료 API에서 환율을 조회하고,
거래의 실질수익률(환율 변동 포함)을 계산한다.

환율 소스 우선순위:
  1순위: exchangerate.host (무료, API키 불필요)
  2순위: KIS API (고시환율, 하루 1회 갱신)
  3순위: DB 최근 기록
  4순위: 하드코딩 폴백 (1450.0)

백그라운드 태스크로 1시간마다 자동 갱신하며, 인메모리 캐시를 통해
매 요청마다 외부 API를 호출하지 않는다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from sqlalchemy import select

from src.db.connection import get_session
from src.db.models import FxRate, TaxRecord, Trade
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 하드코딩 폴백 환율 (KRW per 1 USD)
_DEFAULT_RATE: float = 1450.0

# 주기 업데이트 간격 (초 단위: 1시간)
_UPDATE_INTERVAL_SEC: int = 3600

# 외부 API 요청 타임아웃 (초)
_HTTP_TIMEOUT_SEC: int = 10

# 외부 환율 API 목록 (우선순위 순)
_EXTERNAL_APIS = [
    # exchangerate-api.com open endpoint (API 키 불필요, 무료)
    {
        "url": "https://open.er-api.com/v6/latest/USD",
        "parser": lambda data: float(data["rates"]["KRW"]),
        "name": "open.er-api.com",
    },
    # fawazahmed0 currency API (완전 무료, API 키 불필요)
    {
        "url": "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
        "parser": lambda data: float(data["usd"]["krw"]),
        "name": "fawazahmed0-cdn",
    },
]


class FXManager:
    """USD/KRW 환율을 관리하고 실질수익률을 계산한다.

    외부 무료 API를 1순위로 조회하고, 실패 시 KIS API → DB → 폴백 순으로
    환율을 가져온다. 백그라운드 태스크로 1시간마다 자동 갱신하며 인메모리
    캐시를 통해 동기적으로 빠르게 환율을 제공한다.
    """

    def __init__(self, kis_client: Any = None) -> None:
        """FXManager를 초기화한다.

        Args:
            kis_client: KISClient 인스턴스. None이면 KIS API 조회가 불가하다.
        """
        self._kis_client = kis_client
        self._cached_rate: float | None = None
        self._cache_time: datetime | None = None
        self._update_task: asyncio.Task | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # 캐시 접근
    # ------------------------------------------------------------------

    async def get_cached_rate(self) -> float:
        """캐시된 환율을 반환한다.

        캐시가 없거나 만료된 경우(2시간 초과) fetch_current_rate()를 호출하여
        갱신한 뒤 반환한다.

        Returns:
            USD/KRW 환율.
        """
        now = datetime.now(tz=timezone.utc)
        cache_valid = (
            self._cached_rate is not None
            and self._cache_time is not None
            and (now - self._cache_time) < timedelta(hours=2)
        )
        if cache_valid:
            logger.debug(
                "캐시 환율 반환 | rate=%.2f | cached_at=%s",
                self._cached_rate,
                self._cache_time.isoformat() if self._cache_time else "N/A",
            )
            return self._cached_rate  # type: ignore[return-value]

        logger.debug("캐시 만료 또는 미존재 -- fetch_current_rate() 호출")
        return await self.fetch_current_rate()

    def get_cached_rate_sync(self) -> float | None:
        """동기적으로 캐시된 환율을 반환한다 (await 없이 사용 가능).

        캐시가 없으면 None을 반환하며, 호출자가 직접 폴백을 처리해야 한다.

        Returns:
            캐시된 환율, 또는 캐시가 없을 경우 None.
        """
        return self._cached_rate

    # ------------------------------------------------------------------
    # 외부 API 조회
    # ------------------------------------------------------------------

    async def _fetch_external_rate(self) -> float | None:
        """외부 무료 환율 API에서 USD/KRW 환율을 조회한다.

        _EXTERNAL_APIS 목록을 우선순위대로 순회하며, 처음으로 성공한
        응답을 반환한다. 모든 소스가 실패하면 None을 반환한다.

        Returns:
            USD/KRW 환율, 또는 모든 소스 실패 시 None.
        """
        timeout = aiohttp.ClientTimeout(total=_HTTP_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for api in _EXTERNAL_APIS:
                try:
                    async with session.get(api["url"]) as resp:
                        if resp.status != 200:
                            logger.warning(
                                "외부 환율 API HTTP 오류 | source=%s | status=%d",
                                api["name"],
                                resp.status,
                            )
                            continue
                        data = await resp.json(content_type=None)
                        rate = api["parser"](data)
                        if rate and rate > 0:
                            logger.info(
                                "외부 환율 조회 성공 | source=%s | rate=%.2f",
                                api["name"],
                                rate,
                            )
                            return round(rate, 2)
                except asyncio.TimeoutError:
                    logger.warning(
                        "외부 환율 API 타임아웃 | source=%s | timeout=%ds",
                        api["name"],
                        _HTTP_TIMEOUT_SEC,
                    )
                except Exception:
                    logger.warning(
                        "외부 환율 API 호출 실패 | source=%s",
                        api["name"],
                        exc_info=True,
                    )

        logger.warning("모든 외부 환율 API 실패")
        return None

    # ------------------------------------------------------------------
    # 메인 조회 로직
    # ------------------------------------------------------------------

    async def fetch_current_rate(self) -> float:
        """현재 USD/KRW 환율을 조회하고 캐시를 갱신한다.

        소스 우선순위:
          1. 외부 무료 API (open.er-api.com → fawazahmed0-cdn)
          2. KIS API (고시환율)
          3. DB 최근 기록
          4. 하드코딩 폴백 (1450.0)

        성공한 환율은 인메모리 캐시와 DB에 모두 저장한다.

        Returns:
            USD/KRW 환율 (소수점 2자리).
        """
        # 1순위: 외부 무료 API
        try:
            rate = await self._fetch_external_rate()
            if rate is not None and rate > 0:
                await self._update_cache(rate, source="EXTERNAL")
                return rate
        except Exception:
            logger.exception("외부 환율 API 처리 중 예외 발생, KIS로 폴백")

        # 2순위: KIS API
        try:
            if self._kis_client is not None:
                rate = await self._kis_client.get_exchange_rate()
                if rate and rate > 0:
                    await self._update_cache(rate, source="KIS")
                    return round(rate, 2)
                logger.warning("KIS API 환율 0 반환, DB fallback 시도")
        except Exception:
            logger.exception("KIS API 환율 조회 실패, DB fallback 시도")

        # 3순위: DB 최근 기록
        try:
            rate = await self._get_latest_rate_from_db()
            self._cached_rate = rate
            self._cache_time = datetime.now(tz=timezone.utc)
            return rate
        except Exception:
            logger.exception("DB 환율 조회도 실패, 기본값 사용")

        # 4순위: 하드코딩 폴백
        logger.warning("모든 환율 소스 실패, 기본값 사용: %.2f KRW/USD", _DEFAULT_RATE)
        return _DEFAULT_RATE

    async def _update_cache(self, rate: float, source: str) -> None:
        """인메모리 캐시를 갱신하고 DB에 기록한다.

        Args:
            rate: USD/KRW 환율.
            source: 데이터 출처 문자열.
        """
        self._cached_rate = round(rate, 2)
        self._cache_time = datetime.now(tz=timezone.utc)
        await self.record_rate(self._cached_rate, source=source)

    # ------------------------------------------------------------------
    # 백그라운드 주기 업데이트
    # ------------------------------------------------------------------

    def start_periodic_update(self) -> None:
        """1시간 주기 환율 자동 갱신 태스크를 시작한다.

        asyncio.create_task()로 백그라운드 태스크를 생성한다.
        이미 실행 중인 태스크가 있으면 아무 작업도 하지 않는다.
        반드시 실행 중인 이벤트 루프 내에서 호출되어야 한다.
        """
        if self._update_task is not None and not self._update_task.done():
            logger.debug("환율 주기 업데이트 태스크가 이미 실행 중이다.")
            return

        self._update_task = asyncio.create_task(
            self._periodic_update_loop(),
            name="fx_periodic_update",
        )
        logger.info(
            "환율 주기 업데이트 태스크 시작 | 주기=%d초 (%d분)",
            _UPDATE_INTERVAL_SEC,
            _UPDATE_INTERVAL_SEC // 60,
        )

    def stop_periodic_update(self) -> None:
        """1시간 주기 환율 자동 갱신 태스크를 중단한다.

        실행 중인 태스크를 취소하고 참조를 None으로 초기화한다.
        이미 완료된 태스크나 태스크가 없는 경우 아무 작업도 하지 않는다.
        """
        if self._update_task is None or self._update_task.done():
            logger.debug("환율 주기 업데이트 태스크가 실행 중이 아니다.")
            return

        self._update_task.cancel()
        self._update_task = None
        logger.info("환율 주기 업데이트 태스크 중단 완료")

    async def _periodic_update_loop(self) -> None:
        """1시간마다 환율을 조회하고 갱신하는 내부 루프이다.

        서버 시작 시 즉시 최초 조회를 수행한 뒤, 이후에는 _UPDATE_INTERVAL_SEC
        간격으로 반복한다. CancelledError가 발생하면 정상 종료한다.
        """
        logger.info("환율 주기 업데이트 루프 시작")
        try:
            # 최초 1회 즉시 실행 (캐시 워밍업)
            await self._run_single_update()

            while True:
                await asyncio.sleep(_UPDATE_INTERVAL_SEC)
                await self._run_single_update()
        except asyncio.CancelledError:
            logger.info("환율 주기 업데이트 루프 정상 종료 (CancelledError)")
        except Exception:
            logger.exception("환율 주기 업데이트 루프 예외 발생 -- 루프 종료")

    async def _run_single_update(self) -> None:
        """환율을 1회 조회하고 캐시 및 DB를 갱신한다.

        예외가 발생해도 루프가 중단되지 않도록 내부에서 처리한다.
        """
        try:
            rate = await self.fetch_current_rate()
            logger.info(
                "환율 주기 갱신 완료 | rate=%.2f | next_update=%s",
                rate,
                (
                    datetime.now(tz=timezone.utc)
                    + timedelta(seconds=_UPDATE_INTERVAL_SEC)
                ).strftime("%H:%M UTC"),
            )
        except Exception:
            logger.exception("환율 주기 갱신 실패 -- 다음 주기에 재시도")

    # ------------------------------------------------------------------
    # DB 조회 / 기록
    # ------------------------------------------------------------------

    async def _get_latest_rate_from_db(self) -> float:
        """DB에서 가장 최근 환율을 조회한다.

        Returns:
            최근 USD/KRW 환율.

        Raises:
            ValueError: DB에 환율 기록이 없을 때.
        """
        async with get_session() as session:
            result = await session.execute(
                select(FxRate.usd_krw_rate)
                .order_by(FxRate.timestamp.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()

        if row is None:
            raise ValueError("DB에 환율 기록이 없음")

        rate = round(float(row), 2)
        logger.info("DB fallback 환율 사용 | rate=%.2f", rate)
        return rate

    async def record_rate(self, rate: float, source: str = "KIS") -> None:
        """환율 기록을 DB에 저장한다.

        Args:
            rate: USD/KRW 환율.
            source: 데이터 출처 (기본값 "KIS").

        Raises:
            Exception: DB 저장 실패 시 예외를 재발생시킨다.
        """
        try:
            record = FxRate(
                timestamp=datetime.now(tz=timezone.utc),
                usd_krw_rate=round(rate, 2),
                source=source,
            )

            async with get_session() as session:
                session.add(record)

            logger.info("환율 기록 저장 | rate=%.2f | source=%s", rate, source)
        except Exception:
            logger.exception("환율 기록 저장 실패 | rate=%.2f", rate)
            raise

    # ------------------------------------------------------------------
    # 비즈니스 로직
    # ------------------------------------------------------------------

    async def get_effective_return(self, trade_id: str) -> dict[str, Any]:
        """특정 거래의 실질수익률을 계산한다.

        USD 수익률에 환율 변동분을 반영하여 KRW 기준 실질수익률을 산출한다.

        Args:
            trade_id: 거래 UUID.

        Returns:
            {"usd_return_pct", "fx_change_pct", "effective_krw_return_pct"}.

        Raises:
            ValueError: 거래를 찾을 수 없거나 진입가가 유효하지 않을 때.
            Exception: DB 조회 또는 환율 조회 실패 시.
        """
        try:
            async with get_session() as session:
                trade = await session.get(Trade, trade_id)
                if trade is None:
                    raise ValueError(f"거래를 찾을 수 없음: {trade_id}")

                result = await session.execute(
                    select(TaxRecord.fx_rate_at_trade)
                    .where(TaxRecord.trade_id == trade_id)
                    .order_by(TaxRecord.created_at.asc())
                    .limit(1)
                )
                entry_fx_rate = result.scalar_one_or_none()

            if trade.entry_price is None or trade.entry_price == 0:
                raise ValueError(f"유효하지 않은 진입가: {trade_id}")

            usd_return_pct = 0.0
            if trade.exit_price is not None:
                usd_return_pct = (
                    (trade.exit_price - trade.entry_price) / trade.entry_price
                ) * 100.0

            current_fx = await self.get_cached_rate()
            fx_at_entry = float(entry_fx_rate) if entry_fx_rate else current_fx

            fx_change_pct = 0.0
            if fx_at_entry > 0:
                fx_change_pct = ((current_fx - fx_at_entry) / fx_at_entry) * 100.0

            effective_krw_return_pct = (
                (1 + usd_return_pct / 100.0) * (1 + fx_change_pct / 100.0) - 1
            ) * 100.0

            result_dict = {
                "usd_return_pct": round(usd_return_pct, 4),
                "fx_change_pct": round(fx_change_pct, 4),
                "effective_krw_return_pct": round(effective_krw_return_pct, 4),
            }

            logger.info(
                "실질수익률 | trade_id=%s | usd=%.2f%% | fx=%.2f%% | krw=%.2f%%",
                trade_id,
                usd_return_pct,
                fx_change_pct,
                effective_krw_return_pct,
            )
            return result_dict
        except Exception:
            logger.exception("실질수익률 계산 실패 | trade_id=%s", trade_id)
            raise

    async def get_fx_history(self, days: int = 30) -> list[dict]:
        """최근 N일 환율 이력을 반환한다.

        Args:
            days: 조회 일수 (기본값 30).

        Returns:
            환율 이력 리스트. 각 항목은 {"timestamp", "rate", "source"}.

        Raises:
            Exception: DB 조회 실패 시.
        """
        try:
            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

            async with get_session() as session:
                result = await session.execute(
                    select(FxRate)
                    .where(FxRate.timestamp >= cutoff)
                    .order_by(FxRate.timestamp.desc())
                )
                rows = result.scalars().all()

            history = [
                {
                    "timestamp": row.timestamp.isoformat(),
                    "rate": round(row.usd_krw_rate, 2),
                    "source": row.source,
                }
                for row in rows
            ]

            logger.info("환율 이력 조회 | days=%d | records=%d", days, len(history))
            return history
        except Exception:
            logger.exception("환율 이력 조회 실패 | days=%d", days)
            raise

    async def calculate_krw_value(self, usd_amount: float) -> float:
        """USD 금액을 현재 환율로 KRW로 변환한다.

        Args:
            usd_amount: USD 금액.

        Returns:
            KRW 금액 (소수점 2자리).

        Raises:
            Exception: 환율 조회 또는 계산 실패 시.
        """
        try:
            rate = await self.get_cached_rate()
            krw_value = round(usd_amount * rate, 2)
            logger.info(
                "환율 변환 | usd=%.2f | rate=%.2f | krw=%.2f",
                usd_amount,
                rate,
                krw_value,
            )
            return krw_value
        except Exception:
            logger.exception("환율 변환 실패 | usd_amount=%.2f", usd_amount)
            raise
