"""Memory data models."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional
from enum import Enum


class MemoryType(str, Enum):
    WORKING = "working"       # Current step, 1 turn
    SESSION = "session"       # Within session, 24h
    CONVERSATION = "conversation"  # Story-level, persistent
    LONG_TERM = "long_term"   # Cross-story, indefinite


class MemoryEntry(BaseModel):
    """A single memory record."""
    id: str
    type: MemoryType
    text: str
    entity: str = ""
    
    # Scoping
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    agent_id: Optional[str] = None
    
    # Quality
    confidence: float = 1.0
    embedding: list[float] = Field(default_factory=list)
    
    # Metadata
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Timestamps
    created_at: float = 0.0
    expires_at: float = 0.0  # 0 = never expires


class MemoryQuery(BaseModel):
    """Query for memory retrieval."""
    query: str = ""
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None
    memory_types: list[MemoryType] = Field(
        default_factory=lambda: [MemoryType.CONVERSATION, MemoryType.SESSION]
    )
    limit: int = 10
    min_confidence: float = 0.5
    tags: list[str] = Field(default_factory=list)