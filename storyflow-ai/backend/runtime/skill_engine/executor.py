"""Skill Executor - Executes skills with prompt rendering and tool invocation."""
from __future__ import annotations
import logging
import time
from typing import Any
from runtime.skill_engine.models import Skill, SkillExecutionResult
from runtime.hook.dispatcher import HookEvent, get_hook_dispatcher
from runtime.hook import events as hook_events

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Executes a skill by rendering its prompt template and invoking tools.
    
    The executor handles:
    1. Prompt template rendering with context injection
    2. LLM call (delegated to the Agent Runtime)
    3. Tool invocation if needed
    4. Hook event emission
    """
    
    def __init__(self):
        self.hooks = get_hook_dispatcher()
    
    def render_prompt(self, skill: Skill, context: dict[str, Any]) -> str:
        """Render the skill's prompt template with the given context."""
        template = skill.prompt_template
        try:
            return template.format(**context)
        except KeyError as e:
            logger.warning("Prompt template rendering missing key: %s, using fallback", e)
            return template
    
    def build_system_prompt(self, skill: Skill, memories: str = "") -> str:
        """Build the system prompt with skill identity, constraints, and memory."""
        parts = [
            f"You are {skill.name}.",
            f"Description: {skill.description}",
        ]
        
        if skill.constraints.style:
            parts.append(f"Style constraint: {skill.constraints.style}")
        
        if skill.constraints.max_output_items:
            parts.append(f"Maximum output items: {skill.constraints.max_output_items}")
        
        if skill.constraints.custom_rules:
            parts.append("Rules:")
            for rule in skill.constraints.custom_rules:
                parts.append(f"  - {rule}")
        
        if memories:
            parts.append(f"\nContext Memory:\n{memories}")
        
        return "\n".join(parts)
    
    async def execute(
        self,
        skill: Skill,
        context: dict[str, Any],
        llm_call=None,
        tool_executor=None,
        trace_id: str = "",
        session_id: str = "",
        agent_id: str = "",
    ) -> SkillExecutionResult:
        """Execute a skill end-to-end.
        
        Args:
            skill: The skill to execute.
            context: Input context for prompt rendering.
            llm_call: Async callable for LLM invocation.
            tool_executor: Optional tool executor for tool calls.
            trace_id: For hook tracing.
            session_id: For hook session tracking.
            agent_id: For hook agent tracking.
        
        Returns:
            SkillExecutionResult with output or error.
        """
        start_time = time.time()
        
        # Emit BEFORE_SKILL hook
        await self.hooks.emit(HookEvent(
            name=hook_events.BEFORE_SKILL,
            payload={"skill_id": skill.skill_id, "context": context},
            trace_id=trace_id, session_id=session_id, agent_id=agent_id,
        ))
        
        try:
            # Render prompt
            prompt = self.render_prompt(skill, context)
            
            # Call LLM if provided
            llm_output = None
            if llm_call:
                system_prompt = self.build_system_prompt(skill)
                llm_output = await llm_call(
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    model="default",
                )
            
            output = llm_output or {}
            
            # Execute tools if needed
            if tool_executor and isinstance(output, dict) and output.get("tool_calls"):
                tool_results = await tool_executor(output["tool_calls"])
                output["tool_results"] = tool_results
            
            latency = (time.time() - start_time) * 1000
            
            # Emit AFTER_SKILL hook
            await self.hooks.emit(HookEvent(
                name=hook_events.AFTER_SKILL,
                payload={"skill_id": skill.skill_id, "output": output, "latency_ms": latency},
                trace_id=trace_id, session_id=session_id, agent_id=agent_id,
            ))
            
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                success=True,
                output=output if isinstance(output, dict) else {"result": output},
                latency_ms=latency,
            )
        
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error("Skill execution failed [%s]: %s", skill.skill_id, error_msg)
            
            await self.hooks.emit(HookEvent(
                name=hook_events.ON_ERROR,
                payload={"skill_id": skill.skill_id, "error": error_msg},
                trace_id=trace_id, session_id=session_id, agent_id=agent_id,
            ))
            
            return SkillExecutionResult(
                skill_id=skill.skill_id,
                success=False,
                error=error_msg,
                latency_ms=latency,
            )
