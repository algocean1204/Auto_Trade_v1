"""ConcentrationLimiter (F6.11) -- 단일 포지션 집중도 한도를 검사한다.

특정 티커가 총자산의 허용 비율을 초과하면 진입을 차단한다.
HardSafety의 max_position_pct와 연동하여 이중 보호 역할을 한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.risk.models import ConcentrationResult
from src.strategy.params.strategy_params import StrategyParamsManager

_logger = get_logger(__name__)

def _get_default_max_pct() -> float:
    """strategy_params.json의 max_position_pct를 매번 로드하여 반환한다.

    EOD에서 파라미터가 자동 튜닝되므로 캐싱하지 않고 항상 최신 값을 읽는다.
    """
    try:
        params = StrategyParamsManager().load()
        return params.max_position_pct
    except Exception as exc:
        _logger.warning(
            "strategy_params.json 로드 실패, 기본값 15.0%% 사용: %s", exc,
        )
        return 15.0


def check_concentration(
    positions: list[dict],
    ticker: str,
    total_value: float,
    max_pct: float | None = None,
) -> ConcentrationResult:
    """단일 티커의 포트폴리오 집중도를 검사한다.

    Args:
        positions: 보유 포지션 목록. 각 dict에 ticker, value 키 필요.
        ticker: 검사 대상 티커.
        total_value: 포트폴리오 총 가치(USD).
        max_pct: 허용 최대 비율(%). None이면 strategy_params.json에서 로드한다.

    Returns:
        집중도 검사 결과. exceeded=True이면 한도 초과.
    """
    if max_pct is None:
        max_pct = _get_default_max_pct()
    if total_value <= 0:
        return ConcentrationResult(
            exceeded=False, ticker=ticker,
            current_pct=0.0, max_allowed_pct=max_pct,
        )

    current_value = _sum_ticker_value(positions, ticker)
    current_pct = (current_value / total_value) * 100

    exceeded = current_pct >= max_pct

    if exceeded:
        _logger.warning(
            "집중도 초과: %s %.1f%% >= %.1f%%",
            ticker, current_pct, max_pct,
        )

    return ConcentrationResult(
        exceeded=exceeded,
        ticker=ticker,
        current_pct=round(current_pct, 2),
        max_allowed_pct=max_pct,
    )


def _sum_ticker_value(
    positions: list[dict], ticker: str,
) -> float:
    """포지션 목록에서 특정 티커의 합산 가치를 계산한다."""
    return sum(
        pos.get("value", 0.0)
        for pos in positions
        if pos.get("ticker") == ticker
    )
