"""StoryFlow Runtime - Unified Agent Runtime for AI content creation.

Architecture:
    StoryFlowRuntime (core.py)
    ├── WorkflowEngine  - Pipeline execution with DSL, hooks, retry, parallelism
    ├── EventBus        - Async pub/sub for decoupled communication
    ├── Blackboard      - Shared state with dotted-key access
    ├── ArtifactManager - File-based artifact storage + checkpoints
    ├── SessionManager  - Session tracking + partial regeneration
    ├── HookFramework   - Before/after/error hooks (cross-cutting concerns)
    ├── DirectorAgent   - Decision making: retry/rollback/skip/abort
    ├── PlannerAgent    - Task decomposition into DAG
    ├── QualityEngine   - Multi-dimensional quality checking
    ├── AdapterRegistry - Pluggable model backends (LLM/Image/Voice/Video)
    └── AgentRegistry   - Agent discovery + BaseAgent SDK

Usage:
    runtime = StoryFlowRuntime()
    runtime.register_existing_agents()

    session = runtime.create_session(story_id="...", prompt="...", genre="...")
    result = await runtime.run(session.id)

    # Partial regeneration: re-run from a specific step
    result = await runtime.rerun_step(session.id, "image")
"""

# Core
from runtime.core import StoryFlowRuntime, get_runtime

# Infrastructure
from runtime.event_bus import EventBus, EventType, Event, get_event_bus
from runtime.blackboard import Blackboard
from runtime.artifact_manager import ArtifactManager
from runtime.session_manager import SessionManager, Session, SessionStatus, get_session_manager
from runtime.hooks import HookFramework, StepContext, HookAbort, ErrorAction

# Execution
from runtime.workflow_engine import WorkflowEngine, PipelineStep

# Intelligence
from runtime.director import DirectorAgent, Decision, DecisionType
from runtime.planner import PlannerAgent, ExecutionPlan, TaskNode
from runtime.quality import QualityEngine, QualityResult

# Extensibility
from runtime.adapters import AdapterRegistry
from runtime.agent_sdk import BaseAgent, AgentRegistry, get_agent_registry

__all__ = [
    # Core
    "StoryFlowRuntime", "get_runtime",
    # Infrastructure
    "EventBus", "EventType", "Event", "get_event_bus",
    "Blackboard",
    "ArtifactManager",
    "SessionManager", "Session", "SessionStatus", "get_session_manager",
    "HookFramework", "StepContext", "HookAbort", "ErrorAction",
    # Execution
    "WorkflowEngine", "PipelineStep",
    # Intelligence
    "DirectorAgent", "Decision", "DecisionType",
    "PlannerAgent", "ExecutionPlan", "TaskNode",
    "QualityEngine", "QualityResult",
    # Extensibility
    "AdapterRegistry",
    "BaseAgent", "AgentRegistry", "get_agent_registry",
]