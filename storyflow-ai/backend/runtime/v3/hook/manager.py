"""HookManager — Runtime 的核心扩展点.

所有横切逻辑走 Hook，不污染 Agent 逻辑。

生命周期事件:
  BEFORE_AGENT   / AFTER_AGENT
  BEFORE_CAPABILITY / AFTER_CAPABILITY
  QUALITY_CHECK  / QUALITY_FAILED / QUALITY_PASSED
  CHECKPOINT_SAVE / CHECKPOINT_RESTORE
  HUMAN_REVIEW_REQUEST / HUMAN_FEEDBACK
  PROJECT_RESUME
  WORLD_UPDATE

扩展示例:
  Langfuse Tracing → 监听 AFTER_AGENT, AFTER_CAPABILITY
  Token 统计       → 监听 AFTER_CAPABILITY (LLM type)
  自动重试         → 监听 QUALITY_FAILED
  进度推送         → 监听 AFTER_AGENT
  日志             → 监听所有事件 (on_any)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from runtime.v3.event_bus import EventBus, Event, get_event_bus

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Hook Events
# ──────────────────────────────────────────────

# Agent lifecycle
BEFORE_AGENT = "hook.before_agent"
AFTER_AGENT = "hook.after_agent"

# Capability lifecycle
BEFORE_CAPABILITY = "hook.before_capability"
AFTER_CAPABILITY = "hook.after_capability"

# Quality
QUALITY_CHECK = "hook.quality_check"
QUALITY_PASSED = "hook.quality_passed"
QUALITY_FAILED = "hook.quality_failed"
QUALITY_ASK_USER = "hook.quality_ask_user"

# Checkpoint
CHECKPOINT_SAVE = "hook.checkpoint_save"
CHECKPOINT_RESTORE = "hook.checkpoint_restore"

# Human Review
HUMAN_REVIEW_REQUEST = "hook.human_review_request"
HUMAN_FEEDBACK = "hook.human_feedback"

# World
WORLD_UPDATE = "hook.world_update"

# Project
PROJECT_START = "hook.project_start"
PROJECT_COMPLETE = "hook.project_complete"
PROJECT_RESUME = "hook.project_resume"
PROJECT_ERROR = "hook.project_error"

# All event types for reference
ALL_HOOK_EVENTS = [
    BEFORE_AGENT, AFTER_AGENT,
    BEFORE_CAPABILITY, AFTER_CAPABILITY,
    QUALITY_CHECK, QUALITY_PASSED, QUALITY_FAILED, QUALITY_ASK_USER,
    CHECKPOINT_SAVE, CHECKPOINT_RESTORE,
    HUMAN_REVIEW_REQUEST, HUMAN_FEEDBACK,
    WORLD_UPDATE,
    PROJECT_START, PROJECT_COMPLETE, PROJECT_RESUME, PROJECT_ERROR,
]


# ──────────────────────────────────────────────
# Hook Handler
# ──────────────────────────────────────────────

@dataclass
class HookHandler:
    """Hook 处理器."""
    name: str
    event_type: str
    handler: Callable[..., Awaitable[None]] | Callable[..., None]
    priority: int = 0           # Lower = earlier execution
    sync: bool = False          # If True, await result before continuing


# ──────────────────────────────────────────────
# HookManager
# ──────────────────────────────────────────────

class HookManager:
    """Hook 管理器 — Runtime 的核心扩展点.

    使用 EventBus 底层，提供更语义化的 API。
    """

    def __init__(self, event_bus: EventBus | None = None):
        self._bus = event_bus or get_event_bus()
        self._handlers: list[HookHandler] = []
        self._index: dict[str, list[HookHandler]] = {}

    def register(self, event_type: str, name: str,
                 handler: Callable, priority: int = 0, sync: bool = False):
        """注册 Hook.

        Args:
            event_type: 事件类型 (如 BEFORE_AGENT)
            name: Hook 名称 (用于日志和移除)
            handler: 处理函数
            priority: 优先级，越小越先执行
            sync: 是否同步等待完成
        """
        hh = HookHandler(
            name=name,
            event_type=event_type,
            handler=handler,
            priority=priority,
            sync=sync,
        )
        self._handlers.append(hh)
        self._index.setdefault(event_type, []).append(hh)
        self._index[event_type].sort(key=lambda h: h.priority)

        # Also register on EventBus for actual dispatch
        self._bus.on(event_type, handler)
        logger.debug("[HookManager] Registered '%s' on %s (priority=%d, sync=%s)",
                     name, event_type, priority, sync)

    def register_global(self, name: str, handler: Callable, priority: int = 0):
        """注册全局 Hook — 监听所有事件."""
        self._bus.on_any(handler)
        logger.debug("[HookManager] Registered global '%s' (priority=%d)", name, priority)

    def unregister(self, name: str):
        """按名称移除 Hook."""
        for hh in self._handlers[:]:
            if hh.name == name:
                self._handlers.remove(hh)
                self._bus.off(hh.event_type, hh.handler)
                if hh.event_type in self._index:
                    self._index[hh.event_type] = [
                        h for h in self._index[hh.event_type] if h.name != name
                    ]

    async def emit(self, event_type: str, data: dict[str, Any] | None = None,
                   source: str = "") -> list[Any]:
        """发射 Hook 事件.

        自动包装为 Event 并通过 EventBus 分发。
        """
        event = Event(type=event_type, data=data or {}, source=source)
        return await self._bus.emit(event)

    async def emit_sync(self, event_type: str, data: dict[str, Any] | None = None,
                        source: str = "") -> list[Any]:
        """同步发射 — 等待所有 sync handler 完成."""
        handlers = self._index.get(event_type, [])
        results = []
        event = Event(type=event_type, data=data or {}, source=source)

        for hh in handlers:
            try:
                if asyncio.iscoroutinefunction(hh.handler):
                    result = await hh.handler(event)
                else:
                    result = hh.handler(event)
                results.append(result)
            except Exception as e:
                logger.error("[HookManager] Hook '%s' error on %s: %s",
                             hh.name, event_type, e)

        return results

    def list_hooks(self, event_type: str | None = None) -> list[dict]:
        """列出已注册的 Hook."""
        if event_type:
            handlers = self._index.get(event_type, [])
        else:
            handlers = self._handlers
        return [
            {"name": h.name, "event": h.event_type, "priority": h.priority, "sync": h.sync}
            for h in handlers
        ]


# ──────────────────────────────────────────────
# Built-in Hooks
# ──────────────────────────────────────────────

def create_logging_hook() -> HookHandler:
    """结构化日志 Hook — 监听所有 Agent 事件."""
    async def handler(event: Event):
        etype = event.type
        data = event.data
        if etype == BEFORE_AGENT:
            logger.info("[Hook:Log] ▶ Agent '%s' starting (episode=%s, scene=%s)",
                        data.get("agent_id"), data.get("episode"), data.get("scene"))
        elif etype == AFTER_AGENT:
            duration = data.get("duration", 0)
            status = data.get("status", "unknown")
            logger.info("[Hook:Log] ✅ Agent '%s' done in %.1fs — %s",
                        data.get("agent_id"), duration, status)
        elif etype == QUALITY_FAILED:
            logger.warning("[Hook:Log] ❌ Quality failed for '%s': %s",
                           data.get("step"), data.get("reason"))
        elif etype == WORLD_UPDATE:
            logger.info("[Hook:Log] 📖 World updated: %s (v%d)",
                        data.get("event_type"), data.get("version"))

    return HookHandler(
        name="structured_logger",
        event_type="*",  # Will be registered as global
        handler=handler,
        priority=100,   # Run late
    )


def create_quality_hook(quality_engine) -> HookHandler:
    """质量检查 Hook — AFTER_AGENT 后自动触发 Quality Engine."""
    async def handler(event: Event):
        if event.type != AFTER_AGENT:
            return

        data = event.data
        step = data.get("agent_id", "")
        artifact = data.get("output", {})
        context = data.get("context", {})

        report = await quality_engine.check(step, artifact, context)
        data["quality_report"] = report

        if report.passed:
            await quality_engine.emit(QUALITY_PASSED, {"step": step, "report": report.model_dump()})
        else:
            await quality_engine.emit(QUALITY_FAILED, {
                "step": step,
                "report": report.model_dump(),
                "worst": report.worst_result.value,
            })

    return HookHandler(
        name="quality_gate",
        event_type=AFTER_AGENT,
        handler=handler,
        priority=10,   # Run early so failures are caught
        sync=True,     # Wait for quality check before continuing
    )


def create_progress_hook() -> HookHandler:
    """进度推送 Hook — AFTER_AGENT 后推送进度."""
    async def handler(event: Event):
        if event.type != AFTER_AGENT:
            return

        data = event.data
        progress = data.get("progress", 0)
        step = data.get("agent_id", "")
        message = data.get("message", f"{step} 完成")

        # Emit via EventBus for WebSocket consumers
        await event_bus().emit(Event(
            type="progress.update",
            data={"progress": progress, "step": step, "message": message},
            source="hook:progress",
        ))

    return HookHandler(
        name="progress_tracker",
        event_type=AFTER_AGENT,
        handler=handler,
        priority=50,
    )


# Helper to avoid circular import
def event_bus() -> EventBus:
    return get_event_bus()