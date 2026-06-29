"""Model Router - Intelligent model selection based on task type.

Instead of using one model for everything, ModelRouter selects the best
model/provider for each task based on quality, speed, and cost.

Routing rules (configurable):
    script generation    → creative-focused LLM (Claude/GPT-4o)
    prompt building      → fast, capable LLM (Gemini/GPT-4o)
    character design     → structured-output LLM (GPT-4o)
    storyboard          → creative LLM (GPT-4o)
    image generation     → Flux / DALL-E 3 / DashScope
    image-to-video       → Kling / Runway
    voice synthesis      → DashScope TTS / FishSpeech
    video assembly       → FFmpeg (local)

The router integrates with AdapterRegistry to actually switch providers.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModelRoute:
    """A routing decision for a specific task type."""
    task_type: str
    model: str
    provider: str
    reason: str = ""
    priority: int = 0  # Higher = preferred

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "model": self.model,
            "provider": self.provider,
            "reason": self.reason,
            "priority": self.priority,
        }


# Default routing table
DEFAULT_ROUTES: list[ModelRoute] = [
    # LLM tasks
    ModelRoute(
        task_type="script", model="gpt-4o", provider="openai",
        reason="Long-form creative writing benefits from GPT-4o's creativity",
        priority=10,
    ),
    ModelRoute(
        task_type="character", model="gpt-4o", provider="openai",
        reason="Structured output for character cards, needs reliability",
        priority=10,
    ),
    ModelRoute(
        task_type="storyboard", model="gpt-4o", provider="openai",
        reason="Detailed scene descriptions need creative capability",
        priority=10,
    ),
    ModelRoute(
        task_type="reflection", model="gpt-4o", provider="openai",
        reason="Quality analysis needs reasoning capability",
        priority=5,
    ),
    ModelRoute(
        task_type="director", model="gpt-4o", provider="openai",
        reason="Decision-making needs strong reasoning",
        priority=10,
    ),
    # Image tasks
    ModelRoute(
        task_type="image", model="wanx-v1", provider="dashscope",
        reason="DashScope Wanx for high-quality Chinese-style illustrations",
        priority=10,
    ),
    ModelRoute(
        task_type="image", model="dall-e-3", provider="openai",
        reason="DALL-E 3 as fallback for image generation",
        priority=5,
    ),
    # I2V tasks
    ModelRoute(
        task_type="image_to_video", model="kling-v1", provider="kling",
        reason="Kling for high-quality image-to-video",
        priority=10,
    ),
    # Voice tasks
    ModelRoute(
        task_type="voice", model="cosyvoice", provider="dashscope",
        reason="DashScope TTS for natural Chinese voice",
        priority=10,
    ),
]


class ModelRouter:
    """Intelligent model selection for different task types.

    The router maintains a priority-ordered list of ModelRoutes for each
    task type. When asked to select a model, it returns the highest-priority
    available route.

    Routes can be overridden via environment variables or programmatically.
    """

    def __init__(self):
        self._routes: dict[str, list[ModelRoute]] = {}
        self._fallbacks: dict[str, str] = {
            "image": "mock",
            "image_to_video": "mock",
            "voice": "mock",
        }
        self._stats = {
            "selections": 0,
            "by_task": {},
            "fallbacks_used": 0,
        }

        # Load default routes
        for route in DEFAULT_ROUTES:
            self.register_route(route)

    def register_route(self, route: ModelRoute) -> None:
        """Register a model route."""
        if route.task_type not in self._routes:
            self._routes[route.task_type] = []
        self._routes[route.task_type].append(route)
        # Sort by priority (highest first)
        self._routes[route.task_type].sort(
            key=lambda r: r.priority, reverse=True)

    def set_fallback(self, task_type: str, provider: str) -> None:
        """Set a fallback provider for when all routes fail."""
        self._fallbacks[task_type] = provider

    def select_model(self, task_type: str) -> ModelRoute | None:
        """Select the best available model for a task type.

        Returns the highest-priority route, or None if no routes exist.
        """
        self._stats["selections"] += 1
        self._stats["by_task"][task_type] = (
            self._stats["by_task"].get(task_type, 0) + 1)

        routes = self._routes.get(task_type, [])
        if not routes:
            logger.warning("ModelRouter: no routes for task type '%s'",
                           task_type)
            return None

        # Return highest priority route
        selected = routes[0]
        logger.debug(
            "ModelRouter: %s → %s (%s) [%s]",
            task_type, selected.model, selected.provider, selected.reason,
        )
        return selected

    def get_all_routes(self, task_type: str) -> list[ModelRoute]:
        """Get all routes for a task type (for fallback chaining)."""
        return list(self._routes.get(task_type, []))

    def get_fallback_provider(self, task_type: str) -> str:
        """Get the fallback provider for a task type."""
        return self._fallbacks.get(task_type, "mock")

    def get_stats(self) -> dict:
        return dict(self._stats)

    def get_routing_table(self) -> dict[str, list[dict]]:
        """Get the full routing table for display."""
        table = {}
        for task_type, routes in self._routes.items():
            table[task_type] = [r.to_dict() for r in routes]
        return table