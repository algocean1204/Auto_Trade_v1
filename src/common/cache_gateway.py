"""
CacheGateway (C0.3) -- Redis 비동기 클라이언트를 생성하고 CRUD/Pub-Sub 인터페이스를 제공한다.

redis-py 5.0+ async 클라이언트 기반이며, 커넥션 풀과 Pub/Sub를 관리한다.
JSON 직렬화 시 datetime 호환을 위해 default=str을 사용한다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import redis.asyncio as aioredis

from src.common.logger import get_logger

logger = get_logger(__name__)

# -- 싱글톤 인스턴스 --
_instance: CacheClient | None = None


class CacheClient:
    """Redis 캐시 클라이언트이다.

    read/write/delete CRUD와 JSON 헬퍼, Pub/Sub 기능을 제공한다.
    aclose()로 연결을 정리한다 (redis-py 5.0+ 규약).
    """

    def __init__(self, redis_url: str) -> None:
        """Redis 클라이언트를 초기화한다.

        Args:
            redis_url: Redis 접속 URL (예: redis://localhost:6379/0)
        """
        self._client: aioredis.Redis = aioredis.from_url(
            redis_url,
            max_connections=20,
            decode_responses=True,
        )
        logger.info("CacheGateway Redis 클라이언트 생성 완료 (max_connections=20)")

    async def read(self, key: str) -> str | None:
        """키에 해당하는 값을 읽는다. 없으면 None을 반환한다."""
        value = await self._client.get(key)
        return value

    async def write(self, key: str, value: str, ttl: int | None = None) -> None:
        """키-값 쌍을 저장한다. ttl(초)이 주어지면 만료 시간을 설정한다."""
        if ttl is not None:
            await self._client.set(key, value, ex=ttl)
        else:
            await self._client.set(key, value)

    async def delete(self, key: str) -> None:
        """키를 삭제한다. 존재하지 않아도 에러를 발생시키지 않는다."""
        await self._client.delete(key)

    async def read_json(self, key: str) -> dict | list | None:
        """JSON 문자열을 읽어 dict 또는 list로 반환한다. 키가 없으면 None을 반환한다."""
        raw = await self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def write_json(
        self, key: str, data: dict | list, ttl: int | None = None
    ) -> None:
        """dict 또는 list를 JSON으로 직렬화하여 저장한다.

        datetime 등 비표준 타입은 default=str로 자동 변환한다.
        """
        serialized = json.dumps(data, default=str, ensure_ascii=False)
        await self.write(key, serialized, ttl=ttl)

    async def publish(self, channel: str, message: str) -> None:
        """Pub/Sub 채널에 메시지를 발행한다."""
        await self._client.publish(channel, message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        """Pub/Sub 채널을 구독한다. 메시지를 비동기 이터레이터로 반환한다.

        사용 후 반드시 break 또는 async for 종료로 구독을 해제해야 한다.
        """
        pubsub: aioredis.client.PubSub = self._client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for raw_message in pubsub.listen():
                if raw_message["type"] == "message":
                    yield raw_message["data"]
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def aclose(self) -> None:
        """Redis 연결을 정리한다. redis-py 5.0+ 규약에 따라 aclose를 사용한다."""
        await self._client.aclose()
        logger.info("CacheGateway Redis 연결 종료 완료")


def get_cache_client(redis_url: str | None = None) -> CacheClient:
    """CacheClient 싱글톤을 반환한다.

    최초 호출 시 redis_url이 필수이다. 이후에는 캐싱된 인스턴스를 반환한다.

    Args:
        redis_url: Redis 접속 URL. 최초 호출 시 필수.

    Returns:
        CacheClient 싱글톤 인스턴스
    """
    global _instance
    if _instance is not None:
        return _instance

    if redis_url is None:
        raise ValueError(
            "최초 호출 시 redis_url이 필수이다. "
            "SecretVault에서 REDIS_URL을 조회하여 전달해야 한다."
        )

    _instance = CacheClient(redis_url)
    return _instance


def reset_cache_client() -> None:
    """테스트용: 싱글톤 인스턴스를 초기화한다."""
    global _instance
    _instance = None
