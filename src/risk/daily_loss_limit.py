"""
일일 손실 한도 게이트 (Addendum 26 - Gate 1)

3단계 일일 손실 한도를 관리한다:
    Level 1: -1.0% -> 포지션 크기 50% 축소
    Level 2: -1.5% -> 신규 진입 차단
    Level 3: -2.0% -> 모든 매매 중단 (halt)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select

from src.db.connection import get_session
from src.risk.risk_gate import GateResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# 3단계 일일 손실 한도
LOSS_LEVELS: list[dict[str, Any]] = [
    {"level": 1, "threshold_pct": -1.0, "action": "reduce", "description": "포지션 크기 50% 축소"},
    {"level": 2, "threshold_pct": -1.5, "action": "block", "description": "신규 진입 차단"},
    {"level": 3, "threshold_pct": -2.0, "action": "halt", "description": "모든 매매 중단"},
]


class DailyLossLimiter:
    """일일 손실 한도를 3단계로 관리한다.

    장중 누적 손실률이 각 단계 임계값에 도달하면
    해당 단계의 조치를 권고한다.

    Attributes:
        levels: 손실 한도 단계 설정.
        current_daily_pnl_pct: 현재 일일 누적 손익률.
        current_level: 현재 발동된 한도 단계.
    """

    def __init__(self, levels: list[dict[str, Any]] | None = None) -> None:
        """DailyLossLimiter를 초기화한다.

        Args:
            levels: 손실 한도 단계 설정. None이면 기본값 사용.
        """
        self.levels = levels or list(LOSS_LEVELS)
        self.current_daily_pnl_pct: float = 0.0
        self.current_level: int = 0

        logger.info(
            "DailyLossLimiter 초기화 | levels=%s",
            [(lvl["threshold_pct"], lvl["action"]) for lvl in self.levels],
        )

    async def check(self, portfolio: dict[str, Any]) -> GateResult:
        """일일 손실 한도를 점검한다.

        Args:
            portfolio: 현재 포트폴리오 상태.
                필수 키: "total_value" (float), "today_pnl" (float).

        Returns:
            게이트 실행 결과.
        """
        try:
            total_value = portfolio.get("total_value", 0.0)
            today_pnl = portfolio.get("today_pnl", 0.0)

            if total_value <= 0:
                return GateResult(
                    passed=True,
                    action="allow",
                    message="포트폴리오 가치 0, 체크 생략",
                    gate_name="daily_loss_limiter",
                )

            daily_pnl_pct = (today_pnl / total_value) * 100.0
            self.current_daily_pnl_pct = daily_pnl_pct

            # 가장 심각한 위반 수준 찾기
            triggered_level = None
            for level in sorted(self.levels, key=lambda x: x["threshold_pct"]):
                if daily_pnl_pct <= level["threshold_pct"]:
                    triggered_level = level
                    break

            if triggered_level is None:
                self.current_level = 0
                return GateResult(
                    passed=True,
                    action="allow",
                    message=f"일일 손실 정상 범위 ({daily_pnl_pct:.2f}%)",
                    gate_name="daily_loss_limiter",
                    details={"daily_pnl_pct": round(daily_pnl_pct, 4)},
                )

            self.current_level = triggered_level["level"]
            passed = triggered_level["action"] == "reduce"

            logger.warning(
                "일일 손실 한도 Level %d 발동 | pnl=%.2f%% | threshold=%.1f%% | action=%s",
                triggered_level["level"],
                daily_pnl_pct,
                triggered_level["threshold_pct"],
                triggered_level["action"],
            )

            # 리스크 이벤트 기록
            await self._log_risk_event(triggered_level, daily_pnl_pct)

            return GateResult(
                passed=passed,
                action=triggered_level["action"],
                message=(
                    f"일일 손실 Level {triggered_level['level']}: "
                    f"{daily_pnl_pct:.2f}% <= {triggered_level['threshold_pct']}% "
                    f"-> {triggered_level['description']}"
                ),
                gate_name="daily_loss_limiter",
                details={
                    "daily_pnl_pct": round(daily_pnl_pct, 4),
                    "triggered_level": triggered_level["level"],
                    "threshold_pct": triggered_level["threshold_pct"],
                },
            )
        except Exception as e:
            logger.error("일일 손실 한도 체크 실패: %s", e)
            return GateResult(
                passed=False,
                action="block",
                message=f"체크 오류: {e}",
                gate_name="daily_loss_limiter",
            )

    async def _log_risk_event(
        self, level: dict[str, Any], pnl_pct: float
    ) -> None:
        """리스크 이벤트를 DB에 기록한다."""
        try:
            from src.db.models import RiskEvent

            async with get_session() as session:
                event = RiskEvent(
                    event_type="daily_loss_limit",
                    gate_name="daily_loss_limiter",
                    severity=level["action"],
                    details={
                        "level": level["level"],
                        "threshold_pct": level["threshold_pct"],
                        "actual_pnl_pct": round(pnl_pct, 4),
                        "action": level["action"],
                    },
                )
                session.add(event)
        except Exception as e:
            logger.warning("리스크 이벤트 기록 실패: %s", e)

    def reset_daily(self) -> None:
        """일일 카운터를 리셋한다."""
        self.current_daily_pnl_pct = 0.0
        self.current_level = 0
        logger.debug("DailyLossLimiter 일일 리셋")

    def get_status(self) -> dict[str, Any]:
        """현재 상태를 반환한다."""
        return {
            "current_daily_pnl_pct": round(self.current_daily_pnl_pct, 4),
            "current_level": self.current_level,
            "levels": self.levels,
        }
