"""FW WebSocket 연결 관리 -- KIS WebSocket 비동기 연결을 관리한다.

자동 재연결(3회), AES-256-CBC 복호화, approval_key 발급을 처리한다.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from typing import TYPE_CHECKING

import aiohttp
import websockets
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from src.common.logger import get_logger

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

_logger = get_logger(__name__)

# KIS WebSocket 엔드포인트이다
_WS_URL_REAL = "ws://ops.koreainvestment.com:21000"
_WS_URL_VIRTUAL = "ws://ops.koreainvestment.com:31000"
_APPROVAL_URL_REAL = "https://openapi.koreainvestment.com:9443/oauth2/Approval"
_APPROVAL_URL_VIRTUAL = "https://openapivts.koreainvestment.com:29443/oauth2/Approval"

_MAX_RETRIES = 3
_RETRY_DELAY_SEC = 2.0


def _derive_aes_key(approval_key: str) -> bytes:
    """approval_key에서 AES-256 키를 파생한다."""
    return hashlib.sha256(approval_key.encode("utf-8")).digest()


def _decrypt_aes(encrypted: str, key: bytes, iv: bytes) -> str:
    """AES-256-CBC로 암호화된 메시지를 복호화한다."""
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decoded = base64.b64decode(encrypted)
    decrypted = unpad(cipher.decrypt(decoded), AES.block_size)
    return decrypted.decode("utf-8")


class WebSocketConnection:
    """KIS WebSocket 연결 관리자이다.

    비동기 연결, 자동 재연결, AES 복호화를 담당한다.
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        is_real: bool = False,
    ) -> None:
        """브로커 설정으로 초기화한다."""
        self._app_key = app_key
        self._app_secret = app_secret
        self._is_real = is_real
        self._ws: ClientConnection | None = None
        self._approval_key: str | None = None
        self._aes_key: bytes | None = None
        self._aes_iv: bytes | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        """연결 상태를 반환한다."""
        return self._connected

    async def _fetch_approval_key(self) -> str:
        """KIS Approval API로 WebSocket 접속키를 발급한다."""
        url = _APPROVAL_URL_REAL if self._is_real else _APPROVAL_URL_VIRTUAL
        body = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "secretkey": self._app_secret,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise ConnectionError(f"Approval 키 발급 실패: {data}")
        key = data.get("approval_key", "")
        _logger.info("KIS WebSocket approval_key 발급 완료")
        return key

    async def connect(self) -> None:
        """WebSocket 연결을 수립한다. 최대 3회 재시도한다."""
        self._approval_key = await self._fetch_approval_key()
        self._aes_key = _derive_aes_key(self._approval_key)
        # IV는 approval_key 앞 16바이트를 사용한다
        self._aes_iv = self._approval_key[:16].encode("utf-8")
        ws_url = _WS_URL_REAL if self._is_real else _WS_URL_VIRTUAL
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._ws = await websockets.connect(ws_url)
                self._connected = True
                _logger.info("KIS WebSocket 연결 성공 (시도 %d)", attempt)
                return
            except Exception as exc:
                _logger.warning("WebSocket 연결 실패 (시도 %d/%d): %s", attempt, _MAX_RETRIES, exc)
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_DELAY_SEC * attempt)
        raise ConnectionError("WebSocket 연결 실패: 최대 재시도 횟수 초과")

    async def send(self, message: str) -> None:
        """메시지를 전송한다."""
        if self._ws is None:
            raise ConnectionError("WebSocket이 연결되지 않았다")
        await self._ws.send(message)

    async def receive(self) -> str:
        """메시지를 수신한다. 암호화된 경우 복호화한다."""
        if self._ws is None:
            raise ConnectionError("WebSocket이 연결되지 않았다")
        raw = await self._ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return self._try_decrypt(raw)

    def _try_decrypt(self, raw: str) -> str:
        """암호화 여부를 판단하여 복호화를 시도한다."""
        # KIS 프로토콜: 헤더의 encrypt 필드가 '1'이면 암호화됨
        parts = raw.split("|")
        if len(parts) >= 4:
            header = parts[0]
            if len(header) > 0 and header[-1] == "1":
                if self._aes_key and self._aes_iv:
                    try:
                        decrypted = _decrypt_aes(parts[3], self._aes_key, self._aes_iv)
                        return f"{parts[0]}|{parts[1]}|{parts[2]}|{decrypted}"
                    except Exception:
                        _logger.debug("AES 복호화 실패, 원본 반환")
        return raw

    async def disconnect(self) -> None:
        """WebSocket 연결을 종료한다."""
        self._connected = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        _logger.info("KIS WebSocket 연결 종료")

    def build_subscribe_message(
        self, tr_id: str, tr_key: str,
    ) -> str:
        """구독 요청 JSON 메시지를 생성한다."""
        return json.dumps({
            "header": {
                "approval_key": self._approval_key or "",
                "custtype": "P",
                "tr_type": "1",
                "content-type": "utf-8",
            },
            "body": {
                "input": {"tr_id": tr_id, "tr_key": tr_key},
            },
        })

    def build_unsubscribe_message(
        self, tr_id: str, tr_key: str,
    ) -> str:
        """구독 해제 JSON 메시지를 생성한다."""
        return json.dumps({
            "header": {
                "approval_key": self._approval_key or "",
                "custtype": "P",
                "tr_type": "2",
                "content-type": "utf-8",
            },
            "body": {
                "input": {"tr_id": tr_id, "tr_key": tr_key},
            },
        })
