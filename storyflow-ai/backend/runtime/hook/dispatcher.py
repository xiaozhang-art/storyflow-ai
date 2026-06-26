"""Hook Dispatcher - Central event dispatcher for the Agent OS."""
from __future__ import annotations
import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Awaitable
from runtime.hook.events import ALL_HOOK_EVENTS

logger = logging.getLogger(__name__)

HookHandler = Callable[..., Awaitable[None]]


class HookEvent:
    """Event object passed to hook handlers."""
    __slots__ = ("name", "trace_id", "session_id", "conversation_id", "agent_id", "payload", "timestamp")
    
    def __init__(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        trace_id: str = "",
        session_id: str = "",
        conversation_id: str = "",
        agent_id: str = "",
    ):
        self.name = name
        self.payload = payload or {}
        self.trace_id = trace_id
        self.session_id = session_id
        self.conversation_id = conversation_id
        self.agent_id = agent_id
        self.timestamp = int(time.time() * 1000)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.name,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class HookDispatcher:
    """Central hook event dispatcher.
    
    Hook execution must NOT block the Agent Runtime main flow.
    All handlers run as fire-and-forget asyncio tasks.
    """
    
    def __init__(self):
        self._registry: dict[str, list[HookHandler]] = defaultdict(list)
        self._global_handlers: list[HookHandler] = []
    
    def register(self, event_name: str, handler: HookHandler):
        """Register a handler for a specific event."""
        if event_name not in ALL_HOOK_EVENTS:
            logger.warning("Registering handler for non-standard event: %s", event_name)
        self._registry[event_name].append(handler)
        logger.debug("Hook registered: %s -> %s", event_name, handler.__qualname__)
    
    def register_global(self, handler: HookHandler):
        """Register a handler that fires on ALL events."""
        self._global_handlers.append(handler)
    
    def unregister(self, event_name: str, handler: HookHandler):
        if handler in self._registry.get(event_name, []):
            self._registry[event_name].remove(handler)
    
    async def emit(self, event: HookEvent):
        """Emit an event to all registered handlers (non-blocking)."""
        handlers = list(self._registry.get(event.name, []))
        all_handlers = self._global_handlers + handlers
        
        if not all_handlers:
            return
        
        # Fire all handlers concurrently, non-blocking
        tasks = []
        for handler in all_handlers:
            tasks.append(asyncio.create_task(self._safe_handle(handler, event)))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def emit_sync(self, event: HookEvent):
        """Emit an event and wait for all handlers to complete (blocking)."""
        handlers = list(self._registry.get(event.name, []))
        all_handlers = self._global_handlers + handlers
        
        for handler in all_handlers:
            await self._safe_handle(handler, event)
    
    async def _safe_handle(self, handler: HookHandler, event: HookEvent):
        """Execute a handler with error protection."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                "Hook handler error [event=%s, handler=%s]: %s",
                event.name, handler.__qualname__, e,
            )


# Singleton-like global dispatcher
_global_dispatcher: HookDispatcher | None = None


def get_hook_dispatcher() -> HookDispatcher:
    global _global_dispatcher
    if _global_dispatcher is None:
        _global_dispatcher = HookDispatcher()
    return _global_dispatcher