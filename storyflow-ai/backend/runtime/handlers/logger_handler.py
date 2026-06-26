"""Structured Logger Hook - Logs all hook events in structured JSON format."""
from __future__ import annotations
import logging
import json
from runtime.hook.dispatcher import HookEvent, HookHandler

logger = logging.getLogger("storyflow.hook")


class StructuredLogHandler:
    """Logs hook events as structured JSON for debugging and auditing."""
    
    async def handle(self, event: HookEvent):
        log_entry = event.to_dict()
        # Truncate large payloads for logging
        payload_str = json.dumps(event.payload, ensure_ascii=False)
        if len(payload_str) > 2000:
            log_entry["payload_truncated"] = True
        logger.info("HOOK %s | agent=%s | trace=%s | session=%s",
                     event.name, event.agent_id, event.trace_id, event.session_id)


def create_logger_handler() -> HookHandler:
    handler = StructuredLogHandler()
    return handler.handle