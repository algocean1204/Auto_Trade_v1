"""
수익 목표 관리 모듈 (Addendum 25)

월간 수익 목표 대비 진행률을 추적하고, 진행률에 따라
공격성(aggression) 수준을 동적으로 조절한다.

주요 기능:
    - 월간/일간 수익 목표 설정 및 진행률 계산
    - 시간 대비 달성률 기반 공격성 자동 조절
    - 공격성 수준별 파라미터 매핑
    - Claude AI 프롬프트 컨텍스트 생성
    - DB 영속화 (월간 목표, 일별 PnL 로그)
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import and_, func, select

from src.db.connection import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AggressionLevel(str, Enum):
    """공격성 수준을 정의한다.

    DEFENSIVE: 목표 달성 완료, 리스크 최소화
    CONSERVATIVE: 보수적 운영
    MODERATE: 일반 운영
    AGGRESSIVE: 적극적 운영 (목표 달성이 뒤처질 때)
    """

    DEFENSIVE = "defensive"
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass
class TargetConfig:
    """수익 목표 설정을 담는 데이터 클래스이다.

    Attributes:
        monthly_target_usd: 월간 수익 목표 (USD).
        daily_target_usd: 일간 수익 목표 (USD).
        aggression_level: 현재 공격성 수준.
        auto_adjust: 공격성 자동 조절 활성화 여부.
    """

    monthly_target_usd: float = 300.0
    daily_target_usd: float = 15.0
    aggression_level: AggressionLevel = AggressionLevel.MODERATE
    auto_adjust: bool = True


# 공격성 수준별 전략 파라미터 매핑
AGGRESSION_PARAMS: dict[AggressionLevel, dict[str, Any]] = {
    AggressionLevel.DEFENSIVE: {
        "max_position_pct": 0.10,
        "max_trades_per_day": 2,
        "min_confidence": 0.85,
        "stop_loss_pct": -0.02,
        "stop_loss_tighter": True,
        "description": "목표 달성 완료, 리스크 최소화 모드",
    },
    AggressionLevel.CONSERVATIVE: {
        "max_position_pct": 0.15,
        "max_trades_per_day": 4,
        "min_confidence": 0.75,
        "stop_loss_pct": -0.03,
        "description": "보수적 운영, 안정적 수익 추구",
    },
    AggressionLevel.MODERATE: {
        "max_position_pct": 0.20,
        "max_trades_per_day": 6,
        "min_confidence": 0.65,
        "stop_loss_pct": -0.05,
        "description": "일반 운영, 균형 잡힌 리스크/보상",
    },
    AggressionLevel.AGGRESSIVE: {
        "max_position_pct": 0.25,
        "max_trades_per_day": 8,
        "min_confidence": 0.60,
        "stop_loss_pct": -0.05,
        "description": "적극적 운영, 목표 달성 가속 (손절은 절대 완화하지 않음)",
    },
}


class ProfitTargetManager:
    """수익 목표를 관리하고 공격성 수준을 동적으로 조절한다.

    월간 목표 대비 진행률을 추적하며, 시간 진행률과 수익 진행률의
    비율에 따라 공격성 수준을 자동 조절한다.

    Attributes:
        config: 수익 목표 설정.
        _month_pnl_cache: 월간 누적 PnL 캐시.
    """

    def __init__(self, config: TargetConfig | None = None) -> None:
        """ProfitTargetManager를 초기화한다.

        Args:
            config: 수익 목표 설정. None이면 기본값 사용.
        """
        self.config = config or TargetConfig()
        self._month_pnl_cache: float = 0.0
        self._last_cache_date: date | None = None

        logger.info(
            "ProfitTargetManager 초기화 | "
            "monthly_target=$%.0f | daily_target=$%.0f | "
            "aggression=%s | auto_adjust=%s",
            self.config.monthly_target_usd,
            self.config.daily_target_usd,
            self.config.aggression_level.value,
            self.config.auto_adjust,
        )

    def get_month_progress(self, today: date | None = None) -> dict[str, Any]:
        """월간 시간 진행률을 계산한다.

        Args:
            today: 기준 날짜. None이면 오늘.

        Returns:
            월간 진행 정보 딕셔너리.
        """
        if today is None:
            today = date.today()

        total_days = calendar.monthrange(today.year, today.month)[1]
        elapsed_days = today.day
        time_ratio = elapsed_days / total_days

        remaining_days = total_days - elapsed_days
        remaining_trading_days = max(1, int(remaining_days * 5 / 7))

        return {
            "year": today.year,
            "month": today.month,
            "total_days": total_days,
            "elapsed_days": elapsed_days,
            "remaining_days": remaining_days,
            "remaining_trading_days": remaining_trading_days,
            "time_ratio": round(time_ratio, 4),
        }

    async def get_month_pnl(self, today: date | None = None) -> float:
        """월간 누적 PnL을 DB에서 조회한다.

        Args:
            today: 기준 날짜.

        Returns:
            월간 누적 PnL (USD).
        """
        if today is None:
            today = date.today()

        try:
            from src.db.models import DailyPnlLog

            async with get_session() as session:
                month_start = today.replace(day=1)
                stmt = select(
                    func.coalesce(func.sum(DailyPnlLog.realized_pnl), 0.0)
                ).where(
                    and_(
                        DailyPnlLog.date >= month_start,
                        DailyPnlLog.date <= today,
                    )
                )
                result = await session.execute(stmt)
                total = float(result.scalar_one())
                self._month_pnl_cache = total
                self._last_cache_date = today
                return total
        except Exception as e:
            logger.warning("월간 PnL 조회 실패, 캐시 사용: %s", e)
            return self._month_pnl_cache

    def calculate_remaining_daily_target(
        self, month_pnl: float, remaining_trading_days: int
    ) -> float:
        """남은 기간 동안의 일일 목표 수익을 계산한다.

        Args:
            month_pnl: 현재까지의 월간 누적 PnL.
            remaining_trading_days: 남은 거래일 수.

        Returns:
            조정된 일일 목표 수익 (USD).
        """
        remaining_target = self.config.monthly_target_usd - month_pnl
        if remaining_trading_days <= 0:
            return 0.0
        adjusted_daily = remaining_target / remaining_trading_days
        return round(max(0.0, adjusted_daily), 2)

    def determine_aggression(
        self, month_pnl: float, time_ratio: float
    ) -> AggressionLevel:
        """시간 대비 달성률에 기반하여 공격성 수준을 결정한다.

        달성 비율(progress) = 현재 누적 PnL / 월간 목표
        시간 비율(time_ratio) = 경과 일수 / 총 일수
        진행률(ratio) = 달성 비율 / 시간 비율

        규칙:
            - progress >= 1.0: DEFENSIVE (목표 이미 달성)
            - ratio >= 1.2: CONSERVATIVE (앞서가고 있음)
            - ratio >= 0.8: MODERATE (정상 궤도)
            - ratio >= 0.5: AGGRESSIVE (뒤처지고 있음, 가속 필요)
            - ratio < 0.5: CONSERVATIVE (무리한 회복 방지)

        Args:
            month_pnl: 월간 누적 PnL.
            time_ratio: 시간 진행률 (0.0~1.0).

        Returns:
            결정된 공격성 수준.
        """
        if self.config.monthly_target_usd <= 0:
            return AggressionLevel.MODERATE

        progress = month_pnl / self.config.monthly_target_usd

        if progress >= 1.0:
            return AggressionLevel.DEFENSIVE

        if time_ratio <= 0:
            return AggressionLevel.MODERATE

        ratio = progress / time_ratio

        if ratio >= 1.2:
            return AggressionLevel.CONSERVATIVE
        elif ratio >= 0.8:
            return AggressionLevel.MODERATE
        elif ratio >= 0.5:
            return AggressionLevel.AGGRESSIVE
        else:
            return AggressionLevel.CONSERVATIVE

    def get_aggression_params(
        self, level: AggressionLevel | None = None
    ) -> dict[str, Any]:
        """공격성 수준에 해당하는 전략 파라미터를 반환한다.

        Args:
            level: 공격성 수준. None이면 현재 설정 사용.

        Returns:
            전략 파라미터 딕셔너리.
        """
        if level is None:
            level = self.config.aggression_level
        return dict(AGGRESSION_PARAMS.get(level, AGGRESSION_PARAMS[AggressionLevel.MODERATE]))

    async def update_aggression(self, today: date | None = None) -> AggressionLevel:
        """현재 상태에 기반하여 공격성 수준을 업데이트한다.

        auto_adjust가 False이면 현재 수준을 유지한다.

        Args:
            today: 기준 날짜.

        Returns:
            업데이트된 공격성 수준.
        """
        if not self.config.auto_adjust:
            logger.debug("auto_adjust 비활성, 현재 수준 유지: %s", self.config.aggression_level.value)
            return self.config.aggression_level

        month_pnl = await self.get_month_pnl(today)
        progress = self.get_month_progress(today)
        new_level = self.determine_aggression(month_pnl, progress["time_ratio"])

        if new_level != self.config.aggression_level:
            old_level = self.config.aggression_level
            self.config.aggression_level = new_level
            logger.info(
                "공격성 수준 변경: %s -> %s | month_pnl=$%.2f | time_ratio=%.2f",
                old_level.value,
                new_level.value,
                month_pnl,
                progress["time_ratio"],
            )

        return new_level

    async def get_context(self, today: date | None = None) -> dict[str, Any]:
        """Claude AI 프롬프트에 주입할 수익 목표 컨텍스트를 생성한다.

        Args:
            today: 기준 날짜.

        Returns:
            AI 판단용 컨텍스트 딕셔너리.
        """
        try:
            month_pnl = await self.get_month_pnl(today)
            progress = self.get_month_progress(today)

            await self.update_aggression(today)
            params = self.get_aggression_params()

            remaining_daily = self.calculate_remaining_daily_target(
                month_pnl, progress["remaining_trading_days"]
            )

            achievement_pct = 0.0
            if self.config.monthly_target_usd > 0:
                achievement_pct = round(
                    (month_pnl / self.config.monthly_target_usd) * 100, 2
                )

            context = {
                "monthly_target_usd": self.config.monthly_target_usd,
                "month_pnl_usd": round(month_pnl, 2),
                "achievement_pct": achievement_pct,
                "remaining_daily_target_usd": remaining_daily,
                "time_progress": progress,
                "aggression_level": self.config.aggression_level.value,
                "aggression_params": params,
                "auto_adjust": self.config.auto_adjust,
            }

            logger.debug(
                "수익 목표 컨텍스트 생성 | achievement=%.1f%% | aggression=%s",
                achievement_pct,
                self.config.aggression_level.value,
            )

            return context
        except Exception as e:
            logger.error("수익 목표 컨텍스트 생성 실패: %s", e)
            return {
                "monthly_target_usd": self.config.monthly_target_usd,
                "month_pnl_usd": 0.0,
                "achievement_pct": 0.0,
                "aggression_level": self.config.aggression_level.value,
                "error": str(e),
            }

    async def log_daily_pnl(
        self,
        trade_date: date,
        realized_pnl: float,
        unrealized_pnl: float = 0.0,
        trade_count: int = 0,
    ) -> None:
        """일일 PnL을 DB에 기록한다.

        Args:
            trade_date: 거래일.
            realized_pnl: 실현 손익 (USD).
            unrealized_pnl: 미실현 손익 (USD).
            trade_count: 당일 거래 횟수.
        """
        try:
            from src.db.models import DailyPnlLog

            async with get_session() as session:
                # 기존 레코드 업데이트 또는 새로 생성
                stmt = select(DailyPnlLog).where(DailyPnlLog.date == trade_date)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.realized_pnl = realized_pnl
                    existing.unrealized_pnl = unrealized_pnl
                    existing.trade_count = trade_count
                    logger.debug("일일 PnL 업데이트: %s | pnl=$%.2f", trade_date, realized_pnl)
                else:
                    new_log = DailyPnlLog(
                        date=trade_date,
                        realized_pnl=realized_pnl,
                        unrealized_pnl=unrealized_pnl,
                        trade_count=trade_count,
                    )
                    session.add(new_log)
                    logger.info("일일 PnL 기록: %s | pnl=$%.2f", trade_date, realized_pnl)
        except Exception as e:
            logger.error("일일 PnL 기록 실패: %s", e)

    async def get_monthly_target_from_db(self) -> dict[str, Any]:
        """DB에서 현재 월간 목표 설정을 조회한다.

        ProfitTarget 모델은 month(Date) 컬럼으로 해당 월 1일을 저장한다.

        Returns:
            목표 설정 딕셔너리.
        """
        try:
            from src.db.models import ProfitTarget

            today = date.today()
            month_first = today.replace(day=1)
            async with get_session() as session:
                stmt = select(ProfitTarget).where(
                    ProfitTarget.month == month_first
                )
                result = await session.execute(stmt)
                target = result.scalar_one_or_none()

                if target:
                    self.config.monthly_target_usd = float(target.target_usd)
                    return {
                        "year": today.year,
                        "month": today.month,
                        "monthly_target_usd": float(target.target_usd),
                        "daily_target_usd": self.config.daily_target_usd,
                    }
                else:
                    return {
                        "year": today.year,
                        "month": today.month,
                        "monthly_target_usd": self.config.monthly_target_usd,
                        "daily_target_usd": self.config.daily_target_usd,
                        "source": "default",
                    }
        except Exception as e:
            logger.error("월간 목표 DB 조회 실패: %s", e)
            return {
                "monthly_target_usd": self.config.monthly_target_usd,
                "daily_target_usd": self.config.daily_target_usd,
                "error": str(e),
            }

    async def update_monthly_target(
        self,
        monthly_target_usd: float,
        daily_target_usd: float | None = None,
    ) -> dict[str, Any]:
        """월간 수익 목표를 업데이트하고 DB에 저장한다.

        Args:
            monthly_target_usd: 새 월간 목표 (USD).
            daily_target_usd: 새 일간 목표 (USD). None이면 월간 목표에서 자동 계산.

        Returns:
            업데이트 결과 딕셔너리.
        """
        try:
            from src.db.models import ProfitTarget

            today = date.today()
            month_first = today.replace(day=1)
            total_days = calendar.monthrange(today.year, today.month)[1]
            trading_days = max(1, int(total_days * 5 / 7))

            if daily_target_usd is None:
                daily_target_usd = round(monthly_target_usd / trading_days, 2)

            self.config.monthly_target_usd = monthly_target_usd
            self.config.daily_target_usd = daily_target_usd

            async with get_session() as session:
                stmt = select(ProfitTarget).where(
                    ProfitTarget.month == month_first
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.target_usd = monthly_target_usd
                else:
                    new_target = ProfitTarget(
                        month=month_first,
                        target_usd=monthly_target_usd,
                    )
                    session.add(new_target)

            logger.info(
                "월간 목표 업데이트: $%.0f/month, $%.2f/day",
                monthly_target_usd,
                daily_target_usd,
            )

            return {
                "status": "updated",
                "monthly_target_usd": monthly_target_usd,
                "daily_target_usd": daily_target_usd,
            }
        except Exception as e:
            logger.error("월간 목표 업데이트 실패: %s", e)
            return {"status": "error", "error": str(e)}

    async def get_target_history(
        self, months: int = 6
    ) -> list[dict[str, Any]]:
        """과거 월간 목표 및 달성률 이력을 반환한다.

        Args:
            months: 조회할 개월 수.

        Returns:
            월별 목표/달성 이력 리스트.
        """
        try:
            from src.db.models import DailyPnlLog, ProfitTarget

            today = date.today()
            history: list[dict[str, Any]] = []

            async with get_session() as session:
                for i in range(months):
                    y = today.year
                    m = today.month - i
                    while m <= 0:
                        m += 12
                        y -= 1

                    month_start = date(y, m, 1)
                    month_end_day = calendar.monthrange(y, m)[1]
                    month_end = date(y, m, month_end_day)

                    # 목표 조회 (ProfitTarget.month는 해당 월 1일 Date)
                    target_stmt = select(ProfitTarget).where(
                        ProfitTarget.month == month_start
                    )
                    target_result = await session.execute(target_stmt)
                    target = target_result.scalar_one_or_none()

                    # 실적 조회
                    pnl_stmt = select(
                        func.coalesce(func.sum(DailyPnlLog.realized_pnl), 0.0)
                    ).where(
                        and_(
                            DailyPnlLog.date >= month_start,
                            DailyPnlLog.date <= month_end,
                        )
                    )
                    pnl_result = await session.execute(pnl_stmt)
                    actual_pnl = float(pnl_result.scalar_one())

                    target_val = float(target.target_usd) if target else self.config.monthly_target_usd
                    achievement_pct = (actual_pnl / target_val * 100) if target_val > 0 else 0.0

                    history.append({
                        "year": y,
                        "month": m,
                        "target_usd": target_val,
                        "actual_pnl_usd": round(actual_pnl, 2),
                        "achievement_pct": round(achievement_pct, 2),
                    })

            return history
        except Exception as e:
            logger.error("목표 이력 조회 실패: %s", e)
            return []

    async def get_projection(self, today: date | None = None) -> dict[str, Any]:
        """현재 추세 기반 월말 예상 수익을 계산한다.

        Args:
            today: 기준 날짜.

        Returns:
            예측 정보 딕셔너리.
        """
        try:
            if today is None:
                today = date.today()

            month_pnl = await self.get_month_pnl(today)
            progress = self.get_month_progress(today)

            elapsed = progress["elapsed_days"]
            total = progress["total_days"]

            if elapsed > 0:
                daily_avg = month_pnl / elapsed
                projected_total = daily_avg * total
            else:
                daily_avg = 0.0
                projected_total = 0.0

            on_track = projected_total >= self.config.monthly_target_usd
            deficit = max(0.0, self.config.monthly_target_usd - projected_total)

            return {
                "current_pnl_usd": round(month_pnl, 2),
                "daily_avg_usd": round(daily_avg, 2),
                "projected_month_end_usd": round(projected_total, 2),
                "monthly_target_usd": self.config.monthly_target_usd,
                "on_track": on_track,
                "projected_deficit_usd": round(deficit, 2),
                "remaining_daily_target_usd": self.calculate_remaining_daily_target(
                    month_pnl, progress["remaining_trading_days"]
                ),
                "time_progress": progress,
            }
        except Exception as e:
            logger.error("수익 예측 실패: %s", e)
            return {"error": str(e)}

    def get_status(self) -> dict[str, Any]:
        """현재 ProfitTargetManager 상태를 반환한다.

        Returns:
            상태 딕셔너리.
        """
        return {
            "monthly_target_usd": self.config.monthly_target_usd,
            "daily_target_usd": self.config.daily_target_usd,
            "aggression_level": self.config.aggression_level.value,
            "auto_adjust": self.config.auto_adjust,
            "month_pnl_cache": round(self._month_pnl_cache, 2),
        }
