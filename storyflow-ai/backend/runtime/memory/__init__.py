"""Unified Memory System - Multi-layer memory for agent cognition.

Layers:
    - Working Memory: Current step context (short-lived)
    - Session Memory: Within-session facts (24h TTL)
    - Conversation Memory: Story-level state (persistent)
    - Long-term Memory: Cross-story knowledge (indefinite)

Specialized layers:
    - CharacterMemory: Per-character structured data (appearance, voice, personality)
    - WorldMemory: World-building information (era, location, rules, atmosphere)
    - TimelineMemory: Ordered event/progression history
    - StoryMemory: Unified 7-dimensional memory (Scene/Visual/Style/World + Character/Timeline)
    - MemoryGraph: Timeline-aware graph memory for characters and world state
"""
from runtime.memory.manager import MemoryManager
from runtime.memory.character_memory import CharacterMemory
from runtime.memory.world_memory import WorldMemory
from runtime.memory.timeline_memory import TimelineMemory
from runtime.memory.story_memory import StoryMemory
from runtime.memory.models import MemoryEntry, MemoryQuery, MemoryType

__all__ = [
    "MemoryManager",
    "CharacterMemory",
    "WorldMemory",
    "TimelineMemory",
    "StoryMemory",
    "MemoryEntry",
    "MemoryQuery",
    "MemoryType",
]