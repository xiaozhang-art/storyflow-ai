"""EventBus — 轻量 Python 本地事件总线.

替代 A2A MessageBus 的分布式复杂度。
同一 Runtime 进程内，同步/异步事件分发。
以后需要分布式，替换为 Redis PubSub 即可。
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Type alias
EventHandler = Callable[..., Coroutine[Any, Any, None]] | Callable[..., None]


@dataclass
class Event:
    """事件对象."""
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str = ""              # 触发源 (agent name, "system", "quality_engine", etc.)
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            import time
            self.timestamp = time.time()


class EventBus:
    """本地事件总线.

    用法:
        bus = EventBus()
        bus.on("agent.complete", my_handler)
        await bus.emit(Event(type="agent.complete", data={"agent": "script"}))
    """

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []
        self._event_log: list[Event] = []  # Keep last N events for debugging
        self._max_log = 1000

    def on(self, event_type: str, handler: EventHandler) -> None:
        """注册事件处理器."""
        self._handlers[event_type].append(handler)
        logger.debug("[EventBus] Registered handler for '%s': %s", event_type, handler.__name__)

    def on_any(self, handler: EventHandler) -> None:
        """注册全局处理器 — 所有事件都会触发."""
        self._global_handlers.append(handler)

    def off(self, event_type: str, handler: EventHandler) -> None:
        """移除事件处理器."""
        if handler in self._handlers.get(event_type, []):
            self._handlers[event_type].remove(handler)

    async def emit(self, event: Event) -> list[Any]:
        """发射事件，返回所有处理器的结果."""
        handlers = self._handlers.get(event.type, []) + self._global_handlers

        if not handlers:
            self._log_event(event)
            return []

        results = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(event)
                else:
                    result = handler(event)
                results.append(result)
            except Exception as e:
                logger.error("[EventBus] Handler error on '%s': %s", event.type, e)

        self._log_event(event)
        return results

    def emit_sync(self, event: Event) -> list[Any]:
        """同步发射（用于非 async 上下文）."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in async context — create a task
            asyncio.ensure_future(self.emit(event))
            return []

        # No event loop — run synchronously
        handlers = self._handlers.get(event.type, []) + self._global_handlers
        results = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    logger.warning("[EventBus] Async handler in sync emit: %s", handler.__name__)
                else:
                    results.append(handler(event))
            except Exception as e:
                logger.error("[EventBus] Handler error: %s", e)

        self._log_event(event)
        return results

    def get_recent_events(self, event_type: str | None = None, limit: int = 50) -> list[Event]:
        """获取最近的事件日志."""
        events = self._event_log
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

    def clear_log(self):
        self._event_log.clear()

    def _log_event(self, event: Event):
        self._event_log.append(event)
        if len(self._event_log) > self._max_log:
            self._event_log = self._event_log[-self._max_log:]


# Global singleton
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus():
    """Reset the global bus (for testing)."""
    global _event_bus
    _event_bus = EventBus()