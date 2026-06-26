"""Runtime Context - Execution context for a single agent invocation."""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field
from runtime.mcp.envelope import MCPEnvelope


class RuntimeContext(BaseModel):
    """Immutable execution context created from an incoming Envelope.
    
    Contains everything an agent needs for a single execution:
    - Identity (agent_id, trace_id)
    - Task (action, payload)
    - Configuration (model, temperature, etc.)
    - Feature flags (enable_judge, enable_retry)
    """
    agent_id: str = ""
    action: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    
    trace_id: str = ""
    conversation_id: str = ""
    session_id: str = ""
    source_agent: str = ""
    
    # Execution config
    model: str = "default"
    temperature: float = 0.7
    max_tokens: int = 4096
    
    # Feature flags
    enable_judge: bool = False
    enable_retry: bool = True
    judge_threshold: float = 0.6
    max_retries: int = 2
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def from_envelope(cls, envelope: MCPEnvelope, **overrides) -> RuntimeContext:
        """Create a RuntimeContext from an MCP Envelope."""
        return cls(
            agent_id=envelope.target_agent or envelope.source_agent,
            action=envelope.action,
            payload=envelope.payload,
            trace_id=envelope.trace_id,
            conversation_id=envelope.conversation_id,
            session_id=envelope.target_session_id or "",
            source_agent=envelope.source_agent,
            metadata=envelope.metadata,
            **overrides,
        )