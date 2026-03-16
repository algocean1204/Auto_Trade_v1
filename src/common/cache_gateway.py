"""CacheGateway (C0.3) -- 인메모리 캐시 클라이언트를 생성하고 CRUD/Pub-Sub 인터페이스를 제공한다.

Python dict + asyncio.Lock 기반 인메모리 구현이다.
JSON 직렬화 시 datetime 호환을 위해 default=str을 사용한다.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import AsyncIterator

from src.common.logger import get_logger

logger = get_logger(__name__)

# -- 싱글톤 인스턴스 --
_instance: CacheClient | None = None


class CacheClient:
    """인메모리 캐시 클라이언트이다.

    read/write/delete CRUD와 JSON 헬퍼, Pub/Sub 기능을 제공한다.
    aclose()로 리소스를 정리한다.
    """

    def __init__(self) -> None:
        """인메모리 캐시를 초기화한다."""
        self._store: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._pubsub: defaultdict[str, list[asyncio.Queue[str]]] = defaultdict(list)
        self._cleanup_task: asyncio.Task | None = None
        try:
            loop = asyncio.get_running_loop()
            self._cleanup_task = loop.create_task(self._cleanup_expired())
        except RuntimeError:
            pass  # 이벤트 루프 없으면 cleanup 스킵
        logger.info("CacheGateway 인메모리 캐시 생성 완료")

    async def _cleanup_expired(self) -> None:
        """만료된 키를 60초 주기로 정리한다."""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired = [k for k, exp in self._expiry.items() if now >= exp]
            if expired:
                async with self._lock:
                    for k in expired:
                        self._store.pop(k, None)
                        self._expiry.pop(k, None)

    def _is_expired(self, key: str) -> bool:
        """키가 만료되었는지 확인한다. 만료 시 lazy 삭제한다."""
        if key in self._expiry and time.time() >= self._expiry[key]:
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    async def read(self, key: str) -> str | None:
        """키에 해당하는 값을 읽는다. 없거나 만료되면 None을 반환한다."""
        if self._is_expired(key):
            return None
        return self._store.get(key)

    async def write(self, key: str, value: str, ttl: int | None = None) -> None:
        """키-값 쌍을 저장한다. ttl(초)이 주어지면 만료 시간을 설정한다."""
        async with self._lock:
            self._store[key] = value
            if ttl is not None:
                self._expiry[key] = time.time() + ttl
            elif key in self._expiry:
                del self._expiry[key]

    async def delete(self, key: str) -> None:
        """키를 삭제한다. 존재하지 않아도 에러를 발생시키지 않는다."""
        async with self._lock:
            self._store.pop(key, None)
            self._expiry.pop(key, None)

    async def read_json(self, key: str) -> dict | list | None:
        """JSON 문자열을 읽어 dict 또는 list로 반환한다. 키가 없으면 None을 반환한다."""
        raw = await self.read(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def write_json(self, key: str, data: dict | list, ttl: int | None = None) -> None:
        """dict 또는 list를 JSON으로 직렬화하여 저장한다.

        datetime 등 비표준 타입은 default=str로 자동 변환한다.
        """
        serialized = json.dumps(data, default=str, ensure_ascii=False)
        await self.write(key, serialized, ttl=ttl)

    async def atomic_list_append(
        self,
        key: str,
        new_items: list[dict],
        max_size: int,
        ttl: int | None = None,
    ) -> None:
        """JSON 리스트에 항목을 원자적으로 추가한다. Lock으로 동시 쓰기를 방지한다."""
        async with self._lock:
            raw = self._store.get(key)
            existing: list = json.loads(raw) if raw else []
            existing.extend(new_items)
            while len(existing) > max_size:
                existing.pop(0)
            serialized = json.dumps(existing, default=str, ensure_ascii=False)
            self._store[key] = serialized
            if ttl is not None:
                self._expiry[key] = time.time() + ttl

    async def publish(self, channel: str, message: str) -> None:
        """Pub/Sub 채널에 메시지를 발행한다."""
        for queue in self._pubsub.get(channel, []):
            await queue.put(message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        """Pub/Sub 채널을 구독한다. 메시지를 비동기 이터레이터로 반환한다."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._pubsub[channel].append(queue)
        try:
            while True:
                message = await queue.get()
                yield message
        finally:
            self._pubsub[channel].remove(queue)

    async def ping(self) -> bool:
        """캐시 연결 상태를 확인한다. 인메모리이므로 항상 True이다."""
        return True

    async def aclose(self) -> None:
        """리소스를 정리한다."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
        self._store.clear()
        self._expiry.clear()
        logger.info("CacheGateway 인메모리 캐시 종료 완료")


def get_cache_client() -> CacheClient:
    """CacheClient 싱글톤을 반환한다."""
    global _instance
    if _instance is not None:
        return _instance
    _instance = CacheClient()
    return _instance


def reset_cache_client() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
