"""F4 뉴스 페이딩 -- 뉴스 스파이크의 역방향 페이딩 신호를 생성한다."""
from __future__ import annotations

from src.common.logger import get_logger
from src.strategy.models import FadeSignal

logger = get_logger(__name__)

# 스파이크 임계값
_SPIKE_PCT_THRESHOLD = 1.0   # 1% 이상 변동
_SPIKE_SECONDS_MAX = 60       # 60초 이내

# 디케이 추정 상수
_DECAY_BASE = 0.6             # 기본 디케이율 60%
_DECAY_HIGH_IMPACT = 0.3      # 고영향 뉴스 디케이율 30%
_HIGH_IMPACT_THRESHOLD = 0.8  # 영향도 임계값


def _is_spike(pct_change: float, seconds: int) -> bool:
    """가격 스파이크 조건을 확인한다. 60초 이내 1% 이상 변동이면 True이다."""
    return abs(pct_change) >= _SPIKE_PCT_THRESHOLD and seconds <= _SPIKE_SECONDS_MAX


def _estimate_decay(news_impact: float) -> float:
    """뉴스 영향도에 따른 디케이율을 추정한다."""
    if news_impact >= _HIGH_IMPACT_THRESHOLD:
        # 고영향 뉴스는 디케이가 적다 (반등 약하다)
        return _DECAY_HIGH_IMPACT
    return _DECAY_BASE


def _determine_fade_direction(pct_change: float) -> str:
    """스파이크 반대 방향을 결정한다."""
    if pct_change > 0:
        return "short"  # 급등 후 하락 예상
    return "long"       # 급락 후 반등 예상


def _calculate_entry_price(current_price: float, pct_change: float, decay: float) -> float:
    """페이딩 진입 가격을 계산한다. 스파이크의 디케이율만큼 되돌림을 예상한다."""
    reversion_pct = abs(pct_change) * decay
    if pct_change > 0:
        # 급등 후 하락 예상: 현재가에서 되돌림만큼 아래
        return round(current_price * (1 - reversion_pct / 100), 2)
    # 급락 후 반등 예상: 현재가에서 되돌림만큼 위
    return round(current_price * (1 + reversion_pct / 100), 2)


class NewsFading:
    """뉴스 스파이크의 역방향 페이딩 신호를 생성한다."""

    def evaluate(
        self,
        price_spike: dict,
        news_context: dict,
    ) -> FadeSignal:
        """스파이크 감지 시 페이딩 신호를 생성한다.

        Args:
            price_spike: pct_change(%), seconds(초), current_price
            news_context: impact_score(0~1), category
        """
        pct_change = price_spike.get("pct_change", 0.0)
        seconds = price_spike.get("seconds", 999)
        current_price = price_spike.get("current_price", 0.0)
        impact_score = news_context.get("impact_score", 0.5)

        # 스파이크 미충족
        if not _is_spike(pct_change, seconds):
            return FadeSignal(should_fade=False)

        # 고영향 뉴스는 페이딩 금지 (구조적 변화일 수 있다)
        if impact_score >= 0.9:
            logger.info("뉴스 페이딩 금지: 고영향 뉴스 (impact=%.2f)", impact_score)
            return FadeSignal(should_fade=False)

        decay = _estimate_decay(impact_score)
        direction = _determine_fade_direction(pct_change)
        entry = _calculate_entry_price(current_price, pct_change, decay)

        logger.info(
            "뉴스 페이딩 신호: dir=%s decay=%.1f%% entry=$%.2f spike=%.2f%%/%ds",
            direction, decay * 100, entry, pct_change, seconds,
        )

        return FadeSignal(
            should_fade=True,
            direction=direction,
            decay_estimate=decay,
            entry_price=entry,
        )
