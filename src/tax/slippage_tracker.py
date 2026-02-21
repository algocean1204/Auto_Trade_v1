"""
주문 체결 슬리피지 추적 모듈.

예상 가격과 실제 체결 가격의 차이를 기록하고,
시간대별 슬리피지 통계를 통해 최적 체결 시간을 제안한다.
"""

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.sql import func

from src.db.connection import get_session
from src.db.models import SlippageLog
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SlippageTracker:
    """주문 체결 슬리피지를 추적하고 분석한다.

    체결 시 예상가와 실제가의 차이를 기록하며,
    시간대별 통계를 기반으로 최적 매매 시간을 제안한다.
    """

    async def record_slippage(
        self,
        trade_id: str,
        ticker: str,
        expected_price: float,
        actual_price: float,
        volume: int | None = None,
    ) -> None:
        """슬리피지 기록을 저장한다.

        Args:
            trade_id: 거래 UUID.
            ticker: 종목 심볼.
            expected_price: 예상 체결가.
            actual_price: 실제 체결가.
            volume: 체결 수량 (선택).
        """
        try:
            if expected_price <= 0:
                raise ValueError(f"expected_price는 양수여야 함: {expected_price}")

            slippage_pct = (
                (actual_price - expected_price) / expected_price
            ) * 100.0

            now = datetime.now(tz=timezone.utc)

            record = SlippageLog(
                trade_id=trade_id,
                ticker=ticker,
                expected_price=expected_price,
                actual_price=actual_price,
                slippage_pct=round(slippage_pct, 6),
                volume_at_fill=volume,
                time_of_day=now,
            )

            async with get_session() as session:
                session.add(record)

            logger.info(
                "슬리피지 기록 | trade_id=%s | ticker=%s | expected=%.4f | "
                "actual=%.4f | slippage=%.4f%%",
                trade_id,
                ticker,
                expected_price,
                actual_price,
                slippage_pct,
            )
        except Exception as exc:
            logger.exception(
                "슬리피지 기록 실패 | trade_id=%s | ticker=%s",
                trade_id,
                ticker,
            )
            raise

    async def get_stats(
        self, ticker: str | None = None, days: int = 30
    ) -> dict[str, Any]:
        """슬리피지 통계를 반환한다.

        Args:
            ticker: 종목 심볼. None이면 전체 종목 대상.
            days: 조회 기간 (일).

        Returns:
            {"avg_slippage_pct", "median_slippage_pct", "max_slippage_pct", "by_hour"}.
        """
        try:
            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

            stmt = select(SlippageLog).where(SlippageLog.time_of_day >= cutoff)
            if ticker is not None:
                stmt = stmt.where(SlippageLog.ticker == ticker)

            async with get_session() as session:
                result = await session.execute(stmt)
                logs = result.scalars().all()

            if not logs:
                empty_stats: dict[str, Any] = {
                    "avg_slippage_pct": 0.0,
                    "median_slippage_pct": 0.0,
                    "max_slippage_pct": 0.0,
                    "by_hour": {},
                }
                logger.info(
                    "슬리피지 통계 | ticker=%s | days=%d | 기록 없음",
                    ticker,
                    days,
                )
                return empty_stats

            pcts = [log.slippage_pct for log in logs]
            abs_pcts = [abs(p) for p in pcts]

            by_hour: dict[str, float] = {}
            hour_values: dict[int, list[float]] = {}
            for log in logs:
                hour = log.time_of_day.hour
                hour_values.setdefault(hour, []).append(abs(log.slippage_pct))

            for hour, values in sorted(hour_values.items()):
                by_hour[f"{hour:02d}"] = round(
                    sum(values) / len(values), 4
                )

            stats: dict[str, Any] = {
                "avg_slippage_pct": round(
                    sum(abs_pcts) / len(abs_pcts), 4
                ),
                "median_slippage_pct": round(statistics.median(abs_pcts), 4),
                "max_slippage_pct": round(max(abs_pcts), 4),
                "by_hour": by_hour,
            }

            logger.info(
                "슬리피지 통계 | ticker=%s | days=%d | records=%d | avg=%.4f%%",
                ticker,
                days,
                len(logs),
                stats["avg_slippage_pct"],
            )
            return stats
        except Exception as exc:
            logger.exception(
                "슬리피지 통계 조회 실패 | ticker=%s | days=%d", ticker, days
            )
            raise

    async def get_optimal_execution_time(
        self, ticker: str
    ) -> dict[str, Any]:
        """슬리피지가 가장 낮은 시간대를 추천한다.

        개장 후 30분(09:30~10:00 ET)과 마감 전 30분(15:30~16:00 ET)은
        일반적으로 슬리피지가 높으므로 회피를 권장한다.

        Args:
            ticker: 종목 심볼.

        Returns:
            {"best_hour", "best_avg_slippage_pct", "avoid_hours", "message"}.
        """
        try:
            stats = await self.get_stats(ticker=ticker, days=90)
            by_hour = stats.get("by_hour", {})

            avoid_hours = ["09", "10", "15", "16"]

            if not by_hour:
                result: dict[str, Any] = {
                    "best_hour": None,
                    "best_avg_slippage_pct": None,
                    "avoid_hours": avoid_hours,
                    "message": "슬리피지 데이터 부족으로 추천 불가. 개장/마감 시간대 회피 권장.",
                }
                logger.info(
                    "최적 체결 시간 | ticker=%s | 데이터 부족", ticker
                )
                return result

            best_hour = min(by_hour, key=by_hour.get)  # type: ignore[arg-type]
            best_slippage = by_hour[best_hour]

            result = {
                "best_hour": best_hour,
                "best_avg_slippage_pct": round(best_slippage, 4),
                "avoid_hours": avoid_hours,
                "message": (
                    f"최적 체결 시간대: {best_hour}시 (평균 슬리피지 {best_slippage:.4f}%). "
                    f"개장 후 30분/마감 전 30분 회피 권장."
                ),
            }

            logger.info(
                "최적 체결 시간 | ticker=%s | best_hour=%s | slippage=%.4f%%",
                ticker,
                best_hour,
                best_slippage,
            )
            return result
        except Exception as exc:
            logger.exception(
                "최적 체결 시간 분석 실패 | ticker=%s", ticker
            )
            raise

    async def is_slippage_acceptable(
        self, ticker: str, threshold_pct: float = 0.3
    ) -> bool:
        """최근 평균 슬리피지가 임계값 이내인지 확인한다.

        Args:
            ticker: 종목 심볼.
            threshold_pct: 허용 슬리피지 임계값 (%, 기본값 0.3).

        Returns:
            True이면 허용 범위, False이면 초과.
        """
        try:
            stats = await self.get_stats(ticker=ticker, days=30)
            avg = stats["avg_slippage_pct"]
            acceptable = avg <= threshold_pct

            logger.info(
                "슬리피지 허용 판단 | ticker=%s | avg=%.4f%% | threshold=%.2f%% | %s",
                ticker,
                avg,
                threshold_pct,
                "허용" if acceptable else "초과",
            )
            return acceptable
        except Exception as exc:
            logger.exception(
                "슬리피지 허용 판단 실패 | ticker=%s", ticker
            )
            raise
