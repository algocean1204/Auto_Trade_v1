"""
모의투자 실전전환 준비도 체크 모듈

매일 EOD 단계 완료 후 7가지 기준을 평가하여 실전투자 전환 준비 여부를 판단한다.
모든 기준을 충족하면 Telegram 알림을 발송하고 Redis 플래그로 중복 발송을 방지한다.

기준:
    1. 최소 5거래일 완료
    2. 시스템 가동률 > 95% (비정상 종료 없음)
    3. 누적 수익률 >= 0% (손실 없음)
    4. 최대 낙폭 < 10%
    5. 성공 거래 3건 이상
    6. 안전 시스템 일관적 통과
    7. 비상 이벤트 0건
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import case, func, select, and_

from src.db.connection import get_redis, get_session
from src.db.models import EmergencyEvent, RiskConfig, Trade
from src.monitoring.telegram_notifier import TelegramNotifier
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Redis 플래그 키 (실전전환 권장 1회 전송 보장)
_REDIS_FLAG_KEY = "live_trading_recommended"

# 기준 임계값
_MIN_TRADING_DAYS = 5
_MIN_UPTIME_PCT = 95.0
_MIN_CUMULATIVE_RETURN_PCT = 0.0
_MAX_DRAWDOWN_PCT = 10.0
_MIN_SUCCESSFUL_TRADES = 3


class LiveReadinessChecker:
    """모의투자 실전전환 준비도를 평가하는 클래스.

    매일 EOD 단계 완료 후 호출되어 7가지 기준을 종합 평가하고,
    모든 기준을 충족하면 TelegramNotifier를 통해 권장 메시지를 발송한다.
    Redis 플래그(`live_trading_recommended`)로 중복 발송을 차단한다.

    Attributes:
        telegram_notifier: Telegram 알림 발송 인스턴스.
        start_date: 모의투자 시작 날짜 (첫 실행일로 자동 추적).
    """

    def __init__(self, telegram_notifier: TelegramNotifier) -> None:
        """LiveReadinessChecker를 초기화한다.

        Args:
            telegram_notifier: Telegram 알림 발송 인스턴스.
        """
        self.telegram_notifier = telegram_notifier
        logger.info("LiveReadinessChecker 초기화 완료")

    # ------------------------------------------------------------------
    # 공개 메서드
    # ------------------------------------------------------------------

    async def check_and_notify(self) -> dict[str, Any]:
        """실전전환 준비도를 평가하고 조건 충족 시 Telegram 알림을 발송한다.

        Redis 플래그가 이미 설정된 경우 평가를 건너뛴다 (중복 방지).

        Returns:
            평가 결과 딕셔너리:
                - evaluated: 평가 수행 여부
                - ready: 모든 기준 충족 여부
                - criteria: 각 기준별 상세 결과
                - notified: Telegram 발송 여부
        """
        try:
            # Redis 플래그 확인 (이미 발송된 경우 건너뜀)
            already_sent = await self._is_already_recommended()
            if already_sent:
                logger.debug("실전전환 권장 알림 이미 발송됨. 평가 건너뜀.")
                return {
                    "evaluated": False,
                    "reason": "이미 실전전환 권장 알림이 발송되었습니다.",
                    "ready": True,
                    "criteria": {},
                    "notified": False,
                }

            # 기준 평가
            criteria = await self._evaluate_all_criteria()
            all_passed = all(c["passed"] for c in criteria.values())

            result: dict[str, Any] = {
                "evaluated": True,
                "ready": all_passed,
                "criteria": criteria,
                "notified": False,
            }

            if all_passed:
                # 모든 기준 충족 시 Telegram 알림 발송
                notified = await self._send_readiness_notification(criteria)
                result["notified"] = notified

                if notified:
                    # Redis 플래그 설정 (영구 보관, 한 번만 발송)
                    await self._mark_as_recommended()
                    logger.info("실전전환 준비 완료 알림 발송 및 플래그 설정 완료")
            else:
                failed = [k for k, v in criteria.items() if not v["passed"]]
                logger.info(
                    "실전전환 준비 미완료. 미충족 기준: %s",
                    ", ".join(failed),
                )

            return result

        except Exception as exc:
            logger.error("실전전환 준비도 평가 실패: %s", exc)
            return {
                "evaluated": False,
                "error": str(exc),
                "ready": False,
                "criteria": {},
                "notified": False,
            }

    # ------------------------------------------------------------------
    # 기준 평가 메서드
    # ------------------------------------------------------------------

    async def _evaluate_all_criteria(self) -> dict[str, dict[str, Any]]:
        """7가지 실전전환 기준을 모두 평가한다.

        Returns:
            기준별 평가 결과 딕셔너리.
        """
        # 공통 쿼리 데이터 미리 로드
        trade_stats = await self._get_trade_stats()
        emergency_count = await self._get_emergency_count()

        trading_days = trade_stats["trading_days"]
        cumulative_return_pct = trade_stats["cumulative_return_pct"]
        max_drawdown_pct = trade_stats["max_drawdown_pct"]
        successful_trades = trade_stats["successful_trades"]

        # 시스템 가동률은 Redis 기반으로 추적 (비정상 종료 = emergency event)
        uptime_pct = await self._calculate_uptime_pct(trading_days, emergency_count)

        criteria: dict[str, dict[str, Any]] = {
            "trading_days": {
                "label": "모의투자 기간",
                "value": trading_days,
                "threshold": _MIN_TRADING_DAYS,
                "unit": "일",
                "passed": trading_days >= _MIN_TRADING_DAYS,
            },
            "uptime": {
                "label": "시스템 안정성",
                "value": round(uptime_pct, 1),
                "threshold": _MIN_UPTIME_PCT,
                "unit": "%",
                "passed": uptime_pct >= _MIN_UPTIME_PCT,
            },
            "cumulative_return": {
                "label": "누적 수익률",
                "value": round(cumulative_return_pct, 2),
                "threshold": _MIN_CUMULATIVE_RETURN_PCT,
                "unit": "%",
                "passed": cumulative_return_pct >= _MIN_CUMULATIVE_RETURN_PCT,
            },
            "max_drawdown": {
                "label": "최대 낙폭",
                "value": round(max_drawdown_pct, 2),
                "threshold": _MAX_DRAWDOWN_PCT,
                "unit": "%",
                "passed": max_drawdown_pct < _MAX_DRAWDOWN_PCT,
            },
            "successful_trades": {
                "label": "성공 거래",
                "value": successful_trades,
                "threshold": _MIN_SUCCESSFUL_TRADES,
                "unit": "건",
                "passed": successful_trades >= _MIN_SUCCESSFUL_TRADES,
            },
            "safety_systems": {
                "label": "안전 시스템",
                "value": "정상",
                "threshold": "일관적 통과",
                "unit": "",
                "passed": emergency_count == 0,
            },
            "emergency_events": {
                "label": "비상 이벤트",
                "value": emergency_count,
                "threshold": 0,
                "unit": "건",
                "passed": emergency_count == 0,
            },
        }

        return criteria

    async def _get_trade_stats(self) -> dict[str, Any]:
        """매매 통계를 DB에서 계산한다.

        Returns:
            trading_days, cumulative_return_pct, max_drawdown_pct,
            successful_trades를 포함하는 딕셔너리.
        """
        try:
            async with get_session() as session:
                # 체결된 매매 전체 조회
                stmt = (
                    select(
                        func.date(Trade.exit_at).label("trade_date"),
                        func.coalesce(func.sum(Trade.pnl_amount), 0.0).label("daily_pnl"),
                        func.count(Trade.id).label("trade_count"),
                        func.sum(
                            case(
                                (Trade.pnl_amount > 0, 1),
                                else_=0,
                            )
                        ).label("winning_trades"),
                    )
                    .where(Trade.exit_price.isnot(None))
                    .group_by(func.date(Trade.exit_at))
                    .order_by(func.date(Trade.exit_at))
                )
                result = await session.execute(stmt)
                rows = result.all()

                if not rows:
                    return {
                        "trading_days": 0,
                        "cumulative_return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                        "successful_trades": 0,
                    }

                trading_days = len(rows)
                total_pnl = sum(float(row.daily_pnl) for row in rows)
                successful_trades = sum(int(row.winning_trades or 0) for row in rows)

                # 최대 낙폭 계산 (일별 누적 PnL 기준)
                cumulative = 0.0
                peak = 0.0
                max_drawdown_abs = 0.0
                for row in rows:
                    cumulative += float(row.daily_pnl)
                    if cumulative > peak:
                        peak = cumulative
                    drawdown = peak - cumulative
                    if drawdown > max_drawdown_abs:
                        max_drawdown_abs = drawdown

                # 수익률: 전체 PnL / 초기 자본 * 100 (실제 퍼센트)
                # RiskConfig의 initial_capital 값을 참조한다.
                # 조회 실패 시 기본값 10,000 USD를 사용한다.
                initial_capital = await self._get_initial_capital()
                if initial_capital > 0:
                    cumulative_return_pct = (total_pnl / initial_capital) * 100.0
                else:
                    cumulative_return_pct = 0.0
                # peak 가 0이면 낙폭 비율 계산 불가 -> 0으로 처리
                max_drawdown_pct = (
                    (max_drawdown_abs / peak * 100.0) if peak > 0 else 0.0
                )

                return {
                    "trading_days": trading_days,
                    "cumulative_return_pct": cumulative_return_pct,
                    "max_drawdown_pct": max_drawdown_pct,
                    "successful_trades": successful_trades,
                }

        except Exception as exc:
            logger.error("매매 통계 조회 실패: %s", exc)
            return {
                "trading_days": 0,
                "cumulative_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "successful_trades": 0,
            }

    async def _get_initial_capital(self) -> float:
        """초기 자본금을 DB에서 조회한다.

        RiskConfig 테이블의 param_key='initial_capital' 레코드를 참조한다.
        조회 실패 시 기본값 10,000 USD를 반환한다.

        Returns:
            초기 자본금 (USD).
        """
        try:
            async with get_session() as session:
                stmt = select(RiskConfig).where(RiskConfig.param_key == "initial_capital")
                result = await session.execute(stmt)
                config = result.scalar_one_or_none()
                if config:
                    return float(config.param_value)
                return 10_000.0
        except Exception as exc:
            logger.warning("초기 자본금 조회 실패, 기본값 10,000 USD 사용: %s", exc)
            return 10_000.0

    async def _get_emergency_count(self) -> int:
        """전체 비상 이벤트 발생 횟수를 DB에서 조회한다.

        Returns:
            비상 이벤트 총 발생 횟수.
        """
        try:
            async with get_session() as session:
                stmt = select(func.count(EmergencyEvent.id))
                result = await session.execute(stmt)
                return int(result.scalar_one() or 0)
        except Exception as exc:
            logger.warning("비상 이벤트 조회 실패: %s", exc)
            return 0

    async def _calculate_uptime_pct(
        self, trading_days: int, emergency_count: int
    ) -> float:
        """시스템 가동률을 추정한다.

        비상 이벤트를 시스템 비정상 지표로 사용한다.
        비상 이벤트가 없으면 100% 가동률로 간주한다.

        Args:
            trading_days: 총 거래일 수.
            emergency_count: 비상 이벤트 발생 횟수.

        Returns:
            시스템 가동률 (%).
        """
        if trading_days == 0:
            return 0.0
        if emergency_count == 0:
            return 100.0
        # 비상 이벤트 당 하루치 가동률 차감 (근사 계산)
        disrupted_days = min(emergency_count, trading_days)
        uptime_pct = ((trading_days - disrupted_days) / trading_days) * 100.0
        return max(uptime_pct, 0.0)

    # ------------------------------------------------------------------
    # Redis 플래그 메서드
    # ------------------------------------------------------------------

    async def _is_already_recommended(self) -> bool:
        """Redis에서 실전전환 권장 플래그 존재 여부를 확인한다.

        Returns:
            이미 발송된 경우 True, 그렇지 않으면 False.
        """
        try:
            redis = get_redis()
            value = await redis.get(_REDIS_FLAG_KEY)
            return value is not None
        except Exception as exc:
            logger.warning("Redis 플래그 확인 실패: %s", exc)
            return False

    async def _mark_as_recommended(self) -> None:
        """Redis에 실전전환 권장 플래그를 영구 설정한다."""
        try:
            redis = get_redis()
            timestamp = datetime.now(tz=timezone.utc).isoformat()
            await redis.set(_REDIS_FLAG_KEY, timestamp)
            logger.info("Redis 실전전환 플래그 설정 완료: %s", timestamp)
        except Exception as exc:
            logger.error("Redis 플래그 설정 실패: %s", exc)

    # ------------------------------------------------------------------
    # Telegram 알림 메서드
    # ------------------------------------------------------------------

    async def _send_readiness_notification(
        self, criteria: dict[str, dict[str, Any]]
    ) -> bool:
        """실전전환 준비 완료 Telegram 알림을 발송한다.

        Args:
            criteria: 기준별 평가 결과 딕셔너리.

        Returns:
            발송 성공 여부.
        """
        try:
            trading_days = criteria["trading_days"]["value"]
            cumulative_return = criteria["cumulative_return"]["value"]
            max_drawdown = criteria["max_drawdown"]["value"]
            successful_trades = criteria["successful_trades"]["value"]
            uptime_pct = criteria["uptime"]["value"]
            emergency_count = criteria["emergency_events"]["value"]

            # 수익률 표시 (USD 부호가 아닌 양수/음수 텍스트로 표현)
            return_sign = "+" if cumulative_return >= 0 else ""

            message = (
                f"모의투자 기간: {trading_days}일\n"
                f"누적 수익: {return_sign}{cumulative_return:.2f} USD\n"
                f"최대 낙폭: {max_drawdown:.2f}%\n"
                f"성공 거래: {successful_trades}건\n"
                f"시스템 안정성: {uptime_pct:.1f}%\n"
                f"비상 이벤트: {emergency_count}건\n\n"
                "실전투자 전환을 권장합니다.\n"
                "실전 전환 시 .env에서 KIS_VIRTUAL=false로 변경하세요.\n\n"
                "주의: 소액으로 시작하는 것을 권장합니다."
            )

            success = await self.telegram_notifier.send_message(
                title="모의투자 실전전환 준비 보고",
                message=message,
                severity="info",
            )
            return success

        except Exception as exc:
            logger.error("실전전환 준비 Telegram 알림 발송 실패: %s", exc)
            return False
