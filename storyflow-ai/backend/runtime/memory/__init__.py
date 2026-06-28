"""Memory Runtime - Four-layer memory system for AI agents.

Layers:
    SessionMemory   - Current execution context (step, attempt, state)
    CharacterMemory - Per-character structured data (appearance, voice, personality)
    WorldMemory     - World settings (era, location, rules, atmosphere)
    TimelineMemory  - Ordered event/progression history

All agents receive: prompt + memory context (instead of just prompt).

Usage:
    memory = MemoryRuntime(session_id="abc123")
    memory.character.upsert_character("林晓", {
        "name": "林晓", "gender": "女",
        "appearance": {"hair": "long black", "body": "slender", ...}
    })
    memory.world.set("era", "ancient China")

    # Build context for any agent
    context = memory.build_context("image")
    # → Returns formatted string with relevant character appearances, world info
"""

import logging
from typing import Any

from runtime.memory.base import BaseMemory
from runtime.memory.session_memory import SessionMemory
from runtime.memory.character_memory import CharacterMemory
from runtime.memory.world_memory import WorldMemory
from runtime.memory.timeline_memory import TimelineMemory

logger = logging.getLogger(__name__)


class MemoryRuntime:
    """Four-layer memory system.

    Provides shared, structured context to all agents so that
    character consistency, world coherence, and progression
    awareness are maintained across the pipeline.

    Layers:
        session   — Ephemeral per-run state (step, attempt)
        character — Persistent character data (appearance, voice, personality)
        world     — World-building settings (era, genre, rules)
        timeline  — Chronological event history
    """

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.session: SessionMemory = SessionMemory()
        self.character: CharacterMemory = CharacterMemory()
        self.world: WorldMemory = WorldMemory()
        self.timeline: TimelineMemory = TimelineMemory()

    # ── Build context for agents ──

    def build_context(self, agent_name: str, state: dict | None = None) -> str:
        """Build a memory context string for an agent prompt.

        Different agents need different memory slices:
        - script:       world settings + timeline
        - character:    world settings + existing characters
        - storyboard:   ALL (characters, world, timeline)
        - image:        character appearances (formatted for image gen)
        - image_to_video: minimal (just scene count)
        - voice:        character voice/gender mapping
        - video:        minimal (just timeline)

        Returns a formatted string that can be appended to any prompt.
        """
        parts: list[str] = []
        state = state or {}

        # All agents get world context
        world_summary = self.world.get_setting_summary()
        if world_summary:
            parts.append(f"[World Settings]\n{world_summary}")

        # Character context — varies by agent
        if agent_name in ("script", "character", "storyboard"):
            chars = self.character.get_all_characters()
            if chars:
                char_lines = []
                for name, data in chars.items():
                    personality = data.get("personality", "")
                    desc = f"- {name} ({data.get('gender', 'unknown')})"
                    if personality:
                        desc += f": {personality}"
                    char_lines.append(desc)
                parts.append("[Characters]\n" + "\n".join(char_lines))

        if agent_name == "image":
            chars = self.character.get_all_characters()
            if chars:
                appearances = []
                for name, data in chars.items():
                    prompt = self.character.get_appearance_prompt(name)
                    if prompt:
                        appearances.append(f"{name}: {prompt}")
                if appearances:
                    parts.append(
                        "[Character Appearances (for image generation)]\n"
                        + "\n".join(appearances)
                    )

        if agent_name == "voice":
            chars = self.character.get_all_characters()
            if chars:
                voice_lines = [
                    f"{name}: {data.get('gender', 'unknown')}"
                    for name, data in chars.items()
                ]
                parts.append("[Voice Mapping]\n" + "\n".join(voice_lines))

        # Timeline context
        if agent_name in ("script", "storyboard"):
            recent = self.timeline.get_recent(5)
            if recent:
                lines = [
                    f"- {e.get('step', '?')}: {e.get('summary', '')}"
                    for e in recent
                ]
                parts.append("[Recent Timeline]\n" + "\n".join(lines))

        return "\n\n".join(parts)

    # ── Auto-populate from pipeline state ──

    def populate_from_state(self, state: dict) -> None:
        """Auto-populate memory layers from pipeline state.

        Call after each step to keep memory in sync with the pipeline.
        """
        # Characters
        characters = state.get("characters", [])
        if characters:
            for char in characters:
                self.character.upsert_character(char.get("name", ""), char)

        # World
        if state.get("genre"):
            self.world.set("genre", state["genre"])
        if state.get("prompt"):
            self.world.set("original_prompt", state["prompt"])

        # Storyboard → timeline
        storyboard = state.get("storyboard", [])
        for scene in storyboard:
            self.timeline.add_event({
                "step": "storyboard",
                "scene_no": scene.get("scene_no"),
                "summary": f"Scene {scene.get('scene_no')}: "
                           f"{scene.get('dialogue', '')[:50]}",
            })

    # ── Serialization ──

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "session": self.session.to_dict(),
            "character": self.character.to_dict(),
            "world": self.world.to_dict(),
            "timeline": self.timeline.to_dict(),
        }

    def clear(self) -> None:
        self.session.clear()
        self.character.clear()
        self.world.clear()
        self.timeline.clear()

    def get_stats(self) -> dict:
        return {
            "characters": len(self.character.get_character_names()),
            "world_keys": len(self.world.to_dict()),
            "timeline_events": self.timeline.count(),
        }


# Global singleton
_memory_runtime: MemoryRuntime | None = None


def get_memory_runtime() -> MemoryRuntime:
    """Get the global MemoryRuntime instance."""
    global _memory_runtime
    if _memory_runtime is None:
        _memory_runtime = MemoryRuntime()
    return _memory_runtime