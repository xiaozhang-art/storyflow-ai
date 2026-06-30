"""StoryFlow Runtime - The unified runtime that ties everything together.

This is the main entry point for the Runtime. It assembles:
    - WorkflowEngine (step execution with Director decisions and A2A communication)
    - EventBus (decoupled communication)
    - ArtifactManager (file-based storage for artifacts/checkpoints)
    - SessionManager (session tracking)
    - HookFramework (cross-cutting concerns)
    - Director (LLM-powered step analysis and decision-making)
    - PlannerAgent (task decomposition + dynamic workflow)
    - QualityEngine (quality validation)
    - AdapterRegistry (pluggable models)
    - AgentRegistry (agent discovery)

V1.5 Runtime Upgrades:
    - ReflectionRuntime (post-step analysis: good/bad/suggestion)
    - PromptRuntime (dynamic prompt construction)
    - MemoryGraph (timeline-aware character state)
    - AgentConversationBus (inter-agent discussion)
    - ModelRouter (intelligent model selection)
    - MemoryManager + StoryMemory (Phase 3 memory system)

Usage:
    runtime = StoryFlowRuntime()
    runtime.register_existing_agents()

    session = runtime.create_session(story_id="...", prompt="...", genre="...")
    result = await runtime.run(session.id)

    # Partial regeneration: re-run from a specific step
    result = await runtime.rerun_step(session.id, "image")
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.event_bus import EventBus, get_event_bus
from runtime.artifact_manager import ArtifactManager
from runtime.session_manager import SessionManager, get_session_manager
from runtime.hooks import HookFramework
from runtime.workflow_engine import WorkflowEngine
from runtime.director import Director, DirectorDecision
from runtime.planner import PlannerAgent
from runtime.quality import QualityEngine
from runtime.retry_engine import RetryEngine
from runtime.memory.manager import MemoryManager
from runtime.memory.story_memory import StoryMemory
from runtime.trace import TraceRuntime, get_trace_runtime
from runtime.agent_sdk import AgentRegistry, get_agent_registry

# V1.5 Runtime Upgrades
from runtime.reflection import ReflectionRuntime
from runtime.prompt_runtime import PromptRuntime
from runtime.memory.graph import MemoryGraph
from runtime.agent_conversation import AgentConversationBus
from runtime.model_router import ModelRouter
from runtime.adapters import AdapterRegistry

logger = logging.getLogger(__name__)


class StoryFlowRuntime:
    """The unified StoryFlow Runtime.

    Provides a simple API:
        1. create_session() -> session
        2. run(session_id) -> result
        3. rerun_step(session_id, step) -> result (partial regeneration)
    """

    def __init__(
        self,
        artifact_base_path: str = "./artifacts",
    ):
        # ── Core infrastructure ──────────────────────────────────
        self.event_bus: EventBus = get_event_bus()
        self.artifact_manager: ArtifactManager = ArtifactManager(
            base_path=artifact_base_path,
        )
        self.session_manager: SessionManager = get_session_manager()
        self.hooks: HookFramework = HookFramework()
        self.agent_registry: AgentRegistry = get_agent_registry()

        # ── V1.5 Director (LLM-powered step analysis) ────────────
        # The Director has its own in-memory ArtifactManager for
        # collecting LLM analysis context. The file-based
        # ArtifactManager above is separate and handles persistence.
        self.director: Director = Director(
            artifact_manager=None,  # Director creates its own in-memory one
            session_manager=self.session_manager,
        )

        # ── Intelligence subsystems ──────────────────────────────
        self.planner: PlannerAgent = PlannerAgent(event_bus=self.event_bus)
        self.quality_engine: QualityEngine = QualityEngine(event_bus=self.event_bus)
        self.adapter_registry: AdapterRegistry = AdapterRegistry()
        self.model_router: ModelRouter = ModelRouter()

        # ── Memory system (Phase 3) ─────────────────────────────
        self.memory_manager: MemoryManager = MemoryManager()
        self.story_memory: StoryMemory = StoryMemory(
            memory_manager=self.memory_manager,
        )

        # ── V1.5 Subsystems ─────────────────────────────────────
        self.retry_engine: RetryEngine = RetryEngine(event_bus=self.event_bus)
        self.trace: TraceRuntime = get_trace_runtime()
        self.reflection: ReflectionRuntime = ReflectionRuntime(
            event_bus=self.event_bus, enabled=True, use_llm=True,
        )
        self.prompt_runtime: PromptRuntime = PromptRuntime(
            memory=self.memory_manager,
            reflection=self.reflection,
            event_bus=self.event_bus,
        )
        self.memory_graph: MemoryGraph = MemoryGraph()
        self.conversation_bus: AgentConversationBus = AgentConversationBus()

        # ── Execution engine (depends on all above) ─────────────
        self.workflow_engine: WorkflowEngine = WorkflowEngine(
            director=self.director,
            artifact_manager=self.director.artifact_manager,
            conversation_bus=self.conversation_bus,
            story_memory=self.story_memory,
            event_bus=self.event_bus,
        )

        logger.info("StoryFlow Runtime 5.0.0 initialized (V1.5 Runtime upgrade complete)")

    # ── Agent registration ───────────────────────────────────────

    def register_existing_agents(self) -> None:
        """Register all 7 standard agents with the Runtime."""

        from agents.script_agent import script_agent
        from agents.character_agent import character_agent
        from agents.storyboard_agent import storyboard_agent
        from agents.image_agent import image_agent
        from agents.image_to_video_agent import image_to_video_agent
        from agents.voice_agent import voice_agent
        from agents.video_agent import video_agent

        # V1.5 WorkflowEngine.register_agent takes (agent_id, agent_func)
        self.workflow_engine.register_agent("script", script_agent)
        self.workflow_engine.register_agent("character", character_agent)
        self.workflow_engine.register_agent("storyboard", storyboard_agent)
        self.workflow_engine.register_agent("image", image_agent)
        self.workflow_engine.register_agent("image_to_video", image_to_video_agent)
        self.workflow_engine.register_agent("voice", voice_agent)
        self.workflow_engine.register_agent("video", video_agent)

        logger.info("Registered 7 agents with Runtime")

    def register_agent(self, name: str, agent_func, **kwargs) -> None:
        """Register a custom agent function.

        Args:
            name: Step name in the pipeline
            agent_func: async function(state: dict) -> dict
            **kwargs: Reserved for future use
        """
        self.workflow_engine.register_agent(name, agent_func)

    # ── Session management ───────────────────────────────────────

    def create_session(
        self,
        story_id: str,
        task_id: str = "",
        prompt: str = "",
        genre: str = "",
        session_id: str = "",
    ) -> Any:
        """Create a new generation session.

        Args:
            story_id: The story ID from the database
            task_id: The task ID for progress tracking
            prompt: User's creative prompt
            genre: Story genre
            session_id: Optional pre-existing session ID

        Returns:
            Session object
        """
        return self.session_manager.create(
            story_id=story_id,
            task_id=task_id,
            prompt=prompt,
            genre=genre,
            session_id=session_id,
        )

    # ── Pipeline execution ───────────────────────────────────────

    async def run(self, session_id: str) -> dict:
        """Execute the full pipeline for a session.

        Uses the V1.5 WorkflowEngine.run_pipeline() which provides
        Director-driven step analysis, A2A messages, and StoryMemory.

        Args:
            session_id: Session to run

        Returns:
            Final state dict with all results
        """
        session = self.session_manager.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Use Planner if requested
        if session.metadata.get("use_planner"):
            plan = await self.planner.plan(
                prompt=session.prompt,
                genre=session.genre,
                metadata=session.metadata,
            )
            pipeline = plan.get_linear_pipeline()
            session.metadata["pipeline"] = pipeline
            logger.info("Using Planner pipeline: %s", pipeline)

        return await self.workflow_engine.run_pipeline(
            task_id=session.task_id or session_id,
            story_id=session.story_id,
            prompt=session.prompt,
            genre=session.genre,
            conversation_id=session_id,
            trace_id=session.task_id or "",
        )

    async def rerun_step(self, session_id: str, step_name: str) -> dict:
        """Re-run from a specific step (partial regeneration).

        Resets the session from the target step, then executes the
        pipeline. Previously completed artifacts remain on disk.

        Args:
            session_id: Session to modify
            step_name: Step to re-run from

        Returns:
            Result dict from the re-run
        """
        # Reset session from the target step
        self.session_manager.reset_from_step(session_id, step_name)

        session = self.session_manager.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        return await self.workflow_engine.run_pipeline(
            task_id=session.task_id or session_id,
            story_id=session.story_id,
            prompt=session.prompt,
            genre=session.genre,
            conversation_id=session_id,
            trace_id=session.task_id or "",
        )

    # ── Observability ────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get comprehensive Runtime statistics."""
        return {
            "version": "5.0.0",
            "workflow_engine": self.workflow_engine.get_stats(),
            "session_manager": self.session_manager.get_stats(),
            "director": self.director.get_stats(),
            "planner": self.planner.get_stats(),
            "quality_engine": self.quality_engine.get_stats(),
            "retry_engine": self.retry_engine.get_stats(),
            "memory_manager": self.memory_manager.get_stats(),
            "story_memory": self.story_memory.get_stats(),
            "trace": self.trace.get_stats(),
            "reflection": self.reflection.get_stats(),
            "prompt_runtime": self.prompt_runtime.get_stats(),
            "memory_graph": self.memory_graph.get_stats(),
            "conversation_bus": self.conversation_bus.get_stats(),
            "model_router": self.model_router.get_stats(),
            "adapters": self.adapter_registry.list_adapters(),
            "agent_registry": self.agent_registry.get_stats(),
        }


# ── Global singleton ─────────────────────────────────────────────

_runtime: StoryFlowRuntime | None = None


def get_runtime() -> StoryFlowRuntime:
    """Get the global StoryFlow Runtime instance."""
    global _runtime
    if _runtime is None:
        _runtime = StoryFlowRuntime()
        _runtime.register_existing_agents()
    return _runtime