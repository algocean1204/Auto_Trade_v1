"""
리스크 예산 관리 모듈 (Addendum 26)

월간 리스크 예산(-5%)을 4단계로 분할하여 소비를 추적한다.

소비 단계:
    Tier 1: 0~30% 소비 -> 정상 운영 (x1.0)
    Tier 2: 30~60% 소비 -> 포지션 크기 축소 (x0.70)
    Tier 3: 60~80% 소비 -> 신규 진입 최소화 (x0.40)
    Tier 4: 80~100% 소비 -> 신규 진입 차단 (x0.0)
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select

from src.db.connection import get_session
from src.risk.risk_gate import GateResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 월간 리스크 예산 기본값 (%)
DEFAULT_MONTHLY_BUDGET_PCT: float = -5.0

# 소비 단계별 설정
BUDGET_TIERS: list[dict[str, Any]] = [
    {"tier": 1, "max_consumption_pct": 30.0, "position_scale": 1.0, "action": "allow"},
    {"tier": 2, "max_consumption_pct": 60.0, "position_scale": 0.70, "action": "allow"},
    {"tier": 3, "max_consumption_pct": 80.0, "position_scale": 0.40, "action": "reduce"},
    {"tier": 4, "max_consumption_pct": 100.0, "position_scale": 0.0, "action": "block"},
]


class RiskBudget:
    """월간 리스크 예산을 관리하고 소비 단계를 추적한다.

    월간 최대 허용 손실(-5%)을 4단계로 나누어 관리하며,
    현재 소비 단계에 따라 포지션 크기를 조절한다.

    Attributes:
        monthly_budget_pct: 월간 리스크 예산 (음수, %).
        tiers: 소비 단계 설정.
        _current_consumption_pct: 현재 예산 소비율 캐시.
    """

    def __init__(
        self,
        monthly_budget_pct: float = DEFAULT_MONTHLY_BUDGET_PCT,
        tiers: list[dict[str, Any]] | None = None,
    ) -> None:
        """RiskBudget을 초기화한다.

        Args:
            monthly_budget_pct: 월간 리스크 예산 (음수, %).
            tiers: 소비 단계 설정. None이면 기본값 사용.
        """
        self.monthly_budget_pct = monthly_budget_pct
        self.tiers = tiers or list(BUDGET_TIERS)
        self._current_consumption_pct: float = 0.0
        self._current_tier: int = 1

        logger.info(
            "RiskBudget 초기화 | monthly_budget=%.1f%% | tiers=%d",
            monthly_budget_pct,
            len(self.tiers),
        )

    async def get_consumption(self, today: date | None = None) -> dict[str, Any]:
        """현재 월간 리스크 예산 소비 현황을 계산한다.

        Args:
            today: 기준 날짜.

        Returns:
            소비 현황 딕셔너리.
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
                        DailyPnlLog.realized_pnl < 0,
                    )
                )
                result = await session.execute(stmt)
                total_losses = float(result.scalar_one())

            # 초기 자본 조회 (RiskConfig에서)
            initial_capital = await self._get_initial_capital()

            if initial_capital <= 0:
                return {
                    "consumption_pct": 0.0,
                    "current_tier": 1,
                    "position_scale": 1.0,
                    "error": "초기 자본 정보 없음",
                }

            budget_amount = initial_capital * (abs(self.monthly_budget_pct) / 100.0)
            actual_loss = abs(total_losses)

            consumption_pct = (actual_loss / budget_amount * 100.0) if budget_amount > 0 else 0.0
            self._current_consumption_pct = consumption_pct

            # 현재 단계 결정
            current_tier = 1
            position_scale = 1.0
            for tier in self.tiers:
                if consumption_pct <= tier["max_consumption_pct"]:
                    current_tier = tier["tier"]
                    position_scale = tier["position_scale"]
                    break
            else:
                current_tier = self.tiers[-1]["tier"]
                position_scale = self.tiers[-1]["position_scale"]

            self._current_tier = current_tier

            return {
                "month": today.month,
                "year": today.year,
                "budget_pct": self.monthly_budget_pct,
                "budget_amount_usd": round(budget_amount, 2),
                "total_losses_usd": round(total_losses, 2),
                "consumption_pct": round(consumption_pct, 2),
                "remaining_budget_usd": round(budget_amount - actual_loss, 2),
                "current_tier": current_tier,
                "position_scale": position_scale,
            }
        except Exception as e:
            logger.error("리스크 예산 소비 계산 실패: %s", e)
            return {
                "consumption_pct": 0.0,
                "current_tier": 1,
                "position_scale": 1.0,
                "error": str(e),
            }

    async def check_order(self, order: dict[str, Any]) -> GateResult:
        """주문이 리스크 예산 내인지 검증한다.

        Args:
            order: 주문 정보.

        Returns:
            검증 결과.
        """
        try:
            consumption = await self.get_consumption()
            consumption_pct = consumption["consumption_pct"]
            current_tier = consumption["current_tier"]
            position_scale = consumption["position_scale"]

            if current_tier >= 4 or consumption_pct >= 100.0:
                return GateResult(
                    passed=False,
                    action="block",
                    message=f"리스크 예산 소진 (Tier {current_tier}, {consumption_pct:.1f}% 소비)",
                    gate_name="risk_budget",
                    details=consumption,
                )

            if current_tier >= 3:
                return GateResult(
                    passed=True,
                    action="reduce",
                    message=(
                        f"리스크 예산 경고 (Tier {current_tier}, "
                        f"{consumption_pct:.1f}% 소비, scale={position_scale})"
                    ),
                    gate_name="risk_budget",
                    details=consumption,
                )

            return GateResult(
                passed=True,
                action="allow",
                message=f"리스크 예산 정상 (Tier {current_tier}, {consumption_pct:.1f}% 소비)",
                gate_name="risk_budget",
                details=consumption,
            )
        except Exception as e:
            logger.error("리스크 예산 체크 실패: %s", e)
            return GateResult(
                passed=True,
                action="allow",
                message=f"예산 체크 오류 (안전 통과): {e}",
                gate_name="risk_budget",
            )

    async def update_budget(self) -> dict[str, Any]:
        """리스크 예산을 업데이트한다 (EOD 호출).

        RiskConfig에 현재 소비율을 기록한다 (param_key/param_value 구조).

        Returns:
            업데이트 결과.
        """
        try:
            consumption = await self.get_consumption()

            from src.db.models import RiskConfig

            async with get_session() as session:
                stmt = select(RiskConfig).where(
                    RiskConfig.param_key == "risk_budget_consumption_pct"
                )
                result = await session.execute(stmt)
                config = result.scalar_one_or_none()

                if config:
                    config.param_value = consumption["consumption_pct"]
                else:
                    new_config = RiskConfig(
                        param_key="risk_budget_consumption_pct",
                        param_value=consumption["consumption_pct"],
                        description="월간 리스크 예산 소비율 (%)",
                    )
                    session.add(new_config)

            logger.info(
                "리스크 예산 업데이트: Tier %d, %.1f%% 소비",
                consumption["current_tier"],
                consumption["consumption_pct"],
            )
            return consumption
        except Exception as e:
            logger.error("리스크 예산 업데이트 실패: %s", e)
            return {"error": str(e)}

    async def _get_initial_capital(self) -> float:
        """초기 자본금을 조회한다.

        RiskConfig에서 param_key='initial_capital'의 param_value를 읽는다.

        Returns:
            초기 자본금 (USD).
        """
        try:
            from src.db.models import RiskConfig

            async with get_session() as session:
                stmt = select(RiskConfig).where(
                    RiskConfig.param_key == "initial_capital"
                )
                result = await session.execute(stmt)
                config = result.scalar_one_or_none()

                if config:
                    return float(config.param_value)
                return 10000.0
        except Exception as e:
            logger.warning("초기 자본금 조회 실패, 기본값 사용: %s", e)
            return 10000.0

    def get_status(self) -> dict[str, Any]:
        """현재 상태를 반환한다."""
        return {
            "monthly_budget_pct": self.monthly_budget_pct,
            "current_consumption_pct": round(self._current_consumption_pct, 2),
            "current_tier": self._current_tier,
            "tiers": self.tiers,
        }
