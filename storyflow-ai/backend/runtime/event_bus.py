"""Event Bus - Decoupled async pub/sub for Runtime event-driven communication.

Agents and Runtime components communicate by publishing/subscribing to events,
never by calling each other directly.

Events:
    - StepStarted(step, session_id)
    - StepCompleted(step, session_id, result)
    - StepFailed(step, session_id, error)
    - ArtifactSaved(artifact_type, path, session_id)
    - BlackboardChanged(key, value, session_id)
    - QualityCheck(artifact_type, result, session_id)
    - DirectorDecision(decision, reason, session_id)
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """All event types in the StoryFlow Runtime."""
    # Lifecycle events
    SESSION_CREATED = "session.created"
    SESSION_COMPLETED = "session.completed"
    SESSION_FAILED = "session.failed"

    # Step events
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_RETRY = "step.retry"

    # Artifact events
    ARTIFACT_SAVED = "artifact.saved"
    ARTIFACT_LOADED = "artifact.loaded"

    # Blackboard events
    BLACKBOARD_CHANGED = "blackboard.changed"

    # Quality events
    QUALITY_CHECK = "quality.check"
    QUALITY_PASS = "quality.pass"
    QUALITY_FAIL = "quality.fail"

    # Director events
    DIRECTOR_DECISION = "director.decision"
    DIRECTOR_INTERVENE = "director.intervene"

    # Planner events
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"


@dataclass
class Event:
    """An event in the StoryFlow Runtime."""
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    source: str = ""  # Which component published this event

    def __repr__(self):
        return f"Event({self.type.value}, session={self.session_id}, src={self.source})"


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Async event bus for decoupled component communication.

    Components subscribe to event types and get notified when events are published.
    All handlers run asynchronously and concurrently.
    """

    def __init__(self):
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = 1000
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType, handler: EventHandler):
        """Subscribe a handler to an event type."""
        self._handlers[event_type].append(handler)
        logger.debug("EventBus: %s subscribed to %s", handler.__qualname__, event_type.value)

    def unsubscribe(self, event_type: EventType, handler: EventHandler):
        """Unsubscribe a handler from an event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Event):
        """Publish an event to all subscribed handlers.

        Handlers run concurrently. Errors in individual handlers are logged
        but do not affect other handlers or the publisher.
        """
        event.timestamp = time.time()
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        handlers = self._handlers.get(event.type, [])
        if not handlers:
            logger.debug("EventBus: %s published (no handlers)", event)
            return

        logger.info("EventBus: %s → %d handlers", event, len(handlers))
        tasks = []
        for handler in handlers:
            tasks.append(self._safe_call(handler, event))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def publish_event(self, event_type: EventType, data: dict = None,
                            session_id: str = "", source: str = ""):
        """Convenience method to publish an event by type and data."""
        event = Event(
            type=event_type,
            data=data or {},
            session_id=session_id,
            source=source,
        )
        await self.publish(event)

    async def _safe_call(self, handler: EventHandler, event: Event):
        """Call a handler safely, catching and logging errors."""
        try:
            await handler(event)
        except Exception as e:
            logger.error("EventBus handler %s failed for %s: %s",
                         handler.__qualname__, event, e, exc_info=True)

    def get_history(self, event_type: EventType = None,
                    session_id: str = None, limit: int = 100) -> list[Event]:
        """Get event history, optionally filtered by type and session."""
        events = self._history
        if event_type:
            events = [e for e in events if e.type == event_type]
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        return events[-limit:]

    def clear_history(self):
        """Clear event history."""
        self._history.clear()

    def get_handler_count(self, event_type: EventType) -> int:
        """Get the number of handlers subscribed to an event type."""
        return len(self._handlers.get(event_type, []))


# Global singleton (created lazily)
_global_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global EventBus instance."""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus