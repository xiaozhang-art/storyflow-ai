"""Blackboard - Shared state space for Agent communication.

Agents never call each other directly. Instead:
    - Agents READ from and WRITE to the Blackboard.
    - The Blackboard publishes change events via EventBus.
    - Other Agents subscribe to relevant changes.

This implements the Blackboard Pattern from AI architecture.

Example:
    blackboard.set("scenes.0.status", "image_done")
    blackboard.set("scenes.0.image_url", "/storage/.../scene_001.png")

    Image Agent writes → Blackboard notifies → Voice Agent reads and starts
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from runtime.event_bus import EventBus, EventType, get_event_bus, Event

logger = logging.getLogger(__name__)


class Blackboard:
    """Shared state store with change notification.

    Supports dotted key paths for nested access:
        blackboard.set("scenes.0.status", "done")
        blackboard.get("scenes.0.status")  # → "done"
        blackboard.get("scenes")           # → [{"status": "done", ...}, ...]
    """

    def __init__(self, session_id: str = "", event_bus: EventBus | None = None):
        self._data: dict[str, Any] = {}
        self._session_id = session_id
        self._event_bus = event_bus or get_event_bus()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value by dotted key path.

        Args:
            key: Dotted path like "scenes.0.status" or "characters"
            default: Value to return if key not found
        """
        keys = key.split(".")
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            elif isinstance(value, (list, tuple)):
                try:
                    value = value[int(k)]
                except (ValueError, IndexError):
                    return default
            else:
                return default
            if value is None:
                return default
        return value

    def set(self, key: str, value: Any, notify: bool = True):
        """Set a value by dotted key path.

        Creates intermediate dicts/lists as needed.
        Publishes BLACKBOARD_CHANGED event if notify=True.

        Args:
            key: Dotted path like "scenes.0.status"
            value: Value to set
            notify: Whether to publish change event
        """
        keys = key.split(".")
        data = self._data

        # Navigate to the parent, creating intermediate containers
        for k in keys[:-1]:
            next_key = keys[keys.index(k) + 1] if keys.index(k) + 1 < len(keys) else None
            if k not in data:
                # If next key is numeric, create a list placeholder
                if next_key is not None and next_key.isdigit():
                    data[k] = []
                else:
                    data[k] = {}
            data = data[k]

        old_value = data.get(keys[-1]) if isinstance(data, dict) else None
        if isinstance(data, dict):
            data[keys[-1]] = value
        elif isinstance(data, (list, tuple)):
            idx = int(keys[-1])
            while len(data) <= idx:
                if isinstance(data, list):
                    data.append({})
                else:
                    data = list(data)
                    data.append({})
            data[idx] = value

        if notify and old_value != value:
            self._notify_change(key, value, old_value)

    def _notify_change(self, key: str, new_value: Any, old_value: Any):
        """Publish a change event via EventBus."""
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(self._event_bus.publish_event(
                EventType.BLACKBOARD_CHANGED,
                data={
                    "key": key,
                    "new_value": self._safe_copy(new_value),
                    "old_value": self._safe_copy(old_value),
                },
                session_id=self._session_id,
                source="blackboard",
            ))
        except RuntimeError:
            # No event loop running (e.g., during testing)
            pass

    @staticmethod
    def _safe_copy(value: Any) -> Any:
        """Create a safe copy of a value for event data."""
        try:
            return copy.deepcopy(value)
        except Exception:
            return str(value)

    def get_all(self) -> dict[str, Any]:
        """Get a deep copy of all blackboard data."""
        return copy.deepcopy(self._data)

    def set_all(self, data: dict[str, Any]):
        """Replace all blackboard data."""
        self._data = copy.deepcopy(data)

    def has(self, key: str) -> bool:
        """Check if a key exists."""
        try:
            return self.get(key) is not None
        except Exception:
            return False

    def delete(self, key: str):
        """Delete a key from the blackboard."""
        keys = key.split(".")
        data = self._data
        for k in keys[:-1]:
            if isinstance(data, dict) and k in data:
                data = data[k]
            else:
                return
        if isinstance(data, dict) and keys[-1] in data:
            del data[keys[-1]]

    def keys(self) -> list[str]:
        """Get all top-level keys."""
        return list(self._data.keys())

    def update(self, data: dict[str, Any], notify: bool = True):
        """Merge a dict into the blackboard.

        Unlike set(), this merges at the top level.
        """
        self._data.update(copy.deepcopy(data))
        if notify:
            for key in data:
                self._notify_change(key, data[key], None)

    def get_snapshot(self) -> dict[str, Any]:
        """Get a snapshot suitable for checkpoint/serialization."""
        return {
            "session_id": self._session_id,
            "data": self.get_all(),
        }

    def load_snapshot(self, snapshot: dict[str, Any]):
        """Restore from a checkpoint snapshot."""
        self._session_id = snapshot.get("session_id", self._session_id)
        self._data = snapshot.get("data", {})

    def __repr__(self):
        top_keys = list(self._data.keys())
        return f"Blackboard(session={self._session_id}, keys={top_keys})"