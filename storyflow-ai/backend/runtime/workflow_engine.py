"""Workflow Engine - Orchestrates the story pipeline with Director decisions and A2A communication.

Replaces RuntimeWorkflowRunner with these V1.5 capabilities:
1. Director integration: LLM-based analysis after each step with 5 decision types
2. ROLLBACK: Go back to a previous step and re-execute from there
3. MODIFY_AND_RETRY (REWRITE_PROMPT): Inject improved prompt and re-run
4. A2A messages: Structured context/feedback/constraint passing between agents
5. StoryMemory integration: Query memory before each step for context
"""
from __future__ import annotations
import logging
import time
from typing import Any, Callable, Awaitable, Optional

from runtime.director import (
    Director, DirectorDecision, DirectorVerdict, ArtifactManager,
)
from runtime.event_bus import EventBus, EventType, Event, get_event_bus

logger = logging.getLogger(__name__)

LegacyAgentFunc = Callable[[dict], Awaitable[dict] | dict]


class WorkflowEngine:
    """Orchestrates the story generation pipeline with Director brain and A2A communication.

    Pipeline: script -> character -> storyboard -> image -> voice -> video

    After each step, the Director analyzes output and decides:
    - PROCEED: continue to next step
    - RETRY: re-run current step with same inputs
    - ROLLBACK: go back to a previous step, remove artifacts, re-execute
    - REWRITE_PROMPT: modify prompt/state and re-run current step
    - SKIP: log warning, continue to next step

    Additionally, between steps, A2A messages carry structured context,
    constraints, and feedback to the next agent.
    """
    PIPELINE_ORDER = ["script", "character", "storyboard", "image", "voice", "video"]
    MAX_ROLLBACKS = 2
    STEP_PROGRESS = {
        "init": 0, "script": 10, "character": 25, "storyboard": 40,
        "image": 65, "voice": 80, "video": 95, "done": 100,
    }

    def __init__(
        self,
        director: Director | None = None,
        artifact_manager: ArtifactManager | None = None,
        conversation_bus=None,
        story_memory=None,
        event_bus=None,
    ):
        self.director = director
        self.artifact_manager = artifact_manager or (director.artifact_manager if director else ArtifactManager())
        self.conversation_bus = conversation_bus
        self.story_memory = story_memory
        self.event_bus = event_bus or get_event_bus()
        self._registered_agents: dict[str, LegacyAgentFunc] = {}
        self._rollback_count = 0
        self._insert_step_registry: dict[str, Callable] = {}

    def register_insert_step(self, step_type: str, func: Callable):
        """Register a custom insert step function.

        Insert steps are remediation actions the Director can request.
        Built-in types: 'consistency_check', 'style_extract', 'character_verify'

        Args:
            step_type: Unique identifier for the insert step type.
            func: async function(state, verdict) -> dict
        """
        self._insert_step_registry[step_type] = func
        logger.info("[WorkflowEngine] Insert step registered: %s", step_type)

    async def _store_to_story_memory(
        self, agent_id: str, output: dict, state: dict, conversation_id: str,
    ):
        """Store step output to StoryMemory for downstream agents.

        Phase 3 integration: After each successful step, persist key
        information into the appropriate memory dimension.
        """
        try:
            if agent_id == "character":
                await self.story_memory.populate_from_state(state, conversation_id)
            elif agent_id == "storyboard":
                for scene in state.get("storyboard", []):
                    await self.story_memory.store_scene(scene, conversation_id)
            elif agent_id == "image":
                for img in output.get("images", []):
                    await self.story_memory.store_visual(
                        scene_no=img.get("scene_no", 0),
                        image_url=img.get("image_url", ""),
                        image_prompt=img.get("prompt", ""),
                        conversation_id=conversation_id,
                    )
            logger.debug("[StoryMemory] Stored %s output to memory", agent_id)
        except Exception as e:
            logger.warning("[StoryMemory] Store failed for %s: %s", agent_id, e)

    def register_agent(self, agent_id: str, agent_func: LegacyAgentFunc):
        """Register an agent function for the pipeline."""
        self._registered_agents[agent_id] = agent_func
        logger.info("[WorkflowEngine] Agent registered: %s", agent_id)

    async def run_pipeline(
        self,
        task_id: str,
        story_id: str,
        prompt: str,
        genre: str,
        progress_callback=None,
        persist_callback=None,
        conversation_id: str = "",
        trace_id: str = "",
    ) -> dict:
        """Execute the full story pipeline with Director brain and A2A messages.

        Args:
            task_id: Task tracking ID.
            story_id: Story database ID.
            prompt: User's creative prompt.
            genre: Story genre.
            progress_callback: Async callback(step, progress_dict).
            persist_callback: Async callback(step, state) for DB persistence.
            conversation_id: Conversation ID for A2A tracking.
            trace_id: Trace ID for observability.

        Returns:
            Final state dict with all pipeline results.
        """
        # Build A2A conversation ID if not provided
        if not conversation_id:
            import uuid as _uuid
            conversation_id = _uuid.uuid4().hex[:16]

        # Initial state
        state: dict[str, Any] = {
            "task_id": task_id, "story_id": story_id,
            "prompt": prompt, "genre": genre,
            "outline": "", "characters": [],
            "episodes": [], "storyboard": [],
            "images": [], "audios": [],
            "video_path": "",
            "current_step": "init", "status": "running", "error": "",
        }

        pipeline = list(self.PIPELINE_ORDER)
        available = [a for a in pipeline if a in self._registered_agents]
        if not available:
            raise ValueError("No agents registered with WorkflowEngine")

        # Send A2A messages between steps
        async def _send_a2a(
            from_agent: str, to_agent: str,
            step_output: dict, validation_result: dict | None,
            step_error: str | None,
        ):
            if not self.conversation_bus:
                return
            from runtime.agent_conversation import AgentConversationBus
            msg = self.conversation_bus.build_handoff_message(
                from_agent=from_agent, to_agent=to_agent,
                state=state, agent_output=step_output,
                validation_result=validation_result,
                error=step_error,
                conversation_id=conversation_id,
            )
            self.conversation_bus.send_message(msg, conversation_id)
            logger.info(
                "[A2A] %s -> %s: %s",
                from_agent, to_agent, msg.message_type,
            )

        # Main pipeline execution loop
        pipeline_idx = 0
        while pipeline_idx < len(available):
            agent_id = available[pipeline_idx]
            next_agent_id = available[pipeline_idx + 1] if pipeline_idx + 1 < len(available) else ""
            agent_func = self._registered_agents[agent_id]
            start_time = time.time()
            retry = False
            skip = False

            # Phase 3: Inject StoryMemory context
            if self.story_memory:
                try:
                    memory_ctx = await self.story_memory.get_context(agent_id, state)
                    if memory_ctx:
                        state["_story_memory_context"] = memory_ctx
                        logger.debug("[StoryMemory] Injected context for %s (%d chars)",
                                     agent_id, len(memory_ctx))
                except Exception as e:
                    logger.warning("[StoryMemory] Context injection failed for %s: %s", agent_id, e)

            # Phase 2: Inject A2A messages into state for next agent
            if self.conversation_bus and self.conversation_bus.get_messages_for(agent_id, conversation_id):
                a2a_msgs = self.conversation_bus.get_messages_for(agent_id, conversation_id)
                constraints_list = []
                for m in a2a_msgs:
                    constraints_list.extend(m.constraints)
                    if m.feedback:
                        state["_a2a_feedback"] = "; ".join(m.feedback)
                if constraints_list:
                    state["_a2a_constraints"] = constraints_list
                self.conversation_bus.mark_delivered(agent_id, conversation_id)
                a2a_summary = self.conversation_bus.get_summary(conversation_id)
                if a2a_summary:
                    state["_a2a_history"] = a2a_summary

            # Emit STEP_STARTED event
            await self.event_bus.publish(Event(
                type=EventType.STEP_STARTED,
                data={"agent_id": agent_id, "story_id": story_id, "step": agent_id, "trace_id": trace_id, "conversation_id": conversation_id},
                session_id="",
                source=agent_id,
            ))

            step_error = None
            step_output = None
            validation_result = None
            verdict = None  # Ensure always defined for post-loop check

            for attempt in range(3):  # max 3 attempts (1 initial + 2 retries)
                retry = False
                skip = False

                try:
                    result = await agent_func(state)
                    if not isinstance(result, dict):
                        result = {"result": result}
                    state.update(result)
                    step_output = result

                    latency = (time.time() - start_time) * 1000

                    # Emit STEP_COMPLETED event
                    after_event = Event(
                        type=EventType.STEP_COMPLETED,
                        data={
                        "agent_id": agent_id, "success": True,
                        "adapter": False,
                        "output": step_output,
                        "latency_ms": latency,
                        "trace_id": trace_id,
                        "conversation_id": conversation_id,
                    },
                    session_id="",
                    source=agent_id,
                )
                    await self.event_bus.publish(after_event)

                    validation_result = after_event.data.get("validation_result", {})
                    validation_failed = after_event.data.get("validation_failed", False)

                    # Phase 1: Director analysis
                    verdict = await self.director.analyze_step(
                        agent_id=agent_id,
                        output=step_output,
                        error=None,
                        validation_result=validation_result,
                        conversation_id=conversation_id,
                        trace_id=trace_id,
                    )

                    # Execute Director decision
                    if verdict.decision == DirectorDecision.PROCEED:
                        self.director.reset_retry_count(agent_id)
                        break

                    if verdict.decision == DirectorDecision.RETRY:
                        logger.info(
                            "[Director] RETRY %s (attempt %d): %s",
                            agent_id, attempt + 1, verdict.reasoning[:100],
                        )
                        await self.event_bus.publish(Event(
                            type=EventType.STEP_RETRY,
                            data={
                                "agent_id": agent_id, "attempt": attempt + 1,
                                "max_retries": self.director.max_retries_per_step,
                                "reasoning": verdict.reasoning,
                                "trace_id": trace_id,
                            },
                            source=agent_id,
                        ))
                        retry = True
                        continue

                    if verdict.decision == DirectorDecision.REWRITE_PROMPT:
                        logger.info(
                            "[Director] REWRITE_PROMPT %s: %s",
                            agent_id, verdict.reasoning[:100],
                        )
                        if verdict.modified_prompt:
                            state["_retry_hint"] = verdict.modified_prompt
                        await self.event_bus.publish(Event(
                            type=EventType.STEP_RETRY,
                            data={
                                "agent_id": agent_id, "attempt": attempt + 1,
                                "reasoning": "REWRITE_PROMPT",
                                "modified_prompt": verdict.modified_prompt[:200],
                                "trace_id": trace_id,
                            },
                            source=agent_id,
                        ))
                        retry = True
                        continue

                    if verdict.decision == DirectorDecision.SKIP:
                        logger.warning(
                            "[Director] SKIP %s: %s", agent_id, verdict.reasoning[:100],
                        )
                        skip = True
                        break

                    if verdict.decision == DirectorDecision.ROLLBACK:
                        target = verdict.target_step or "character"
                        logger.warning(
                            "[Director] ROLLBACK from %s to %s (attempt %d): %s",
                            agent_id, target, self._rollback_count + 1, verdict.reasoning[:100],
                        )
                        await self.event_bus.publish(Event(
                            type=EventType.DIRECTOR_DECISION,
                            data={
                                "from": agent_id, "target": target,
                                "reasoning": verdict.reasoning,
                                "trace_id": trace_id,
                            },
                            source=agent_id,
                        ))
                        self._rollback_count += 1

                        if self._rollback_count > self.MAX_ROLLBACKS:
                            logger.error("[Director] Max rollbacks (%d) exceeded, proceeding", self.MAX_ROLLBACKS)
                            break

                        # Remove artifacts from target step onward
                        self.artifact_manager.remove_from(target)
                        # Reset retry counts for affected steps
                        target_idx = self.PIPELINE_ORDER.index(target) if target in self.PIPELINE_ORDER else 0
                        for aff_agent in self.PIPELINE_ORDER[target_idx:]:
                            self.director.reset_retry_count(aff_agent)
                        # Clear A2A messages for affected steps
                        if self.conversation_bus:
                            for aff_agent in self.PIPELINE_ORDER[target_idx:]:
                                pending = self.conversation_bus.get_messages_for(aff_agent, conversation_id)
                                for p in pending:
                                    p.metadata["delivered"] = True

                        # Rollback pipeline index
                        pipeline_idx = target_idx - 1
                        logger.info(
                            "[Director] Pipeline rolled back to index %d (%s)",
                            pipeline_idx, self.PIPELINE_ORDER[pipeline_idx] if pipeline_idx >= 0 else "done",
                        )
                        break

                    if verdict.decision == DirectorDecision.INSERT_STEP:
                        logger.info("[Director] INSERT_STEP requested for %s", agent_id)
                        insert_config = verdict.insert_step_config or {}
                        insert_type = insert_config.get("type", "consistency_check")
                        insert_func = self._insert_step_registry.get(insert_type)

                        if insert_func:
                            try:
                                logger.info(
                                    "[Director] Executing insert step '%s' before %s",
                                    insert_type, agent_id,
                                )
                                insert_result = await insert_func(state, verdict)
                                if isinstance(insert_result, dict):
                                    state.update(insert_result)
                                await self.event_bus.publish(Event(
                                    type=EventType.DIRECTOR_DECISION,
                                    data={
                                        "agent_id": agent_id,
                                        "insert_type": insert_type,
                                        "insert_result": insert_result,
                                        "trace_id": trace_id,
                                    },
                                    source=agent_id,
                                ))
                            except Exception as insert_err:
                                logger.error(
                                    "[Director] Insert step '%s' failed: %s",
                                    insert_type, insert_err,
                                )
                        else:
                            logger.warning(
                                "[Director] Unknown insert step type: %s, skipping",
                                insert_type,
                            )
                        break

                    # Unknown decision — proceed
                    break

                except Exception as e:
                    step_error = f"{type(e).__name__}: {str(e)}"
                    logger.error("[WorkflowEngine] Agent %s failed: %s", agent_id, step_error[:200])

                    await self.event_bus.publish(Event(
                        type=EventType.STEP_FAILED,
                        data={"agent_id": agent_id, "error": step_error, "trace_id": trace_id},
                        source=agent_id,
                    ))

                    # Let Director analyze the error
                    error_verdict = await self.director.analyze_step(
                        agent_id=agent_id, output=None, error=step_error,
                        validation_result=None,
                        conversation_id=conversation_id, trace_id=trace_id,
                    )
                    if error_verdict.decision == DirectorDecision.SKIP:
                        logger.warning("[Director] Skipping failed %s", agent_id)
                        skip = True
                        break
                    # If Director says PROCEED or any other decision on error,
                    # we can't continue without output — skip to avoid infinite loop
                    if attempt >= 1:  # Already retried once
                        logger.warning(
                            "[Director] Step %s still failing after error analysis, skipping",
                            agent_id,
                        )
                        skip = True
                        break
                    # First attempt: let the retry loop try again

            # After step completion (or skip)
            if skip:
                logger.warning("[WorkflowEngine] Skipped step %s", agent_id)
            else:
                # Store artifact
                if step_output:
                    self.artifact_manager.store(agent_id, step_output)

                # Send A2A handoff message to next agent
                if next_agent_id:
                    await _send_a2a(
                        from_agent=agent_id, to_agent=next_agent_id,
                        step_output=step_output or {},
                        validation_result=validation_result,
                        step_error=step_error,
                    )

            # Incremental persistence
            if persist_callback and not skip:
                try:
                    await persist_callback(agent_id, state)
                except Exception as e:
                    logger.warning("[WorkflowEngine] Persist failed for %s: %s", agent_id, e)

            # Progress report
            if progress_callback:
                pct = self.STEP_PROGRESS.get(agent_id, 0)
                await progress_callback(agent_id, {
                    "task_id": task_id, "progress": pct,
                    "current_step": agent_id,
                    "message": f"{agent_id} completed (WorkflowEngine v1.5)",
                })

            # Advance pipeline if we didn't rollback
            # (skip still advances — the step is intentionally skipped)
            if not retry and (verdict is None or verdict.decision != DirectorDecision.ROLLBACK):
                # Phase 3: Store step output to StoryMemory after successful step
                if self.story_memory and step_output and not skip:
                    await self._store_to_story_memory(
                        agent_id, step_output, state, conversation_id,
                    )
                pipeline_idx += 1

        # Final cleanup
        state.pop("_retry_hint", None)
        state.pop("_story_memory_context", None)
        state.pop("_a2a_feedback", None)
        state.pop("_a2a_constraints", None)
        state.pop("_a2a_history", None)
        state.pop("_character_consistency", None)
        state.pop("_existing_character_profiles", None)
        state.pop("_character_profiles_for_verify", None)
        state.pop("_consistency_warnings", None)

        logger.info(
            "[WorkflowEngine] Pipeline completed | task=%s | director_decisions=%d | rollbacks=%d",
            task_id, self.director._total_decisions, self._rollback_count,
        )
        return state

    def get_stats(self) -> dict:
        return {
            "director": self.director.get_stats() if self.director else {},
            "artifacts": len(self.artifact_manager.get_all()),
            "rollback_count": self._rollback_count,
        }