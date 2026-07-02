"""Async Redis client and task status helpers.

Falls back to an in-memory store when Redis is unavailable (local dev without Docker).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as redis
from configs.settings import settings

logger = logging.getLogger(__name__)


class InMemoryTaskStore:
    """Minimal Redis-compatible store for task progress and pub/sub."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._channels: dict[str, list[asyncio.Queue[str]]] = {}

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def publish(self, channel: str, message: str) -> None:
        for queue in self._channels.get(channel, []):
            await queue.put(message)

    def pubsub(self) -> "InMemoryPubSub":
        return InMemoryPubSub(self)


class InMemoryPubSub:
    def __init__(self, store: InMemoryTaskStore):
        self._store = store
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._channels: set[str] = set()

    async def subscribe(self, channel: str) -> None:
        self._channels.add(channel)
        self._store._channels.setdefault(channel, []).append(self._queue)

    async def unsubscribe(self, channel: str) -> None:
        self._channels.discard(channel)
        queues = self._store._channels.get(channel, [])
        if self._queue in queues:
            queues.remove(self._queue)

    async def aclose(self) -> None:
        for channel in list(self._channels):
            await self.unsubscribe(channel)

    async def listen(self):
        while True:
            message = await self._queue.get()
            yield {"type": "message", "data": message}


def _create_redis_client() -> Any:
    if settings.REDIS_URL.startswith("memory://"):
        logger.info("Using in-memory task store (REDIS_URL=memory://)")
        return InMemoryTaskStore()
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=20,
    )


redis_client = _create_redis_client()


async def get_task_status(task_id: str) -> dict | None:
    """Get task progress status from Redis."""
    data = await redis_client.get(f"task:{task_id}")
    if data:
        return json.loads(data)
    return None


async def set_task_status(task_id: str, data: dict, ttl: int = 86400):
    """Set task progress status in Redis with TTL (default 24h)."""
    payload = json.dumps(data, ensure_ascii=False)
    await redis_client.set(f"task:{task_id}", payload, ex=ttl)
    await redis_client.publish(f"task:{task_id}", payload)


async def delete_task_status(task_id: str):
    """Delete task status from Redis."""
    await redis_client.delete(f"task:{task_id}")
