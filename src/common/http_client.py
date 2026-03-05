"""
HttpClient (C0.4) -- 외부 HTTP 통신용 공유 비동기 클라이언트를 제공한다.

aiohttp.ClientSession 기반이며, 지연 초기화/재시도/타임아웃/에러 래핑을 처리한다.
5xx 에러에 대해 최대 3회 재시도하며, aiohttp 예외를 HttpClientError로 변환한다.
"""
from __future__ import annotations

import asyncio
import json

import aiohttp
from pydantic import BaseModel

from src.common.logger import get_logger

logger = get_logger(__name__)

_instance: AsyncHttpClient | None = None
_RETRYABLE_STATUS_CODES: set[int] = {500, 502, 503, 504}
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0  # 지수 백오프 기준 간격(초)이다


class TimeoutConfig(BaseModel):
    """HTTP 타임아웃 설정이다."""
    total: float = 30.0
    connect: float = 10.0


class HttpResponse(BaseModel):
    """HTTP 응답 래퍼이다. 상태 코드, 본문, 헤더를 보유한다."""
    status: int
    body: str
    headers: dict[str, str] = {}

    def json(self) -> dict:
        """응답 본문을 JSON dict로 파싱한다."""
        return json.loads(self.body)

    @property
    def ok(self) -> bool:
        """200~299 상태 코드이면 True이다."""
        return 200 <= self.status < 300


class HttpClientError(Exception):
    """HTTP 클라이언트 에러 래퍼이다. aiohttp 내부 예외를 감싼다."""
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class AsyncHttpClient:
    """공유 HTTP 클라이언트이다. 지연 초기화 + 지수 백오프 재시도를 수행한다."""

    def __init__(self, timeout_config: TimeoutConfig | None = None) -> None:
        """클라이언트를 초기화한다. 실제 세션은 첫 요청 시 생성된다."""
        self._config = timeout_config or TimeoutConfig()
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """세션이 없으면 생성한다. 지연 초기화로 이벤트 루프 안전성을 보장한다."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self._config.total, connect=self._config.connect,
            )
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _send_once(
        self, method: str, url: str, headers: dict | None = None,
        params: dict | None = None, json_data: dict | None = None,
        data: str | None = None,
    ) -> HttpResponse:
        """단일 HTTP 요청을 전송하고 HttpResponse를 반환한다."""
        session = await self._ensure_session()
        resp = await session.request(
            method, url, headers=headers,
            params=params, json=json_data, data=data,
        )
        body = await resp.text()
        return HttpResponse(
            status=resp.status, body=body, headers=dict(resp.headers),
        )

    async def _wait_before_retry(self, method: str, url: str, attempt: int, reason: str) -> None:
        """재시도 전 지수 백오프 대기를 수행하고 로그를 남긴다."""
        delay = _RETRY_BASE_DELAY * (2 ** attempt)
        logger.debug(
            "%s %s %s (%.1f초 후 재시도 %d/%d)",
            method, url, reason, delay, attempt + 1, _MAX_RETRIES,
        )
        await asyncio.sleep(delay)

    async def _request(
        self, method: str, url: str, headers: dict | None = None,
        params: dict | None = None, json_data: dict | None = None,
        data: str | None = None,
    ) -> HttpResponse:
        """HTTP 요청을 실행한다. 5xx 에러 시 지수 백오프 재시도를 수행한다."""
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._send_once(method, url, headers, params, json_data, data)
                if response.status not in _RETRYABLE_STATUS_CODES:
                    logger.debug("%s %s -> %d", method, url, response.status)
                    return response
                if attempt == _MAX_RETRIES - 1:
                    logger.warning("%s %s -> %d (재시도 소진)", method, url, response.status)
                    return response
                await self._wait_before_retry(method, url, attempt, f"-> {response.status}")
            except aiohttp.ClientError as exc:
                last_error = exc
                if attempt == _MAX_RETRIES - 1:
                    raise HttpClientError(f"HTTP 요청 실패: {method} {url}", cause=exc) from exc
                await self._wait_before_retry(method, url, attempt, f"네트워크 에러: {exc}")
        raise HttpClientError(f"HTTP 요청 재시도 소진: {method} {url}", cause=last_error)

    async def get(
        self, url: str, headers: dict | None = None, params: dict | None = None,
    ) -> HttpResponse:
        """GET 요청을 수행한다."""
        return await self._request("GET", url, headers=headers, params=params)

    async def post(
        self, url: str, json: dict | None = None,
        data: str | None = None, headers: dict | None = None,
    ) -> HttpResponse:
        """POST 요청을 수행한다. json 또는 data 중 하나를 전달한다."""
        return await self._request("POST", url, headers=headers, json_data=json, data=data)

    async def put(
        self, url: str, json: dict | None = None, headers: dict | None = None,
    ) -> HttpResponse:
        """PUT 요청을 수행한다."""
        return await self._request("PUT", url, headers=headers, json_data=json)

    async def delete(self, url: str, headers: dict | None = None) -> HttpResponse:
        """DELETE 요청을 수행한다."""
        return await self._request("DELETE", url, headers=headers)

    async def close(self) -> None:
        """aiohttp 세션을 닫는다. 애플리케이션 종료 시 호출해야 한다."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            logger.info("HttpClient 세션 종료 완료")


def get_http_client(timeout_config: TimeoutConfig | None = None) -> AsyncHttpClient:
    """AsyncHttpClient 싱글톤을 반환한다. 이후 호출에서는 캐싱된 인스턴스를 반환한다."""
    global _instance
    if _instance is not None:
        return _instance
    _instance = AsyncHttpClient(timeout_config)
    return _instance


def reset_http_client() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
