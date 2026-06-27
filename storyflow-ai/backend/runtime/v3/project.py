"""Project + ProjectRuntime — v3 Runtime 的顶层编排.

核心思想:
- 每个 Story 是一个 Project
- Project 拥有独立的 Runtime 实例
- 关闭网页回来可以恢复
- Agent 只做 Planner，能力由 Capability 提供
- 质量由 Quality Engine 保证
- 一切通过 Hook 扩展

Agent → Capability → Workspace → Quality → Event → Next Agent
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from runtime.v3.world.story_world import StoryWorld, StoryBible, CharacterProfile
from runtime.v3.quality.engine import QualityEngine, QualityReport, CheckResult
from runtime.v3.capability.registry import CapabilityRegistry
from runtime.v3.hook.manager import (
    HookManager, HookHandler,
    BEFORE_AGENT, AFTER_AGENT,
    QUALITY_FAILED, QUALITY_PASSED, QUALITY_ASK_USER,
    CHECKPOINT_SAVE, WORLD_UPDATE,
    PROJECT_START, PROJECT_COMPLETE, PROJECT_RESUME, PROJECT_ERROR,
)
from runtime.v3.event_bus import EventBus, Event, get_event_bus, reset_event_bus
from runtime.v3.workspace import Workspace
from runtime.v3.checkpoint.store import CheckpointStore

logger = logging.getLogger(__name__)


class ProjectStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"        # Human Review 中
    COMPLETED = "completed"
    FAILED = "failed"


# Pipeline step definition
@dataclass
class PipelineStep:
    """管线中的一个步骤."""
    name: str                              # "script", "character", etc.
    agent_func: Callable                   # async def(state, context) -> dict
    capabilities_needed: list[str] = field(default_factory=list)
    human_review: bool = False             # 该步骤完成后是否暂停等用户确认
    quality_checkers: list[str] | None = None  # None = use defaults


# The standard 7-step pipeline (v3.1: added image_to_video for 漫剧)
STANDARD_PIPELINE = ["script", "character", "storyboard", "image", "image_to_video", "voice", "video"]


@dataclass
class Project:
    """一个漫剧项目."""
    id: str
    title: str = ""
    genre: str = ""
    prompt: str = ""
    status: ProjectStatus = ProjectStatus.CREATED
    total_episodes: int = 6
    current_episode: int = 0
    current_step: str = ""
    current_scene: int = 0
    retry_count: int = 0
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ProjectRuntime:
    """Project Runtime — 每个项目一个独立实例.

    组件:
        StoryWorld      — 长期知识 (Story Bible)
        Workspace       — 文件管理
        CheckpointStore — 存档/恢复
        QualityEngine   — 质量审核
        CapabilityRegistry — 能力调用
        HookManager     — 生命周期扩展
        EventBus        — 事件分发
    """

    def __init__(
        self,
        project: Project,
        storage_path: str = "./storage",
        event_bus: EventBus | None = None,
    ):
        self.project = project
        self.world = StoryWorld(story_id=project.id, project_id=project.id)
        self.workspace = Workspace(storage_path, project.id)
        self.checkpoint_store = CheckpointStore(self.workspace)
        self.quality_engine = QualityEngine()
        self.capability_registry = CapabilityRegistry()
        self.hook_manager = HookManager(event_bus or get_event_bus())
        self._event_bus = event_bus or get_event_bus()

        # Agent registry: step_name → agent_func
        self._agents: dict[str, Callable] = {}
        self._human_review_callback: Callable | None = None
        self._progress_callback: Callable | None = None

        # Setup defaults
        self.quality_engine.setup_defaults()
        self.capability_registry.setup_defaults()
        self._register_default_hooks()

    # ── Registration ──

    def register_agent(self, step: str, agent_func: Callable):
        """注册 Agent 函数.

        Agent 签名: async def agent_func(state: dict, context: dict) -> dict
        context 包含: story_world, workspace, capability_registry, use_capability
        """
        self._agents[step] = agent_func

    def set_human_review_callback(self, callback: Callable):
        """设置人工审核回调.

        callback(review_info: dict) -> {"approved": True} or {"patch": {...}} or None
        """
        self._human_review_callback = callback
        self.quality_engine.set_human_review_callback(
            lambda step, info: self._async_wrap_callback(info)
        )

    def set_progress_callback(self, callback: Callable):
        """设置进度回调.

        callback(progress: int, step: str, message: str)
        """
        self._progress_callback = callback

    # ── Main Execution ──

    async def run(self, from_step: str | None = None, from_episode: int = 0) -> dict:
        """执行项目管线.

        Args:
            from_step: 从哪步恢复 (None = 从头开始)
            from_episode: 从哪集恢复

        Returns:
            Final state dict
        """
        start_time = time.time()
        self.project.status = ProjectStatus.RUNNING

        # Try to restore from checkpoint
        is_resume = from_step is not None
        if is_resume:
            resume_point = self.checkpoint_store.get_resume_point()
            if resume_point and resume_point.get("checkpoint"):
                cp = resume_point["checkpoint"]
                if cp.world_snapshot:
                    self.world = StoryWorld.from_dict(cp.world_snapshot)
                # Restore artifacts into state
                from_step = from_step or resume_point["step"]
                logger.info("[ProjectRuntime] Resumed from checkpoint: step=%s, episode=%d",
                            from_step, resume_point.get("episode", 0))
            await self.hook_manager.emit(PROJECT_RESUME, {
                "project_id": self.project.id, "from_step": from_step,
            })
        else:
            await self.hook_manager.emit(PROJECT_START, {
                "project_id": self.project.id,
            })

        # Determine starting point
        steps = STANDARD_PIPELINE.copy()
        start_idx = 0
        if from_step and from_step in steps:
            start_idx = steps.index(from_step)

        # Shared state
        state: dict[str, Any] = {
            "story_id": self.project.id,
            "title": self.project.title,
            "genre": self.project.genre,
            "prompt": self.project.prompt,
            "total_episodes": self.project.total_episodes,
            "episodes": [],
            "characters": [],
            "storyboard": [],
            "images": [],
            "video_clips": [],
            "voices": [],
            "audios": [],
            "video_path": "",
            "video_url": "",
            "status": "running",
        }

        # Restore artifacts from checkpoint if resuming
        if is_resume:
            cp = self.checkpoint_store.get_resume_point()
            if cp and cp.get("checkpoint"):
                state.update(cp["checkpoint"].artifacts)

        context = self._build_context()

        try:
            for step_name in steps[start_idx:]:
                self.project.current_step = step_name
                step_start = time.time()

                agent_func = self._agents.get(step_name)
                if not agent_func:
                    logger.warning("[ProjectRuntime] No agent for step: %s, skipping", step_name)
                    continue

                # BEFORE_AGENT hook
                await self.hook_manager.emit(BEFORE_AGENT, {
                    "agent_id": step_name,
                    "project_id": self.project.id,
                    "episode": self.project.current_episode,
                })

                # Execute agent (with retry via Quality Engine)
                max_retries = 2
                for attempt in range(max_retries + 1):
                    try:
                        result = await agent_func(state, context)
                        if result:
                            state.update(result)
                    except Exception as e:
                        logger.error("[ProjectRuntime] Agent %s error (attempt %d): %s",
                                     step_name, attempt + 1, e)
                        result = {"status": "error", "error": str(e)}
                        state.update(result)

                    # Quality check
                    quality_ctx = {
                        "story_world": self.world,
                        "episode": self.project.current_episode,
                        "scene": self.project.current_scene,
                    }
                    report, should_continue = await self.quality_engine.check_and_handle(
                        step_name, result or {}, quality_ctx, max_retries=0,
                    )

                    if should_continue:
                        break
                    elif report.worst_result == CheckResult.RETRY and attempt < max_retries:
                        logger.info("[ProjectRuntime] %s quality retry %d/%d",
                                    step_name, attempt + 1, max_retries)
                        # Inject retry hints into state
                        state["_retry_hint"] = "; ".join(report.retry_hints)
                        continue
                    elif report.worst_result == CheckResult.ASK_USER:
                        # Pause for human review
                        self.project.status = ProjectStatus.PAUSED
                        logger.info("[ProjectRuntime] Paused for human review at %s", step_name)
                        return state
                    else:
                        # FAIL
                        state["status"] = "failed"
                        self.project.status = ProjectStatus.FAILED
                        self.project.error_message = f"{step_name}: " + "; ".join(report.failed_checkers)
                        await self.hook_manager.emit(PROJECT_ERROR, {
                            "project_id": self.project.id,
                            "step": step_name,
                            "error": self.project.error_message,
                        })
                        return state

                # Post-step: update world, save checkpoint
                await self._post_step(step_name, state)

                # Report progress
                step_idx = steps.index(step_name)
                progress = int((step_idx + 1) / len(steps) * 100)
                await self._report_progress(progress, step_name, f"{step_name} 完成")

                # AFTER_AGENT hook
                await self.hook_manager.emit(AFTER_AGENT, {
                    "agent_id": step_name,
                    "project_id": self.project.id,
                    "status": "success",
                    "duration": time.time() - step_start,
                    "output": result or {},
                    "context": quality_ctx,
                    "progress": progress,
                })

                # Human Review Checkpoint
                if step_name in ("script", "character") and self._human_review_callback:
                    await self._request_human_review(step_name, state)

            # Pipeline complete
            state["status"] = "completed"
            self.project.status = ProjectStatus.COMPLETED
            await self._report_progress(100, "done", "漫剧生成完成")
            await self.hook_manager.emit(PROJECT_COMPLETE, {
                "project_id": self.project.id,
                "duration": time.time() - start_time,
            })

        except Exception as e:
            logger.error("[ProjectRuntime] Unhandled error: %s\n%s", e, traceback.format_exc())
            state["status"] = "failed"
            self.project.status = ProjectStatus.FAILED
            self.project.error_message = str(e)
            await self.hook_manager.emit(PROJECT_ERROR, {
                "project_id": self.project.id, "error": str(e),
            })

        # Final world save
        self.workspace.save_world(self.world.to_dict())

        return state

    # ── Post-Step Processing ──

    async def _post_step(self, step_name: str, state: dict):
        """步骤完成后: 更新 StoryWorld + 保存 Checkpoint."""

        # Update StoryWorld based on step output
        if step_name == "script" and state.get("episodes"):
            self.world.story_bible = StoryBible(
                title=state.get("title", ""),
                genre=state.get("genre", ""),
                total_episodes=len(state["episodes"]),
                visual_style=state.get("visual_style", "anime"),
            )

        elif step_name == "character" and state.get("characters"):
            for char_data in state["characters"]:
                profile = CharacterProfile(
                    name=char_data.get("name", ""),
                    gender=char_data.get("gender", ""),
                    age=char_data.get("age", ""),
                    appearance=char_data.get("appearance", {}),
                    personality=char_data.get("personality", []),
                    backstory=char_data.get("backstory", ""),
                )
                if profile.name:
                    self.world.add_character(profile)

        elif step_name == "storyboard" and state.get("storyboard"):
            # Extract locations from storyboard
            for scene in state["storyboard"]:
                loc_name = scene.get("location", "")
                if loc_name and loc_name not in self.world.locations:
                    from runtime.v3.world.story_world import LocationProfile
                    self.world.add_location(LocationProfile(
                        name=loc_name,
                        description=scene.get("background", ""),
                    ))

        # Save Checkpoint
        self.checkpoint_store.save(
            step=step_name,
            world_snapshot=self.world.to_dict(),
            artifacts={
                k: v for k, v in state.items()
                if k in ("episodes", "characters", "storyboard", "images", "voices", "video_path")
            },
            episode=self.project.current_episode,
        )

        # Save World
        self.workspace.save_world(self.world.to_dict())

        # Emit world update
        await self.hook_manager.emit(WORLD_UPDATE, {
            "event_type": step_name,
            "version": self.world.version,
            "character_count": len(self.world.characters),
            "location_count": len(self.world.locations),
        })

    # ── Human Review ──

    async def _request_human_review(self, step_name: str, state: dict):
        """请求人工审核 — 在关键节点暂停."""
        review_info = {
            "step": step_name,
            "project_id": self.project.id,
            "summary": self._build_review_summary(step_name, state),
        }

        await self.hook_manager.emit("hook.human_review_request", review_info)

        if self._human_review_callback:
            feedback = await self._human_review_callback(review_info)
            if feedback and feedback.get("patch"):
                patch = feedback["patch"]
                if patch.get("character_name") and patch.get("field_path"):
                    self.world.apply_patch(
                        patch["character_name"],
                        patch["field_path"],
                        patch.get("old_value", ""),
                        patch["new_value"],
                    )
                    self.workspace.save_world(self.world.to_dict())

    def _build_review_summary(self, step_name: str, state: dict) -> dict:
        """构建审核摘要."""
        if step_name == "script":
            return {
                "type": "script_review",
                "episode_count": len(state.get("episodes", [])),
                "titles": [ep.get("title", "") for ep in state.get("episodes", [])[:5]],
                "character_names": [c.get("name", "") for c in state.get("characters", [])],
            }
        elif step_name == "character":
            return {
                "type": "character_review",
                "characters": [
                    {"name": c.get("name"), "gender": c.get("gender"), "appearance": c.get("appearance")}
                    for c in state.get("characters", [])
                ],
            }
        return {"type": step_name}

    # ── Helpers ──

    def _build_context(self) -> dict:
        """构建 Agent 上下文."""
        return {
            "story_world": self.world,
            "workspace": self.workspace,
            "capability_registry": self.capability_registry,
            "use_capability": self.capability_registry.use,
            "project_id": self.project.id,
        }

    def _register_default_hooks(self):
        """注册默认 Hook."""
        from runtime.v3.hook.manager import create_logging_hook, create_progress_hook
        logging_hook = create_logging_hook()
        self.hook_manager.register_global(logging_hook.name, logging_hook.handler, priority=100)

    async def _report_progress(self, progress: int, step: str, message: str):
        """报告进度."""
        if self._progress_callback:
            try:
                if asyncio.iscoroutinefunction(self._progress_callback):
                    await self._progress_callback(progress, step, message)
                else:
                    self._progress_callback(progress, step, message)
            except Exception as e:
                logger.error("[ProjectRuntime] Progress callback error: %s", e)

        # Also emit via EventBus for WebSocket consumers
        await self._event_bus.emit(Event(
            type="progress.update",
            data={
                "project_id": self.project.id,
                "progress": progress,
                "step": step,
                "message": message,
                "status": self.project.status.value,
            },
            source="project_runtime",
        ))

    async def _async_wrap_callback(self, info: dict) -> dict | None:
        """Wrap sync human review callback to async."""
        if not self._human_review_callback:
            return None
        if asyncio.iscoroutinefunction(self._human_review_callback):
            return await self._human_review_callback(info)
        return self._human_review_callback(info)

    # ── Lifecycle ──

    def can_resume(self) -> bool:
        """是否可以恢复."""
        return self.workspace.exists() and self.checkpoint_store.load_latest() is not None

    def get_resume_info(self) -> dict | None:
        """获取恢复信息."""
        point = self.checkpoint_store.get_resume_point()
        if not point:
            return None
        cp = point["checkpoint"]
        return {
            "step": point["step"],
            "episode": point.get("episode", 0),
            "world_version": cp.world_version,
            "timestamp": cp.timestamp,
        }

    def get_stats(self) -> dict:
        """获取 Runtime 统计."""
        return {
            "project_id": self.project.id,
            "status": self.project.status.value,
            "world_version": self.world.version,
            "characters": len(self.world.characters),
            "locations": len(self.world.locations),
            "timeline_events": len(self.world.timeline),
            "checkpoints": len(self.checkpoint_store.list_all()),
            "capabilities": [c["name"] for c in self.capability_registry.list_all()],
            "hooks": [h["name"] for h in self.hook_manager.list_hooks()],
        }