"""CommandProcessor -- 텔레그램 봇 명령어를 해석하고 처리한다.

/status, /positions, /stop, /help 등 시스템 제어 명령을 수행한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.common.logger import get_logger
from src.telegram.models import CommandResult

logger = get_logger(__name__)


class CommandProcessor:
    """봇 명령어 처리기이다. 시스템 상태 조회/제어 명령을 담당한다."""

    def __init__(self) -> None:
        """명령어 핸들러를 등록한다."""
        self._trading_active: bool = False
        self._status_callback: object | None = None
        self._positions_callback: object | None = None
        self._stop_callback: object | None = None
        logger.info("CommandProcessor 초기화 완료")

    def set_callbacks(
        self,
        status_cb: object | None = None,
        positions_cb: object | None = None,
        stop_cb: object | None = None,
    ) -> None:
        """외부 콜백을 등록한다. 실제 시스템 연동에 사용한다."""
        self._status_callback = status_cb
        self._positions_callback = positions_cb
        self._stop_callback = stop_cb

    async def process(self, command: str, args: list[str]) -> CommandResult:
        """명령어를 파싱하여 실행한다.

        Args:
            command: 명령어 이름 (/status, /positions 등)
            args: 명령어 인자 목록

        Returns:
            명령어 처리 결과
        """
        cmd = command.lower().strip("/")
        handler = _HANDLERS.get(cmd)
        if handler is None:
            return CommandResult(
                response_text=f"알 수 없는 명령어: /{cmd}\n/help 로 도움말 확인",
                success=False,
            )
        try:
            return await handler(self, args)
        except Exception:
            logger.exception("명령어 처리 실패: /%s", cmd)
            return CommandResult(response_text="명령어 처리 중 오류 발생", success=False)


async def _handle_status(proc: CommandProcessor, _args: list[str]) -> CommandResult:
    """시스템 상태를 반환한다."""
    if proc._status_callback is not None:
        data = await proc._status_callback()  # type: ignore[operator]
        return CommandResult(response_text=str(data), success=True)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return CommandResult(response_text=f"시스템 가동 중\n시각: {now}", success=True)


async def _handle_positions(proc: CommandProcessor, _args: list[str]) -> CommandResult:
    """보유 포지션을 반환한다."""
    if proc._positions_callback is not None:
        data = await proc._positions_callback()  # type: ignore[operator]
        return CommandResult(response_text=str(data), success=True)
    return CommandResult(response_text="포지션 콜백 미등록", success=False)


async def _handle_stop(proc: CommandProcessor, _args: list[str]) -> CommandResult:
    """매매를 중지한다."""
    if proc._stop_callback is not None:
        await proc._stop_callback()  # type: ignore[operator]
        return CommandResult(response_text="매매 중지 요청 완료", success=True)
    return CommandResult(response_text="중지 콜백 미등록", success=False)


async def _handle_help(_proc: CommandProcessor, _args: list[str]) -> CommandResult:
    """도움말을 반환한다."""
    text = (
        "<b>사용 가능한 명령어:</b>\n"
        "/status - 시스템 상태 조회\n"
        "/positions - 보유 포지션 조회\n"
        "/stop - 매매 중지\n"
        "/help - 도움말"
    )
    return CommandResult(response_text=text, success=True)


# 명령어 핸들러 매핑
_HANDLERS: dict[str, object] = {
    "status": _handle_status,
    "positions": _handle_positions,
    "stop": _handle_stop,
    "help": _handle_help,
    "start": _handle_help,
}
