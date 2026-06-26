"""Agent Runtime - The OS kernel for executing agents."""
from __future__ import annotations
import logging
import time
from typing import Any, Callable, Awaitable, Optional
from runtime.agent_runtime.context import RuntimeContext
from runtime.mcp.envelope import MCPEnvelope
from runtime.hook.dispatcher import HookEvent, get_hook_dispatcher
from runtime.hook import events as hook_events
from runtime.skill_engine.selector import SkillSelector
from runtime.skill_engine.executor import SkillExecutor
from runtime.skill_engine.validator import SkillValidator
from runtime.skill_engine.registry import SkillRegistry
from runtime.skill_engine.models import Skill, SkillExecutionResult

logger = logging.getLogger(__name__)

LLMCallFunc = Callable[..., Awaitable[dict[str, Any]]]
ToolExecutorFunc = Callable[[list[dict]], Awaitable[list[dict]]]
JudgeFunc = Callable[[dict, dict], Awaitable[float]]


class AgentRuntime:
    """The central execution engine for all agents.
    
    Agent Runtime = OS for Agents
    Agent = Process
    Skill = Function
    Tool = System Call
    Memory = Disk
    Hook = Kernel Event
    Message Bus = IPC
    
    The Runtime handles the complete execution lifecycle:
    1. Parse context from Envelope
    2. Load Memory
    3. Load Skills
    4. Hook: BEFORE_AGENT
    5. Select Skill
    6. Build Prompt
    7. Hook: BEFORE_LLM
    8. LLM Call
    9. Hook: AFTER_LLM
    10. Tool Execution (optional)
    11. Judge/Evaluation (optional)
    12. Retry Loop (optional)
    13. Hook: AFTER_AGENT
    14. Return Envelope
    """
    
    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        hook_dispatcher=None,
        memory_manager=None,
        llm_call: LLMCallFunc | None = None,
        tool_executor: ToolExecutorFunc | None = None,
        judge_func: JudgeFunc | None = None,
    ):
        self.skill_registry = skill_registry or SkillRegistry()
        self.hooks = hook_dispatcher or get_hook_dispatcher()
        self.memory = memory_manager
        self.llm_call = llm_call
        self.tool_executor = tool_executor
        self.judge_func = judge_func
        
        self.skill_selector = SkillSelector(self.skill_registry)
        self.skill_executor = SkillExecutor()
        self.skill_validator = SkillValidator()
    
    async def run(self, envelope: MCPEnvelope, **overrides) -> MCPEnvelope:
        """Execute an agent invocation end-to-end.
        
        This is the main entry point. Takes an Envelope, runs the full
        execution pipeline, and returns a result Envelope.
        """
        start_time = time.time()
        ctx = RuntimeContext.from_envelope(envelope, **overrides)
        
        logger.info("Runtime executing: agent=%s, action=%s, trace=%s",
                     ctx.agent_id, ctx.action, ctx.trace_id[:8])
        
        # 1. Load memory if available
        memories = ""
        if self.memory:
            try:
                memories = await self.memory.load_for_agent(
                    agent_id=ctx.agent_id,
                    conversation_id=ctx.conversation_id,
                    query=ctx.payload.get("query", ctx.action),
                )
            except Exception as e:
                logger.warning("Memory load failed: %s", e)
        
        # 2. Hook: BEFORE_AGENT
        await self.hooks.emit(HookEvent(
            name=hook_events.BEFORE_AGENT,
            payload={"agent_id": ctx.agent_id, "action": ctx.action},
            trace_id=ctx.trace_id, session_id=ctx.session_id,
            conversation_id=ctx.conversation_id, agent_id=ctx.agent_id,
        ))
        
        try:
            # 3. Select skill
            skill = self.skill_selector.select(
                ctx.agent_id,
                task_description=ctx.action,
            )
            
            if not skill:
                # No skill found, execute raw LLM call
                result = await self._raw_llm_execute(ctx, memories)
            else:
                # Execute via skill pipeline
                result = await self._skill_execute(
                    ctx, skill, memories,
                )
            
            # Build output envelope
            latency = (time.time() - start_time) * 1000
            output_envelope = envelope.reply(
                payload=result,
                metadata={"latency_ms": latency, "agent_id": ctx.agent_id},
            )
            output_envelope.status = MCPEnvelope.model_fields["status"].default  # pending
            
            # 4. Hook: AFTER_AGENT
            await self.hooks.emit(HookEvent(
                name=hook_events.AFTER_AGENT,
                payload={
                    "agent_id": ctx.agent_id,
                    "latency_ms": latency,
                    "success": True,
                },
                trace_id=ctx.trace_id, session_id=ctx.session_id,
                conversation_id=ctx.conversation_id, agent_id=ctx.agent_id,
            ))
            
            return output_envelope
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error("Runtime execution failed [agent=%s]: %s", ctx.agent_id, error_msg)
            
            await self.hooks.emit(HookEvent(
                name=hook_events.ON_ERROR,
                payload={"agent_id": ctx.agent_id, "error": error_msg},
                trace_id=ctx.trace_id, session_id=ctx.session_id,
                conversation_id=ctx.conversation_id, agent_id=ctx.agent_id,
            ))
            
            return envelope.reply(
                payload={"error": error_msg, "success": False},
            )
    
    async def _skill_execute(
        self,
        ctx: RuntimeContext,
        skill: Skill,
        memories: str,
    ) -> dict[str, Any]:
        """Execute through the skill pipeline with validation and retry."""
        context = {
            "task": ctx.action,
            "input": ctx.payload,
            "memories": memories,
        }
        
        for attempt in range(ctx.max_retries + 1):
            result = await self.skill_executor.execute(
                skill=skill,
                context=context,
                llm_call=self.llm_call,
                tool_executor=self.tool_executor,
                trace_id=ctx.trace_id,
                session_id=ctx.session_id,
                agent_id=ctx.agent_id,
            )
            
            # Validate output
            result = self.skill_validator.validate(result, skill)
            
            if result.success and result.validation_passed:
                return result.output
            
            if not result.validation_passed and attempt < ctx.max_retries and ctx.enable_retry:
                logger.warning(
                    "Skill %s validation failed (attempt %d/%d), retrying...",
                    skill.skill_id, attempt + 1, ctx.max_retries,
                )
                await self.hooks.emit(HookEvent(
                    name=hook_events.ON_RETRY,
                    payload={
                        "skill_id": skill.skill_id,
                        "attempt": attempt + 1,
                        "errors": result.validation_errors,
                    },
                    trace_id=ctx.trace_id, session_id=ctx.session_id, agent_id=ctx.agent_id,
                ))
                continue
            
            # Return even if validation failed (after retries exhausted)
            return result.output if result.output else {"error": result.error}
        
        return {"error": "Max retries exceeded"}
    
    async def _raw_llm_execute(self, ctx: RuntimeContext, memories: str) -> dict[str, Any]:
        """Execute a raw LLM call without skill pipeline."""
        if not self.llm_call:
            return {"error": "No LLM call function configured"}
        
        system_prompt = f"You are {ctx.agent_id} agent."
        if memories:
            system_prompt += f"\n\nContext:\n{memories}"
        
        result = await self.llm_call(
            system_prompt=system_prompt,
            user_prompt=str(ctx.payload),
            model=ctx.model,
        )
        
        return result if isinstance(result, dict) else {"result": result}