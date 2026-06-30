"""StoryFlow Runtime - Unified Agent Runtime for AI content creation.

Architecture (V5.0 - V1.5 Runtime Upgrade Complete):
    StoryFlowRuntime (core.py)
    ├── WorkflowEngine  - Pipeline execution with Director decisions, A2A, StoryMemory
    ├── EventBus        - Async pub/sub for decoupled communication
    ├── Blackboard      - Shared state with dotted-key access
    ├── ArtifactManager - File-based artifact storage + checkpoints
    ├── SessionManager  - Session tracking + partial regeneration
    ├── HookFramework   - Before/after/error hooks (cross-cutting concerns)
    ├── Director        - LLM-powered 5-decision brain (retry/rollback/rewrite/skip/insert)
    ├── PlannerAgent    - Task decomposition into DAG
    ├── QualityEngine   - Multi-dimensional quality checking
    ├── AdapterRegistry - Pluggable model backends (LLM/Image/Voice/Video)
    ├── AgentRegistry   - Agent discovery + BaseAgent SDK
    ├── MemoryManager   - 4-layer memory hierarchy (working/session/conversation/long-term)
    ├── StoryMemory     - Unified 7-dimensional memory (Scene/Visual/Style/World + Character/Timeline)
    ├── ReflectionRuntime - Post-step analysis (good/bad/suggestion)
    ├── PromptRuntime   - Dynamic prompt construction from memory
    ├── MemoryGraph     - Timeline-aware graph memory for characters/world
    ├── AgentConversationBus - A2A structured context/feedback/constraint passing
    ├── ModelRouter     - Intelligent model selection per task type
    └── RetryEngine     - Strategy-based retry with pluggable policies

All model backends use cloud APIs (no local GPU required):
    - LLM: OpenAI-compatible API (GPT-4o / Qwen / DeepSeek)
    - Image: DashScope Wanx / DALL-E 3 / ComfyUI (SDXL) [optional local]
    - TTS: DashScope CosyVoice / OpenAI TTS
    - Image-to-Video: Kling / Runway
    - Video Assembly: FFmpeg (local)

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
from runtime.workflow_engine import WorkflowEngine

# Intelligence
from runtime.director import Director, DirectorDecision, DirectorVerdict
from runtime.planner import PlannerAgent, ExecutionPlan, TaskNode
from runtime.quality import QualityEngine, QualityResult

# V1.5 Runtime Layers
from runtime.retry_engine import RetryEngine, RetryPolicy, RetryAction, RetryResult
from runtime.trace import TraceRuntime, Span, TraceTree, get_trace_runtime

# Memory System (Phase 3)
from runtime.memory.manager import MemoryManager
from runtime.memory.story_memory import StoryMemory
from runtime.memory.models import MemoryEntry, MemoryQuery, MemoryType
from runtime.memory.character_memory import CharacterMemory
from runtime.memory.world_memory import WorldMemory
from runtime.memory.timeline_memory import TimelineMemory

# V1.5 Runtime Upgrades
from runtime.reflection import ReflectionRuntime, ReflectionResult
from runtime.prompt_runtime import PromptRuntime
from runtime.memory.graph import MemoryGraph, MemoryNode, MemoryEdge
from runtime.agent_conversation import AgentConversationBus, A2AMessage
from runtime.model_router import ModelRouter, ModelRoute

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
    "WorkflowEngine",
    # Intelligence
    "Director", "DirectorDecision", "DirectorVerdict",
    "PlannerAgent", "ExecutionPlan", "TaskNode",
    "QualityEngine", "QualityResult",
    # V1.5 Runtime Layers
    "RetryEngine", "RetryPolicy", "RetryAction", "RetryResult",
    "TraceRuntime", "Span", "TraceTree", "get_trace_runtime",
    # Memory System (Phase 3)
    "MemoryManager",
    "StoryMemory",
    "MemoryEntry", "MemoryQuery", "MemoryType",
    "CharacterMemory",
    "WorldMemory",
    "TimelineMemory",
    # V1.5 Runtime Upgrades
    "ReflectionRuntime", "ReflectionResult",
    "PromptRuntime",
    "MemoryGraph", "MemoryNode", "MemoryEdge",
    "AgentConversationBus", "A2AMessage",
    "ModelRouter", "ModelRoute",
    # Extensibility
    "AdapterRegistry",
    "BaseAgent", "AgentRegistry", "get_agent_registry",
]