"""Character Memory - Per-character structured data (appearance, voice, personality).

All agents share this layer so character consistency is maintained
across the entire pipeline.
"""

import copy
import logging
from typing import Any

from runtime.memory.base import BaseMemory

logger = logging.getLogger(__name__)


class CharacterMemory(BaseMemory):
    """Stores per-character structured data keyed by character name.

    Supports deep merge on upsert so incremental updates don't
    overwrite existing fields.
    """

    name = "character"

    def __init__(self):
        self._characters: dict[str, dict] = {}

    # ── BaseMemory interface ──

    def get(self, key: str, default: Any = None) -> Any:
        return self._characters.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._characters[key] = value

    def delete(self, key: str) -> None:
        self._characters.pop(key, None)

    def to_dict(self) -> dict:
        return dict(self._characters)

    def clear(self) -> None:
        self._characters.clear()

    # ── Character-specific API ──

    def upsert_character(self, name: str, data: dict) -> None:
        """Insert or deep-merge character data."""
        if not name:
            return
        if name in self._characters:
            self._characters[name] = _deep_merge(self._characters[name], data)
        else:
            self._characters[name] = copy.deepcopy(data)

    def get_character(self, name: str) -> dict | None:
        return self._characters.get(name)

    def get_all_characters(self) -> dict[str, dict]:
        return dict(self._characters)

    def get_character_names(self) -> list[str]:
        return list(self._characters.keys())

    def update_character_field(self, name: str, field_path: str, value: Any) -> None:
        """Update a nested field like 'appearance.hair'."""
        char = self._characters.get(name)
        if not char:
            self._characters[name] = {}
            char = self._characters[name]

        parts = field_path.split(".")
        obj = char
        for part in parts[:-1]:
            if part not in obj or not isinstance(obj[part], dict):
                obj[part] = {}
            obj = obj[part]
        obj[parts[-1]] = value

    def get_appearance_prompt(self, name: str) -> str:
        """Return a formatted English appearance string for image generation.

        Combines hair + body + cloth + face from the appearance dict.
        """
        char = self._characters.get(name)
        if not char:
            return ""

        appearance = char.get("appearance", {})
        if isinstance(appearance, str):
            return appearance

        parts = []
        for dim in ("hair", "face", "body", "cloth"):
            val = appearance.get(dim, "")
            if val:
                parts.append(str(val))
        return ", ".join(parts)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (base is mutated)."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result