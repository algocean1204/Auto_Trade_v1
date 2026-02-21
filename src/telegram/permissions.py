"""
텔레그램 사용자 권한 관리.

User 1 (TELEGRAM_CHAT_ID): READ + CONTROL + TRADE
User 2 (TELEGRAM_CHAT_ID_2): READ ONLY
미등록 사용자: 모든 접근 차단
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from enum import Enum

from src.utils.logger import get_logger

logger = get_logger(__name__)


class Permission(Enum):
    """사용자 권한 등급을 정의한다."""

    READ = "read"
    CONTROL = "control"
    TRADE = "trade"


# 분당 최대 명령 수
_RATE_LIMIT_PER_MINUTE = 30

# 사용자별 명령 타임스탬프 추적
_command_timestamps: dict[str, list[float]] = defaultdict(list)


def get_user1_chat_id() -> str:
    """User 1의 chat_id를 환경변수에서 반환한다."""
    return os.getenv("TELEGRAM_CHAT_ID", "")


def get_user2_chat_id() -> str:
    """User 2의 chat_id를 환경변수에서 반환한다."""
    return os.getenv("TELEGRAM_CHAT_ID_2", "")


def is_known_user(chat_id: int | str) -> bool:
    """등록된 사용자인지 확인한다.

    Args:
        chat_id: 텔레그램 chat ID.

    Returns:
        등록된 사용자이면 True.
    """
    cid = str(chat_id)
    if not cid:
        return False
    user1 = get_user1_chat_id()
    user2 = get_user2_chat_id()
    if user1 and cid == user1:
        return True
    if user2 and cid == user2:
        return True
    return False


def check_permission(chat_id: int | str, required: Permission) -> bool:
    """특정 chat_id가 요구되는 권한을 보유하는지 확인한다.

    Args:
        chat_id: 텔레그램 chat ID.
        required: 필요한 권한 등급.

    Returns:
        권한이 있으면 True.
    """
    cid = str(chat_id)
    if not cid:
        return False
    user1_id = get_user1_chat_id()
    user2_id = get_user2_chat_id()

    if user1_id and cid == user1_id:
        # User 1: 모든 권한 보유
        return required in (Permission.READ, Permission.CONTROL, Permission.TRADE)
    elif user2_id and cid == user2_id:
        # User 2: 읽기 전용
        return required == Permission.READ
    else:
        # 미등록 사용자: 모든 접근 차단
        return False


def check_rate_limit(chat_id: int | str) -> bool:
    """분당 명령 수 제한을 확인한다.

    등록된 사용자에 대해서만 호출해야 한다.

    Args:
        chat_id: 텔레그램 chat ID.

    Returns:
        제한 내이면 True, 초과 시 False.
    """
    cid = str(chat_id)
    if not cid:
        return False

    now = time.time()
    cutoff = now - 60.0

    # 1분 이전 기록 제거
    timestamps = _command_timestamps.get(cid, [])
    timestamps = [ts for ts in timestamps if ts > cutoff]
    _command_timestamps[cid] = timestamps

    if len(timestamps) >= _RATE_LIMIT_PER_MINUTE:
        logger.warning(
            "Rate limit 초과: chat_id=%s, count=%d/%d",
            cid,
            len(timestamps),
            _RATE_LIMIT_PER_MINUTE,
        )
        return False

    timestamps.append(now)
    return True


def get_user_label(chat_id: int | str) -> str:
    """chat_id에 대응하는 사용자 라벨을 반환한다.

    Args:
        chat_id: 텔레그램 chat ID.

    Returns:
        "User1", "User2", 또는 "Unknown".
    """
    cid = str(chat_id)
    if cid == get_user1_chat_id():
        return "User1"
    elif cid == get_user2_chat_id():
        return "User2"
    return "Unknown"
