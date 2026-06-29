"""Agent SDK - Base class and registration for building new agents.

To add a new agent (e.g., MusicAgent), you only need:

    from runtime.agent_sdk import BaseAgent, agent_registry

    class MusicAgent(BaseAgent):
        name = "music"

        async def execute(self, state: dict) -> dict:
            # Your logic here
            return {"music_url": "..."}

    # That's it! The Runtime auto-discovers and uses it.
    agent_registry.register(MusicAgent())
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all StoryFlow agents.

    Every agent:
        1. Receives a state dict as input
        2. Returns a result dict as output
        3. Never calls another agent directly

    The Runtime handles:
        - When to call this agent
        - What state to pass in
        - What to do with the output
        - Retry on failure
        - Quality checks
    """

    name: str = "base_agent"
    description: str = ""

    @abstractmethod
    async def execute(self, state: dict) -> dict:
        """Execute the agent's task.

        Args:
            state: Current pipeline state (from Blackboard)

        Returns:
            Result dict to merge back into the state
        """
        ...

    async def validate_input(self, state: dict) -> bool:
        """Validate that required inputs are present.

        Returns True if the agent can proceed.
        """
        return True

    async def validate_output(self, result: dict) -> bool:
        """Validate the agent's output.

        Returns True if the output is acceptable.
        """
        return bool(result)

    def __repr__(self):
        return f"Agent({self.name})"


class AgentRegistry:
    """Registry for all agents.

    The Runtime discovers agents from this registry.
    """

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):
        """Register an agent instance."""
        self._agents[agent.name] = agent
        logger.info("Agent registered: %s", agent.name)

    def get(self, name: str) -> BaseAgent | None:
        """Get an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def to_agent_func(self, name: str):
        """Wrap a registered agent as a callable function.

        This allows BaseAgent instances to be used with the WorkflowEngine
        alongside the existing function-based agents.
        """
        agent = self.get(name)
        if not agent:
            raise ValueError(f"Agent '{name}' not registered")

        async def agent_func(state: dict) -> dict:
            if not await agent.validate_input(state):
                logger.warning("Agent %s: input validation failed", name)
                return {}
            result = await agent.execute(state)
            if not await agent.validate_output(result):
                logger.warning("Agent %s: output validation failed", name)
            return result

        agent_func.__name__ = f"agent_{name}"
        return agent_func

    def get_stats(self) -> dict:
        return {
            "registered_agents": self.list_agents(),
            "count": len(self._agents),
        }


# Global singleton
_agent_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Get the global AgentRegistry instance."""
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistry()
    return _agent_registry