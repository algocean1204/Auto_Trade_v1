"""CacheGateway (C0.3) -- 인메모리 캐시 클라이언트를 생성하고 CRUD/Pub-Sub 인터페이스를 제공한다.

Python dict + asyncio.Lock 기반 인메모리 구현이다.
JSON 직렬화 시 datetime 호환을 위해 default=str을 사용한다.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable

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
            # Lock 안에서 만료 판별 + 삭제를 원자적으로 수행한다.
            # Lock 밖에서 expired 리스트를 만들면 그 사이 write()가
            # TTL을 갱신한 키를 잘못 삭제할 수 있다.
            async with self._lock:
                now = time.time()
                expired = [k for k, exp in self._expiry.items() if now >= exp]
                for k in expired:
                    self._store.pop(k, None)
                    self._expiry.pop(k, None)

    def _is_expired(self, key: str) -> bool:
        """키가 만료되었는지 확인한다. 만료 여부만 판별하고 삭제하지 않는다.

        _lock을 보유하지 않는 경로에서 호출될 수 있으므로
        dict 변이는 수행하지 않고 만료 여부만 판별한다.
        실제 삭제는 _cleanup_expired() 주기 태스크가 처리한다.
        """
        exp = self._expiry.get(key)
        if exp is not None and time.time() >= exp:
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
            # 만료 확인 — atomic_increment와 동일 패턴이다
            exp = self._expiry.get(key)
            if exp is not None and time.time() >= exp:
                raw = None
                self._store.pop(key, None)
                self._expiry.pop(key, None)
            existing: list = json.loads(raw) if raw else []
            existing.extend(new_items)
            while len(existing) > max_size:
                existing.pop(0)
            serialized = json.dumps(existing, default=str, ensure_ascii=False)
            self._store[key] = serialized
            if ttl is not None:
                self._expiry[key] = time.time() + ttl

    async def atomic_increment(
        self,
        key: str,
        amount: int = 1,
        ttl: int | None = None,
    ) -> int:
        """키의 정수 값을 원자적으로 증가시킨다. 키가 없으면 0에서 시작한다.

        read → increment → write 사이에 다른 코루틴이 개입하는
        경합 조건을 방지한다.
        """
        async with self._lock:
            raw = self._store.get(key)
            # 만료 여부도 lock 내에서 확인한다
            exp = self._expiry.get(key)
            if exp is not None and time.time() >= exp:
                raw = None
                self._store.pop(key, None)
                self._expiry.pop(key, None)
            current = int(raw) if raw else 0
            new_val = current + amount
            self._store[key] = str(new_val)
            if ttl is not None:
                self._expiry[key] = time.time() + ttl
            return new_val

    async def atomic_list_remove(
        self,
        key: str,
        predicate_key: str,
        predicate_value: str,
        ttl: int | None = None,
    ) -> dict | None:
        """JSON 리스트에서 특정 조건의 항목을 원자적으로 제거한다.

        predicate_key/predicate_value로 일치하는 첫 번째 항목을 제거하고 반환한다.
        Lock으로 동시 읽기-수정-쓰기 경합을 방지한다.
        일치 항목이 없으면 None을 반환한다.
        """
        async with self._lock:
            raw = self._store.get(key)
            # 만료 확인 — atomic_list_append와 동일 패턴이다
            exp = self._expiry.get(key)
            if exp is not None and time.time() >= exp:
                raw = None
                self._store.pop(key, None)
                self._expiry.pop(key, None)
            if not raw:
                return None
            existing: list = json.loads(raw)
            removed: dict | None = None
            remaining: list = []
            for item in existing:
                if (
                    removed is None
                    and isinstance(item, dict)
                    and str(item.get(predicate_key, "")) == predicate_value
                ):
                    removed = item
                else:
                    remaining.append(item)
            if removed is not None:
                self._store[key] = json.dumps(remaining, default=str, ensure_ascii=False)
                if ttl is not None:
                    self._expiry[key] = time.time() + ttl
            return removed

    async def atomic_set_add(
        self,
        key: str,
        value: str,
        max_size: int = 10000,
        ttl: int | None = None,
    ) -> None:
        """JSON 리스트(집합 용도)에 값을 원자적으로 추가한다.

        중복 값은 추가하지 않는다. Lock으로 동시 쓰기를 방지한다.
        """
        async with self._lock:
            raw = self._store.get(key)
            # 만료 확인 — atomic_list_append와 동일 패턴이다
            exp = self._expiry.get(key)
            if exp is not None and time.time() >= exp:
                raw = None
                self._store.pop(key, None)
                self._expiry.pop(key, None)
            existing: list = json.loads(raw) if raw else []
            existing_set = set(existing)
            existing_set.add(value)
            # max_size 초과 시 가장 오래된 항목(앞)부터 제거한다
            result = list(existing_set)
            if len(result) > max_size:
                result = result[-max_size:]
            self._store[key] = json.dumps(result, default=str, ensure_ascii=False)
            if ttl is not None:
                self._expiry[key] = time.time() + ttl

    async def atomic_dict_update(
        self,
        key: str,
        updater: Callable[[dict], dict],
        default: dict | None = None,
        ttl: int | None = None,
    ) -> dict:
        """JSON dict를 원자적으로 읽고-수정-저장한다.

        updater 콜백이 현재 dict를 받아 수정된 dict를 반환한다.
        Lock으로 동시 읽기-수정-쓰기 경합을 방지한다.
        """
        async with self._lock:
            raw = self._store.get(key)
            # 만료 확인
            exp = self._expiry.get(key)
            if exp is not None and time.time() >= exp:
                raw = None
                self._store.pop(key, None)
                self._expiry.pop(key, None)
            current: dict = json.loads(raw) if raw else (default or {})
            updated = updater(current)
            self._store[key] = json.dumps(updated, default=str, ensure_ascii=False)
            if ttl is not None:
                self._expiry[key] = time.time() + ttl
            return updated

    async def publish(self, channel: str, message: str) -> None:
        """Pub/Sub 채널에 메시지를 발행한다.

        구독자 큐가 가득 차면 가장 오래된 메시지를 버리고 새 메시지를 넣는다.
        """
        for queue in self._pubsub.get(channel, []):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.debug("Pub/Sub 큐 포화 (channel=%s)", channel)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        """Pub/Sub 채널을 구독한다. 메시지를 비동기 이터레이터로 반환한다."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
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
        """리소스를 정리한다. _cleanup_task 완료를 대기하여 정리 누수를 방지한다."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
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
