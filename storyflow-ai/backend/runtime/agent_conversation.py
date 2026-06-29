"""Agent Conversation Bus - Enables agents to discuss and negotiate like a team.

Instead of agents only communicating via the Blackboard, the ConversationBus
allows the Director to initiate discussions between agents:

    Director: ImageAgent, why did you fail?
    Image: The character doesn't look right.
    Director: Storyboard, is the prompt too simple?
    Storyboard: I suggest adding "long hair" and "white dress".
    Director: Image, redraw with the improved prompt.

This is built on top of EventBus and uses asyncio for async message passing.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from runtime.event_bus import EventBus, EventType, get_event_bus

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Types of agent messages."""
    REQUEST = "request"
    RESPONSE = "response"
    INFORM = "inform"  # Fire-and-forget notification
    BROADCAST = "broadcast"  # To all agents


@dataclass
class AgentMessage:
    """A message between agents."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    conversation_id: str = ""
    from_agent: str = ""
    to_agent: str = ""  # Empty = broadcast
    message_type: MessageType = MessageType.REQUEST
    content: str = ""
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""  # ID of the message this replies to

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type.value,
            "content": self.content,
            "data": self.data,
            "timestamp": self.timestamp,
            "reply_to": self.reply_to,
        }


# Agent message handler type
AgentMessageHandler = Callable[[AgentMessage], Coroutine[Any, Any, str]]


class AgentConversationBus:
    """Message bus for inter-agent communication.

    Agents register handlers for their name. When a message is sent
    to an agent, the handler is called and the response is collected.

    The Director uses this bus to coordinate multi-agent discussions.
    """

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or get_event_bus()
        self._handlers: dict[str, AgentMessageHandler] = {}
        self._conversations: dict[str, list[AgentMessage]] = {}
        self._pending_replies: dict[str, asyncio.Future] = {}
        self._stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "conversations_started": 0,
            "responses_timeout": 0,
        }

    def register_agent(self, agent_name: str,
                       handler: AgentMessageHandler) -> None:
        """Register a message handler for an agent."""
        self._handlers[agent_name] = handler
        logger.info("ConversationBus: %s registered for messages", agent_name)

    def unregister_agent(self, agent_name: str) -> None:
        self._handlers.pop(agent_name, None)

    # ── Conversation management ──

    def start_conversation(
        self, participants: list[str], topic: str = ""
    ) -> str:
        """Start a new multi-agent conversation."""
        conv_id = uuid.uuid4().hex[:12]
        self._conversations[conv_id] = []
        self._stats["conversations_started"] += 1
        logger.info(
            "ConversationBus: started conversation %s with %s (topic: %s)",
            conv_id, participants, topic,
        )
        return conv_id

    def get_conversation_history(self, conv_id: str) -> list[AgentMessage]:
        return list(self._conversations.get(conv_id, []))

    # ── Message sending ──

    async def send(self, message: AgentMessage) -> None:
        """Send a message (fire-and-forget, no response expected)."""
        self._store_message(message)
        self._stats["messages_sent"] += 1

        await self.event_bus.publish_event(
            EventType.AGENT_MESSAGE,
            data=message.to_dict(),
            source=f"conversation_bus:{message.from_agent}",
        )

        if message.to_agent and message.to_agent in self._handlers:
            try:
                await self._handlers[message.to_agent](message)
                self._stats["messages_received"] += 1
            except Exception as e:
                logger.error(
                    "ConversationBus: handler for %s failed: %s",
                    message.to_agent, e)
        elif message.to_agent:
            logger.warning(
                "ConversationBus: no handler for agent '%s'",
                message.to_agent)

    async def request(
        self, from_agent: str, to_agent: str, content: str,
        conversation_id: str = "", data: dict | None = None,
        timeout: float = 30.0,
    ) -> AgentMessage | None:
        """Send a request and wait for a response."""
        msg = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=MessageType.REQUEST,
            content=content,
            conversation_id=conversation_id,
            data=data or {},
        )

        # Create future for the reply
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_replies[msg.id] = future

        await self.send(msg)

        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
            return reply
        except asyncio.TimeoutError:
            self._stats["responses_timeout"] += 1
            logger.warning(
                "ConversationBus: timeout waiting for %s to reply to %s",
                to_agent, from_agent)
            return None
        finally:
            self._pending_replies.pop(msg.id, None)

    async def reply(self, original_message: AgentMessage,
                    content: str, data: dict | None = None) -> None:
        """Reply to a received message."""
        reply_msg = AgentMessage(
            conversation_id=original_message.conversation_id,
            from_agent=original_message.to_agent,
            to_agent=original_message.from_agent,
            message_type=MessageType.RESPONSE,
            content=content,
            data=data or {},
            reply_to=original_message.id,
        )
        await self.send(reply_msg)

        # Resolve pending future if this is a response to a request
        future = self._pending_replies.get(original_message.id)
        if future and not future.done():
            future.set_result(reply_msg)

    # ── Director convenienced methods ──

    async def director_ask(
        self, agent_name: str, question: str,
        conversation_id: str = "", context: dict | None = None,
        timeout: float = 30.0,
    ) -> str:
        """Director asks an agent a question, returns the text response."""
        response = await self.request(
            from_agent="director", to_agent=agent_name,
            content=question, conversation_id=conversation_id,
            data=context or {}, timeout=timeout,
        )
        if response:
            return response.content
        return "(no response)"

    async def director_investigate(
        self,
        failed_step: str,
        error: str,
        agents_to_ask: list[str],
        conversation_id: str = "",
    ) -> dict[str, str]:
        """Director investigates a failure by asking multiple agents.

        Returns a dict of {agent_name: response_text}.
        """
        results = {}
        tasks = []
        for agent_name in agents_to_ask:
            question = (
                f"The '{failed_step}' step failed with: {error}\n"
                f"From your perspective as the {agent_name} agent, "
                f"what do you think went wrong and how should we fix it? "
                f"Be specific and actionable."
            )
            tasks.append(self.director_ask(
                agent_name, question, conversation_id, timeout=20.0))

        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for agent_name, resp in zip(agents_to_ask, responses):
            if isinstance(resp, Exception):
                results[agent_name] = f"(error: {resp})"
            else:
                results[agent_name] = resp

        return results

    # ── Internal ──

    def _store_message(self, message: AgentMessage) -> None:
        if message.conversation_id:
            conv = self._conversations.setdefault(message.conversation_id, [])
            conv.append(message)

    def get_stats(self) -> dict:
        stats = dict(self._stats)
        stats["registered_agents"] = list(self._handlers.keys())
        stats["active_conversations"] = len(self._conversations)
        stats["pending_replies"] = len(self._pending_replies)
        return stats