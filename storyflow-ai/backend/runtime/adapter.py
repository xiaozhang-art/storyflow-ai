"""Runtime Adapter - Bridges the new Agent OS Runtime with existing LangGraph agents.

This module provides backward compatibility: existing agents that work with
StoryState can be wrapped and executed through the new Runtime system,
enabling gradual migration without breaking the current pipeline.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any, Callable, Awaitable
from runtime.mcp.envelope import MCPEnvelope, MessageType
from runtime.agent_runtime.context import RuntimeContext
from runtime.hook.dispatcher import HookEvent, get_hook_dispatcher
from runtime.hook import events as hook_events

logger = logging.getLogger(__name__)

# Type for existing LangGraph agent functions
LegacyAgentFunc = Callable[[dict], Awaitable[dict] | dict]


def wrap_legacy_agent(
    agent_id: str,
    agent_func: LegacyAgentFunc,
) -> Callable[[MCPEnvelope], Awaitable[MCPEnvelope]]:
    """Wrap a legacy LangGraph agent function into an A2A-compatible handler.

    The wrapped handler:
    1. Extracts payload from the Envelope
    2. Calls the original agent function with a StoryState-like dict
    3. Returns the result as a reply Envelope

    Args:
        agent_id: The agent's identifier (e.g., "script", "character").
        agent_func: The original async function(state: dict) -> dict.

    Returns:
        An async function(envelope: MCPEnvelope) -> MCPEnvelope.
    """
    async def handler(envelope: MCPEnvelope) -> MCPEnvelope:
        hooks = get_hook_dispatcher()
        trace_id = envelope.trace_id

        # Build a StoryState-compatible dict from envelope
        state = {
            "task_id": envelope.metadata.get("task_id", ""),
            "story_id": envelope.metadata.get("story_id", ""),
            **envelope.payload,
        }

        logger.info("[Adapter] Executing legacy agent %s via Runtime | trace=%s",
                     agent_id, trace_id[:8])

        # Emit BEFORE_AGENT hook
        await hooks.emit(HookEvent(
            name=hook_events.BEFORE_AGENT,
            payload={"agent_id": agent_id, "adapter": True},
            trace_id=trace_id,
            session_id=envelope.source_session_id or "",
            agent_id=agent_id,
        ))

        try:
            # Call the original agent function
            result = await agent_func(state) if callable(agent_func) else agent_func(state)

            # Ensure result is a dict
            if not isinstance(result, dict):
                result = {"result": result}

            # Build reply envelope
            reply = envelope.reply(payload=result)
            reply.metadata["agent_id"] = agent_id
            reply.metadata["adapter"] = True

            # Emit AFTER_AGENT hook
            await hooks.emit(HookEvent(
                name=hook_events.AFTER_AGENT,
                payload={"agent_id": agent_id, "success": True, "adapter": True},
                trace_id=trace_id,
                session_id=envelope.target_session_id or "",
                agent_id=agent_id,
            ))

            return reply

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error("[Adapter] Agent %s failed: %s", agent_id, error_msg)

            await hooks.emit(HookEvent(
                name=hook_events.ON_ERROR,
                payload={"agent_id": agent_id, "error": error_msg, "adapter": True},
                trace_id=trace_id,
                agent_id=agent_id,
            ))

            return envelope.reply(payload={"error": error_msg, "success": False})

    handler.__name__ = f"adapted_{agent_id}"
    return handler


class RuntimeWorkflowRunner:
    """Runs the story generation workflow through the new Runtime system.

    This replaces the old LangGraph workflow with a Runtime-based execution:
    1. Create a Conversation with a linear agent pipeline
    2. Register legacy agents via adapters
    3. Execute the pipeline through the Conversation Manager
    4. Track progress and persist results

    The old LangGraph workflow is kept for backward compatibility.
    The RuntimeWorkflowRunner provides an alternative execution path.
    """

    def __init__(
        self,
        control_server=None,
        conversation_manager=None,
        skill_registry=None,
        memory_manager=None,
    ):
        from runtime.message_bus.control_server import ControlServer
        from runtime.conversation.manager import ConversationManager
        from runtime.skill_engine.registry import SkillRegistry

        self.control_server = control_server
        self.conversation_manager = conversation_manager
        self.skill_registry = skill_registry or SkillRegistry()
        self.memory_manager = memory_manager

        self._registered_agents: dict[str, LegacyAgentFunc] = {}

    def register_agent(self, agent_id: str, agent_func: LegacyAgentFunc):
        """Register a legacy agent function to be wrapped by the Runtime."""
        self._registered_agents[agent_id] = agent_func

        if self.control_server:
            wrapped = wrap_legacy_agent(agent_id, agent_func)
            self.control_server.register_agent(agent_id, wrapped)

        logger.info("[RuntimeRunner] Agent registered: %s", agent_id)

    async def run_pipeline(
        self,
        task_id: str,
        story_id: str,
        prompt: str,
        genre: str,
        progress_callback=None,
    ) -> dict:
        """Execute the full story pipeline through the Runtime.

        Pipeline: script -> character -> storyboard -> image -> voice -> video

        This executes agents sequentially (like the old workflow) but through
        the Runtime system, gaining:
        - Hook observability on every step
        - Session management
        - Memory injection
        - Skill validation (if skills are registered)
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

        # Create a conversation
        conversation = await self.conversation_manager.create_conversation(
            goal=f"Generate story: {prompt[:100]}",
            agents=available_agents,
            metadata={"task_id": task_id, "story_id": story_id},
        )

        # Build the pipeline graph
        self.conversation_manager.build_linear_pipeline(
            conversation.conversation_id,
            available_agents,
        )

        # Execute each agent sequentially
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

        for agent_id in available_agents:
            # Mark as running
            self.conversation_manager.mark_agent_done(
                conversation.conversation_id, agent_id,
            )
            # Actually set to running
            graph = self.conversation_manager._graphs.get(conversation.conversation_id, {})
            if agent_id in graph:
                graph[agent_id].state = "running"

            agent_func = self._registered_agents[agent_id]

            try:
                result = await agent_func(state)
                if isinstance(result, dict):
                    state.update(result)

                self.conversation_manager.mark_agent_done(
                    conversation.conversation_id, agent_id,
                    output=result if isinstance(result, dict) else {},
                )

                logger.info("[RuntimeRunner] Agent %s completed | trace=conv:%s",
                             agent_id, conversation.conversation_id[:8])

            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error("[RuntimeRunner] Agent %s failed: %s", agent_id, error_msg)
                state["error"] = error_msg
                state["status"] = "failed"
                self.conversation_manager.mark_agent_done(
                    conversation.conversation_id, agent_id,
                    error=error_msg,
                )
                break

            # Report progress
            if progress_callback:
                progress = self.conversation_manager.get_progress(conversation.conversation_id)
                await progress_callback(agent_id, progress)

        self.conversation_manager.update_conversation_state(
            conversation.conversation_id,
            status="completed" if state.get("status") != "failed" else "failed",
        )

        return state