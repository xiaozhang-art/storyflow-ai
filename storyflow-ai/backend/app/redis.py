"""Async Redis client and task status helpers."""

import json
import redis.asyncio as redis
from configs.settings import settings

redis_client = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=20,
)


async def get_task_status(task_id: str) -> dict | None:
    """Get task progress status from Redis."""
    data = await redis_client.get(f"task:{task_id}")
    if data:
        return json.loads(data)
    return None


async def set_task_status(task_id: str, data: dict, ttl: int = 86400):
    """Set task progress status in Redis with TTL (default 24h)."""
    await redis_client.set(f"task:{task_id}", json.dumps(data, ensure_ascii=False), ex=ttl)
    # Also publish to WebSocket subscribers
    await redis_client.publish(f"task:{task_id}", json.dumps(data, ensure_ascii=False))


async def delete_task_status(task_id: str):
    """Delete task status from Redis."""
    await redis_client.delete(f"task:{task_id}")