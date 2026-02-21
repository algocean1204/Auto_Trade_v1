"""
AI 전략 수익률과 패시브 벤치마크(SPY Buy&Hold, SSO Buy&Hold, 현금) 비교 모듈.

일간/주간 스냅샷을 기록하고 AI 전략의 상대적 성과를 분석한다.
2주 연속 SPY/SSO 모두 하회 시 전략 재검토 알림을 트리거한다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, func, and_

from src.db.connection import get_session
from src.db.models import BenchmarkSnapshot
from src.indicators.data_fetcher import PriceDataFetcher
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.executor.kis_client import KISClient

logger = get_logger(__name__)

_UNDERPERFORM_THRESHOLD_WEEKS = 2


class BenchmarkComparison:
    """AI 전략 수익률과 패시브 벤치마크를 비교한다.

    비교 대상:
        - SPY Buy&Hold
        - SSO Buy&Hold
        - 현금 (항상 0%)
    """

    def __init__(self, kis_client: "KISClient") -> None:
        """BenchmarkComparison을 초기화한다.

        Args:
            kis_client: KIS API 클라이언트 인스턴스.
        """
        self._data_fetcher = PriceDataFetcher(kis_client)

    # ------------------------------------------------------------------
    # 일간 스냅샷
    # ------------------------------------------------------------------

    async def record_daily_snapshot(
        self,
        ai_return_pct: float,
        spy_return_pct: float,
        sso_return_pct: float,
    ) -> None:
        """일간 수익률 스냅샷을 저장한다.

        Args:
            ai_return_pct: AI 전략 일간 수익률 (%).
            spy_return_pct: SPY Buy&Hold 일간 수익률 (%).
            sso_return_pct: SSO Buy&Hold 일간 수익률 (%).
        """
        today = date.today()
        ai_vs_spy = round(ai_return_pct - spy_return_pct, 4)
        ai_vs_sso = round(ai_return_pct - sso_return_pct, 4)

        try:
            async with get_session() as session:
                snapshot = BenchmarkSnapshot(
                    date=today,
                    period_type="daily",
                    ai_return_pct=ai_return_pct,
                    spy_buyhold_return_pct=spy_return_pct,
                    sso_buyhold_return_pct=sso_return_pct,
                    cash_return_pct=0.0,
                    ai_vs_spy_diff=ai_vs_spy,
                    ai_vs_sso_diff=ai_vs_sso,
                    consecutive_underperform_weeks=0,
                )
                session.add(snapshot)

            logger.info(
                "일간 벤치마크 스냅샷 저장 | AI=%.2f%% | SPY=%.2f%% | SSO=%.2f%% | diff_spy=%+.2f%% | diff_sso=%+.2f%%",
                ai_return_pct,
                spy_return_pct,
                sso_return_pct,
                ai_vs_spy,
                ai_vs_sso,
            )
        except Exception as exc:
            logger.error("일간 벤치마크 스냅샷 저장 실패: %s", exc)

    # ------------------------------------------------------------------
    # 주간 스냅샷
    # ------------------------------------------------------------------

    async def record_weekly_snapshot(self) -> dict[str, Any]:
        """주간 스냅샷을 생성한다. 해당 주의 일간 데이터를 합산하여 계산한다.

        Returns:
            주간 스냅샷 데이터 딕셔너리.
        """
        today = date.today()
        # 이번 주 월요일 ~ 오늘까지
        week_start = today - timedelta(days=today.weekday())

        try:
            async with get_session() as session:
                stmt = select(BenchmarkSnapshot).where(
                    and_(
                        BenchmarkSnapshot.period_type == "daily",
                        BenchmarkSnapshot.date >= week_start,
                        BenchmarkSnapshot.date <= today,
                    )
                )
                result = await session.execute(stmt)
                daily_snapshots = result.scalars().all()

            if not daily_snapshots:
                logger.warning("주간 스냅샷 생성 실패: 일간 데이터 없음 (week_start=%s)", week_start)
                return {"error": "no_daily_data", "week_start": str(week_start)}

            ai_total = sum(s.ai_return_pct for s in daily_snapshots)
            spy_total = sum(s.spy_buyhold_return_pct for s in daily_snapshots)
            sso_total = sum(s.sso_buyhold_return_pct for s in daily_snapshots)

            ai_vs_spy = round(ai_total - spy_total, 4)
            ai_vs_sso = round(ai_total - sso_total, 4)

            # 연속 하회 주 수 계산
            consecutive_weeks = await self._count_consecutive_underperform_weeks()
            if ai_vs_spy < 0 and ai_vs_sso < 0:
                consecutive_weeks += 1

            async with get_session() as session:
                weekly_snapshot = BenchmarkSnapshot(
                    date=today,
                    period_type="weekly",
                    ai_return_pct=round(ai_total, 4),
                    spy_buyhold_return_pct=round(spy_total, 4),
                    sso_buyhold_return_pct=round(sso_total, 4),
                    cash_return_pct=0.0,
                    ai_vs_spy_diff=ai_vs_spy,
                    ai_vs_sso_diff=ai_vs_sso,
                    consecutive_underperform_weeks=consecutive_weeks,
                )
                session.add(weekly_snapshot)

            result_data = {
                "week_start": str(week_start),
                "week_end": str(today),
                "ai_return_pct": round(ai_total, 4),
                "spy_return_pct": round(spy_total, 4),
                "sso_return_pct": round(sso_total, 4),
                "ai_vs_spy_diff": ai_vs_spy,
                "ai_vs_sso_diff": ai_vs_sso,
                "consecutive_underperform_weeks": consecutive_weeks,
                "daily_count": len(daily_snapshots),
            }

            logger.info(
                "주간 벤치마크 스냅샷 저장 | AI=%.2f%% | SPY=%.2f%% | SSO=%.2f%% | 연속하회=%d주",
                ai_total,
                spy_total,
                sso_total,
                consecutive_weeks,
            )
            return result_data

        except Exception as exc:
            logger.error("주간 벤치마크 스냅샷 생성 실패: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # 비교 데이터 조회
    # ------------------------------------------------------------------

    async def get_comparison(
        self,
        period: str = "weekly",
        lookback: int = 4,
    ) -> dict[str, Any]:
        """최근 N주/일 비교 데이터를 반환한다.

        Args:
            period: "daily" 또는 "weekly".
            lookback: 조회할 기간 수.

        Returns:
            비교 데이터 딕셔너리. periods 리스트와 summary를 포함한다.
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(BenchmarkSnapshot)
                    .where(BenchmarkSnapshot.period_type == period)
                    .order_by(BenchmarkSnapshot.date.desc())
                    .limit(lookback)
                )
                result = await session.execute(stmt)
                snapshots = result.scalars().all()

            if not snapshots:
                return {
                    "periods": [],
                    "summary": {
                        "ai_total": 0.0,
                        "spy_total": 0.0,
                        "sso_total": 0.0,
                        "ai_win_rate_vs_spy": 0.0,
                        "ai_win_rate_vs_sso": 0.0,
                    },
                }

            periods = []
            ai_total = 0.0
            spy_total = 0.0
            sso_total = 0.0
            ai_wins_spy = 0
            ai_wins_sso = 0

            for s in snapshots:
                periods.append({
                    "date": str(s.date),
                    "ai_return_pct": s.ai_return_pct,
                    "spy_return_pct": s.spy_buyhold_return_pct,
                    "sso_return_pct": s.sso_buyhold_return_pct,
                    "ai_vs_spy_diff": s.ai_vs_spy_diff,
                    "ai_vs_sso_diff": s.ai_vs_sso_diff,
                })
                ai_total += s.ai_return_pct
                spy_total += s.spy_buyhold_return_pct
                sso_total += s.sso_buyhold_return_pct
                if s.ai_vs_spy_diff >= 0:
                    ai_wins_spy += 1
                if s.ai_vs_sso_diff >= 0:
                    ai_wins_sso += 1

            count = len(snapshots)
            return {
                "periods": periods,
                "summary": {
                    "ai_total": round(ai_total, 4),
                    "spy_total": round(spy_total, 4),
                    "sso_total": round(sso_total, 4),
                    "ai_win_rate_vs_spy": round(ai_wins_spy / count * 100, 2),
                    "ai_win_rate_vs_sso": round(ai_wins_sso / count * 100, 2),
                },
            }

        except Exception as exc:
            logger.error("벤치마크 비교 데이터 조회 실패: %s", exc)
            return {"periods": [], "summary": {}, "error": str(exc)}

    # ------------------------------------------------------------------
    # 언더퍼포먼스 체크
    # ------------------------------------------------------------------

    async def check_underperformance(self) -> dict[str, Any]:
        """2주 연속 SPY/SSO 모두 하회 시 전략 재검토 알림을 트리거한다.

        Returns:
            언더퍼포먼스 상태 딕셔너리.
            needs_review가 True이면 전략 재검토가 필요하다.
        """
        try:
            consecutive_weeks = await self._count_consecutive_underperform_weeks()

            needs_review = consecutive_weeks >= _UNDERPERFORM_THRESHOLD_WEEKS

            if needs_review:
                details = (
                    f"AI 전략이 {consecutive_weeks}주 연속 SPY와 SSO 모두 하회. "
                    f"전략 파라미터 재검토 필요."
                )
                logger.warning(details)
            else:
                details = (
                    f"현재 연속 하회 {consecutive_weeks}주. "
                    f"임계값 {_UNDERPERFORM_THRESHOLD_WEEKS}주 미달."
                )

            return {
                "needs_review": needs_review,
                "consecutive_weeks": consecutive_weeks,
                "threshold": _UNDERPERFORM_THRESHOLD_WEEKS,
                "details": details,
            }

        except Exception as exc:
            logger.error("언더퍼포먼스 체크 실패: %s", exc)
            return {
                "needs_review": False,
                "consecutive_weeks": 0,
                "details": f"체크 실패: {exc}",
            }

    # ------------------------------------------------------------------
    # SPY / SSO 수익률 계산
    # ------------------------------------------------------------------

    async def calculate_spy_return(
        self,
        start_date: date,
        end_date: date,
    ) -> float:
        """SPY buy&hold 수익률을 계산한다.

        Args:
            start_date: 시작 날짜.
            end_date: 종료 날짜.

        Returns:
            기간 수익률 (%). 데이터 조회 실패 시 0.0을 반환한다.
        """
        return await self._calculate_ticker_return("SPY", start_date, end_date)

    async def calculate_sso_return(
        self,
        start_date: date,
        end_date: date,
    ) -> float:
        """SSO buy&hold 수익률을 계산한다.

        Args:
            start_date: 시작 날짜.
            end_date: 종료 날짜.

        Returns:
            기간 수익률 (%). 데이터 조회 실패 시 0.0을 반환한다.
        """
        return await self._calculate_ticker_return("SSO", start_date, end_date)

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    async def _calculate_ticker_return(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> float:
        """특정 종목의 buy&hold 수익률을 계산한다.

        Args:
            ticker: 종목 심볼.
            start_date: 시작 날짜.
            end_date: 종료 날짜.

        Returns:
            기간 수익률 (%).
        """
        try:
            days = (end_date - start_date).days + 30  # 여유분
            df = await self._data_fetcher.get_daily_prices(ticker, days=max(days, 30))

            if df is None or df.empty:
                logger.warning("%s 가격 데이터 없음", ticker)
                return 0.0

            # 날짜 필터링 (인덱스가 DatetimeIndex)
            mask = (df.index.date >= start_date) & (df.index.date <= end_date)
            filtered = df.loc[mask]

            if len(filtered) < 2:
                logger.warning(
                    "%s 필터링 후 데이터 부족: %d rows", ticker, len(filtered)
                )
                return 0.0

            start_price = float(filtered["Close"].iloc[0])
            end_price = float(filtered["Close"].iloc[-1])

            if start_price <= 0:
                return 0.0

            return_pct = round((end_price - start_price) / start_price * 100, 4)
            logger.info(
                "%s 수익률 계산 | %s~%s | %.2f -> %.2f | return=%.2f%%",
                ticker,
                start_date,
                end_date,
                start_price,
                end_price,
                return_pct,
            )
            return return_pct

        except Exception as exc:
            logger.error("%s 수익률 계산 실패: %s", ticker, exc)
            return 0.0

    async def _count_consecutive_underperform_weeks(self) -> int:
        """최근 주간 스냅샷에서 연속 하회 주 수를 계산한다.

        Returns:
            연속으로 SPY와 SSO 모두 하회한 주 수.
        """
        try:
            async with get_session() as session:
                stmt = (
                    select(BenchmarkSnapshot)
                    .where(BenchmarkSnapshot.period_type == "weekly")
                    .order_by(BenchmarkSnapshot.date.desc())
                    .limit(10)
                )
                result = await session.execute(stmt)
                weekly_snapshots = result.scalars().all()

            count = 0
            for s in weekly_snapshots:
                if s.ai_vs_spy_diff < 0 and s.ai_vs_sso_diff < 0:
                    count += 1
                else:
                    break

            return count

        except Exception as exc:
            logger.error("연속 하회 주 수 계산 실패: %s", exc)
            return 0
