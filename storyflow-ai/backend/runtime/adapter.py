"""Runtime Adapter - Bridges the new Agent OS Runtime with existing LangGraph agents.

This module provides backward compatibility: existing agents that work with
StoryState can be wrapped and executed through the new Runtime system,
enabling gradual migration without breaking the current pipeline.

v2.0: Now with Memory injection, Hook quality gates, and Skill-driven retry.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Awaitable

from runtime.mcp.envelope import MCPEnvelope, MessageType
from runtime.agent_runtime.context import RuntimeContext
from runtime.hook.dispatcher import HookEvent, get_hook_dispatcher
from runtime.hook import events as hook_events
from runtime.conversation.models import ConversationStatus

logger = logging.getLogger(__name__)

# Type for existing LangGraph agent functions
LegacyAgentFunc = Callable[[dict], Awaitable[dict] | dict]

# Maximum retries when quality gate fails
MAX_QUALITY_RETRIES = 2


def wrap_legacy_agent(
    agent_id: str,
    agent_func: LegacyAgentFunc,
    memory_manager=None,
    character_memory=None,
    skill_registry=None,
) -> Callable[[MCPEnvelope], Awaitable[MCPEnvelope]]:
    """Wrap a legacy LangGraph agent function into an A2A-compatible handler.

    v2.0 enhancements:
    - BEFORE_AGENT: inject character memory into state for relevant agents
    - AFTER_AGENT: run quality gate hooks, trigger retry on failure
    - Uses Skill constraints if a matching skill is registered

    Args:
        agent_id: The agent's identifier (e.g., "script", "character").
        agent_func: The original async function(state: dict) -> dict.
        memory_manager: Optional MemoryManager for context injection.
        character_memory: Optional CharacterMemoryService for consistency.
        skill_registry: Optional SkillRegistry for constraint lookup.

    Returns:
        An async function(envelope: MCPEnvelope) -> MCPEnvelope.
    """
    async def handler(envelope: MCPEnvelope) -> MCPEnvelope:
        hooks = get_hook_dispatcher()
        trace_id = envelope.trace_id
        conversation_id = envelope.source_session_id or ""

        # Build a StoryState-compatible dict from envelope
        state = {
            "task_id": envelope.metadata.get("task_id", ""),
            "story_id": envelope.metadata.get("story_id", ""),
            **envelope.payload,
        }

        logger.info("[Adapter] Executing agent %s via Runtime | trace=%s",
                     agent_id, trace_id[:8])

        # ─────────────────────────────────────────────────
        # BEFORE_AGENT: Memory injection
        # ─────────────────────────────────────────────────
        await hooks.emit(HookEvent(
            name=hook_events.BEFORE_AGENT,
            payload={"agent_id": agent_id, "adapter": True},
            trace_id=trace_id,
            session_id=conversation_id,
            agent_id=agent_id,
        ))

        # Inject character memory into relevant agents
        if character_memory and agent_id in ("character", "storyboard", "image"):
            await _inject_character_memory(state, agent_id, character_memory, conversation_id)

        # ─────────────────────────────────────────────────
        # EXECUTE: Run agent with quality-gated retry
        # ─────────────────────────────────────────────────
        result = None
        last_error = None
        last_validation = None

        for attempt in range(1, MAX_QUALITY_RETRIES + 2):  # 1 initial + N retries
            try:
                result = await agent_func(state)
                if not isinstance(result, dict):
                    result = {"result": result}

                # Merge result into state for next agent
                state.update(result)

                # ─────────────────────────────────────────
                # AFTER_AGENT: Quality gate check
                # ─────────────────────────────────────────
                after_event = HookEvent(
                    name=hook_events.AFTER_AGENT,
                    payload={
                        "agent_id": agent_id,
                        "success": True,
                        "adapter": True,
                        "output": result,
                    },
                    trace_id=trace_id,
                    session_id=conversation_id,
                    agent_id=agent_id,
                )

                # Emit synchronously so we can check validation result
                await hooks.emit_sync(after_event)

                validation_failed = after_event.payload.get("validation_failed", False)
                validation_result = after_event.payload.get("validation_result", {})

                if validation_failed and attempt <= MAX_QUALITY_RETRIES:
                    last_validation = validation_result
                    fix_suggestion = validation_result.get("fix_suggestion", "")
                    errors = validation_result.get("errors", [])

                    logger.warning(
                        "[Adapter] Quality gate failed for %s (attempt %d/%d): %s",
                        agent_id, attempt, MAX_QUALITY_RETRIES + 1,
                        "; ".join(errors),
                    )

                    # Emit ON_RETRY hook
                    await hooks.emit(HookEvent(
                        name=hook_events.ON_RETRY,
                        payload={
                            "agent_id": agent_id,
                            "attempt": attempt,
                            "max_retries": MAX_QUALITY_RETRIES,
                            "errors": errors,
                            "fix_suggestion": fix_suggestion,
                        },
                        trace_id=trace_id,
                        session_id=conversation_id,
                        agent_id=agent_id,
                    ))

                    # Try adaptive retry: inject fix suggestion into state
                    if fix_suggestion:
                        state["_retry_hint"] = fix_suggestion
                    continue

                # Either passed or out of retries
                last_validation = validation_result
                break

            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)}"
                logger.error("[Adapter] Agent %s failed: %s", agent_id, last_error)

                await hooks.emit(HookEvent(
                    name=hook_events.ON_ERROR,
                    payload={"agent_id": agent_id, "error": last_error, "adapter": True},
                    trace_id=trace_id,
                    agent_id=agent_id,
                ))

                if attempt <= MAX_QUALITY_RETRIES:
                    await hooks.emit(HookEvent(
                        name=hook_events.ON_RETRY,
                        payload={
                            "agent_id": agent_id,
                            "attempt": attempt,
                            "max_retries": MAX_QUALITY_RETRIES,
                            "error": last_error,
                        },
                        trace_id=trace_id,
                        session_id=conversation_id,
                        agent_id=agent_id,
                    ))
                    continue
                break

        # Build reply envelope
        if result:
            reply = envelope.reply(payload=result)
        else:
            reply = envelope.reply(payload={
                "error": last_error or "Unknown error",
                "success": False,
            })

        reply.metadata["agent_id"] = agent_id
        reply.metadata["adapter"] = True
        reply.metadata["validation"] = last_validation or {}

        # Emit final AFTER_AGENT
        await hooks.emit(HookEvent(
            name=hook_events.AFTER_AGENT,
            payload={
                "agent_id": agent_id,
                "success": result is not None,
                "adapter": True,
                "output": result or {},
                "validation": last_validation or {},
            },
            trace_id=trace_id,
            session_id=conversation_id,
            agent_id=agent_id,
        ))

        return reply

    handler.__name__ = f"adapted_{agent_id}"
    return handler


async def _inject_character_memory(
    state: dict,
    agent_id: str,
    character_memory,
    conversation_id: str,
):
    """Inject character memory into state for consistency-aware agents.

    - character agent: inject existing profiles (for multi-episode runs)
    - storyboard agent: inject consistency section into each episode
    - image agent: store consistency verification metadata
    """
    if agent_id == "character":
        # For multi-episode runs, check if we have existing profiles
        existing_profiles = await character_memory.load_all_character_profiles(
            conversation_id=conversation_id,
        )
        if existing_profiles:
            # Inject as context for the LLM to maintain consistency
            state["_existing_character_profiles"] = existing_profiles
            logger.info(
                "[Memory] Injected %d existing character profiles for consistency",
                len(existing_profiles),
            )

    elif agent_id == "storyboard":
        # Load character context and build consistency section
        character_names = [
            c.get("name", "") for c in state.get("characters", [])
        ]
        char_context = await character_memory.load_character_context(
            character_names=character_names if character_names else None,
            conversation_id=conversation_id,
        )
        if char_context:
            consistency_section = character_memory.build_consistency_section(char_context)
            state["_character_consistency"] = consistency_section
            logger.info("[Memory] Injected character consistency section for storyboard")

    elif agent_id == "image":
        # Load profiles for post-generation verification
        profiles = await character_memory.load_all_character_profiles(
            conversation_id=conversation_id,
        )
        if profiles:
            state["_character_profiles_for_verify"] = profiles
            logger.info(
                "[Memory] Loaded %d profiles for image consistency verification",
                len(profiles),
            )


class RuntimeWorkflowRunner:
    """Runs the story generation workflow through the new Runtime system.

    v2.0: Now with Memory, Hook quality gates, and Skill-driven execution.

    Pipeline: script -> character -> storyboard -> image -> voice -> video

    Enhancements over v1.0:
    1. Memory injection: Character profiles flow through the pipeline
    2. Quality gates: Each step is validated, retries on failure
    3. Skill validation: Output structure checked against skill definitions
    4. Incremental persistence: Results saved to DB after each step
    5. Character consistency: Memory-backed consistency enforcement
    """

    def __init__(
        self,
        control_server=None,
        conversation_manager=None,
        skill_registry=None,
        memory_manager=None,
        character_memory=None,
        hook_dispatcher=None,
    ):
        from runtime.message_bus.control_server import ControlServer
        from runtime.conversation.manager import ConversationManager
        from runtime.skill_engine.registry import SkillRegistry

        self.control_server = control_server
        self.conversation_manager = conversation_manager
        self.skill_registry = skill_registry or SkillRegistry()
        self.memory_manager = memory_manager
        self.character_memory = character_memory
        self.hook_dispatcher = hook_dispatcher or get_hook_dispatcher()

        self._registered_agents: dict[str, LegacyAgentFunc] = {}

    def register_agent(self, agent_id: str, agent_func: LegacyAgentFunc):
        """Register a legacy agent function to be wrapped by the Runtime."""
        self._registered_agents[agent_id] = agent_func

        if self.control_server:
            wrapped = wrap_legacy_agent(
                agent_id,
                agent_func,
                memory_manager=self.memory_manager,
                character_memory=self.character_memory,
                skill_registry=self.skill_registry,
            )
            self.control_server.register_agent(agent_id, wrapped)

        logger.info("[RuntimeRunner] Agent registered: %s", agent_id)

    async def run_pipeline(
        self,
        task_id: str,
        story_id: str,
        prompt: str,
        genre: str,
        progress_callback=None,
        persist_callback=None,
    ) -> dict:
        """Execute the full story pipeline through the Runtime.

        v2.0: With Memory, Hook quality gates, and incremental persistence.

        Args:
            task_id: Task ID for tracking.
            story_id: Story ID for database operations.
            prompt: User's story prompt.
            genre: Story genre.
            progress_callback: Optional async callback(step, progress_dict).
            persist_callback: Optional async callback(step, state) for DB persistence.

        Returns:
            Final state dict with all pipeline results.
        """
        from runtime.conversation.manager import ConversationManager

        if not self.conversation_manager:
            self.conversation_manager = ConversationManager(
                control_server=self.control_server,
            )

        agent_pipeline = ["script", "character", "storyboard", "image", "voice", "video"]

        # Check which agents are registered
        available_agents = [a for a in agent_pipeline if a in self._registered_agents]
        if not available_agents:
            raise ValueError("No agents registered with RuntimeWorkflowRunner")

        # Create a conversation for tracking
        conversation = await self.conversation_manager.create_conversation(
            goal=f"Generate story: {prompt[:100]}",
            agents=available_agents,
            metadata={"task_id": task_id, "story_id": story_id},
        )
        conversation_id = conversation.conversation_id

        # Build the pipeline graph
        self.conversation_manager.build_linear_pipeline(
            conversation_id,
            available_agents,
        )

        # Initial state
        state: dict[str, Any] = {
            "task_id": task_id,
            "story_id": story_id,
            "prompt": prompt,
            "genre": genre,
            "outline": "",
            "characters": [],
            "episodes": [],
            "storyboard": [],
            "images": [],
            "audios": [],
            "video_path": "",
            "current_step": "init",
            "status": "running",
            "error": "",
        }

        # ─────────────────────────────────────────────────
        # Execute each agent with Memory + Hook + Skill
        # ─────────────────────────────────────────────────
        hooks = self.hook_dispatcher

        for agent_id in available_agents:
            # Set agent to running
            graph = self.conversation_manager._graphs.get(conversation_id, {})
            if agent_id in graph:
                graph[agent_id].state = "running"

            agent_func = self._registered_agents[agent_id]
            start_time = time.time()

            # ── BEFORE: Memory injection ──
            if self.character_memory and agent_id in ("character", "storyboard", "image"):
                await _inject_character_memory(
                    state, agent_id, self.character_memory, conversation_id,
                )

            # ── BEFORE: Emit hook ──
            await hooks.emit(HookEvent(
                name=hook_events.BEFORE_AGENT,
                payload={
                    "agent_id": agent_id,
                    "story_id": story_id,
                    "step": agent_id,
                },
                trace_id=conversation_id,
                session_id="",
                agent_id=agent_id,
            ))

            try:
                # ── EXECUTE agent ──
                result = await agent_func(state)

                if isinstance(result, dict):
                    state.update(result)

                latency = (time.time() - start_time) * 1000

                # ── AFTER: Store to Memory (character profiles) ──
                if agent_id == "character" and self.character_memory:
                    characters = state.get("characters", [])
                    if characters:
                        await self.character_memory.store_character_profiles(
                            characters=characters,
                            story_id=story_id,
                            conversation_id=conversation_id,
                        )
                        logger.info(
                            "[Memory] Stored %d character profiles after character_agent",
                            len(characters),
                        )

                # ── AFTER: Image prompt consistency verification ──
                if agent_id == "storyboard" and self.character_memory:
                    await self._verify_storyboard_consistency(
                        state, conversation_id,
                    )

                # ── AFTER: Quality gate hook ──
                after_event = HookEvent(
                    name=hook_events.AFTER_AGENT,
                    payload={
                        "agent_id": agent_id,
                        "success": True,
                        "adapter": False,
                        "output": result if isinstance(result, dict) else {},
                        "latency_ms": latency,
                    },
                    trace_id=conversation_id,
                    session_id="",
                    agent_id=agent_id,
                )

                # Use emit_sync so we can check validation
                await hooks.emit_sync(after_event)

                validation_failed = after_event.payload.get("validation_failed", False)
                validation_result = after_event.payload.get("validation_result", {})

                # ── Quality gate retry loop ──
                if validation_failed:
                    for retry_attempt in range(1, MAX_QUALITY_RETRIES + 1):
                        errors = validation_result.get("errors", [])
                        fix_suggestion = validation_result.get("fix_suggestion", "")

                        logger.warning(
                            "[RuntimeRunner] Quality gate failed for %s (retry %d/%d): %s",
                            agent_id, retry_attempt, MAX_QUALITY_RETRIES,
                            "; ".join(errors),
                        )

                        await hooks.emit(HookEvent(
                            name=hook_events.ON_RETRY,
                            payload={
                                "agent_id": agent_id,
                                "attempt": retry_attempt,
                                "max_retries": MAX_QUALITY_RETRIES,
                                "errors": errors,
                                "fix_suggestion": fix_suggestion,
                            },
                            trace_id=conversation_id,
                            agent_id=agent_id,
                        ))

                        # Re-execute with fix hint
                        if fix_suggestion:
                            state["_retry_hint"] = fix_suggestion

                        retry_result = await agent_func(state)
                        if isinstance(retry_result, dict):
                            state.update(retry_result)

                        # Re-validate
                        retry_event = HookEvent(
                            name=hook_events.AFTER_AGENT,
                            payload={
                                "agent_id": agent_id,
                                "success": True,
                                "adapter": False,
                                "output": retry_result if isinstance(retry_result, dict) else {},
                                "latency_ms": (time.time() - start_time) * 1000,
                            },
                            trace_id=conversation_id,
                            session_id="",
                            agent_id=agent_id,
                        )
                        await hooks.emit_sync(retry_event)

                        if not retry_event.payload.get("validation_failed", False):
                            logger.info(
                                "[RuntimeRunner] Quality gate passed for %s on retry %d",
                                agent_id, retry_attempt,
                            )
                            break

                        # Update validation for next iteration
                        validation_result = retry_event.payload.get("validation_result", {})
                else:
                    if validation_result.get("warnings"):
                        logger.info(
                            "[RuntimeRunner] %s passed with warnings: %s",
                            agent_id, "; ".join(validation_result.get("warnings", [])),
                        )

                # Mark agent as done in conversation
                self.conversation_manager.mark_agent_done(
                    conversation_id, agent_id,
                    output=result if isinstance(result, dict) else {},
                )

                logger.info(
                    "[RuntimeRunner] Agent %s completed (%.0fms) | conv=%s",
                    agent_id, latency, conversation_id[:8],
                )

            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error("[RuntimeRunner] Agent %s failed: %s", agent_id, error_msg)
                state["error"] = error_msg
                state["status"] = "failed"

                await hooks.emit(HookEvent(
                    name=hook_events.ON_ERROR,
                    payload={"agent_id": agent_id, "error": error_msg},
                    trace_id=conversation_id,
                    agent_id=agent_id,
                ))

                self.conversation_manager.mark_agent_done(
                    conversation_id, agent_id,
                    error=error_msg,
                )
                break

            # ── Incremental persistence ──
            if persist_callback:
                try:
                    await persist_callback(agent_id, state)
                except Exception as e:
                    logger.warning("[RuntimeRunner] Persist callback failed for %s: %s", agent_id, e)

            # ── Progress report ──
            if progress_callback:
                progress = self.conversation_manager.get_progress(conversation_id)
                await progress_callback(agent_id, progress)

        # Update conversation final status
        self.conversation_manager.update_conversation_state(
            conversation_id,
            status=ConversationStatus.COMPLETED if state.get("status") != "failed" else ConversationStatus.FAILED,
        )

        # Clean up retry hints
        state.pop("_retry_hint", None)
        state.pop("_character_consistency", None)
        state.pop("_existing_character_profiles", None)
        state.pop("_character_profiles_for_verify", None)

        return state

    async def _verify_storyboard_consistency(self, state: dict, conversation_id: str):
        """Verify that storyboard prompts maintain character consistency.

        Uses CharacterMemoryService to check each scene prompt against
        stored character profiles. Logs warnings for missing features.
        """
        if not self.character_memory:
            return

        profiles = await self.character_memory.load_all_character_profiles(
            conversation_id=conversation_id,
        )
        if not profiles:
            return

        storyboard = state.get("storyboard", [])
        total_scenes = len(storyboard)
        inconsistent_count = 0

        for scene in storyboard:
            prompt = scene.get("prompt", "")
            if not prompt:
                continue

            is_consistent, missing = self.character_memory.verify_prompt_consistency(
                prompt, profiles,
            )

            if not is_consistent:
                inconsistent_count += 1
                logger.debug(
                    "[Consistency] Scene %d has %d missing features: %s",
                    scene.get("scene_no", "?"),
                    len(missing),
                    "; ".join(missing[:3]),  # Log first 3
                )

        if inconsistent_count > 0:
            logger.warning(
                "[Consistency] %d/%d scenes have character consistency issues",
                inconsistent_count, total_scenes,
            )
            # Store this metric in state for downstream use
            state["_consistency_warnings"] = inconsistent_count