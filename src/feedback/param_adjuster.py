"""
파라미터 자동 조정 모듈.

안전 규칙:
- 한 번에 1개 파라미터만 변경
- 변경 폭 10% 이내
- 사용자 승인 후에만 적용

Thinking.md Part 4.4 기반.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_session
from src.db.models import PendingAdjustment, StrategyParamHistory
from src.strategy.params import StrategyParams
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ParamAdjuster:
    """파라미터 자동 조정 관리자.

    주간 분석에서 제안된 파라미터 조정을 pending_adjustments 테이블에 저장하고,
    사용자 승인 후에만 실제 파라미터에 반영한다.
    모든 변경 이력은 strategy_param_history 테이블에 기록된다.
    """

    ADJUSTABLE_PARAMS: list[str] = [
        "min_confidence",
        "take_profit_pct",
        "stop_loss_pct",
        "trailing_stop_pct",
        "max_position_pct",
    ]

    def __init__(self, strategy_params: StrategyParams) -> None:
        """ParamAdjuster 초기화.

        Args:
            strategy_params: 전략 파라미터 관리 인스턴스.
        """
        self.params = strategy_params

    async def propose_adjustment(
        self,
        param_name: str,
        new_value: float,
        reason: str,
    ) -> dict[str, Any]:
        """파라미터 조정 제안을 생성한다.

        1. 조정 가능한 파라미터인지 확인
        2. 변경 폭 10% 이내인지 검증
        3. pending_adjustments 테이블에 저장

        Args:
            param_name: 조정할 파라미터 이름.
            new_value: 제안 값.
            reason: 조정 근거.

        Returns:
            조정 제안 딕셔너리::

                {
                    "id", "param_name", "current", "proposed",
                    "change_pct", "reason", "status",
                }
        """
        # 검증
        is_valid, error_msg = await self._validate_adjustment(param_name, new_value)
        if not is_valid:
            logger.warning(
                "파라미터 조정 제안 거부 | param=%s | value=%.4f | reason=%s",
                param_name,
                new_value,
                error_msg,
            )
            return {
                "id": None,
                "param_name": param_name,
                "current": None,
                "proposed": new_value,
                "change_pct": None,
                "reason": reason,
                "status": "rejected",
                "error": error_msg,
            }

        current_value = float(self.params.get_param(param_name))

        # 변경률 계산
        if current_value != 0:
            change_pct = round((new_value - current_value) / abs(current_value) * 100, 2)
        else:
            change_pct = 0.0

        # DB에 저장
        adjustment_id = str(uuid4())

        async with get_session() as session:
            record = PendingAdjustment(
                id=adjustment_id,
                param_name=param_name,
                current_value=current_value,
                proposed_value=new_value,
                change_pct=change_pct,
                reason=reason,
                status="pending",
            )
            session.add(record)

        logger.info(
            "파라미터 조정 제안 생성 | id=%s | param=%s | %.4f -> %.4f (%.2f%%)",
            adjustment_id,
            param_name,
            current_value,
            new_value,
            change_pct,
        )

        return {
            "id": adjustment_id,
            "param_name": param_name,
            "current": current_value,
            "proposed": new_value,
            "change_pct": change_pct,
            "reason": reason,
            "status": "pending",
        }

    async def approve_adjustment(
        self, adjustment_id: str, approved_by: str = "user"
    ) -> dict[str, Any]:
        """조정 제안을 승인하고 파라미터에 적용한다.

        1. pending_adjustments 상태를 approved로 변경
        2. StrategyParams 업데이트
        3. strategy_param_history에 변경 이력 기록

        Args:
            adjustment_id: 조정 제안 UUID.
            approved_by: 승인자 (기본값: "user").

        Returns:
            승인 결과 딕셔너리::

                {"id", "param_name", "old_value", "new_value", "status"}
        """
        async with get_session() as session:
            stmt = select(PendingAdjustment).where(
                PendingAdjustment.id == adjustment_id,
                PendingAdjustment.status == "pending",
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                logger.warning("승인 대상 조정 없음 | id=%s", adjustment_id)
                return {
                    "id": adjustment_id,
                    "param_name": None,
                    "old_value": None,
                    "new_value": None,
                    "status": "not_found",
                }

            param_name = record.param_name
            old_value = record.current_value
            new_value = record.proposed_value
            reason = record.reason

            # 1. pending_adjustments 상태 변경
            record.status = "approved"
            record.resolved_at = datetime.now(timezone.utc)

            # 2. strategy_param_history 기록
            history = StrategyParamHistory(
                param_name=param_name,
                old_value=old_value,
                new_value=new_value,
                change_reason=reason,
                approved_by=approved_by,
            )
            session.add(history)

        # 3. StrategyParams 실제 업데이트 (파일 영속화)
        self.params.set_param(param_name, new_value)

        logger.info(
            "파라미터 조정 승인 완료 | id=%s | param=%s | %.4f -> %.4f",
            adjustment_id,
            param_name,
            old_value,
            new_value,
        )

        return {
            "id": adjustment_id,
            "param_name": param_name,
            "old_value": old_value,
            "new_value": new_value,
            "status": "approved",
        }

    async def reject_adjustment(
        self, adjustment_id: str, reason: str | None = None
    ) -> dict[str, Any]:
        """조정 제안을 거부한다.

        Args:
            adjustment_id: 조정 제안 UUID.
            reason: 거부 사유 (선택).

        Returns:
            거부 결과 딕셔너리::

                {"id", "param_name", "status", "reject_reason"}
        """
        async with get_session() as session:
            stmt = select(PendingAdjustment).where(
                PendingAdjustment.id == adjustment_id,
                PendingAdjustment.status == "pending",
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                logger.warning("거부 대상 조정 없음 | id=%s", adjustment_id)
                return {
                    "id": adjustment_id,
                    "param_name": None,
                    "status": "not_found",
                    "reject_reason": None,
                }

            param_name = record.param_name
            record.status = "rejected"
            record.resolved_at = datetime.now(timezone.utc)
            if reason:
                record.reason = f"{record.reason} [거부 사유: {reason}]"

        logger.info(
            "파라미터 조정 거부 | id=%s | param=%s | reason=%s",
            adjustment_id,
            param_name,
            reason,
        )

        return {
            "id": adjustment_id,
            "param_name": param_name,
            "status": "rejected",
            "reject_reason": reason,
        }

    async def get_pending_adjustments(self) -> list[dict[str, Any]]:
        """대기 중인 조정 제안 목록을 반환한다.

        Returns:
            대기 중인 조정 딕셔너리 목록.
        """
        async with get_session() as session:
            stmt = (
                select(PendingAdjustment)
                .where(PendingAdjustment.status == "pending")
                .order_by(PendingAdjustment.created_at.desc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        adjustments: list[dict[str, Any]] = []
        for row in rows:
            adjustments.append({
                "id": str(row.id),
                "param_name": row.param_name,
                "current": row.current_value,
                "proposed": row.proposed_value,
                "change_pct": row.change_pct,
                "reason": row.reason,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })

        logger.info("대기 중인 조정 제안 조회 | count=%d", len(adjustments))
        return adjustments

    async def get_adjustment_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """파라미터 조정 이력을 조회한다.

        strategy_param_history 테이블에서 최근 조정 이력을 가져온다.

        Args:
            limit: 조회할 최대 개수 (기본값: 20).

        Returns:
            조정 이력 딕셔너리 목록.
        """
        async with get_session() as session:
            stmt = (
                select(StrategyParamHistory)
                .order_by(StrategyParamHistory.applied_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        history: list[dict[str, Any]] = []
        for row in rows:
            history.append({
                "id": row.id,
                "param_name": row.param_name,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "change_reason": row.change_reason,
                "approved_by": row.approved_by,
                "applied_at": row.applied_at.isoformat() if row.applied_at else None,
            })

        logger.info("파라미터 조정 이력 조회 | count=%d", len(history))
        return history

    async def _validate_adjustment(
        self, param_name: str, new_value: float
    ) -> tuple[bool, str]:
        """파라미터 조정을 검증한다.

        검증 항목:
        1. 조정 가능한 파라미터인지 확인
        2. 변경 폭 10% 이내인지 확인

        Args:
            param_name: 파라미터 이름.
            new_value: 제안 값.

        Returns:
            (유효 여부, 오류 메시지) 튜플. 유효하면 (True, "").
        """
        # 1. 조정 가능 파라미터 확인
        if param_name not in self.ADJUSTABLE_PARAMS:
            return False, f"조정 불가능한 파라미터: {param_name}. 허용: {self.ADJUSTABLE_PARAMS}"

        # 2. 현재 값 조회
        try:
            current_value = float(self.params.get_param(param_name))
        except KeyError:
            return False, f"존재하지 않는 파라미터: {param_name}"

        # 3. 10% 이내 변경 확인
        is_valid = self.params.validate_adjustment(param_name, current_value, new_value)
        if not is_valid:
            if current_value != 0:
                actual_pct = abs((new_value - current_value) / abs(current_value) * 100)
            else:
                actual_pct = abs(new_value) * 100
            return False, (
                f"변경 폭 초과: {param_name} {current_value} -> {new_value} "
                f"(변경률 {actual_pct:.1f}%, 한도 10%)"
            )

        return True, ""
