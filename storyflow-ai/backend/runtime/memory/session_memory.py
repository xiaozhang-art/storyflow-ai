"""Session Memory - Current execution context for a pipeline run."""

import logging
from typing import Any

from runtime.memory.base import BaseMemory

logger = logging.getLogger(__name__)


class SessionMemory(BaseMemory):
    """Stores current execution context: active step, attempt, state snapshot.

    This is the most ephemeral layer — reset on each session.
    """

    name = "session"

    def __init__(self):
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def to_dict(self) -> dict:
        return dict(self._data)

    def clear(self) -> None:
        self._data.clear()

    # ── Convenience accessors ──

    @property
    def step_name(self) -> str:
        return self._data.get("step_name", "")

    @step_name.setter
    def step_name(self, value: str):
        self._data["step_name"] = value

    @property
    def attempt(self) -> int:
        return self._data.get("attempt", 0)

    @attempt.setter
    def attempt(self, value: int):
        self._data["attempt"] = value