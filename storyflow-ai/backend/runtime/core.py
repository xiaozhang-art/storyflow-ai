"""StoryFlow Runtime - The unified runtime that ties everything together.

This is the main entry point for the Runtime. It assembles:
    - WorkflowEngine (step execution with DSL, parallelism, hooks)
    - EventBus (decoupled communication)
    - Blackboard (shared state)
    - ArtifactManager (file storage)
    - SessionManager (session tracking)
    - HookFramework (cross-cutting concerns)
    - DirectorAgent (decision making)
    - PlannerAgent (task decomposition)
    - QualityEngine (quality validation)
    - AdapterRegistry (pluggable models)
    - AgentRegistry (agent discovery)

Usage:
    runtime = StoryFlowRuntime()
    runtime.register_existing_agents()

    session = runtime.create_session(story_id="...", prompt="...", genre="...")
    result = await runtime.run(session.id)

    # Partial regeneration: re-run from a specific step
    result = await runtime.rerun_step(session.id, "image")
"""

import logging
from typing import Any

from runtime.event_bus import EventBus, get_event_bus
from runtime.blackboard import Blackboard
from runtime.artifact_manager import ArtifactManager
from runtime.session_manager import SessionManager, get_session_manager
from runtime.hooks import HookFramework
from runtime.workflow_engine import WorkflowEngine
from runtime.director import DirectorAgent
from runtime.planner import PlannerAgent
from runtime.quality import QualityEngine
from runtime.retry_engine import RetryEngine
from runtime.memory import MemoryRuntime
from runtime.trace import TraceRuntime, get_trace_runtime
from runtime.agent_sdk import AgentRegistry, get_agent_registry

logger = logging.getLogger(__name__)


class StoryFlowRuntime:
    """The unified StoryFlow Runtime.

    Provides a simple API:
        1. create_session() → session
        2. run(session_id) → result
        3. rerun_step(session_id, step) → result (partial regeneration)
    """

    def __init__(
        self,
        artifact_base_path: str = "./artifacts",
        max_retries: int = 3,
    ):
        # Core infrastructure
        self.event_bus = get_event_bus()
        self.artifact_manager = ArtifactManager(base_path=artifact_base_path)
        self.session_manager = get_session_manager()
        self.hooks = HookFramework()
        self.agent_registry = get_agent_registry()

        # Intelligence
        self.director = DirectorAgent(event_bus=self.event_bus)
        self.planner = PlannerAgent(event_bus=self.event_bus)
        self.quality_engine = QualityEngine(event_bus=self.event_bus)
        self.adapter_registry = AdapterRegistry()

        # V1.5 Runtime Layers
        self.retry_engine = RetryEngine(event_bus=self.event_bus)
        self.memory = MemoryRuntime()
        self.trace = get_trace_runtime()

        # Execution (depends on all above)
        self.workflow_engine = WorkflowEngine(
            event_bus=self.event_bus,
            artifact_manager=self.artifact_manager,
            session_manager=self.session_manager,
            hooks=self.hooks,
            director=self.director,
            quality_engine=self.quality_engine,
            retry_engine=self.retry_engine,
            memory=self.memory,
            trace=self.trace,
            max_retries=max_retries,
        )

        logger.info("StoryFlow Runtime V3 initialized")

    def register_existing_agents(self):
        """Register all 7 agents with the Runtime."""

        from agents.script_agent import script_agent
        from agents.character_agent import character_agent
        from agents.storyboard_agent import storyboard_agent
        from agents.image_agent import image_agent
        from agents.image_to_video_agent import image_to_video_agent
        from agents.voice_agent import voice_agent
        from agents.video_agent import video_agent

        self.workflow_engine.register_agent("script", script_agent,
            description="Generates script with outline, characters, and episodes")
        self.workflow_engine.register_agent("character", character_agent,
            description="Enriches character visual descriptions")
        self.workflow_engine.register_agent("storyboard", storyboard_agent,
            description="Converts script to scene-by-scene storyboard")
        self.workflow_engine.register_agent("image", image_agent,
            description="Generates images via cloud API (DashScope/DALL-E)")
        self.workflow_engine.register_agent("image_to_video", image_to_video_agent,
            description="Converts images to video clips via cloud API (Kling/Runway)")
        self.workflow_engine.register_agent("voice", voice_agent,
            description="Generates voiceover via cloud TTS API (DashScope TTS)")
        self.workflow_engine.register_agent("video", video_agent,
            description="Merges video clips + audio + subtitles into final MP4")

        logger.info("Registered 7 agents with Runtime")

    def register_agent(self, name: str, agent_func, **kwargs):
        """Register a custom agent function.

        Args:
            name: Step name in the pipeline
            agent_func: async function(state: dict) -> dict
            **kwargs: Additional WorkflowEngine.register_agent() args
        """
        self.workflow_engine.register_agent(name, agent_func, **kwargs)

    def create_session(self, story_id: str, task_id: str = "",
                        prompt: str = "", genre: str = "",
                        session_id: str = "") -> Any:
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

    async def run(self, session_id: str) -> dict:
        """Execute the full pipeline for a session.

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

        initial_state = {
            "task_id": session.task_id,
            "story_id": session.story_id,
            "prompt": session.prompt,
            "genre": session.genre,
        }

        # Load blackboard from last checkpoint if resuming
        checkpoint = self.artifact_manager.load_latest_checkpoint(session_id)
        if checkpoint and checkpoint.get("state"):
            initial_state.update(checkpoint["state"])
            logger.info("Resumed from checkpoint (step: %s)", checkpoint.get("step"))

        return await self.workflow_engine.run(session_id, initial_state)

    async def rerun_step(self, session_id: str, step_name: str) -> dict:
        """Re-run a specific step (partial regeneration).

        This is the key feature enabled by Sessions + Artifacts:
        you can regenerate from any step without re-running earlier steps.

        Args:
            session_id: Session to modify
            step_name: Step to re-run from

        Returns:
            Result dict from the re-run
        """
        # Reset session from the target step
        self.session_manager.reset_from_step(session_id, step_name)

        # Load state from artifacts of completed steps
        session = self.session_manager.get(session_id)
        state = {"story_id": session.story_id}
        for completed_step in session.completed_steps:
            artifact = self.artifact_manager.load_json(session_id, completed_step)
            if artifact:
                if isinstance(artifact, dict):
                    state.update(artifact)

        return await self.workflow_engine.run(session_id, state)

    def get_stats(self) -> dict:
        """Get comprehensive Runtime statistics."""
        return {
            "version": "3.5.0",
            "workflow_engine": self.workflow_engine.get_stats(),
            "session_manager": self.session_manager.get_stats(),
            "director": self.director.get_stats(),
            "planner": self.planner.get_stats(),
            "quality_engine": self.quality_engine.get_stats(),
            "retry_engine": self.retry_engine.get_stats(),
            "memory": self.memory.get_stats(),
            "trace": self.trace.get_stats(),
            "adapters": self.adapter_registry.list_adapters(),
            "agent_registry": self.agent_registry.get_stats(),
        }


# Global singleton
_runtime: StoryFlowRuntime | None = None


def get_runtime() -> StoryFlowRuntime:
    """Get the global StoryFlow Runtime instance."""
    global _runtime
    if _runtime is None:
        _runtime = StoryFlowRuntime()
        _runtime.register_existing_agents()
    return _runtime