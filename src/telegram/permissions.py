"""Permissions -- 텔레그램 사용자 권한을 확인한다.

허용된 chat_id만 봇 명령어를 실행할 수 있다.
SecretVault의 TELEGRAM_CHAT_ID를 기준으로 검증한다.
"""
from __future__ import annotations

from src.common.logger import get_logger
from src.telegram.models import PermissionResult

logger = get_logger(__name__)


class Permissions:
    """텔레그램 사용자 권한 관리자이다."""

    def __init__(self, allowed_chat_ids: list[str]) -> None:
        """허용된 chat_id 목록을 주입받는다."""
        self._allowed: set[str] = set(allowed_chat_ids)
        logger.info("Permissions 초기화: 허용 %d개 chat_id", len(self._allowed))

    def check(self, user_id: int, chat_id: int) -> PermissionResult:
        """사용자의 접근 권한을 확인한다.

        Args:
            user_id: 텔레그램 사용자 ID
            chat_id: 텔레그램 채팅 ID

        Returns:
            권한 확인 결과
        """
        chat_str = str(chat_id)
        if chat_str in self._allowed:
            return PermissionResult(allowed=True, reason="허용된 채팅")

        logger.warning(
            "미허용 접근 시도: user_id=%d chat_id=%d", user_id, chat_id,
        )
        return PermissionResult(
            allowed=False,
            reason=f"chat_id {chat_id}는 허용 목록에 없다",
        )

    def add_chat_id(self, chat_id: str) -> None:
        """chat_id를 허용 목록에 추가한다."""
        self._allowed.add(chat_id)

    def remove_chat_id(self, chat_id: str) -> None:
        """chat_id를 허용 목록에서 제거한다."""
        self._allowed.discard(chat_id)
