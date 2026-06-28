"""StoryFlow Runtime - Agent Operating System for AI content creation.

V2.0 (legacy): MCP, Hook, Memory, Skill, Session, A2A, Execution, Conversation
V3.0 (new): Core Runtime, WorkflowEngine, EventBus, Blackboard, ArtifactManager,
          SessionManager, HookFramework, DirectorAgent, PlannerAgent,
          QualityEngine, AdapterRegistry, AgentSDK, Workflow DSL
"""

# V2.0 exports (legacy, kept for backward compatibility)
from runtime.mcp.envelope import MCPEnvelope, MessageType, MessageStatus
from runtime.hook.dispatcher import HookDispatcher, HookEvent, get_hook_dispatcher
from runtime.mcp.router import MCPRouter

# V3.0 exports (new Runtime)
from runtime.core import StoryFlowRuntime, get_runtime
from runtime.event_bus import EventBus, EventType, Event, get_event_bus
from runtime.blackboard import Blackboard
from runtime.artifact_manager import ArtifactManager
from runtime.session_manager import SessionManager, Session, SessionStatus, get_session_manager
from runtime.hooks import HookFramework, StepContext, HookAbort, ErrorAction
from runtime.workflow_engine import WorkflowEngine, PipelineStep
from runtime.director import DirectorAgent, Decision, DecisionType
from runtime.planner import PlannerAgent, ExecutionPlan, TaskNode
from runtime.quality import QualityEngine, QualityResult
from runtime.adapters import AdapterRegistry
from runtime.agent_sdk import BaseAgent, AgentRegistry, get_agent_registry

__all__ = [
    # V3.0 Core
    "StoryFlowRuntime", "get_runtime",
    "EventBus", "EventType", "Event", "get_event_bus",
    "Blackboard",
    "ArtifactManager",
    "SessionManager", "Session", "SessionStatus", "get_session_manager",
    "HookFramework", "StepContext", "HookAbort", "ErrorAction",
    "WorkflowEngine", "PipelineStep",
    "DirectorAgent", "Decision", "DecisionType",
    "PlannerAgent", "ExecutionPlan", "TaskNode",
    "QualityEngine", "QualityResult",
    "AdapterRegistry",
    "BaseAgent", "AgentRegistry", "get_agent_registry",
    # V2.0 Legacy
    "MCPEnvelope", "MessageType", "MessageStatus",
    "HookDispatcher", "HookEvent", "get_hook_dispatcher",
    "MCPRouter",
]