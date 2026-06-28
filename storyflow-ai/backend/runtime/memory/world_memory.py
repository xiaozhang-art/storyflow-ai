"""World Memory - World-building information (era, location, rules, atmosphere)."""

import logging
from typing import Any

from runtime.memory.base import BaseMemory

logger = logging.getLogger(__name__)


class WorldMemory(BaseMemory):
    """Stores world settings that affect all agents.

    Provides structured access to common world-building fields
    and a formatted summary for prompting.
    """

    name = "world"

    # Known top-level keys with defaults
    _SCHEMA = {
        "era": "",
        "location": "",
        "genre": "",
        "tone": "",
        "atmosphere": "",
        "rules": [],
        "original_prompt": "",
    }

    def __init__(self):
        self._data: dict[str, Any] = {}

    # ── BaseMemory interface ──

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

    # ── World-specific API ──

    def add_rule(self, rule: str) -> None:
        """Append a world-specific rule."""
        rules = self._data.setdefault("rules", [])
        if rule not in rules:
            rules.append(rule)

    def get_setting_summary(self) -> str:
        """Return a formatted paragraph of world settings for prompting."""
        parts = []
        if self._data.get("era"):
            parts.append(f"Time period: {self._data['era']}")
        if self._data.get("genre"):
            parts.append(f"Genre: {self._data['genre']}")
        if self._data.get("tone"):
            parts.append(f"Tone: {self._data['tone']}")
        if self._data.get("location"):
            parts.append(f"Setting: {self._data['location']}")
        if self._data.get("atmosphere"):
            parts.append(f"Atmosphere: {self._data['atmosphere']}")
        rules = self._data.get("rules", [])
        if rules:
            parts.append("World rules: " + "; ".join(rules))
        return ". ".join(parts)