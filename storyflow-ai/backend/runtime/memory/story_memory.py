from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StoryMemory:
    """Unified 7-dimensional Story Memory.

    Integrates and extends the existing MemoryManager + CharacterMemoryService
    with four additional memory dimensions:
    1. Scene Memory - Scene descriptions, transitions, mood
    2. Visual Memory - Generated image references, style patterns
    3. Style Memory - Overall visual style, color palette, art style
    4. World Memory - Setting details, locations, time period, rules

    These complement the existing:
    - Character Graph (via CharacterMemoryService)
    - Timeline (via MemoryManager CONVERSATION entries)

    All memories are stored via the existing MemoryManager's store_fact()
    method, using tags for categorization.
    """

    # Memory dimension tags
    TAG_SCENE = "story_scene"
    TAG_VISUAL = "story_visual"
    TAG_STYLE = "story_style"
    TAG_WORLD = "story_world"

    def __init__(self, memory_manager=None):
        self._memory = memory_manager

    async def get_context(self, agent_id: str, state: dict) -> str:
        """Query all relevant memory dimensions for the given agent.

        Returns a formatted string for injection into the agent's prompt.
        Now fully async to avoid event loop conflicts.
        """
        parts = []
        # Scene Memory: useful for storyboard, image, video agents
        if agent_id in ("storyboard", "image", "video"):
            scene_ctx = await self._query_memory("story_scene", state)
            if scene_ctx:
                parts.append(f"## Scene Memory\n{scene_ctx}")

        # Visual Memory: useful for image agent
        if agent_id in ("image", "video"):
            visual_ctx = await self._query_memory("story_visual", state)
            if visual_ctx:
                parts.append(f"## Visual Memory\n{visual_ctx}")

        # Style Memory: useful for image, video agents
        if agent_id in ("image", "video"):
            style_ctx = await self._query_memory("story_style", state)
            if style_ctx:
                parts.append(f"## Style Memory\n{style_ctx}")

        # World Memory: useful for script, storyboard agents
        if agent_id in ("script", "storyboard"):
            world_ctx = await self._query_memory("story_world", state)
            if world_ctx:
                parts.append(f"## World Memory\n{world_ctx}")

        # Character memory (delegated to CharacterMemoryService)
        if agent_id in ("character", "storyboard", "image"):
            char_ctx = self._get_character_memory(state)
            if char_ctx:
                parts.append(f"## Character Memory\n{char_ctx}")

        return "\n\n".join(parts)

    async def store_scene(self, scene: dict, conversation_id: str = ""):
        """Store a scene's key information into Scene Memory.

        Extracts: scene description, mood, transition from previous,
        location, time of day, camera angle.
        """
        scene_no = scene.get("scene_no", 0)
        prompt = scene.get("prompt", "")
        characters = scene.get("characters", [])
        mood = scene.get("mood", "")
        camera = scene.get("camera", "")

        text = f"Scene {scene_no}: {prompt[:200]}"
        if mood:
            text += f" | Mood: {mood}"
        if camera:
            text += f" | Camera: {camera}"
        if characters:
            text += f" | Characters: {', '.join(characters)}"

        if self._memory:
            await self._memory.store_fact(
                text=text,
                memory_type=self._mem_type("conversation"),
                entity=f"scene_{scene_no}",
                conversation_id=conversation_id,
                tags=[self.TAG_SCENE, f"scene_{scene_no}"],
                confidence=1.0,
            )

    async def store_visual(
        self, scene_no: int, image_url: str, image_prompt: str,
        style_hints: list[str] | None = None, conversation_id: str = "",
    ):
        """Store a visual reference for scene consistency.

        Records which image was generated for a scene, the prompt used,
        and any detected style hints.
        """
        text = f"Scene {scene_no}: image={image_url}"
        if image_prompt:
            text += f" | Prompt: {image_prompt[:150]}"
        if style_hints:
            text += f" | Style: {', '.join(style_hints)}"

        if self._memory:
            await self._memory.store_fact(
                text=text,
                memory_type=self._mem_type("conversation"),
                entity=f"visual_{scene_no}",
                conversation_id=conversation_id,
                tags=[self.TAG_VISUAL, f"scene_{scene_no}"],
                confidence=1.0,
            )

    async def store_style(
        self, style_info: dict, conversation_id: str = "",
    ):
        """Store the overall visual style of the story.

        Extracts: color palette, art style, lighting, overall mood.
        """
        color = style_info.get("color_palette", "")
        art = style_info.get("art_style", "")
        lighting = style_info.get("lighting", "")
        mood = style_info.get("overall_mood", "")

        parts = ["Story visual style"]
        if color:
            parts.append(f"Color palette: {color}")
        if art:
            parts.append(f"Art style: {art}")
        if lighting:
            parts.append(f"Lighting: {lighting}")
        if mood:
            parts.append(f"Overall mood: {mood}")
        text = ". ".join(parts)

        if self._memory:
            await self._memory.store_fact(
                text=text,
                memory_type=self._mem_type("conversation"),
                entity="visual_style",
                conversation_id=conversation_id,
                tags=[self.TAG_STYLE],
                confidence=1.0,
            )

    async def store_world(
        self, world_info: dict, conversation_id: str = "",
    ):
        """Store world-building details.

        Extracts: setting, time period, locations mentioned,
        world rules, technology level.
        """
        setting = world_info.get("setting", "")
        time_period = world_info.get("time_period", "")
        locations = world_info.get("locations", [])
        rules = world_info.get("world_rules", [])

        parts = ["World details"]
        if setting:
            parts.append(f"Setting: {setting}")
        if time_period:
            parts.append(f"Time period: {time_period}")
        if locations:
            parts.append(f"Locations: {', '.join(locations[:5])}")
        if rules:
            parts.append(f"Rules: {', '.join(rules[:5])}")
        text = ". ".join(parts)

        if self._memory:
            await self._memory.store_fact(
                text=text,
                memory_type=self._mem_type("conversation"),
                entity="world",
                conversation_id=conversation_id,
                tags=[self.TAG_WORLD],
                confidence=1.0,
            )

    async def populate_from_state(self, state: dict, conversation_id: str = ""):
        """Populate all memory dimensions from the current state.

        Call after script and character agents complete to seed memories
        before storyboard generation begins.
        """
        # World memory from script
        outline = state.get("outline", "")
        if outline:
            await self.store_world({"setting": outline[:500]})

        # Scene and character memory from episodes
        episodes = state.get("episodes", [])
        for ep in episodes:
            ep_no = ep.get("episode_no", len(episodes))
            summary = ep.get("summary", "")
            if summary:
                await self.store_world({"setting": summary[:300]})

        # Visual style from characters
        characters = state.get("characters", [])
        style_hints = []
        for c in characters:
            appearance = c.get("appearance", {})
            if isinstance(appearance, dict):
                if appearance.get("cloth", ""):
                    style_hints.append(appearance["cloth"])
                if appearance.get("face", ""):
                    style_hints.append(appearance["face"])
        if style_hints:
            await self.store_style({"art_style": ", ".join(style_hints)})

    async def _query_memory(self, dimension: str, state: dict) -> str:
        """Query memory for a specific dimension. Fully async."""
        if not self._memory:
            return ""
        from runtime.memory.models import MemoryQuery, MemoryType
        # Use the dimension name as a tag and include it in query text for matching
        query = MemoryQuery(
            query=dimension,
            memory_types=[MemoryType.CONVERSATION],
            tags=[dimension],
            limit=10,
            min_confidence=0.3,  # Lower threshold for memory recall
        )
        entries = await self._memory.retrieve(query)

        if not entries:
            return ""
        lines = [f"{dimension} records ({len(entries)}):\n"]
        for e in entries[:5]:
            lines.append(f"- {e.text}")
        return "\n".join(lines)

    def _get_character_memory(self, state: dict) -> str:
        """Get character context from stored character profiles."""
        characters = state.get("characters", [])
        if not characters:
            return ""
        lines = []
        for c in characters:
            name = c.get("name", "")
            appearance = c.get("appearance", {})
            if isinstance(appearance, dict):
                parts = [appearance.get(k, "") for k in ("hair", "face", "body", "cloth")]
                valid = [p for p in parts if p]
                if valid:
                    lines.append(f"{name}: {', '.join(valid)}")
        return "\n".join(lines) if lines else "No character data available."

    @staticmethod
    def _mem_type(t: str):
        from runtime.memory.models import MemoryType
        try:
            return MemoryType(t)
        except ValueError:
            return MemoryType.CONVERSATION

    def get_stats(self) -> dict:
        return {"memory_manager": self._memory.get_stats() if self._memory else {}}
