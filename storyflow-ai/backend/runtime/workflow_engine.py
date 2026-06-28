"""Workflow Engine - Executes pipeline steps with full Runtime support.

The WorkflowEngine is the core execution loop of the Runtime. It:
    1. Loads pipeline definition from YAML DSL or uses default
    2. Planner decomposes into a task DAG (V2.5+)
    3. For each step:
       a. Run before-hooks (can modify context)
       b. Call the agent function
       c. Save artifacts
       d. Update the Blackboard
       e. Run after-hooks (can validate/retry)
       f. Run quality checks
       g. Director reviews and may intervene
       h. Publish events
    4. Supports parallel execution for steps in the same parallel_group
    5. Session tracking enables partial regeneration
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

import yaml

from runtime.event_bus import EventBus, EventType, Event
from runtime.blackboard import Blackboard
from runtime.artifact_manager import ArtifactManager
from runtime.session_manager import SessionManager, Session, SessionStatus, get_session_manager
from runtime.hooks import HookFramework, StepContext, HookAbort, ErrorAction
from runtime.director import DirectorAgent, Decision, DecisionType
from runtime.quality import QualityEngine
from runtime.retry_engine import RetryEngine
from runtime.memory import MemoryRuntime
from runtime.trace import TraceRuntime

logger = logging.getLogger(__name__)


# Agent function type: takes state dict, returns result dict
AgentFunc = Callable[[dict], Coroutine[Any, Any, dict]]


@dataclass
class PipelineStep:
    """Definition of a single step in a pipeline."""
    name: str
    agent: str = ""
    agent_func: AgentFunc | None = None
    depends_on: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    produces_artifacts: list[str] = field(default_factory=list)
    description: str = ""
    parallel_group: str = ""  # Steps in the same group run concurrently


@dataclass
class DSLWorkflow:
    """A workflow loaded from a YAML DSL file."""
    name: str
    description: str
    version: str
    steps: list[PipelineStep]
    quality_config: dict = field(default_factory=dict)
    director_config: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "DSLWorkflow":
        """Load a workflow definition from a YAML file."""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow DSL not found: {yaml_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        steps = []
        for step_data in data.get("steps", []):
            steps.append(PipelineStep(
                name=step_data.get("id", step_data.get("name", "")),
                agent=step_data.get("agent", step_data.get("id", "")),
                depends_on=step_data.get("depends_on", []),
                description=step_data.get("description", ""),
                required_artifacts=step_data.get("input", []),
                produces_artifacts=step_data.get("output", []),
                parallel_group=step_data.get("parallel_group", ""),
            ))

        return cls(
            name=data.get("name", "unnamed"),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            steps=steps,
            quality_config=data.get("quality", {}),
            director_config=data.get("director", {}),
        )

    def get_execution_order(self) -> list[list[str]]:
        """Get steps grouped by execution wave (for parallel execution).

        Returns a list of waves, where each wave is a list of step names
        that can run in parallel.
        """
        step_map = {s.name: s for s in self.steps}
        completed = set()
        waves = []
        max_iterations = len(self.steps) + 1

        while len(completed) < len(self.steps) and max_iterations > 0:
            wave = []
            for step in self.steps:
                if step.name in completed:
                    continue
                if all(dep in completed for dep in step.depends_on):
                    wave.append(step.name)
            if not wave:
                break
            waves.append(wave)
            completed.update(wave)
            max_iterations -= 1

        return waves


class WorkflowEngine:
    """Executes pipeline workflows with full Runtime support.

    Features:
        - YAML DSL workflow definitions
        - DAG-based parallel execution
        - Before/after/error hooks
        - Artifact management
        - Blackboard state
        - EventBus notifications
        - Retry with exponential backoff
        - Director-driven decision making
        - Quality engine integration
        - Session tracking for partial regeneration
    """

    # Default pipeline (used when no DSL is loaded)
    DEFAULT_PIPELINE = [
        "script", "character", "storyboard", "image", "image_to_video", "voice", "video",
    ]

    def __init__(
        self,
        event_bus: EventBus | None = None,
        artifact_manager: ArtifactManager | None = None,
        session_manager: SessionManager | None = None,
        hooks: HookFramework | None = None,
        director: DirectorAgent | None = None,
        quality_engine: QualityEngine | None = None,
        retry_engine: RetryEngine | None = None,
        memory: MemoryRuntime | None = None,
        trace: TraceRuntime | None = None,
        max_retries: int = 3,
    ):
        self.event_bus = event_bus or EventBus()
        self.artifact_manager = artifact_manager or ArtifactManager()
        self.session_manager = session_manager or get_session_manager()
        self.hooks = hooks or HookFramework()
        self.director = director
        self.quality_engine = quality_engine
        self.retry_engine = retry_engine or RetryEngine()
        self.memory = memory or MemoryRuntime()
        self.trace = trace or TraceRuntime()
        self.max_retries = max_retries

        # Registry: step_name → agent function
        self._agents: dict[str, AgentFunc] = {}

        # Registry: step_name → PipelineStep definition
        self._steps: dict[str, PipelineStep] = {}

        # Loaded DSL workflow (if any)
        self._dsl: DSLWorkflow | None = None

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
            agent=name,
            agent_func=agent_func,
            required_artifacts=required_artifacts or [],
            produces_artifacts=produces_artifacts or [name],
            description=description or f"{name} agent",
        )
        logger.info("Registered agent: %s", name)

    def load_dsl(self, yaml_path: str):
        """Load a workflow definition from a YAML DSL file.

        The DSL defines the pipeline steps, dependencies, parallel groups,
        quality config, and director config. Agent functions must still be
        registered separately via register_agent().
        """
        self._dsl = DSLWorkflow.from_yaml(yaml_path)
        logger.info("Loaded DSL workflow: %s (v%s, %d steps)",
                     self._dsl.name, self._dsl.version, len(self._dsl.steps))

        # Merge DSL step definitions into the step registry
        for step in self._dsl.steps:
            if step.name not in self._steps:
                self._steps[step.name] = step

        # Apply DSL config
        if self._dsl.quality_config.get("enabled"):
            logger.info("Quality checks enabled for steps: %s",
                        self._dsl.quality_config.get("check_after", []))

    def get_pipeline(self, session_id: str) -> list[str]:
        """Get the linear pipeline steps for a session.

        Priority:
        1. Session metadata pipeline (from Planner)
        2. DSL-defined steps
        3. DEFAULT_PIPELINE
        """
        session = self.session_manager.get(session_id)
        if session and session.metadata.get("pipeline"):
            return session.metadata["pipeline"]

        if self._dsl:
            # Flatten DSL steps to linear order respecting dependencies
            waves = self._dsl.get_execution_order()
            return [step for wave in waves for step in wave]

        return list(self.DEFAULT_PIPELINE)

    def get_execution_waves(self, session_id: str) -> list[list[str]]:
        """Get execution waves for parallel execution.

        Returns a list of waves, where each wave is a list of step names
        that can run in parallel.
        """
        if self._dsl:
            waves = self._dsl.get_execution_order()
            # Filter out already-completed steps
            session = self.session_manager.get(session_id)
            if session:
                waves = [
                    [s for s in wave if not self.session_manager.is_step_completed(session_id, s)]
                    for wave in waves
                ]
                waves = [w for w in waves if w]
            return waves

        # No DSL: return linear pipeline as single-step waves
        pipeline = self.get_pipeline(session_id)
        return [[step] for step in pipeline]

    async def run(self, session_id: str, initial_state: dict | None = None) -> dict:
        """Execute the full pipeline for a session.

        Supports parallel execution when a DSL is loaded with parallel_groups.

        Args:
            session_id: Session to run
            initial_state: Initial state (prompt, genre, etc.)

        Returns:
            Final state dict with all results
        """
        session = self.session_manager.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Initialize blackboard
        blackboard = Blackboard(session_id=session_id, event_bus=self.event_bus)
        if initial_state:
            for key, value in initial_state.items():
                blackboard.set(key, value, notify=False)

        self.session_manager.update_status(session_id, SessionStatus.RUNNING)

        # Start trace
        trace_id = self.trace.start_trace(
            session_id,
            metadata={"prompt": state.get("prompt", ""), "genre": state.get("genre", "")},
        )
        root_span = self.trace._traces[trace_id].root_span if trace_id in self.trace._traces else None

        # Populate memory from initial state
        self.memory.session_id = session_id
        self.memory.populate_from_state(state)

        if session.completed_steps:
            logger.info("Session %s resuming from step %s (completed: %s)",
                        session_id,
                        session.current_step or session.completed_steps[-1],
                        session.completed_steps)

        state = dict(initial_state or {})

        try:
            # Check if parallel execution is possible (DSL loaded)
            waves = self.get_execution_waves(session_id)
            is_parallel = any(len(wave) > 1 for wave in waves)

            if is_parallel:
                result_state = await self._run_parallel(session_id, waves, state, blackboard)
            else:
                # Linear execution (original behavior)
                pipeline = self.get_pipeline(session_id)
                result_state = await self._run_linear(session_id, pipeline, state, blackboard)

            self.session_manager.update_status(session_id, SessionStatus.COMPLETED)

            # End trace
            if root_span:
                self.trace.end_span(
                    root_span.span_id,
                    status="completed",
                    output_summary={"steps_completed": len(session.completed_steps)},
                )

            await self.event_bus.publish_event(
                EventType.SESSION_COMPLETED,
                data={"session_id": session_id},
                session_id=session_id,
                source="workflow_engine",
            )
            logger.info("Session %s completed successfully", session_id)
            return result_state

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error("Session %s failed at step %s: %s",
                         session_id, session.current_step, error_msg)
            self.session_manager.fail_session(session_id, session.current_step, error_msg)
            await self.event_bus.publish_event(
                EventType.SESSION_FAILED,
                data={"session_id": session_id, "error": error_msg,
                      "step": session.current_step},
                session_id=session_id,
                source="workflow_engine",
            )
            raise

    async def _run_linear(self, session_id: str, pipeline: list[str],
                          state: dict, blackboard: Blackboard) -> dict:
        """Execute pipeline steps sequentially."""
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
            self.artifact_manager.save_checkpoint(session_id, step_name, state)

        return state

    async def _run_parallel(self, session_id: str, waves: list[list[str]],
                            state: dict, blackboard: Blackboard) -> dict:
        """Execute pipeline steps in waves, with parallelism within each wave."""
        for wave in waves:
            if not wave:
                continue

            if len(wave) == 1:
                # Single step: run like linear
                step_name = wave[0]
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
                self.artifact_manager.save_checkpoint(session_id, step_name, state)
            else:
                # Multiple steps: run in parallel
                logger.info("Running parallel wave: %s", wave)
                results = await asyncio.gather(
                    *[self._execute_step(
                        session_id=session_id,
                        step_name=step_name,
                        state=dict(state),  # Pass copy to avoid race conditions
                        blackboard=blackboard,
                    ) for step_name in wave],
                    return_exceptions=True,
                )

                for step_name, result in zip(wave, results):
                    if isinstance(result, Exception):
                        logger.error("Parallel step %s failed: %s", step_name, result)
                        raise result
                    if result:
                        state.update(result)
                        blackboard.update(result)
                    self.session_manager.complete_step(session_id, step_name)
                    self.artifact_manager.save_checkpoint(session_id, step_name, state)

        return state

    async def run_single_step(self, session_id: str, step_name: str,
                              state: dict, blackboard: Blackboard | None = None) -> dict:
        """Execute a single step (for partial regeneration)."""
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
        """Execute a single pipeline step with hooks, retry, quality, and director.

        Execution flow:
            1. Build StepContext
            2. Run before-hooks
            3. Call agent function
            4. Save artifacts
            5. Update blackboard
            6. Run after-hooks
            7. Run quality checks (if enabled)
            8. Director reviews (if enabled)
            9. Handle errors with retry logic
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

        await self.event_bus.publish_event(
            EventType.STEP_STARTED,
            data={"step": step_name, "attempt": context.attempt},
            session_id=session_id,
            source="workflow_engine",
        )

        # Start trace span for this step
        step_span = self.trace.start_span(
            name=step_name,
            trace_id=session_id,
            step=step_name,
            input_summary={"attempt": 1},
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

                # Call the agent (with memory context)
                agent_input = dict(context.extra)
                memory_ctx = self.memory.build_context(step_name, state=agent_input)
                if memory_ctx:
                    agent_input["_memory_context"] = memory_ctx

                logger.info("[Session %s] Executing step '%s' (attempt %d/%d)",
                            session_id, step_name, attempt, self.max_retries)
                result = await agent_func(agent_input)

                # Save artifacts
                await self._save_step_artifacts(session_id, step_name, result)

                # Run after-hooks (may raise HookAbort for retry)
                result = await self.hooks.run_after(context, result)

                # Quality check (if enabled for this step)
                if self.quality_engine and self._should_quality_check(step_name):
                    qr = await self.quality_engine.check(
                        step_name, result, context=state, session_id=session_id
                    )
                    if not qr.passed and self.director and self.director.enabled:
                        # Let Director decide what to do
                        decision = await self.director.decide_on_quality_fail(
                            step_name, qr, session_id
                        )
                        if decision.type == DecisionType.RETRY and attempt < self.max_retries:
                            logger.warning("[Session %s] Director retry for '%s': %s",
                                           session_id, step_name, decision.reason)
                            await self.event_bus.publish_event(
                                EventType.STEP_RETRY,
                                data={"step": step_name, "attempt": attempt,
                                      "reason": decision.reason},
                                session_id=session_id,
                                source="director",
                            )
                            continue
                        elif decision.type == DecisionType.CONTINUE:
                            logger.info("[Session %s] Director says continue despite quality fail",
                                        session_id)
                        elif decision.type == DecisionType.ROLLBACK:
                            logger.warning("[Session %s] Director requests rollback to %s",
                                           session_id, decision.target_step)
                            # In linear mode, rollback is handled at a higher level
                            # For now, log and continue
                        elif decision.type == DecisionType.SKIP:
                            logger.info("[Session %s] Director skips step '%s'",
                                        session_id, step_name)
                            return {}

                # Update memory from step result
                self.memory.populate_from_state(result)
                self.memory.session.step_name = step_name
                self.memory.session.attempt = attempt

                # End trace span
                if step_span:
                    self.trace.end_span(
                        step_span.span_id,
                        status="completed",
                        output_summary={"keys": list(result.keys()) if isinstance(result, dict) else []},
                    )

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

                # End trace span (failed)
                if step_span:
                    self.trace.end_span(
                        step_span.span_id,
                        status="failed",
                        error=str(e),
                        retry_count=attempt - 1,
                    )

                # Consult Director if available
                if self.director and self.director.enabled:
                    decision = await self.director.decide_on_error(
                        step_name, e, state
                    )
                    if decision.type == DecisionType.RETRY and attempt < self.max_retries:
                        wait_time = min(2 ** attempt, 10)
                        logger.info("[Session %s] Director retry for '%s' in %ds",
                                    session_id, step_name, wait_time)
                        await self.event_bus.publish_event(
                            EventType.STEP_RETRY,
                            data={"step": step_name, "attempt": attempt,
                                  "reason": decision.reason, "wait": wait_time},
                            session_id=session_id,
                            source="director",
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    elif decision.type == DecisionType.SKIP:
                        logger.warning("[Session %s] Director skips '%s': %s",
                                       session_id, step_name, decision.reason)
                        return {}
                    elif decision.type == DecisionType.ABORT:
                        logger.error("[Session %s] Director aborts: %s",
                                     session_id, decision.reason)
                        raise RuntimeError(decision.reason) from e

                # No Director or Director says continue: use hook-based error handling
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

    def _should_quality_check(self, step_name: str) -> bool:
        """Check if quality checks are enabled for this step."""
        if not self.quality_engine or not self.quality_engine.enabled:
            return False
        if self._dsl and self._dsl.quality_config.get("enabled"):
            check_after = self._dsl.quality_config.get("check_after", [])
            return step_name in check_after
        return True  # Default: check all steps

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
        stats = {
            "registered_agents": list(self._agents.keys()),
            "pipeline": self.DEFAULT_PIPELINE,
        }
        if self._dsl:
            stats["dsl"] = {
                "name": self._dsl.name,
                "version": self._dsl.version,
                "steps": len(self._dsl.steps),
                "quality_enabled": self._dsl.quality_config.get("enabled", False),
            }
        return stats