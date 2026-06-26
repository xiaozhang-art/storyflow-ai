"""MCP Router - Routes envelopes to appropriate handlers based on type."""
from __future__ import annotations
import logging
from typing import Callable, Awaitable
from runtime.mcp.envelope import MCPEnvelope, MessageType

logger = logging.getLogger(__name__)

HandlerFunc = Callable[[MCPEnvelope], Awaitable[MCPEnvelope]]


class MCPRouter:
    """Routes MCP envelopes to registered handlers based on message type."""
    
    def __init__(self):
        self._handlers: dict[MessageType, list[HandlerFunc]] = {}
        self._default_handler: HandlerFunc | None = None
    
    def register(self, msg_type: MessageType | str, handler: HandlerFunc):
        if isinstance(msg_type, str):
            msg_type = MessageType(msg_type)
        self._handlers.setdefault(msg_type, []).append(handler)
        logger.debug("Registered handler for %s: %s", msg_type.value, handler.__name__)
    
    def register_default(self, handler: HandlerFunc):
        self._default_handler = handler
    
    async def route(self, envelope: MCPEnvelope) -> MCPEnvelope:
        """Route envelope to the appropriate handler(s)."""
        handlers = self._handlers.get(envelope.type)
        if not handlers:
            if self._default_handler:
                return await self._default_handler(envelope)
            logger.warning("No handler for message type: %s", envelope.type.value)
            return envelope
        
        result = envelope
        for handler in handlers:
            result = await handler(result)
        return result