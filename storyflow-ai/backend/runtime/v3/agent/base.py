"""BaseAgent — 事件响应式 Agent 基类.

Agent 生命周期:
  Idle → Receive Event → Think → Write Workspace/StoryContext → Emit Event → Idle

Agent 不直接调用其他 Agent，只:
  1. 订阅感兴趣的事件
  2. 从 Blackboard 领取任务
  3. 执行业务逻辑
  4. 将结果写回 StoryContext / Blackboard
  5. 发射新事件通知下游

现有 Agent（纯函数）通过 AgentAdapter 包一层，不用重写业务逻辑。
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from runtime.v3.event_bus import EventBus, Event
from runtime.v3.context.story_context import StoryContext
from runtime.v3.blackboard.blackboard import Blackboard, BlackboardTask, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Agent 执行上下文 — 包含所有 Agent 需要的引用."""
    story_context: StoryContext
    blackboard: Blackboard
    event_bus: EventBus
    task: BlackboardTask | None = None
    extra: dict = field(default_factory=dict)  # capability_registry, use_capability 等


class BaseAgent(ABC):
    """事件响应式 Agent 基类.

    每个 Agent:
      - 有独立的 name / subscribed_events
      - 有自己的 execute() 实现（业务逻辑）
      - 通过 emit() 发射事件
      - 通过 StoryContext 和 Blackboard 与其他 Agent 交互
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 唯一标识."""
        ...

    @property
    def subscribed_events(self) -> list[str]:
        """此 Agent 监听的事件类型列表."""
        return [f"task.{self.name}.ready"]

    @abstractmethod
    async def execute(self, ctx: AgentContext) -> dict:
        """执行 Agent 的核心业务逻辑.

        Args:
            ctx: 包含 StoryContext, Blackboard, EventBus, 当前 Task

        Returns:
            执行结果 dict（会写入 Blackboard task result）
        """
        ...

    async def on_event(self, event: Event, ctx: AgentContext):
        """事件处理入口 — 默认实现: 从 Blackboard 领取任务并执行.

        子类可重写以实现更复杂的事件逻辑。
        """
        task = ctx.blackboard.claim_task(agent_type=self.name)
        if not task:
            logger.debug("[%s] No ready task, skipping event: %s", self.name, event.type)
            return

        ctx.task = task
        logger.info("[%s] ▶ Executing task %s (%s) [retry %d/%d]",
                    self.name, task.id, task.type, task.retry_count + 1, task.max_retries)

        start = time.time()
        try:
            result = await self.execute(ctx)
            duration = time.time() - start

            # 写回 StoryContext
            self._update_context(ctx, result)

            # 标记任务完成
            ctx.blackboard.complete_task(task.id, result)

            # 发射完成事件
            await self.emit(ctx.event_bus, f"agent.{self.name}.finished", {
                "task_id": task.id, "result": result, "duration": duration,
                "project_id": ctx.story_context.project_id,
            })

            logger.info("[%s] ✅ Task %s done in %.1fs", self.name, task.id, duration)

        except Exception as e:
            duration = time.time() - start
            logger.error("[%s] ❌ Task %s failed in %.1fs: %s", self.name, task.id, duration, e)

            ctx.blackboard.fail_task(task.id, error=str(e), retry=True)

            await self.emit(ctx.event_bus, f"agent.{self.name}.failed", {
                "task_id": task.id, "error": str(e), "retry_count": task.retry_count,
                "project_id": ctx.story_context.project_id,
            })

    async def emit(self, event_bus: EventBus, event_type: str, data: dict):
        """发射事件."""
        await event_bus.emit(Event(type=event_type, data=data, source=self.name))

    def _update_context(self, ctx: AgentContext, result: dict):
        """将 Agent 结果写回 StoryContext — 子类可重写."""
        # Auto-detect known artifact keys
        artifact_keys = {
            "outline", "characters", "episodes", "storyboard",
            "images", "video_clips", "audios", "video_path", "video_url",
        }
        for key in artifact_keys:
            if key in result and result[key]:
                ctx.story_context.update_artifact(key, result[key])


# ──────────────────────────────────────────────
# Agent Adapter — 将现有纯函数 Agent 包成 BaseAgent
# ──────────────────────────────────────────────

class AgentAdapter(BaseAgent):
    """适配器 — 把现有的 async def agent(state, context) -> dict 包装为 BaseAgent.

    不重写任何业务逻辑，只是加了一层事件驱动的外壳。
    """

    def __init__(self, name: str, agent_func, subscribed_events: list[str] | None = None):
        self._name = name
        self._agent_func = agent_func
        self._subscribed = subscribed_events or [f"task.{name}.ready"]

    @property
    def name(self) -> str:
        return self._name

    @property
    def subscribed_events(self) -> list[str]:
        return self._subscribed

    async def execute(self, ctx: AgentContext) -> dict:
        """调用原始 agent 函数，用 StoryContext 桥接."""
        state = ctx.story_context.to_state_dict()
        agent_ctx = ctx.story_context.to_agent_context(ctx.extra.get("capability_registry"))
        agent_ctx["blackboard"] = ctx.blackboard

        result = await self._agent_func(state, agent_ctx)
        return result or {}


# ──────────────────────────────────────────────
# Agent Registry — 管理所有 Agent
# ──────────────────────────────────────────────

class AgentRegistry:
    """Agent 注册表 — 按 name 查找 Agent，按 event 分发."""

    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}
        self._event_index: dict[str, list[BaseAgent]] = {}

    def register(self, agent: BaseAgent):
        """注册 Agent."""
        self._agents[agent.name] = agent
        for event_type in agent.subscribed_events:
            self._event_index.setdefault(event_type, []).append(agent)
        logger.info("[AgentRegistry] Registered '%s' (subscribes: %s)",
                     agent.name, agent.subscribed_events)

    def get(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    def get_subscribers(self, event_type: str) -> list[BaseAgent]:
        """获取监听某事件的所有 Agent."""
        return self._event_index.get(event_type, [])

    def list_all(self) -> list[dict]:
        return [
            {"name": a.name, "events": a.subscribed_events}
            for a in self._agents.values()
        ]


def create_default_agents() -> list[BaseAgent]:
    """创建默认的 7 个 Agent 适配器（包装现有纯函数）."""
    # Lazy import to avoid circular deps
    from agents.script_agent import script_agent
    from agents.character_agent import character_agent
    from agents.storyboard_agent import storyboard_agent
    from agents.image_agent import image_agent
    from agents.image_to_video_agent import image_to_video_agent
    from agents.voice_agent import voice_agent
    from agents.video_agent import video_agent

    return [
        AgentAdapter("script", script_agent),
        AgentAdapter("character", character_agent),
        AgentAdapter("storyboard", storyboard_agent),
        AgentAdapter("image", image_agent),
        AgentAdapter("image_to_video", image_to_video_agent),
        AgentAdapter("voice", voice_agent),
        AgentAdapter("video", video_agent),
    ]