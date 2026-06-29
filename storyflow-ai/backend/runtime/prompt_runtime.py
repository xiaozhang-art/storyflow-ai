"""Prompt Runtime - Dynamic prompt construction from multiple information sources.

Instead of fixed prompts, PromptRuntime assembles prompts from:
    Template (base prompt for the agent)
    + Character Memory (character appearance/state)
    + World Memory (world settings)
    + Timeline (story progression)
    + Reflection Suggestions (from ReflectionRuntime)
    + Director Instructions (from DirectorRuntime)
    + Previous Step Context (from Blackboard)

This makes prompts increasingly long and accurate as the pipeline progresses.

Usage:
    prompt_runtime = PromptRuntime(memory, reflection, director)
    final_prompt = await prompt_runtime.build_prompt(
        agent_name="image",
        base_prompt=scene_prompt,
        state=blackboard_state,
        session_id="abc123",
    )
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Per-agent prompt templates that define HOW memory gets injected
AGENT_TEMPLATES = {
    "script": {
        "prefix": "",
        "memory_order": ["world", "timeline"],
        "suffix": (
            "\n\n[Output Requirements]\n"
            "Return a JSON object with: outline, characters, episodes.\n"
            "Each character needs: name, gender, age, appearance (hair/face/body/cloth), personality.\n"
            "Each episode needs: episode_no, title, summary, script, characters."
        ),
    },
    "character": {
        "prefix": (
            "\n[Task]\n"
            "Enrich the visual description of each character. "
            "Every character MUST have complete appearance details in ALL four dimensions."
        ),
        "memory_order": ["world", "existing_characters"],
        "suffix": (
            "\n\n[Critical Rules]\n"
            "1. Every character MUST have appearance.hair, appearance.face, appearance.body, appearance.cloth\n"
            "2. Be specific: 'long black hair' not just 'black hair'\n"
            "3. Include clothing style, color, and accessories\n"
            "4. Return JSON with characters array, each having full appearance dict"
        ),
    },
    "storyboard": {
        "prefix": (
            "\n[Task]\n"
            "Convert the script into detailed scene-by-scene storyboard prompts. "
            "Each scene prompt will be used directly for image generation."
        ),
        "memory_order": ["world", "character_appearances", "reflections", "timeline"],
        "suffix": (
            "\n\n[Scene Prompt Rules]\n"
            "1. Each scene prompt MUST include character appearance details (hair, cloth, etc.)\n"
            "2. Include environment, lighting, mood, camera angle\n"
            "3. Reference specific character names from the character list\n"
            "4. Each scene: 3-15 seconds, with dialogue if applicable\n"
            "5. Keep prompts in English for best image generation quality"
        ),
    },
    "image": {
        "prefix": "",
        "memory_order": ["character_appearances", "world", "reflections"],
        "suffix": "",
    },
    "image_to_video": {
        "prefix": "",
        "memory_order": [],
        "suffix": "",
    },
    "voice": {
        "prefix": "",
        "memory_order": ["voice_mapping"],
        "suffix": "",
    },
    "video": {
        "prefix": "",
        "memory_order": [],
        "suffix": "",
    },
}


class PromptRuntime:
    """Dynamically constructs agent prompts by combining multiple sources.

    The PromptRuntime sits between Memory/Reflection/Director and the Agents.
    It takes a base prompt and enriches it with all available context,
    producing a final prompt that is more detailed and accurate.

    Integration points:
    - Called by WorkflowEngine before each agent execution
    - Reads from MemoryRuntime (character, world, timeline)
    - Reads from ReflectionRuntime (suggestions from previous steps)
    - Reads from DirectorRuntime (instructions)
    - Writes to Blackboard (the enriched prompt)
    """

    def __init__(
        self,
        memory: Any = None,
        reflection: Any = None,
        event_bus: Any = None,
    ):
        self.memory = memory
        self.reflection = reflection
        self._custom_templates: dict[str, str] = {}
        self._director_instructions: dict[str, str] = {}

        self._stats = {
            "prompts_built": 0,
            "by_agent": {},
        }

    def register_template(self, agent_name: str, template: str) -> None:
        """Register a custom base template for an agent."""
        self._custom_templates[agent_name] = template

    def set_director_instruction(
        self, agent_name: str, instruction: str
    ) -> None:
        """Set a Director instruction for a specific agent/step."""
        self._director_instructions[agent_name] = instruction

    def clear_director_instructions(self) -> None:
        self._director_instructions.clear()

    async def build_prompt(
        self,
        agent_name: str,
        base_prompt: str,
        state: dict,
        session_id: str = "",
    ) -> str:
        """Build a dynamically enriched prompt for an agent.

        Args:
            agent_name: The agent/step name
            base_prompt: The original prompt from the agent's template
            state: Current pipeline state
            session_id: Session ID for reflection lookup

        Returns:
            Enriched prompt string
        """
        template_config = AGENT_TEMPLATES.get(agent_name, {})
        parts = []

        # 1. Prefix (task description)
        prefix = template_config.get("prefix", "")
        if prefix:
            parts.append(prefix)

        # 2. Memory sections (ordered per agent)
        memory_order = template_config.get("memory_order", [])
        for section_name in memory_order:
            section = self._build_memory_section(
                section_name, state, session_id
            )
            if section:
                parts.append(section)

        # 3. Director instructions (if any)
        director_inst = self._director_instructions.get(agent_name, "")
        if director_inst:
            parts.append(f"[Director Instructions]\n{director_inst}")

        # 4. The base prompt itself
        if base_prompt:
            parts.append(base_prompt)

        # 5. Suffix (output requirements, rules)
        suffix = template_config.get("suffix", "")
        if suffix:
            parts.append(suffix)

        final_prompt = "\n\n".join(parts)

        # Track stats
        self._stats["prompts_built"] += 1
        self._stats["by_agent"][agent_name] = (
            self._stats["by_agent"].get(agent_name, 0) + 1
        )

        logger.debug(
            "[PromptRuntime] Built prompt for '%s': %d chars (%d sections)",
            agent_name, len(final_prompt), len(parts),
        )

        return final_prompt

    def get_stats(self) -> dict:
        return dict(self._stats)

    # ── Memory section builders ──

    def _build_memory_section(
        self, section_name: str, state: dict, session_id: str
    ) -> str:
        """Build a specific memory section for prompt injection."""

        if section_name == "world" and self.memory:
            summary = self.memory.world.get_setting_summary()
            if summary:
                return f"[World Settings]\n{summary}"

        elif section_name == "character_appearances" and self.memory:
            chars = self.memory.character.get_all_characters()
            if chars:
                lines = ["[Character Appearances (MUST include in image prompts)]"]
                for name, data in chars.items():
                    prompt = self.memory.character.get_appearance_prompt(name)
                    if prompt:
                        lines.append(f"{name}: {prompt}")
                return "\n".join(lines)

        elif section_name == "existing_characters" and self.memory:
            chars = self.memory.character.get_all_characters()
            if chars:
                lines = ["[Existing Characters]"]
                for name, data in chars.items():
                    personality = data.get("personality", "")
                    desc = f"- {name} ({data.get('gender', 'unknown')})"
                    if personality:
                        desc += f": {personality}"
                    lines.append(desc)
                return "\n".join(lines)

        elif section_name == "voice_mapping" and self.memory:
            chars = self.memory.character.get_all_characters()
            if chars:
                lines = ["[Voice Mapping]"]
                for name, data in chars.items():
                    lines.append(f"{name}: {data.get('gender', 'unknown')}")
                return "\n".join(lines)

        elif section_name == "timeline" and self.memory:
            recent = self.memory.timeline.get_recent(5)
            if recent:
                lines = ["[Story Timeline (recent events)]"]
                for e in recent:
                    lines.append(
                        f"- {e.get('step', '?')}: {e.get('summary', '')}"
                    )
                return "\n".join(lines)

        elif section_name == "reflections" and self.reflection and session_id:
            context = self.reflection.get_accumulated_context(session_id)
            if context:
                return context

        return ""

    def build_image_prompt(
        self,
        scene_prompt: str,
        character_names: list[str],
        state: dict,
        session_id: str = "",
    ) -> str:
        """Specialized prompt builder for image generation.

        Combines scene prompt with character appearance details.
        This is the key function that prevents character inconsistency.
        """
        parts = []

        # Character appearances
        if self.memory and character_names:
            char_parts = []
            for name in character_names:
                appearance = self.memory.character.get_appearance_prompt(name)
                if appearance:
                    char_parts.append(f"{name}: {appearance}")
            if char_parts:
                parts.append(
                    "[Character Appearance Constraints]\n"
                    + "\n".join(char_parts)
                )

        # Reflection suggestions for image step
        if self.reflection and session_id:
            ref = self.reflection.get_reflection(session_id, "image")
            if ref and ref.suggestion:
                parts.append(
                    "[Image Quality Improvements]\n"
                    + "\n".join(f"- {s}" for s in ref.suggestion)
                )

        # Previous image reflection (from storyboard step, if exists)
        if self.reflection and session_id:
            for step in ("storyboard", "character"):
                prev_ref = self.reflection.get_reflection(session_id, step)
                if prev_ref and prev_ref.suggestion:
                    filtered = [
                        s for s in prev_ref.suggestion
                        if any(kw in s.lower() for kw in
                               ["prompt", "describe", "detail", "appearance",
                                "character", "scene", "visual"])
                    ]
                    if filtered:
                        parts.append(
                            f"[Suggestions from {step} review]\n"
                            + "\n".join(f"- {s}" for s in filtered[:3])
                        )

        # World settings (era, atmosphere)
        if self.memory:
            world = self.memory.world.to_dict()
            if world.get("era") or world.get("atmosphere"):
                env_parts = []
                if world.get("era"):
                    env_parts.append(f"Time period: {world['era']}")
                if world.get("atmosphere"):
                    env_parts.append(f"Atmosphere: {world['atmosphere']}")
                if env_parts:
                    parts.append(
                        "[Environment]\n" + "\n".join(env_parts)
                    )

        # The actual scene prompt
        parts.append(scene_prompt)

        return "\n\n".join(parts)