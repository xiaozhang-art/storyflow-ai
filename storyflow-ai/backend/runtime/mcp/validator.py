"""MCP Validator - Validates envelopes against defined schemas."""
from __future__ import annotations
import logging
from typing import Any
from runtime.mcp.envelope import MCPEnvelope, MessageType

logger = logging.getLogger(__name__)


class MCPValidator:
    """Validates MCP envelopes for required fields and security constraints."""
    
    # Required fields per message type
    REQUIRED_FIELDS: dict[MessageType, list[str]] = {
        MessageType.TOOL_CALL: ["source_agent", "action", "payload"],
        MessageType.TOOL_RESULT: ["source_agent", "payload"],
        MessageType.SKILL_CALL: ["source_agent", "action", "payload"],
        MessageType.SKILL_RESULT: ["source_agent", "payload"],
        MessageType.A2A_MESSAGE: ["source_agent", "target_agent", "conversation_id"],
        MessageType.CONTROL_EVENT: ["source_agent", "action"],
    }
    
    def validate(self, envelope: MCPEnvelope) -> tuple[bool, list[str]]:
        """Validate an envelope. Returns (is_valid, list_of_errors)."""
        errors: list[str] = []
        required = self.REQUIRED_FIELDS.get(envelope.type, ["source_agent"])
        
        for field in required:
            value = getattr(envelope, field, None)
            if field == "payload":
                if not value:
                    errors.append(f"Missing or empty payload for {envelope.type.value}")
            elif not value:
                errors.append(f"Missing required field '{field}' for {envelope.type.value}")
        
        # Security: prevent session spoofing
        if envelope.metadata.get("session_override"):
            errors.append("Session override is forbidden in metadata")
        
        is_valid = len(errors) == 0
        if not is_valid:
            logger.warning("Envelope validation failed: %s", errors)
        return is_valid, errors