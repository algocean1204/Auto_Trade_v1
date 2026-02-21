"""
Flutter 대시보드용 거래 피드백 및 이력 API 엔드포인트.

일간/주간 피드백 리포트 조회, 대기 중 파라미터 조정 승인/거부
엔드포인트를 제공한다.

엔드포인트 목록:
  GET  /feedback/daily/{date_str}              - 일간 피드백
  GET  /feedback/weekly/{week_str}             - 주간 분석
  GET  /feedback/pending-adjustments           - 대기 중 조정 목록
  POST /feedback/approve-adjustment/{id}       - 조정 승인
  POST /feedback/reject-adjustment/{id}        - 조정 거부
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select

from src.db.connection import get_session
from src.db.models import FeedbackReport, PendingAdjustment
from src.monitoring.alert import AlertManager
from src.monitoring.auth import verify_api_key
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 모듈 레벨 의존성 레지스트리
# api_server.py 가 startup 시 set_trade_deps() 를 호출하여 주입한다.
# ---------------------------------------------------------------------------

_deps: dict[str, Any] = {}

# 알림 매니저 싱글턴
_alert_manager = AlertManager()


def set_trade_deps(
    strategy_params: Any = None,
) -> None:
    """런타임 의존성을 주입한다.

    api_server.py 의 set_dependencies() 호출 시 함께 호출되어야 한다.

    Args:
        strategy_params: 전략 파라미터 인스턴스.
    """
    _deps["strategy_params"] = strategy_params


def _try_get(name: str) -> Any | None:
    """의존성을 조회한다. 없으면 None을 반환한다 (503 대신)."""
    return _deps.get(name)


# ---------------------------------------------------------------------------
# APIRouter
# ---------------------------------------------------------------------------

trade_router = APIRouter(tags=["trade"])


# ===================================================================
# Feedback endpoints
# ===================================================================


@trade_router.get("/feedback/daily/{date_str}")
async def get_daily_feedback(date_str: str) -> dict:
    """지정 날짜의 일간 피드백 리포트를 반환한다.

    DB에 저장된 리포트가 없으면 DailyReportGenerator로 실시간 생성한다.
    """
    try:
        async with get_session() as session:
            report_date = _date.fromisoformat(date_str)
            stmt = select(FeedbackReport).where(
                and_(
                    FeedbackReport.report_type == "daily",
                    FeedbackReport.report_date == report_date,
                )
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                stmt2 = select(FeedbackReport).where(
                    and_(
                        FeedbackReport.report_type == "daily_performance",
                        FeedbackReport.report_date == report_date,
                    )
                )
                result2 = await session.execute(stmt2)
                row = result2.scalar_one_or_none()

        if row is not None:
            return {
                "report_type": row.report_type,
                "report_date": str(row.report_date),
                "content": row.content,
                "created_at": row.created_at.isoformat(),
            }

        # DB에 저장된 리포트가 없으면 실시간으로 생성한다.
        # 단, 오늘 이전 날짜에 거래 데이터가 없으면 404를 반환한다.
        logger.info("저장된 일간 리포트 없음. 실시간 생성: %s", date_str)
        try:
            from src.monitoring.daily_report import DailyReportGenerator
            generator = DailyReportGenerator()
            content = await generator.generate(date_str)

            # 과거 날짜에 거래 데이터가 없으면 404를 반환한다.
            report_date_obj = _date.fromisoformat(date_str)
            summary = content.get("summary", {}) if isinstance(content, dict) else {}
            total_trades = summary.get("total_trades", 0)
            if total_trades == 0 and report_date_obj < _date.today():
                raise HTTPException(
                    status_code=404,
                    detail=f"No daily feedback found for {date_str}",
                )

            return {
                "report_type": "daily_performance",
                "report_date": date_str,
                "content": content,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        except HTTPException:
            raise
        except Exception as gen_exc:
            logger.warning("일간 리포트 실시간 생성 실패: %s", gen_exc)
            raise HTTPException(
                status_code=404,
                detail=f"No daily feedback found for {date_str}",
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get daily feedback for %s: %s", date_str, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@trade_router.get("/feedback/weekly/{week_str}")
async def get_weekly_analysis(week_str: str) -> dict:
    """주간 분석 리포트를 반환한다.

    week_str 형식:
      - YYYY-WNN  (예: 2026-W07) — ISO 주차 형식
      - YYYY-MM-DD (예: 2026-02-16) — 주의 월요일 날짜 형식 (Flutter 클라이언트 호환)
    """
    try:
        # 두 가지 입력 형식을 모두 처리한다.
        # YYYY-MM-DD 형식이면 해당 날짜가 속한 주의 월요일~일요일 범위를 계산한다.
        if "-W" in week_str:
            year, week_part = week_str.split("-W")
            jan4 = _date(int(year), 1, 4)
            week_start = jan4 + timedelta(
                weeks=int(week_part) - 1,
                days=-jan4.weekday(),
            )
        else:
            # YYYY-MM-DD 형식: 해당 날짜가 속한 주의 월요일로 정규화한다.
            anchor = _date.fromisoformat(week_str)
            week_start = anchor - timedelta(days=anchor.weekday())

        week_end = week_start + timedelta(days=7)

        async with get_session() as session:
            stmt = (
                select(FeedbackReport)
                .where(
                    and_(
                        FeedbackReport.report_type == "weekly",
                        FeedbackReport.report_date >= week_start,
                        FeedbackReport.report_date < week_end,
                    )
                )
                .order_by(FeedbackReport.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No weekly analysis found for {week_str}",
                )
            return {
                "report_type": row.report_type,
                "report_date": str(row.report_date),
                "content": row.content,
                "created_at": row.created_at.isoformat(),
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get weekly analysis for %s: %s", week_str, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@trade_router.get("/feedback/pending-adjustments")
async def get_pending_adjustments() -> list[dict]:
    """승인 대기 중인 파라미터 조정 목록을 반환한다."""
    try:
        async with get_session() as session:
            stmt = (
                select(PendingAdjustment)
                .where(PendingAdjustment.status == "pending")
                .order_by(PendingAdjustment.created_at.desc())
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": row.id,
                    "param_name": row.param_name,
                    "current_value": row.current_value,
                    "proposed_value": row.proposed_value,
                    "change_pct": row.change_pct,
                    "reason": row.reason,
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
    except Exception as exc:
        logger.error("Failed to get pending adjustments: %s", exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@trade_router.post("/feedback/approve-adjustment/{adjustment_id}")
async def approve_adjustment(
    adjustment_id: str,
    _: None = Depends(verify_api_key),
) -> dict:
    """대기 중인 파라미터 조정을 승인하고 적용한다."""
    try:
        _adj_param_name: str = ""
        _adj_current_value: Any = None
        _adj_proposed_value: Any = None

        async with get_session() as session:
            stmt = select(PendingAdjustment).where(
                PendingAdjustment.id == adjustment_id
            )
            result = await session.execute(stmt)
            adj = result.scalar_one_or_none()

            if adj is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Adjustment {adjustment_id} not found",
                )
            if adj.status != "pending":
                raise HTTPException(
                    status_code=400,
                    detail=f"Adjustment is already {adj.status}",
                )

            sp = _try_get("strategy_params")
            if sp is not None:
                try:
                    sp.set_param(adj.param_name, adj.proposed_value)
                except KeyError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Unknown parameter: {adj.param_name}",
                    )

            adj.status = "approved"
            adj.resolved_at = datetime.now(tz=timezone.utc)

            _adj_param_name = adj.param_name
            _adj_current_value = adj.current_value
            _adj_proposed_value = adj.proposed_value

        try:
            await _alert_manager.send_alert(
                alert_type=AlertManager.TYPE_ADJUSTMENT_PENDING,
                title=f"Adjustment Approved: {_adj_param_name}",
                message=(
                    f"{_adj_param_name}: {_adj_current_value} -> {_adj_proposed_value}"
                ),
                severity=AlertManager.SEVERITY_INFO,
            )
        except Exception as alert_exc:
            logger.warning("알림 전송 실패 (비치명적): %s", alert_exc)

        return {
            "status": "approved",
            "param_name": _adj_param_name,
            "new_value": _adj_proposed_value,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to approve adjustment %s: %s", adjustment_id, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")


@trade_router.post("/feedback/reject-adjustment/{adjustment_id}")
async def reject_adjustment(
    adjustment_id: str,
    _: None = Depends(verify_api_key),
) -> dict:
    """대기 중인 파라미터 조정을 거부한다."""
    try:
        async with get_session() as session:
            stmt = select(PendingAdjustment).where(
                PendingAdjustment.id == adjustment_id
            )
            result = await session.execute(stmt)
            adj = result.scalar_one_or_none()

            if adj is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Adjustment {adjustment_id} not found",
                )
            if adj.status != "pending":
                raise HTTPException(
                    status_code=400,
                    detail=f"Adjustment is already {adj.status}",
                )

            adj.status = "rejected"
            adj.resolved_at = datetime.now(tz=timezone.utc)

            return {
                "status": "rejected",
                "param_name": adj.param_name,
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to reject adjustment %s: %s", adjustment_id, exc)
        raise HTTPException(status_code=500, detail="내부 서버 오류가 발생했습니다.")
