"""Timeline Memory - Ordered event/progression history."""

import logging
import time
from typing import Any

from runtime.memory.base import BaseMemory

logger = logging.getLogger(__name__)


class TimelineMemory(BaseMemory):
    """Stores ordered timeline of pipeline events.

    Used to give agents context about what has already happened
    in the story generation process.
    """

    name = "timeline"

    def __init__(self):
        self._events: list[dict[str, Any]] = []

    # ── BaseMemory interface (minimal — timeline is list-based) ──

    def get(self, key: str, default: Any = None) -> Any:
        if key == "events":
            return list(self._events)
        if key == "count":
            return len(self._events)
        return default

    def set(self, key: str, value: Any) -> None:
        if key == "events":
            self._events = list(value)

    def delete(self, key: str) -> None:
        pass  # No-op for timeline

    def to_dict(self) -> dict:
        return {"events": list(self._events)}

    def clear(self) -> None:
        self._events.clear()

    # ── Timeline-specific API ──

    def add_event(self, event: dict) -> None:
        """Append an event with auto-timestamp."""
        entry = dict(event)
        entry.setdefault("timestamp", time.time())
        self._events.append(entry)

    def get_recent(self, n: int = 5) -> list[dict]:
        """Get the last N events."""
        return list(self._events[-n:])

    def get_by_step(self, step_name: str) -> list[dict]:
        """Filter events by pipeline step."""
        return [e for e in self._events if e.get("step") == step_name]

    def count(self) -> int:
        return len(self._events)

    def get_chapter_summaries(self) -> list[str]:
        """Get summaries of all timeline events."""
        return [
            e.get("summary", f"{e.get('step', '?')}: (no summary)")
            for e in self._events
        ]