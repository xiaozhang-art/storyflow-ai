"""MCP Envelope - Unified message protocol for all Agent OS communication."""
from __future__ import annotations
import time
import uuid
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SKILL_CALL = "skill_call"
    SKILL_RESULT = "skill_result"
    A2A_MESSAGE = "a2a_message"
    CONTROL_EVENT = "control_event"


class MessageStatus(str, Enum):
    PENDING = "pending"
    ROUTED = "routed"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class MCPEnvelope(BaseModel):
    """Unified message envelope for all Agent OS communication.
    
    This is the 'TCP/IP' of the Agent OS - every piece of communication
    between agents, tools, skills, and the control server must use this format.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: MessageType = MessageType.MESSAGE
    status: MessageStatus = MessageStatus.PENDING
    
    # Routing
    source_agent: str = ""
    target_agent: str = ""
    source_session_id: Optional[str] = None
    target_session_id: Optional[str] = None
    
    # Identity
    conversation_id: str = ""
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    parent_id: Optional[str] = None
    reply_to: Optional[str] = None
    
    # Content
    action: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    
    # References
    memory_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    
    def reply(self, payload: dict[str, Any] | None = None, **kwargs) -> MCPEnvelope:
        """Create a reply envelope from this one."""
        return MCPEnvelope(
            source_agent=self.target_agent,
            target_agent=self.source_agent,
            source_session_id=self.target_session_id,
            target_session_id=self.source_session_id,
            conversation_id=self.conversation_id,
            trace_id=self.trace_id,
            parent_id=self.id,
            reply_to=self.id,
            payload=payload or {},
            **kwargs,
        )
    
    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
    
    @classmethod
    def from_dict(cls, data: dict) -> MCPEnvelope:
        return cls.model_validate(data)


class ToolCallRequest(BaseModel):
    """Standardized tool call within an MCP envelope."""
    tool_name: str
    tool_version: str = "1.0"
    input: dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    trace_id: Optional[str] = None


class ToolCallResult(BaseModel):
    """Standardized tool result."""
    status: str = "success"
    output: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    latency: float = 0.0