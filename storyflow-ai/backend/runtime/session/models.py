"""Session data models."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime


class Session(BaseModel):
    """A Session represents an agent's execution context within a conversation.
    
    Agents NEVER see sessions - they are managed entirely by the Runtime.
    Session = Agent's execution context in a specific conversation.
    """
    session_id: str
    agent_id: str
    conversation_id: str
    partner_session_id: Optional[str] = None
    
    state: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"  # active, idle, suspended, expired
    message_count: int = 0
    cursor: int = 0
    
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_active: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def touch(self):
        """Update last_active timestamp."""
        self.last_active = datetime.utcnow().isoformat()
        self.message_count += 1


class SessionPair(BaseModel):
    """A bidirectional session binding between two agents.
    
    A(Sa) <-> B(Sb) forms the minimal communication unit in A2A.
    """
    session_a: str
    session_b: str
    conversation_id: str
    
    def get_partner(self, session_id: str) -> Optional[str]:
        """Get the partner session ID for a given session."""
        if session_id == self.session_a:
            return self.session_b
        elif session_id == self.session_b:
            return self.session_a
        return None