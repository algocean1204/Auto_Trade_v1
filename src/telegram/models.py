"""FT 텔레그램 봇 -- 공용 모델이다."""
from __future__ import annotations

from pydantic import BaseModel


class BotResponse(BaseModel):
    """봇 응답 결과이다."""

    reply_text: str
    parse_mode: str = "HTML"


class CommandResult(BaseModel):
    """명령어 처리 결과이다."""

    response_text: str
    success: bool


class TradeCommandResult(BaseModel):
    """수동 매매 명령 결과이다."""

    executed: bool
    order_result: dict = {}
    message: str = ""


class FormattedMessage(BaseModel):
    """포맷팅된 메시지이다."""

    text: str
    parse_mode: str = "HTML"


class ParsedCommand(BaseModel):
    """파싱된 명령어이다."""

    command_type: str
    params: dict = {}


class PermissionResult(BaseModel):
    """권한 확인 결과이다."""

    allowed: bool
    reason: str = ""
