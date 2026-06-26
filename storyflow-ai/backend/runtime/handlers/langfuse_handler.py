"""Langfuse Hook - Integrates hook events with Langfuse for observability."""
from __future__ import annotations
import logging
from typing import Any
from runtime.hook.dispatcher import HookEvent, HookHandler
from runtime.hook.events import (
    BEFORE_LLM, AFTER_LLM, BEFORE_TOOL, AFTER_TOOL,
    BEFORE_AGENT, AFTER_AGENT, ON_ERROR, ON_RETRY,
)

logger = logging.getLogger(__name__)

# Langfuse is optional - gracefully degrade if not installed
try:
    from langfuse import Langfuse
    from langfuse.decorators import observe
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    logger.info("Langfuse SDK not installed. Langfuse hooks disabled.")


class LangfuseHookHandler:
    """Binds hook events to Langfuse traces for full observability."""
    
    def __init__(self, public_key: str = "", secret_key: str = "", host: str = "https://cloud.langfuse.com"):
        self.langfuse_client = None
        if LANGFUSE_AVAILABLE and public_key and secret_key:
            self.langfuse_client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
            logger.info("Langfuse client initialized")
    
    def _get_trace(self, event: HookEvent):
        if not self.langfuse_client:
            return None
        try:
            return self.langfuse_client.get_trace(event.trace_id)
        except Exception:
            return None
    
    async def handle(self, event: HookEvent):
        if not self.langfuse_client:
            return
        
        try:
            if event.name == BEFORE_LLM:
                trace = self._get_trace(event)
                if trace:
                    trace.span(
                        name="llm-call",
                        input=event.payload.get("prompt", {}),
                        metadata={"agent": event.agent_id, "session": event.session_id},
                    )
            elif event.name == AFTER_LLM:
                trace = self._get_trace(event)
                if trace:
                    # Update the span with output
                    trace.update(
                        output=event.payload.get("response", {}),
                    )
            elif event.name == BEFORE_TOOL:
                trace = self._get_trace(event)
                if trace:
                    trace.span(
                        name=f"tool-{event.payload.get('tool_name', 'unknown')}",
                        input=event.payload.get("tool_input", {}),
                    )
            elif event.name == AFTER_TOOL:
                trace = self._get_trace(event)
                if trace:
                    trace.update(
                        output=event.payload.get("tool_output", {}),
                        metadata={"latency": event.payload.get("latency", 0)},
                    )
            elif event.name == ON_ERROR:
                trace = self._get_trace(event)
                if trace:
                    trace.score(
                        name="error",
                        value=0,
                        comment=event.payload.get("error", "unknown"),
                    )
        except Exception as e:
            logger.debug("Langfuse hook error: %s", e)


def create_langfuse_handler(
    public_key: str = "", secret_key: str = "", host: str = "https://cloud.langfuse.com",
) -> HookHandler:
    handler = LangfuseHookHandler(public_key=public_key, secret_key=secret_key, host=host)
    return handler.handle