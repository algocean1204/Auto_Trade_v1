"""
긴급 프로토콜 모듈

5가지 긴급 상황에 대한 자동 대응 프로토콜을 정의한다:
    1. flash_crash: 개별 종목 5분 내 -5% 이상 급락
    2. circuit_breaker: VIX > 35 또는 SPY 일일 -3% 이상 하락
    3. system_crash: 프로그램 비정상 종료 후 재시작 시 복원
    4. network_failure: 네트워크 끊김 감지 및 재연결
    5. runaway_loss: 일일 손실 -5% 도달 시 전면 청산
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.db.connection import get_session
from src.db.models import EmergencyEvent
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
FLASH_CRASH_THRESHOLD_PCT: float = -5.0
FLASH_CRASH_WINDOW_MINUTES: int = 5
FLASH_CRASH_COOLDOWN_HOURS: int = 1

CIRCUIT_BREAKER_VIX_TRIGGER: float = 35.0
CIRCUIT_BREAKER_VIX_RELEASE: float = 30.0
CIRCUIT_BREAKER_SPY_DROP_PCT: float = -3.0
CIRCUIT_BREAKER_TIGHT_TRAILING_STOP_PCT: float = 0.5

NETWORK_FAILURE_BACKOFF_INTERVALS: list[int] = [5, 10, 20, 40, 60]
NETWORK_FAILURE_MAX_DISCONNECT_SECONDS: int = 180

RUNAWAY_LOSS_THRESHOLD_PCT: float = -5.0

# 네트워크 연결 확인용 HTTP 요청 타임아웃 (초)
_ALERT_HTTP_TIMEOUT: float = 5.0


class EmergencyProtocol:
    """긴급 프로토콜: 5가지 위기 상황에 대한 자동 대응을 수행한다.

    각 프로토콜은 위기 감지 -> 즉시 대응 -> DB 기록 -> 알림 인터페이스 호출
    순서로 동작한다. 모든 public 메서드는 try/except로 감싸져 있어
    내부 에러가 시스템 크래시로 이어지지 않는다.

    Attributes:
        is_circuit_breaker_active: 서킷 브레이커 발동 상태.
        flash_crash_cooldowns: 종목별 플래시 크래시 쿨다운 만료 시각.
        is_runaway_loss_shutdown: 일일 손실 한도 초과로 매매 중단 상태.
    """

    def __init__(self) -> None:
        """EmergencyProtocol을 초기화한다."""
        self.is_circuit_breaker_active: bool = False
        self.flash_crash_cooldowns: dict[str, datetime] = {}
        self.is_runaway_loss_shutdown: bool = False
        logger.info("EmergencyProtocol 초기화 완료")

    # ------------------------------------------------------------------
    # 1. Flash Crash 감지
    # ------------------------------------------------------------------

    async def detect_flash_crash(
        self, ticker: str, price_history: list[dict]
    ) -> bool:
        """개별 종목이 5분 내 -5% 이상 하락했는지 감지한다.

        Args:
            ticker: 종목 심볼.
            price_history: 최근 가격 이력 리스트.
                각 항목: {"price": float, "timestamp": datetime}.
                최신 데이터가 마지막에 위치해야 한다.

        Returns:
            True이면 플래시 크래시 감지됨.
        """
        try:
            if len(price_history) < 2:
                return False

            now = datetime.now(tz=timezone.utc)
            window_start = now - timedelta(minutes=FLASH_CRASH_WINDOW_MINUTES)

            # 윈도우 내 가격만 필터링
            recent_prices = []
            for entry in price_history:
                ts = entry.get("timestamp")
                if ts is None:
                    continue
                if isinstance(ts, datetime) and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= window_start:
                    recent_prices.append(entry.get("price", 0.0))

            if len(recent_prices) < 2:
                return False

            first_price = recent_prices[0]
            last_price = recent_prices[-1]

            if first_price <= 0:
                return False

            change_pct = ((last_price - first_price) / first_price) * 100.0

            if change_pct <= FLASH_CRASH_THRESHOLD_PCT:
                logger.critical(
                    "FLASH CRASH 감지 | ticker=%s | change=%.2f%% in %d분",
                    ticker, change_pct, FLASH_CRASH_WINDOW_MINUTES,
                )

                # 쿨다운 설정
                cooldown_until = now + timedelta(hours=FLASH_CRASH_COOLDOWN_HOURS)
                self.flash_crash_cooldowns[ticker] = cooldown_until

                # DB 기록
                await self.log_event(
                    event_type="flash_crash",
                    trigger_value=change_pct,
                    action_taken=f"{ticker} 전량 매도 + {FLASH_CRASH_COOLDOWN_HOURS}시간 매수 금지",
                    positions_affected=[ticker],
                )
                return True

            return False

        except Exception as exc:
            logger.error("Flash crash 감지 중 에러 | ticker=%s | error=%s", ticker, exc)
            return False

    def is_flash_crash_cooldown(self, ticker: str) -> bool:
        """해당 종목이 플래시 크래시 쿨다운 중인지 확인한다.

        Args:
            ticker: 종목 심볼.

        Returns:
            True이면 쿨다운 중 (매수 불가).
        """
        cooldown_until = self.flash_crash_cooldowns.get(ticker)
        if cooldown_until is None:
            return False
        now = datetime.now(tz=timezone.utc)
        if now >= cooldown_until:
            del self.flash_crash_cooldowns[ticker]
            logger.info("Flash crash 쿨다운 해제 | ticker=%s", ticker)
            return False
        return True

    # ------------------------------------------------------------------
    # 2. Circuit Breaker 감지
    # ------------------------------------------------------------------

    async def detect_circuit_breaker(
        self, vix: float, spy_change_pct: float
    ) -> bool:
        """VIX > 35 또는 SPY 일일 -3% 이상 하락 시 서킷 브레이커를 발동한다.

        서킷 브레이커 발동 중에는 모든 신규 매수가 중단된다.
        기존 포지션은 유지하되 trailing stop을 0.5%로 타이트하게 조정해야 한다.
        VIX가 30 아래로 내려와야 해제된다.

        Args:
            vix: 현재 VIX 지수 값.
            spy_change_pct: SPY 당일 등락률 (음수=하락).

        Returns:
            True이면 서킷 브레이커 발동 상태.
        """
        try:
            was_active = self.is_circuit_breaker_active

            # 발동 조건 확인
            vix_triggered = vix >= CIRCUIT_BREAKER_VIX_TRIGGER
            spy_triggered = spy_change_pct <= CIRCUIT_BREAKER_SPY_DROP_PCT

            if not self.is_circuit_breaker_active:
                if vix_triggered or spy_triggered:
                    self.is_circuit_breaker_active = True
                    trigger_reason = []
                    if vix_triggered:
                        trigger_reason.append(f"VIX={vix:.1f}>={CIRCUIT_BREAKER_VIX_TRIGGER}")
                    if spy_triggered:
                        trigger_reason.append(
                            f"SPY={spy_change_pct:.2f}%<={CIRCUIT_BREAKER_SPY_DROP_PCT}%"
                        )

                    logger.critical(
                        "CIRCUIT BREAKER 발동 | %s",
                        " + ".join(trigger_reason),
                    )

                    await self.log_event(
                        event_type="circuit_breaker",
                        trigger_value=vix if vix_triggered else spy_change_pct,
                        action_taken=(
                            f"신규 매수 중단, trailing stop {CIRCUIT_BREAKER_TIGHT_TRAILING_STOP_PCT}%로 축소 | "
                            + " + ".join(trigger_reason)
                        ),
                        positions_affected=[],
                    )
            else:
                # 해제 조건: VIX < 30
                if vix < CIRCUIT_BREAKER_VIX_RELEASE:
                    self.is_circuit_breaker_active = False
                    logger.info(
                        "CIRCUIT BREAKER 해제 | VIX=%.1f < %.1f",
                        vix, CIRCUIT_BREAKER_VIX_RELEASE,
                    )
                    await self.log_event(
                        event_type="circuit_breaker",
                        trigger_value=vix,
                        action_taken="서킷 브레이커 해제, 정상 매매 재개",
                        positions_affected=[],
                    )

            return self.is_circuit_breaker_active

        except Exception as exc:
            logger.error("Circuit breaker 감지 중 에러 | error=%s", exc)
            return self.is_circuit_breaker_active

    # ------------------------------------------------------------------
    # 3. System Crash 복원
    # ------------------------------------------------------------------

    async def handle_system_crash(self) -> dict[str, Any]:
        """프로그램 비정상 종료 후 재시작 시 상태를 복원한다.

        1. DB에서 마지막 상태 복원 (미종료 긴급 이벤트)
        2. 미체결 주문 확인 필요 플래그 설정
        3. 포지션 동기화 필요 플래그 설정

        Returns:
            복원 상태 딕셔너리::

                {
                    "recovered": bool,
                    "unresolved_events": list[dict],
                    "needs_order_sync": bool,
                    "needs_position_sync": bool,
                    "details": str,
                }
        """
        try:
            logger.info("System crash 복원 시작")

            unresolved_events: list[dict[str, Any]] = []

            # DB에서 미종료 긴급 이벤트 조회
            try:
                async with get_session() as session:
                    from sqlalchemy import select
                    stmt = select(EmergencyEvent).where(
                        EmergencyEvent.resolved_at.is_(None)
                    ).order_by(EmergencyEvent.created_at.desc())
                    result = await session.execute(stmt)
                    events = result.scalars().all()

                    for event in events:
                        unresolved_events.append({
                            "id": event.id,
                            "event_type": event.event_type,
                            "trigger_value": event.trigger_value,
                            "action_taken": event.action_taken,
                            "created_at": str(event.created_at),
                        })

                        # 서킷 브레이커가 미종료 상태이면 재활성화
                        if event.event_type == "circuit_breaker":
                            self.is_circuit_breaker_active = True
                            logger.warning(
                                "미종료 circuit_breaker 이벤트 복원 | id=%s",
                                event.id,
                            )

                        # runaway_loss가 미종료 상태이면 셧다운 유지
                        if event.event_type == "runaway_loss":
                            self.is_runaway_loss_shutdown = True
                            logger.warning(
                                "미종료 runaway_loss 이벤트 복원 | id=%s",
                                event.id,
                            )
            except Exception as db_exc:
                logger.error("DB에서 미종료 이벤트 조회 실패 | error=%s", db_exc)

            result_data: dict[str, Any] = {
                "recovered": True,
                "unresolved_events": unresolved_events,
                "needs_order_sync": True,
                "needs_position_sync": True,
                "details": (
                    f"미종료 이벤트 {len(unresolved_events)}건 발견, "
                    "주문 및 포지션 동기화 필요"
                ),
            }

            logger.info(
                "System crash 복원 완료 | unresolved=%d건 | "
                "circuit_breaker=%s | runaway_loss=%s",
                len(unresolved_events),
                self.is_circuit_breaker_active,
                self.is_runaway_loss_shutdown,
            )

            await self.log_event(
                event_type="system_crash",
                trigger_value=0.0,
                action_taken=(
                    f"시스템 재시작 복원 완료: 미종료 이벤트 {len(unresolved_events)}건"
                ),
                positions_affected=[],
            )

            return result_data

        except Exception as exc:
            logger.error("System crash 복원 실패 | error=%s", exc)
            return {
                "recovered": False,
                "unresolved_events": [],
                "needs_order_sync": True,
                "needs_position_sync": True,
                "details": f"복원 실패: {exc}",
            }

    # ------------------------------------------------------------------
    # 4. Network Failure 처리
    # ------------------------------------------------------------------

    async def handle_network_failure(self) -> dict[str, Any]:
        """네트워크 끊김을 감지하고 재연결을 시도한다.

        1. 모든 진행 중인 주문 취소 시도 플래그 설정
        2. Exponential backoff로 재연결 대기 (5s, 10s, 20s, 40s, max 60s)
        3. 3분 이상 연결 불가 시 전량 매도 시도 필요 플래그 설정

        Returns:
            네트워크 장애 대응 결과::

                {
                    "reconnected": bool,
                    "total_wait_seconds": int,
                    "attempts": int,
                    "should_cancel_orders": bool,
                    "should_liquidate": bool,
                    "details": str,
                }
        """
        try:
            logger.critical("NETWORK FAILURE 감지 | 재연결 시도 시작")

            total_wait = 0
            attempts = 0
            reconnected = False

            for delay in NETWORK_FAILURE_BACKOFF_INTERVALS:
                attempts += 1
                logger.info(
                    "네트워크 재연결 대기 | attempt=%d | delay=%ds | total_wait=%ds",
                    attempts, delay, total_wait,
                )
                await asyncio.sleep(delay)
                total_wait += delay

                # 실제 네트워크 연결 확인: HTTPS GET 요청으로 검증한다.
                # 재연결이 확인되어도 안전을 위해 모든 backoff 구간을 계속 진행한다.
                # (주문 취소 처리 시간 확보 목적)
                if not reconnected:
                    reconnected = await self._check_network_connectivity()
                    if reconnected:
                        logger.info(
                            "네트워크 재연결 감지 | attempt=%d | total_wait=%ds | 안전을 위해 대기 계속",
                            attempts, total_wait,
                        )

                if total_wait >= NETWORK_FAILURE_MAX_DISCONNECT_SECONDS:
                    break

            should_liquidate = total_wait >= NETWORK_FAILURE_MAX_DISCONNECT_SECONDS

            details = (
                f"재연결 대기 총 {total_wait}초, {attempts}회 시도"
            )
            if should_liquidate:
                details += " | 3분 초과: 전량 매도 필요"
                logger.critical(
                    "NETWORK FAILURE 3분 초과 | 전량 매도 플래그 설정 | total_wait=%ds",
                    total_wait,
                )

            await self.log_event(
                event_type="network_failure",
                trigger_value=float(total_wait),
                action_taken=details,
                positions_affected=[],
            )

            return {
                "reconnected": reconnected,
                "total_wait_seconds": total_wait,
                "attempts": attempts,
                "should_cancel_orders": True,
                "should_liquidate": should_liquidate,
                "details": details,
            }

        except Exception as exc:
            logger.error("Network failure 처리 중 에러 | error=%s", exc)
            return {
                "reconnected": False,
                "total_wait_seconds": 0,
                "attempts": 0,
                "should_cancel_orders": True,
                "should_liquidate": True,
                "details": f"네트워크 장애 처리 실패: {exc}",
            }

    # ------------------------------------------------------------------
    # 네트워크 연결 확인 헬퍼
    # ------------------------------------------------------------------

    async def _check_network_connectivity(self) -> bool:
        """실제 HTTPS 요청으로 네트워크 연결 여부를 확인한다.

        KIS OpenAPI 도메인 또는 공개 HTTPS 엔드포인트에 접속을 시도한다.
        요청 성공(2xx/3xx) 시 True, 실패 시 False를 반환한다.

        Returns:
            네트워크 연결 가능 여부.
        """
        # KIS 실전 서버 호스트를 핑으로 사용한다.
        # 실패 시 공개 HTTPS 엔드포인트(Google DNS API)로 폴백한다.
        check_urls = [
            "https://openapi.koreainvestment.com:9443",
            "https://dns.google/resolve?name=openapi.koreainvestment.com&type=A",
        ]
        for url in check_urls:
            try:
                async with httpx.AsyncClient(timeout=_ALERT_HTTP_TIMEOUT) as client:
                    resp = await client.get(url)
                    if resp.status_code < 500:
                        logger.debug("네트워크 연결 확인 성공 | url=%s | status=%d", url, resp.status_code)
                        return True
            except Exception as exc:
                logger.debug("네트워크 확인 실패 | url=%s | error=%s", url, exc)
        return False

    # ------------------------------------------------------------------
    # 5. Runaway Loss 처리
    # ------------------------------------------------------------------

    async def handle_runaway_loss(
        self, positions: list[dict]
    ) -> dict[str, Any]:
        """일일 손실 -5% 도달 시 모든 포지션을 즉시 청산한다.

        1. 모든 포지션 즉시 청산 플래그 설정
        2. 당일 매매 완전 중단
        3. Telegram 긴급 알림 인터페이스 호출 (알림 모듈 연동용)

        Args:
            positions: 현재 보유 포지션 리스트.
                각 항목: {"ticker": str, "quantity": int, ...}.

        Returns:
            처리 결과::

                {
                    "shutdown": bool,
                    "positions_to_liquidate": list[dict],
                    "notification_payload": dict,
                    "details": str,
                }
        """
        try:
            logger.critical(
                "RUNAWAY LOSS 발동 | 포지션 %d개 즉시 청산 필요",
                len(positions),
            )

            self.is_runaway_loss_shutdown = True

            # 청산 대상 포지션 목록
            positions_to_liquidate = []
            affected_tickers = []
            for pos in positions:
                ticker = pos.get("ticker", "UNKNOWN")
                quantity = pos.get("quantity", 0)
                if quantity > 0:
                    positions_to_liquidate.append({
                        "ticker": ticker,
                        "quantity": quantity,
                        "action": "force_sell",
                        "reason": "runaway_loss_emergency",
                    })
                    affected_tickers.append(ticker)

            # Telegram 알림 페이로드 (알림 모듈이 구현되면 연동)
            notification_payload = {
                "channel": "telegram",
                "severity": "critical",
                "title": "RUNAWAY LOSS - 긴급 청산",
                "message": (
                    f"일일 손실 {RUNAWAY_LOSS_THRESHOLD_PCT}% 도달. "
                    f"포지션 {len(positions_to_liquidate)}개 즉시 청산. "
                    f"당일 매매 완전 중단."
                ),
                "tickers": affected_tickers,
            }

            await self.log_event(
                event_type="runaway_loss",
                trigger_value=RUNAWAY_LOSS_THRESHOLD_PCT,
                action_taken=(
                    f"전체 포지션 {len(positions_to_liquidate)}개 즉시 청산, "
                    "당일 매매 완전 중단"
                ),
                positions_affected=affected_tickers,
            )

            return {
                "shutdown": True,
                "positions_to_liquidate": positions_to_liquidate,
                "notification_payload": notification_payload,
                "details": (
                    f"일일 손실 한도 도달. "
                    f"{len(positions_to_liquidate)}개 포지션 청산 대상. "
                    "당일 매매 중단."
                ),
            }

        except Exception as exc:
            logger.error("Runaway loss 처리 중 에러 | error=%s", exc)
            return {
                "shutdown": True,
                "positions_to_liquidate": [],
                "notification_payload": {},
                "details": f"처리 에러 발생, 매매 중단 유지: {exc}",
            }

    # ------------------------------------------------------------------
    # DB 기록
    # ------------------------------------------------------------------

    async def log_event(
        self,
        event_type: str,
        trigger_value: float,
        action_taken: str,
        positions_affected: list,
    ) -> None:
        """긴급 이벤트를 DB에 기록한다.

        Args:
            event_type: 이벤트 유형
                ("flash_crash", "circuit_breaker", "system_crash",
                 "network_failure", "runaway_loss").
            trigger_value: 발동 기준값 (VIX, 변동률 등).
            action_taken: 수행한 조치 설명.
            positions_affected: 영향받은 종목 리스트.
        """
        try:
            async with get_session() as session:
                event = EmergencyEvent(
                    event_type=event_type,
                    trigger_value=trigger_value,
                    action_taken=action_taken,
                    positions_affected=positions_affected,
                )
                session.add(event)

            logger.info(
                "긴급 이벤트 DB 기록 | type=%s | trigger=%.2f | action=%s",
                event_type, trigger_value, action_taken,
            )
        except Exception as exc:
            logger.error(
                "긴급 이벤트 DB 기록 실패 | type=%s | error=%s",
                event_type, exc,
            )

    # ------------------------------------------------------------------
    # 상태 조회
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """현재 긴급 프로토콜 상태를 반환한다.

        Returns:
            상태 정보 딕셔너리.
        """
        now = datetime.now(tz=timezone.utc)
        active_cooldowns = {
            ticker: str(until)
            for ticker, until in self.flash_crash_cooldowns.items()
            if until > now
        }

        return {
            "circuit_breaker_active": self.is_circuit_breaker_active,
            "runaway_loss_shutdown": self.is_runaway_loss_shutdown,
            "flash_crash_cooldowns": active_cooldowns,
        }

    def reset_daily(self) -> None:
        """일일 상태를 리셋한다. 매일 자정에 호출해야 한다."""
        old_shutdown = self.is_runaway_loss_shutdown
        self.is_runaway_loss_shutdown = False
        self.flash_crash_cooldowns.clear()

        logger.info(
            "EmergencyProtocol 일일 리셋 | runaway_loss: %s->False | cooldowns 초기화",
            old_shutdown,
        )
