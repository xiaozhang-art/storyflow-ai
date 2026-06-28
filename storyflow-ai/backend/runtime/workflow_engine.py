"""Workflow Engine - Executes pipeline steps with EventBus, Blackboard, Hooks, and Artifacts.

The WorkflowEngine is the core execution loop of the Runtime. It:
    1. Reads the next step from the Session
    2. Runs before-hooks (can modify context)
    3. Calls the agent function
    4. Saves artifacts
    5. Updates the Blackboard
    6. Runs after-hooks (can validate/retry)
    7. Publishes events
    8. Moves to the next step

V1: Sequential execution (same as current pipeline)
V2+: Director can intervene, steps can be parallel
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from runtime.event_bus import EventBus, EventType, Event
from runtime.blackboard import Blackboard
from runtime.artifact_manager import ArtifactManager
from runtime.session_manager import SessionManager, Session, SessionStatus, get_session_manager
from runtime.hooks import HookFramework, StepContext, HookAbort, ErrorAction

logger = logging.getLogger(__name__)


# Agent function type: takes state dict, returns result dict
AgentFunc = Callable[[dict], Coroutine[Any, Any, dict]]


@dataclass
class PipelineStep:
    """Definition of a single step in a pipeline."""
    name: str
    agent_func: AgentFunc | None = None
    required_artifacts: list[str] = field(default_factory=list)
    produces_artifacts: list[str] = field(default_factory=list)
    description: str = ""


class WorkflowEngine:
    """Executes pipeline workflows with full Runtime support.

    Features:
        - Sequential or DAG-based execution
        - Before/after/error hooks
        - Artifact management
        - Blackboard state
        - EventBus notifications
        - Retry with exponential backoff
        - Session tracking for partial regeneration
    """

    # Default pipeline definition (V1 - same as current)
    DEFAULT_PIPELINE = [
        "script",
        "character",
        "storyboard",
        "image",
        "voice",
        "video",
    ]

    def __init__(
        self,
        event_bus: EventBus | None = None,
        artifact_manager: ArtifactManager | None = None,
        session_manager: SessionManager | None = None,
        hooks: HookFramework | None = None,
        max_retries: int = 3,
    ):
        self.event_bus = event_bus or EventBus()
        self.artifact_manager = artifact_manager or ArtifactManager()
        self.session_manager = session_manager or get_session_manager()
        self.hooks = hooks or HookFramework()
        self.max_retries = max_retries

        # Registry: step_name → agent function
        self._agents: dict[str, AgentFunc] = {}

        # Registry: step_name → PipelineStep definition
        self._steps: dict[str, PipelineStep] = {}

    def register_agent(self, name: str, agent_func: AgentFunc,
                       required_artifacts: list[str] | None = None,
                       produces_artifacts: list[str] | None = None,
                       description: str = ""):
        """Register an agent function for a pipeline step.

        This is how agents are plugged into the Runtime without modifying
        any existing agent code.
        """
        self._agents[name] = agent_func
        self._steps[name] = PipelineStep(
            name=name,
            agent_func=agent_func,
            required_artifacts=required_artifacts or [],
            produces_artifacts=produces_artifacts or [name],
            description=description or f"{name} agent",
        )
        logger.info("Registered agent: %s", name)

    def get_pipeline(self, session_id: str) -> list[str]:
        """Get the pipeline steps for a session.

        V1: Returns DEFAULT_PIPELINE
        V2.5+: Returns dynamic pipeline from Planner
        """
        session = self.session_manager.get(session_id)
        if session and session.metadata.get("pipeline"):
            return session.metadata["pipeline"]
        return list(self.DEFAULT_PIPELINE)

    async def run(self, session_id: str, initial_state: dict | None = None) -> dict:
        """Execute the full pipeline for a session.

        Args:
            session_id: Session to run
            initial_state: Initial state (prompt, genre, etc.)

        Returns:
            Final state dict with all results
        """
        session = self.session_manager.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Initialize blackboard with initial state
        blackboard = Blackboard(session_id=session_id, event_bus=self.event_bus)
        if initial_state:
            for key, value in initial_state.items():
                blackboard.set(key, value, notify=False)

        self.session_manager.update_status(session_id, SessionStatus.RUNNING)

        # Check for resumable state
        if session.completed_steps:
            logger.info("Session %s resuming from step %s (completed: %s)",
                        session_id, session.current_step or session.completed_steps[-1],
                        session.completed_steps)

        pipeline = self.get_pipeline(session_id)
        state = dict(initial_state or {})

        try:
            for step_name in pipeline:
                if self.session_manager.is_step_completed(session_id, step_name):
                    logger.info("Skipping completed step: %s", step_name)
                    continue

                result = await self._execute_step(
                    session_id=session_id,
                    step_name=step_name,
                    state=state,
                    blackboard=blackboard,
                )

                if result:
                    state.update(result)
                    blackboard.update(result)

                self.session_manager.complete_step(session_id, step_name)

                # Save checkpoint
                self.artifact_manager.save_checkpoint(session_id, step_name, state)

            self.session_manager.update_status(session_id, SessionStatus.COMPLETED)
            await self.event_bus.publish_event(
                EventType.SESSION_COMPLETED,
                data={"session_id": session_id},
                session_id=session_id,
                source="workflow_engine",
            )
            logger.info("Session %s completed successfully", session_id)
            return state

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error("Session %s failed at step %s: %s", session_id,
                         session.current_step, error_msg)
            self.session_manager.fail_session(session_id, session.current_step, error_msg)
            await self.event_bus.publish_event(
                EventType.SESSION_FAILED,
                data={"session_id": session_id, "error": error_msg,
                      "step": session.current_step},
                session_id=session_id,
                source="workflow_engine",
            )
            raise

    async def run_single_step(self, session_id: str, step_name: str,
                              state: dict, blackboard: Blackboard | None = None) -> dict:
        """Execute a single step (for partial regeneration).

        Args:
            session_id: Session ID
            step_name: Step to execute
            state: Current state
            blackboard: Optional blackboard instance

        Returns:
            Result dict from the agent
        """
        if blackboard is None:
            blackboard = Blackboard(session_id=session_id, event_bus=self.event_bus)
            blackboard.set_all(state)

        return await self._execute_step(
            session_id=session_id,
            step_name=step_name,
            state=state,
            blackboard=blackboard,
        )

    async def _execute_step(self, session_id: str, step_name: str,
                             state: dict, blackboard: Blackboard) -> dict:
        """Execute a single pipeline step with hooks, retry, and artifact saving.

        This is the core execution method that implements:
            1. Build StepContext
            2. Run before-hooks
            3. Load required artifacts from cache
            4. Call agent function
            5. Save produced artifacts
            6. Update blackboard
            7. Run after-hooks
            8. Handle errors with retry logic
        """
        agent_func = self._agents.get(step_name)
        if not agent_func:
            logger.warning("No agent registered for step '%s', skipping", step_name)
            return {}

        context = StepContext(
            step_name=step_name,
            session_id=session_id,
            blackboard=blackboard,
            artifact_manager=self.artifact_manager,
            extra=state,
        )

        self.session_manager.start_step(session_id, step_name)

        # Notify: step started
        await self.event_bus.publish_event(
            EventType.STEP_STARTED,
            data={"step": step_name, "attempt": context.attempt},
            session_id=session_id,
            source="workflow_engine",
        )

        attempt = 0
        last_error = None

        while attempt < self.max_retries:
            attempt += 1
            context.attempt = attempt
            last_error = None

            try:
                # Run before-hooks
                context = await self.hooks.run_before(context)

                # Call the agent
                logger.info("[Session %s] Executing step '%s' (attempt %d/%d)",
                            session_id, step_name, attempt, self.max_retries)
                result = await agent_func(context.extra)

                # Save artifacts
                await self._save_step_artifacts(session_id, step_name, result)

                # Run after-hooks (may raise HookAbort for retry)
                result = await self.hooks.run_after(context, result)

                # Notify: step completed
                await self.event_bus.publish_event(
                    EventType.STEP_COMPLETED,
                    data={"step": step_name, "attempt": attempt},
                    session_id=session_id,
                    source="workflow_engine",
                )

                logger.info("[Session %s] Step '%s' completed", session_id, step_name)
                return result if isinstance(result, dict) else {}

            except HookAbort as e:
                if e.retry and attempt < self.max_retries:
                    logger.warning("[Session %s] Hook requested retry for '%s': %s",
                                   session_id, step_name, e)
                    if e.fallback_data is not None:
                        return e.fallback_data if isinstance(e.fallback_data, dict) else {}
                    await self.event_bus.publish_event(
                        EventType.STEP_RETRY,
                        data={"step": step_name, "attempt": attempt, "reason": str(e)},
                        session_id=session_id,
                        source="hooks",
                    )
                    continue
                else:
                    logger.error("[Session %s] Hook abort (no retry): %s", session_id, e)
                    raise

            except Exception as e:
                last_error = e
                logger.error("[Session %s] Step '%s' failed (attempt %d): %s",
                             session_id, step_name, attempt, e)

                # Run error-hooks
                action = await self.hooks.run_on_error(context, e)

                if action == ErrorAction.RETRY and attempt < self.max_retries:
                    wait_time = min(2 ** attempt, 10)
                    logger.info("[Session %s] Retrying '%s' in %ds (attempt %d)",
                                session_id, step_name, wait_time, attempt)
                    await self.event_bus.publish_event(
                        EventType.STEP_RETRY,
                        data={"step": step_name, "attempt": attempt,
                              "reason": str(e), "wait": wait_time},
                        session_id=session_id,
                        source="workflow_engine",
                    )
                    await asyncio.sleep(wait_time)
                    continue
                elif action == ErrorAction.CONTINUE:
                    logger.warning("[Session %s] Error hook says continue, skipping '%s'",
                                   session_id, step_name)
                    return {}
                elif action == ErrorAction.FALLBACK:
                    logger.warning("[Session %s] Using fallback for '%s'",
                                   session_id, step_name)
                    return {}
                else:
                    raise

        # All retries exhausted
        raise RuntimeError(
            f"Step '{step_name}' failed after {self.max_retries} attempts. "
            f"Last error: {last_error}"
        )

    async def _save_step_artifacts(self, session_id: str, step_name: str, result: dict):
        """Save step results as artifacts."""
        if not result:
            return

        # Save the full step result as JSON
        self.artifact_manager.save_json(session_id, step_name, result)

        # Save specific artifacts based on step type
        if step_name == "script" and "episodes" in result:
            self.artifact_manager.save_json(
                session_id, "script", result["episodes"], "episodes.json")
        elif step_name == "character" and "characters" in result:
            self.artifact_manager.save_json(
                session_id, "character", result["characters"], "characters.json")
        elif step_name == "storyboard" and "storyboard" in result:
            self.artifact_manager.save_json(
                session_id, "storyboard", result["storyboard"], "scenes.json")

        await self.event_bus.publish_event(
            EventType.ARTIFACT_SAVED,
            data={"step": step_name, "type": "json"},
            session_id=session_id,
            source="workflow_engine",
        )

    def get_stats(self) -> dict:
        """Get workflow engine statistics."""
        return {
            "registered_agents": list(self._agents.keys()),
            "pipeline": self.DEFAULT_PIPELINE,
        }