"""Conversation data models."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Optional
from enum import Enum


class ConversationStatus(str, Enum):
    INIT = "init"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_FEEDBACK = "waiting_feedback"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRole(str, Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    CRITIC = "critic"
    OPTIMIZER = "optimizer"


class Conversation(BaseModel):
    """A Conversation is a goal-driven multi-agent collaboration graph.
    
    Unlike a Chat (which is just a record), a Conversation is a task system:
    - It has a goal
    - It has a graph of agent interactions
    - It manages state and lifecycle
    """
    conversation_id: str
    goal: str = ""
    
    agents: list[str] = Field(default_factory=list)
    edges: list[tuple[str, str]] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
    status: ConversationStatus = ConversationStatus.INIT
    
    # Sub-conversations for parallel tracks
    sub_conversations: list[str] = Field(default_factory=list)
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0


class AgentNode(BaseModel):
    """A node in the conversation graph representing an agent with a role."""
    agent_id: str
    role: AgentRole = AgentRole.EXECUTOR
    state: str = "pending"  # pending, running, done, failed
    context: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class Edge(BaseModel):
    """An edge in the conversation graph defining message flow."""
    from_agent: str
    to_agent: str
    condition: str = "always"  # success, failure, always


class TaskPlan(BaseModel):
    """A decomposed task plan from the planner."""
    tasks: list[TaskItem] = Field(default_factory=list)


class TaskItem(BaseModel):
    """A single task in a decomposed plan."""
    id: str
    type: str = "skill"
    agent: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    description: str = ""