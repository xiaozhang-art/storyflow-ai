"""StoryContext — 故事全局状态.

扩展 StoryWorld，加入所有产出物引用。
所有 Agent 共享同一个 StoryContext，类似 Git 仓库。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from runtime.v3.world.story_world import StoryWorld
from runtime.v3.workspace import Workspace


@dataclass
class StoryContext:
    """故事全局上下文 — 所有 Agent 的共享读写空间.

    包含:
      - story_world: 世界模型（角色/地点/时间线/设定）
      - workspace: 文件工作区
      - artifacts: 所有步骤的产出物引用
      - metadata: 用户输入 + 项目元信息
      - variables: 运行时变量（Agent 可读写）
    """

    story_world: StoryWorld = field(default_factory=StoryWorld)
    workspace: Optional[Workspace] = None

    # 所有步骤的产出物
    artifacts: dict[str, Any] = field(default_factory=lambda: {
        "outline": "",
        "characters": [],
        "episodes": [],
        "storyboard": [],
        "images": [],
        "video_clips": [],
        "audios": [],
        "video_path": "",
        "video_url": "",
    })

    # 用户输入
    prompt: str = ""
    genre: str = ""
    title: str = ""
    total_episodes: int = 6
    project_id: str = ""

    # 运行时变量 — Agent 间通过这里传递信息
    variables: dict[str, Any] = field(default_factory=dict)

    # 状态
    status: str = "created"  # created / running / paused / completed / failed
    current_step: str = ""
    error_message: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def update_artifact(self, key: str, value: Any):
        """更新产出物."""
        self.artifacts[key] = value
        self.updated_at = time.time()

    def set_variable(self, key: str, value: Any):
        """设置运行时变量 — Agent 间通信."""
        self.variables[key] = value
        self.updated_at = time.time()

    def get_variable(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)

    def to_state_dict(self) -> dict:
        """转换为旧版 state dict（向后兼容）."""
        return {
            "story_id": self.project_id,
            "title": self.title,
            "genre": self.genre,
            "prompt": self.prompt,
            "total_episodes": self.total_episodes,
            **self.artifacts,
            "status": self.status,
        }

    def to_agent_context(self, capability_registry=None) -> dict:
        """转换为 Agent context dict（向后兼容）."""
        ctx = {
            "story_world": self.story_world,
            "workspace": self.workspace,
            "project_id": self.project_id,
            "story_context": self,
        }
        if capability_registry:
            ctx["capability_registry"] = capability_registry
            ctx["use_capability"] = capability_registry.use
        return ctx

    @classmethod
    def from_state(cls, state: dict, world: StoryWorld | None = None,
                   workspace: Workspace | None = None) -> "StoryContext":
        """从旧版 state dict 构建（向后兼容）."""
        artifact_keys = {"outline", "characters", "episodes", "storyboard",
                         "images", "video_clips", "audios", "video_path", "video_url"}
        artifacts = {k: state[k] for k in artifact_keys if k in state}

        return cls(
            story_world=world or StoryWorld(),
            workspace=workspace,
            artifacts=artifacts,
            prompt=state.get("prompt", ""),
            genre=state.get("genre", ""),
            title=state.get("title", ""),
            total_episodes=state.get("total_episodes", 6),
            project_id=state.get("story_id", ""),
            status=state.get("status", "created"),
        )

    def snapshot(self) -> dict:
        """完整快照（用于 Checkpoint）."""
        return {
            "artifacts": self.artifacts,
            "variables": self.variables,
            "status": self.status,
            "current_step": self.current_step,
            "error_message": self.error_message,
            "prompt": self.prompt,
            "genre": self.genre,
            "title": self.title,
            "total_episodes": self.total_episodes,
            "world_snapshot": self.story_world.to_dict(),
            "updated_at": self.updated_at,
        }

    def restore(self, data: dict):
        """从快照恢复."""
        self.artifacts = data.get("artifacts", self.artifacts)
        self.variables = data.get("variables", self.variables)
        self.status = data.get("status", self.status)
        self.current_step = data.get("current_step", "")
        self.error_message = data.get("error_message", "")
        if data.get("world_snapshot"):
            self.story_world = StoryWorld.from_dict(data["world_snapshot"])