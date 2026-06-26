"""Character Memory - Specialized memory subsystem for character consistency.

This is the key innovation for 漫剧 (comic drama) generation:
- When episodes are long, LLM tends to "forget" or alter character appearances
- This module stores structured character visual features and injects them
  as immutable context into downstream agents (storyboard, image generation)

Memory flow:
  1. character_agent produces enriched characters → store in memory as CHARACTER_PROFILE
  2. storyboard_agent queries memory → injects character descriptions into each episode prompt
  3. image_agent queries memory → verifies prompt contains correct character features
  4. On multi-story / multi-episode runs → accumulated profiles persist

Two storage layers:
  - In-memory dict: fast, per-process, for single-generation runs
  - Qdrant: persistent, cross-session, for multi-episode consistency
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from runtime.memory.manager import MemoryManager
from runtime.memory.models import MemoryEntry, MemoryQuery, MemoryType

logger = logging.getLogger(__name__)


# Memory entity tags for character consistency
TAG_CHARACTER = "character"
TAG_APPEARANCE = "appearance"


class CharacterMemoryService:
    """Specialized service for managing character consistency memory.

    This wraps the general MemoryManager with character-specific operations:
    - store_character_profiles(): After character_agent, store all profiles
    - load_character_context(): Before storyboard/image agents, load context
    - verify_consistency(): After image prompt generation, verify consistency
    - build_consistency_prompt(): Build a prompt section enforcing consistency
    """

    def __init__(self, memory_manager: MemoryManager):
        self._memory = memory_manager

    # ─────────────────────────────────────────────────────────────
    # 1. Store character profiles after character_agent
    # ─────────────────────────────────────────────────────────────

    async def store_character_profiles(
        self,
        characters: list[dict],
        story_id: str = "",
        conversation_id: str = "",
    ):
        """Store all character appearance profiles into memory.

        Each character gets a CONVERSATION-level memory entry (persistent)
        with structured metadata so it can be queried by character name.

        The stored text is a formatted English description suitable for
        direct injection into SD/ComfyUI prompts.
        """
        for char in characters:
            name = char.get("name", "").strip()
            if not name:
                continue

            appearance = char.get("appearance", {})
            if isinstance(appearance, str):
                appearance = {"face": appearance}
            if not isinstance(appearance, dict):
                appearance = {}

            hair = appearance.get("hair", "")
            body = appearance.get("body", "")
            cloth = appearance.get("cloth", "")
            face = appearance.get("face", "")

            # Build a structured description for memory
            desc_parts = [p for p in [hair, face, body, cloth] if p.strip()]
            description = ", ".join(desc_parts) if desc_parts else name

            # Store the full profile text
            profile_text = f"{name}: {description}"

            # Build metadata for structured queries
            metadata = {
                "character_name": name,
                "gender": char.get("gender", "unknown"),
                "age": char.get("age"),
                "hair": hair,
                "body": body,
                "cloth": cloth,
                "face": face,
                "personality": char.get("personality", {}),
                "catchphrase": char.get("catchphrase", ""),
            }

            entry = MemoryEntry(
                type=MemoryType.CONVERSATION,  # Persistent across the story
                text=profile_text,
                entity=name,  # Queryable by character name
                conversation_id=conversation_id or None,
                tags=[TAG_CHARACTER, TAG_APPEARANCE, name],
                confidence=1.0,  # Character profiles are ground truth
                metadata=metadata,
            )
            await self._memory.store(entry)

        logger.info(
            "Stored %d character profiles in memory | story=%s",
            len(characters), story_id,
        )

    # ─────────────────────────────────────────────────────────────
    # 2. Load character context for injection into prompts
    # ─────────────────────────────────────────────────────────────

    async def load_character_context(
        self,
        character_names: list[str] | None = None,
        conversation_id: str = "",
    ) -> str:
        """Load character appearance context formatted for prompt injection.

        If character_names is provided, only loads those characters.
        Otherwise loads all character profiles for the conversation.

        Returns a formatted string like:
            "张小明: black short hair, brown eyes, slim body, wearing white shirt
             李小红: long brown hair, green eyes, tall, wearing red dress"
        """
        query = MemoryQuery(
            query="character appearance",
            conversation_id=conversation_id or None,
            memory_types=[MemoryType.CONVERSATION],
            tags=[TAG_CHARACTER, TAG_APPEARANCE],
            min_confidence=0.5,
            limit=20,
        )

        memories = await self._memory.retrieve(query)

        if not memories:
            return ""

        # Filter by character names if specified
        if character_names:
            name_set = set(character_names)
            memories = [
                m for m in memories
                if m.entity in name_set
            ]

        # Format for injection
        lines = []
        for mem in memories:
            lines.append(mem.text)

        return "\n".join(lines)

    async def load_character_metadata(
        self,
        character_name: str,
        conversation_id: str = "",
    ) -> dict[str, Any] | None:
        """Load full metadata for a specific character."""
        query = MemoryQuery(
            query=character_name,
            conversation_id=conversation_id or None,
            memory_types=[MemoryType.CONVERSATION],
            tags=[TAG_CHARACTER, character_name],
            min_confidence=0.5,
            limit=1,
        )

        memories = await self._memory.retrieve(query)
        if memories:
            return memories[0].metadata
        return None

    async def load_all_character_profiles(
        self,
        conversation_id: str = "",
    ) -> list[dict[str, Any]]:
        """Load all character profiles with full metadata."""
        query = MemoryQuery(
            query="character appearance",
            conversation_id=conversation_id or None,
            memory_types=[MemoryType.CONVERSATION],
            tags=[TAG_CHARACTER],
            min_confidence=0.5,
            limit=20,
        )

        memories = await self._memory.retrieve(query)
        profiles = []
        for mem in memories:
            profiles.append({
                "name": mem.entity,
                "description": mem.text,
                "metadata": mem.metadata,
            })
        return profiles

    # ─────────────────────────────────────────────────────────────
    # 3. Build consistency enforcement sections for prompts
    # ─────────────────────────────────────────────────────────────

    def build_consistency_section(
        self,
        character_context: str,
    ) -> str:
        """Build a prompt section that enforces character consistency.

        This is designed to be appended to storyboard and image prompts
        to force the LLM / image model to maintain consistent character
        appearances.
        """
        if not character_context:
            return ""

        return (
            "\n\n## ⚠️ 角色外观一致性约束（必须严格遵守）\n"
            "以下角色外观描述是已确定的视觉参考，所有场景描述必须严格引用这些特征，"
            "不得随意改变角色的发色、发型、服装、肤色等关键视觉特征：\n\n"
            f"{character_context}\n\n"
            "注意：如果某个角色出现在场景中，必须完整包含该角色的所有视觉特征描述。"
        )

    # ─────────────────────────────────────────────────────────────
    # 4. Verify consistency of generated prompts
    # ─────────────────────────────────────────────────────────────

    def verify_prompt_consistency(
        self,
        image_prompt: str,
        character_profiles: list[dict],
    ) -> tuple[bool, list[str]]:
        """Verify that an image prompt contains character appearance features.

        Returns:
            (is_consistent, missing_features)
            - is_consistent: True if all required character features are present
            - missing_features: List of descriptions of what's missing
        """
        prompt_lower = image_prompt.lower()
        missing = []

        for profile in character_profiles:
            name = profile.get("name", "")
            metadata = profile.get("metadata", {})
            if not metadata:
                continue

            # Check if the character is mentioned in this scene
            if name.lower() not in image_prompt and name not in image_prompt:
                # Character not in this scene, skip
                continue

            # Character is in the scene - verify key features are present
            for feature_key in ["hair", "face", "cloth"]:
                feature_value = metadata.get(feature_key, "")
                if not feature_value:
                    continue

                # Check if key visual descriptors are in the prompt
                # Extract meaningful words (skip common words)
                feature_words = self._extract_key_visual_words(feature_value)
                for word in feature_words:
                    if word.lower() not in prompt_lower:
                        missing.append(
                            f"{name} 缺少 {feature_key} 特征: '{word}'"
                        )

        is_consistent = len(missing) == 0
        return is_consistent, missing

    @staticmethod
    def _extract_key_visual_words(feature_text: str) -> list[str]:
        """Extract meaningful visual descriptor words from a feature string.

        Filters out common English filler words to focus on visual descriptors.
        """
        # Common words to skip
        skip_words = {
            "a", "an", "the", "is", "are", "was", "were", "with", "and",
            "or", "of", "in", "on", "at", "to", "for", "has", "have",
            "wearing", "style", "type", "very", "slightly", "some",
        }

        words = feature_text.replace(",", " ").split()
        return [w.strip().lower() for w in words if w.strip().lower() not in skip_words and len(w.strip()) > 2]

    # ─────────────────────────────────────────────────────────────
    # 5. Generate a consistency-fix prompt
    # ─────────────────────────────────────────────────────────────

    def build_fix_prompt(
        self,
        original_prompt: str,
        character_profiles: list[dict],
        missing_features: list[str],
    ) -> str:
        """Build a correction prompt when consistency check fails.

        This can be fed back to the LLM to fix an inconsistent storyboard prompt.
        """
        character_desc = "\n".join(
            f"- {p.get('name', '')}: {p.get('description', '')}"
            for p in character_profiles
        )

        return (
            f"原 prompt:\n{original_prompt}\n\n"
            f"角色外观参考:\n{character_desc}\n\n"
            f"一致性问题:\n" + "\n".join(f"- {m}" for m in missing_features) + "\n\n"
            "请修正这个 prompt，确保包含所有出场角色的完整视觉特征描述。"
            "只输出修正后的英文 prompt，不要包含其他文字。"
        )

    def get_stats(self) -> dict:
        """Get character memory statistics."""
        base_stats = self._memory.get_stats()
        # Count character-specific entries
        char_count = sum(
            1 for entry in self._memory._store.values()
            if TAG_CHARACTER in entry.tags
        )
        return {
            **base_stats,
            "character_profiles": char_count,
        }