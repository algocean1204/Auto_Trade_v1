"""
연패 감지 게이트 (Addendum 26 - Gate 3)

연속 손실 거래와 일일 연속 손실을 감지하여 매매를 제한한다.

규칙:
    - 3연패: 다음 거래 포지션 크기 50% 축소
    - 5연패: 신규 진입 차단 (당일)
    - 7연패: 모든 매매 24시간 중단
    - 3일 연속 일일 손실: 신규 진입 차단
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select

from src.db.connection import get_session
from src.risk.risk_gate import GateResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 연패 규칙
STREAK_RULES: dict[int, dict[str, str]] = {
    3: {"action": "reduce", "description": "3연패: 포지션 크기 50% 축소"},
    5: {"action": "block", "description": "5연패: 당일 신규 진입 차단"},
    7: {"action": "halt", "description": "7연패: 24시간 매매 중단"},
}

# 일일 연속 손실 규칙
DAILY_LOSS_STREAK_THRESHOLD: int = 3


class LosingStreakDetector:
    """연속 손실을 감지하고 매매를 제한한다.

    최근 거래 이력에서 연속 손실 횟수를 계산하고,
    3/5/7 연패 규칙과 일일 연속 손실 규칙을 적용한다.

    Attributes:
        streak_rules: 연패 규칙 설정.
        daily_loss_streak_threshold: 일일 연속 손실 임계값.
        _current_streak: 현재 연패 횟수 캐시.
    """

    def __init__(
        self,
        streak_rules: dict[int, dict[str, str]] | None = None,
        daily_loss_streak_threshold: int = DAILY_LOSS_STREAK_THRESHOLD,
    ) -> None:
        """LosingStreakDetector를 초기화한다.

        Args:
            streak_rules: 연패 규칙. None이면 기본값 사용.
            daily_loss_streak_threshold: 일일 연속 손실 임계값.
        """
        self.streak_rules = streak_rules or dict(STREAK_RULES)
        self.daily_loss_streak_threshold = daily_loss_streak_threshold
        self._current_streak: int = 0
        self._daily_loss_days: int = 0

        logger.info(
            "LosingStreakDetector 초기화 | rules=%s | daily_threshold=%d",
            list(self.streak_rules.keys()),
            daily_loss_streak_threshold,
        )

    async def check(self) -> GateResult:
        """연패 상태를 점검한다.

        Returns:
            게이트 실행 결과.
        """
        try:
            # 거래 연패 체크
            streak = await self._get_current_streak()
            self._current_streak = streak

            # 일일 연속 손실 체크
            daily_loss_days = await self._get_daily_loss_streak()
            self._daily_loss_days = daily_loss_days

            details = {
                "current_streak": streak,
                "daily_loss_days": daily_loss_days,
            }

            # 일일 연속 손실 3일 체크
            if daily_loss_days >= self.daily_loss_streak_threshold:
                logger.warning(
                    "일일 연속 손실 %d일 감지 (임계값=%d)",
                    daily_loss_days,
                    self.daily_loss_streak_threshold,
                )
                await self._log_risk_event("daily_loss_streak", daily_loss_days)
                return GateResult(
                    passed=False,
                    action="block",
                    message=f"{daily_loss_days}일 연속 일일 손실: 신규 진입 차단",
                    gate_name="losing_streak_detector",
                    details=details,
                )

            # 거래 연패 규칙 체크 (역순으로 가장 심각한 것부터)
            for threshold in sorted(self.streak_rules.keys(), reverse=True):
                if streak >= threshold:
                    rule = self.streak_rules[threshold]
                    passed = rule["action"] == "reduce"

                    logger.warning(
                        "연패 감지: %d연패 >= %d | action=%s",
                        streak,
                        threshold,
                        rule["action"],
                    )
                    await self._log_risk_event("losing_streak", streak)

                    return GateResult(
                        passed=passed,
                        action=rule["action"],
                        message=f"{streak}연패: {rule['description']}",
                        gate_name="losing_streak_detector",
                        details=details,
                    )

            return GateResult(
                passed=True,
                action="allow",
                message=f"연패 없음 (streak={streak}, daily_loss={daily_loss_days})",
                gate_name="losing_streak_detector",
                details=details,
            )
        except Exception as e:
            logger.error("연패 감지 실패: %s", e)
            return GateResult(
                passed=True,
                action="allow",
                message=f"연패 감지 오류 (안전 통과): {e}",
                gate_name="losing_streak_detector",
            )

    async def _get_current_streak(self) -> int:
        """최근 거래에서 현재 연패 횟수를 계산한다.

        Returns:
            연속 손실 거래 횟수.
        """
        try:
            from src.db.models import Trade

            async with get_session() as session:
                stmt = (
                    select(Trade.pnl_pct)
                    .where(Trade.exit_price.isnot(None))
                    .order_by(Trade.exit_at.desc())
                    .limit(20)
                )
                result = await session.execute(stmt)
                pnl_values = [row[0] for row in result.all()]

                streak = 0
                for pnl in pnl_values:
                    if pnl is not None and pnl < 0:
                        streak += 1
                    else:
                        break

                return streak
        except Exception as e:
            logger.warning("연패 횟수 조회 실패: %s", e)
            return 0

    async def _get_daily_loss_streak(self) -> int:
        """최근 일일 연속 손실 일수를 계산한다.

        Returns:
            연속 일일 손실 일수.
        """
        try:
            from src.db.models import Trade

            async with get_session() as session:
                # 최근 10일간 일별 PnL 합계
                ten_days_ago = datetime.now(tz=timezone.utc) - timedelta(days=10)
                stmt = (
                    select(
                        func.date(Trade.exit_at).label("trade_date"),
                        func.coalesce(func.sum(Trade.pnl_amount), 0.0).label("daily_pnl"),
                    )
                    .where(
                        and_(
                            Trade.exit_at >= ten_days_ago,
                            Trade.exit_price.isnot(None),
                        )
                    )
                    .group_by(func.date(Trade.exit_at))
                    .order_by(func.date(Trade.exit_at).desc())
                )
                result = await session.execute(stmt)
                daily_pnls = result.all()

                streak = 0
                for row in daily_pnls:
                    if float(row.daily_pnl) < 0:
                        streak += 1
                    else:
                        break

                return streak
        except Exception as e:
            logger.warning("일일 연속 손실 조회 실패: %s", e)
            return 0

    async def _log_risk_event(self, event_type: str, value: int) -> None:
        """리스크 이벤트를 DB에 기록한다."""
        try:
            from src.db.models import RiskEvent

            async with get_session() as session:
                event = RiskEvent(
                    event_type=event_type,
                    gate_name="losing_streak_detector",
                    severity="block" if value >= 5 else "reduce",
                    details={
                        "streak_count": value,
                        "rules": self.streak_rules,
                    },
                )
                session.add(event)
        except Exception as e:
            logger.warning("리스크 이벤트 기록 실패: %s", e)

    def get_status(self) -> dict[str, Any]:
        """현재 상태를 반환한다."""
        return {
            "current_streak": self._current_streak,
            "daily_loss_days": self._daily_loss_days,
            "streak_rules": {k: v["description"] for k, v in self.streak_rules.items()},
            "daily_loss_streak_threshold": self.daily_loss_streak_threshold,
        }
