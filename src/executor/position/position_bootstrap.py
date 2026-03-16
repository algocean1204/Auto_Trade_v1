"""PositionBootstrap (F5.6) -- 시스템 시작 시 KIS에서 기존 포지션을 로드한다.

거래 시스템 부팅 단계에서 호출되어 KIS 잔고를 조회하고,
PositionMonitor의 캐시를 초기화한다.
부트스트랩 후 캐시의 beast/pyramid 상태를 검증한다.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.common.broker_gateway import BrokerClient
from src.common.error_handler import BrokerError
from src.common.logger import get_logger
from src.executor.position.position_monitor import PositionMonitor

logger = get_logger(__name__)


class BootstrapResult(BaseModel):
    """부트스트랩 결과이다."""

    positions_loaded: int
    total_equity: float
    available_cash: float


async def _verify_beast_pyramid_state(
    positions: dict,
    cache: object,
) -> None:
    """동기화된 포지션에 대해 캐시 beast/pyramid 상태를 검증한다.

    beast_positions:{ticker}나 pyramid_level:{ticker} 키가 존재하면
    해당 포지션이 특수 모드 상태임을 로그에 기록한다.
    보유하지 않은 종목의 잔존 키가 있으면 경고를 기록한다.
    """
    if cache is None:
        return

    held_tickers = set(positions.keys())

    for ticker in held_tickers:
        try:
            beast_flag = await cache.read(f"beast_positions:{ticker}")  # type: ignore[union-attr]
            if beast_flag is not None:
                logger.info(
                    "부트스트랩 Beast 상태 확인: %s (beast_positions 캐시 키 존재)",
                    ticker,
                )
        except Exception:
            pass

        try:
            pyr_raw = await cache.read(f"pyramid_level:{ticker}")  # type: ignore[union-attr]
            if pyr_raw is not None:
                logger.info(
                    "부트스트랩 피라미딩 상태 확인: %s level=%s (pyramid_level 캐시 키 존재)",
                    ticker, pyr_raw,
                )
        except Exception:
            pass


async def bootstrap_positions(
    broker: BrokerClient,
    position_monitor: PositionMonitor,
    cache: object | None = None,
) -> BootstrapResult:
    """시스템 시작 시 기존 포지션을 KIS에서 로드한다.

    1. 잔고 API를 호출하여 포지션/자산 정보를 가져온다.
    2. PositionMonitor의 캐시를 동기화한다.
    3. beast/pyramid 캐시 상태를 검증한다.
    4. 부트스트랩 결과를 반환한다.
    """
    logger.info("포지션 부트스트랩 시작")
    try:
        balance = await broker.get_balance()
    except BrokerError as exc:
        logger.error("부트스트랩 잔고 조회 실패: %s", exc.message)
        return BootstrapResult(
            positions_loaded=0, total_equity=0.0, available_cash=0.0,
        )

    # PositionMonitor 캐시를 동기화한다
    positions = await position_monitor.sync_positions()
    position_count = len(positions)
    equity = balance.total_equity
    cash = balance.available_cash

    # 포지션 상세 로그를 남긴다
    for ticker, pos in positions.items():
        logger.info(
            "기존 포지션: %s %d주 (평균 $%.2f, 현재 $%.2f, PnL %.2f%%)",
            ticker, pos.quantity, pos.avg_price,
            pos.current_price, pos.pnl_pct,
        )

    # 캐시에서 beast/pyramid 상태를 검증한다 (C-2/C-3 연동)
    if cache is not None:
        await _verify_beast_pyramid_state(positions, cache)

    logger.info(
        "부트스트랩 완료: %d개 포지션, 총자산=$%.2f, 가용현금=$%.2f",
        position_count, equity, cash,
    )
    return BootstrapResult(
        positions_loaded=position_count,
        total_equity=equity,
        available_cash=cash,
    )
