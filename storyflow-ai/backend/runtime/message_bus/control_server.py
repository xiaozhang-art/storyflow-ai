"""Control Server - The brain of the A2A Message Bus."""
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Any, Callable, Awaitable, Optional
from runtime.mcp.envelope import MCPEnvelope, MessageType
from runtime.session.manager import SessionManager
from runtime.message_bus.transport import BaseTransport, InMemoryTransport
from runtime.hook.dispatcher import HookEvent, get_hook_dispatcher
from runtime.hook import events as hook_events

logger = logging.getLogger(__name__)

AgentHandler = Callable[[MCPEnvelope], Awaitable[MCPEnvelope]]


class ControlServer:
    """Central routing and session management server for A2A communication.
    
    The Control Server is the Single Source of Truth (SSOT) for:
    - Session mapping and pairing
    - Message routing decisions
    - Context/memory injection into envelopes
    - Trace ID propagation
    - Prompt enrichment
    
    Agents NEVER see sessions or routing logic - they only see
    message.content, message.from_agent, message.context.
    """
    
    def __init__(
        self,
        session_manager: SessionManager | None = None,
        transport: BaseTransport | None = None,
    ):
        self.sessions = session_manager or SessionManager()
        self.transport = transport or InMemoryTransport()
        self.hooks = get_hook_dispatcher()
        
        # Agent registry: agent_id -> handler function
        self._agents: dict[str, AgentHandler] = {}
        
        # Conversation mapping
        self._conversations: dict[str, dict[str, Any]] = {}
    
    def register_agent(self, agent_id: str, handler: AgentHandler):
        """Register an agent handler."""
        self._agents[agent_id] = handler
        logger.info("Agent registered: %s", agent_id)
    
    async def send_message(self, envelope: MCPEnvelope) -> MCPEnvelope:
        """Send a message from one agent to another.
        
        This is the main entry point for A2A communication:
        1. Resolve/create session pair
        2. Rewrite envelope with session info
        3. Inject context and memory
        4. Route to target agent
        """
        if not envelope.target_agent:
            logger.warning("No target agent specified, dropping message")
            return envelope
        
        conversation_id = envelope.conversation_id or uuid.uuid4().hex[:16]
        envelope.conversation_id = conversation_id
        
        # Ensure source session exists
        source_session = self.sessions.get_or_create_session(
            envelope.source_agent, conversation_id,
        )
        envelope.source_session_id = source_session.session_id
        
        # Resolve or create target session
        target_session = self.sessions.find_session(
            envelope.target_agent, conversation_id,
        )
        if not target_session:
            target_session = self.sessions.pair_sessions(
                source_session.session_id,
                envelope.target_agent,
                conversation_id,
            )
        
        envelope.target_session_id = target_session.session_id
        
        # Emit hook for A2A routing
        await self.hooks.emit(HookEvent(
            name="A2A_ROUTE",
            payload={
                "source": envelope.source_agent,
                "target": envelope.target_agent,
                "session_pair": f"{source_session.session_id}:{target_session.session_id}",
            },
            trace_id=envelope.trace_id,
            session_id=source_session.session_id,
            agent_id=envelope.source_agent,
        ))
        
        # Send via transport
        await self.transport.send(envelope.target_agent, envelope)
        
        # Update session state
        self.sessions.update_session_state(source_session.session_id, {
            "last_message_id": envelope.id,
        })
        source_session.touch()
        
        logger.info(
            "Message routed: %s(%s) -> %s(%s) [conv=%s]",
            envelope.source_agent, source_session.session_id[:8],
            envelope.target_agent, target_session.session_id[:8],
            conversation_id[:8],
        )
        
        return envelope
    
    async def deliver_to_agent(self, agent_id: str, envelope: MCPEnvelope) -> MCPEnvelope:
        """Deliver an envelope to a registered agent handler.
        
        The agent only sees:
        - envelope.payload (content)
        - envelope.source_agent (who sent it)
        - envelope.metadata (context injected by Control Server)
        """
        handler = self._agents.get(agent_id)
        if not handler:
            logger.error("No handler registered for agent: %s", agent_id)
            envelope.status = MCPEnvelope.model_fields["status"].default  # keep current
            return envelope
        
        try:
            result = await handler(envelope)
            return result
        except Exception as e:
            logger.error("Agent handler error [%s]: %s", agent_id, e)
            await self.hooks.emit(HookEvent(
                name=hook_events.ON_ERROR,
                payload={"agent": agent_id, "error": str(e)},
                trace_id=envelope.trace_id,
            ))
            return envelope
    
    async def start_listening(self, agent_id: str):
        """Start listening for messages addressed to a specific agent."""
        logger.info("Starting listener for agent: %s", agent_id)
        while True:
            try:
                envelope = await self.transport.receive(agent_id, timeout=60.0)
                if envelope:
                    result = await self.deliver_to_agent(agent_id, envelope)
                    
                    # If result has a reply_to, send the reply back
                    if result.reply_to and result.target_agent:
                        await self.send_message(result)
            except Exception as e:
                logger.error("Listener error for %s: %s", agent_id, e)
                await asyncio.sleep(1)
    
    async def create_conversation(
        self,
        conversation_id: str,
        goal: str = "",
        agents: list[str] | None = None,
    ):
        """Initialize a new conversation with participating agents."""
        self._conversations[conversation_id] = {
            "goal": goal,
            "agents": agents or [],
            "status": "init",
        }
        logger.info("Conversation created: %s with agents %s", conversation_id, agents)
    
    def get_stats(self) -> dict:
        return {
            "registered_agents": list(self._agents.keys()),
            "sessions": self.sessions.get_stats(),
            "conversations": len(self._conversations),
        }