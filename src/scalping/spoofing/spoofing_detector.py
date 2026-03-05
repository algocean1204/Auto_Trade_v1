"""FS 스푸핑 탐지기 -- 호가창 조작 패턴을 탐지한다.

연속 호가 스냅샷을 비교하여 대량 주문의 급격한 출현/소멸,
레이어링(여러 단계에 동시 대량 주문) 등 스푸핑 패턴을 식별한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.scalping.models import SpoofingSignal

_logger = get_logger(__name__)

# 패턴 탐지 임계값이다
_VOLUME_SPIKE_RATIO = 3.0     # 잔량 급증 배수
_VANISH_RATIO = 0.2           # 잔량 급감 비율 (80% 이상 감소)
_LAYERING_MIN_LEVELS = 3      # 레이어링 최소 단계 수
_LAYERING_VOL_THRESHOLD = 2.0  # 레이어링 잔량 배수
_MIN_SNAPSHOTS = 3            # 최소 분석 필요 스냅샷 수


def _get_total_volume(levels: list[dict]) -> int:
    """호가 단계 총 잔량을 합산한다."""
    total = 0
    for level in levels:
        vol = level.get("volume", 0)
        if isinstance(vol, (int, float)):
            total += int(vol)
    return total


def _detect_volume_spike(
    prev_snapshot: dict,
    curr_snapshot: dict,
    side: str,
) -> bool:
    """한쪽 호가의 잔량이 급격히 증가했는지 확인한다."""
    prev_vol = _get_total_volume(prev_snapshot.get(side, []))
    curr_vol = _get_total_volume(curr_snapshot.get(side, []))
    if prev_vol <= 0:
        return False
    return curr_vol / prev_vol >= _VOLUME_SPIKE_RATIO


def _detect_vanish(
    prev_snapshot: dict,
    curr_snapshot: dict,
    side: str,
) -> bool:
    """한쪽 호가의 잔량이 급격히 감소(소멸)했는지 확인한다."""
    prev_vol = _get_total_volume(prev_snapshot.get(side, []))
    curr_vol = _get_total_volume(curr_snapshot.get(side, []))
    if prev_vol <= 0:
        return False
    return curr_vol / prev_vol <= _VANISH_RATIO


def _detect_layering(snapshot: dict, side: str) -> bool:
    """여러 호가 단계에 동시에 대량 주문이 있는지 확인한다."""
    levels = snapshot.get(side, [])
    if len(levels) < _LAYERING_MIN_LEVELS:
        return False
    volumes = [int(lv.get("volume", 0)) for lv in levels]
    avg_vol = sum(volumes) / len(volumes) if volumes else 0
    if avg_vol <= 0:
        return False
    large_count = sum(1 for v in volumes if v >= avg_vol * _LAYERING_VOL_THRESHOLD)
    return large_count >= _LAYERING_MIN_LEVELS


def detect_spoofing(snapshots: list[dict]) -> SpoofingSignal:
    """연속 호가 스냅샷에서 스푸핑 패턴을 탐지한다.

    최소 3개 스냅샷이 필요하다. 부족하면 미탐지를 반환한다.
    """
    if len(snapshots) < _MIN_SNAPSHOTS:
        return SpoofingSignal(detected=False)
    # 최근 2개 스냅샷 비교한다
    prev = snapshots[-2]
    curr = snapshots[-1]
    # 패턴 1: 급증 후 급감 (스푸핑 전형)
    for side in ("bids", "asks"):
        if _detect_volume_spike(snapshots[-3], prev, side):
            if _detect_vanish(prev, curr, side):
                _logger.info("스푸핑 탐지: %s 급증 후 급감", side)
                return SpoofingSignal(
                    detected=True,
                    pattern_type=f"spike_vanish_{side}",
                    confidence=0.8,
                )
    # 패턴 2: 레이어링
    for side in ("bids", "asks"):
        if _detect_layering(curr, side):
            _logger.info("레이어링 탐지: %s", side)
            return SpoofingSignal(
                detected=True,
                pattern_type=f"layering_{side}",
                confidence=0.6,
            )
    return SpoofingSignal(detected=False)
