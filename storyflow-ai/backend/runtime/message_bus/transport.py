"""Transport layer for A2A Message Bus - In-memory and Redis Stream implementations."""
from __future__ import annotations
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable
from collections import deque
from runtime.mcp.envelope import MCPEnvelope

logger = logging.getLogger(__name__)

MessageHandler = Callable[[MCPEnvelope], Awaitable[MCPEnvelope]]


class BaseTransport(ABC):
    """Abstract base class for message transport."""
    
    @abstractmethod
    async def send(self, agent_id: str, envelope: MCPEnvelope):
        """Send an envelope to an agent's inbox."""
        ...
    
    @abstractmethod
    async def receive(self, agent_id: str, timeout: float = 30.0) -> MCPEnvelope | None:
        """Receive an envelope from an agent's inbox."""
        ...
    
    @abstractmethod
    async def register_handler(self, agent_id: str, handler: MessageHandler):
        """Register a message handler for an agent."""
        ...


class InMemoryTransport(BaseTransport):
    """In-memory transport for development and testing.
    
    Uses asyncio queues per agent for message passing.
    """
    
    def __init__(self):
        self._inboxes: dict[str, asyncio.Queue] = {}
        self._handlers: dict[str, list[MessageHandler]] = {}
    
    def _get_inbox(self, agent_id: str) -> asyncio.Queue:
        if agent_id not in self._inboxes:
            self._inboxes[agent_id] = asyncio.Queue()
        return self._inboxes[agent_id]
    
    async def send(self, agent_id: str, envelope: MCPEnvelope):
        inbox = self._get_inbox(agent_id)
        await inbox.put(envelope)
        logger.debug("Message sent to %s: %s", agent_id, envelope.id)
    
    async def receive(self, agent_id: str, timeout: float = 30.0) -> MCPEnvelope | None:
        inbox = self._get_inbox(agent_id)
        try:
            return await asyncio.wait_for(inbox.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    
    async def register_handler(self, agent_id: str, handler: MessageHandler):
        self._handlers.setdefault(agent_id, []).append(handler)
    
    async def process_inbox(self, agent_id: str):
        """Process all messages in an agent's inbox."""
        handlers = self._handlers.get(agent_id, [])
        if not handlers:
            return
        
        inbox = self._get_inbox(agent_id)
        while not inbox.empty():
            envelope = await inbox.get()
            for handler in handlers:
                try:
                    await handler(envelope)
                except Exception as e:
                    logger.error("Handler error for %s: %s", agent_id, e)


class RedisStreamTransport(BaseTransport):
    """Redis Stream-based transport for production use.
    
    Uses Redis Streams (XADD/XREADGROUP) for reliable message delivery.
    Each agent has its own stream: agent:{agent_id}:inbox
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._handlers: dict[str, list[MessageHandler]] = {}
    
    async def send(self, agent_id: str, envelope: MCPEnvelope):
        if not self.redis:
            logger.warning("Redis not connected, dropping message to %s", agent_id)
            return
        
        stream_key = f"agent:{agent_id}:inbox"
        data = envelope.model_dump_json()
        await self.redis.xadd(stream_key, {"envelope": data})
        logger.debug("Message sent to %s via Redis Stream: %s", agent_id, envelope.id)
    
    async def receive(self, agent_id: str, timeout: float = 30.0) -> MCPEnvelope | None:
        if not self.redis:
            return None
        
        stream_key = f"agent:{agent_id}:inbox"
        try:
            result = await self.redis.xread(
                {stream_key: "0-0"},
                count=1,
                block=int(timeout * 1000),
            )
            if result:
                for stream_name, messages in result:
                    for msg_id, fields in messages:
                        envelope_data = fields.get(b"envelope", fields.get("envelope", ""))
                        if isinstance(envelope_data, bytes):
                            envelope_data = envelope_data.decode("utf-8")
                        return MCPEnvelope.model_validate_json(envelope_data)
        except Exception as e:
            logger.error("Redis receive error for %s: %s", agent_id, e)
        return None
    
    async def register_handler(self, agent_id: str, handler: MessageHandler):
        self._handlers.setdefault(agent_id, []).append(handler)
    
    async def start_consumer(self, agent_id: str, group: str = "storyflow"):
        """Start a consumer group for an agent's inbox stream."""
        if not self.redis:
            return
        
        stream_key = f"agent:{agent_id}:inbox"
        try:
            await self.redis.xgroup_create(stream_key, group, id="0", mkstream=True)
        except Exception:
            pass  # Group may already exist
        
        logger.info("Consumer group '%s' started for %s", group, agent_id)