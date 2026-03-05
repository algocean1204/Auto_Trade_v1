"""AccountSafety (F6.18) -- 매매 윈도우 밖 자동 정지이다.

MarketClock의 TimeInfo를 받아서 매매 가능 시간대가 아니면
즉시 정지 신호를 반환한다.
"""

from __future__ import annotations

from src.common.logger import get_logger
from src.common.market_clock import TimeInfo
from src.risk.models import AccountSafetyResult

_logger = get_logger(__name__)


def check_account_safety(
    time_info: TimeInfo,
) -> AccountSafetyResult:
    """매매 윈도우 기반 계좌 안전 상태를 확인한다.

    Args:
        time_info: MarketClock에서 제공하는 시간 정보.

    Returns:
        should_stop=True이면 매매를 중단해야 함.
    """
    if not time_info.is_trading_window:
        reason = _build_stop_reason(time_info)
        _logger.info("AccountSafety 정지: %s", reason)
        return AccountSafetyResult(
            should_stop=True, reason=reason,
        )

    return AccountSafetyResult(should_stop=False)


def _build_stop_reason(time_info: TimeInfo) -> str:
    """정지 사유 메시지를 생성한다."""
    kst_str = time_info.now_kst.strftime("%H:%M")
    return (
        f"매매 윈도우 밖 (KST {kst_str}). "
        f"운영 시간: 20:00~06:30 KST"
    )
