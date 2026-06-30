"""Memory Models - Data classes for the memory system."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    """Types of memory storage."""
    WORKING = "working"          # Current step context (short-lived)
    SESSION = "session"          # Within-session facts (24h TTL)
    CONVERSATION = "conversation"  # Story-level state (persistent)
    LONG_TERM = "long_term"      # Cross-story knowledge (indefinite)


@dataclass
class MemoryEntry:
    """A single memory entry in the memory system."""
    id: str = ""
    type: MemoryType = MemoryType.CONVERSATION
    text: str = ""
    entity: str = ""
    conversation_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    confidence: float = 1.0
    tags: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    created_at: float = 0.0
    expires_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex
        if not self.created_at:
            self.created_at = time.time()


@dataclass
class MemoryQuery:
    """A query against the memory system."""
    query: str = ""
    memory_types: list[MemoryType] = field(default_factory=lambda: [MemoryType.CONVERSATION])
    conversation_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    tags: list[str] = field(default_factory=list)
    min_confidence: float = 0.0
    limit: int = 10
    entity: str = ""