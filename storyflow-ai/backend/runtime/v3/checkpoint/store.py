"""Checkpoint — 支持长任务恢复.

核心思想：
- 关键节点自动保存 Checkpoint
- Checkpoint 包含: 当前步骤 + StoryWorld 快照 + Agent 产出物
- 恢复时从最近 Checkpoint 继续，不是重新开始
- 像游戏存档一样

Checkpoint 存储在 Workspace 中（JSON 文件），
以后可替换为数据库存储。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CheckpointStatus(str, Enum):
    SAVED = "saved"
    RESTORED = "restored"
    SKIPPED = "skipped"


@dataclass
class Checkpoint:
    """一个存档点."""
    project_id: str
    step: str                  # "script", "character", "storyboard", "image_ep01", etc.
    timestamp: float = field(default_factory=time.time)
    world_snapshot: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)  # Step outputs
    world_version: int = 0
    episode: int = 0
    scene: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "step": self.step,
            "timestamp": self.timestamp,
            "world_snapshot": self.world_snapshot,
            "artifacts": self.artifacts,
            "world_version": self.world_version,
            "episode": self.episode,
            "scene": self.scene,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Checkpoint":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Steps that trigger automatic checkpoints (before execution)
CHECKPOINT_STEPS = [
    "script", "character", "storyboard",
    "image", "voice", "video",
]


class CheckpointStore:
    """Checkpoint 存储 — 基于 Workspace 文件系统."""

    def __init__(self, workspace):
        """
        Args:
            workspace: Workspace instance
        """
        self.workspace = workspace

    def save(self, step: str, world_snapshot: dict | None = None,
             artifacts: dict | None = None, episode: int = 0, scene: int = 0,
             metadata: dict | None = None) -> Checkpoint:
        """保存 Checkpoint.

        Returns:
            The saved Checkpoint
        """
        import time as _time

        world_data = world_snapshot or {}
        if not world_data:
            # Try loading current world from workspace
            loaded = self.workspace.load_world()
            if loaded:
                world_data = loaded

        cp = Checkpoint(
            project_id=self.workspace.project_id,
            step=step,
            timestamp=_time.time(),
            world_snapshot=world_data,
            artifacts=artifacts or {},
            world_version=world_data.get("version", 0),
            episode=episode,
            scene=scene,
            metadata=metadata or {},
        )

        # Write to workspace
        path = self.workspace.checkpoint_path(step)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cp.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info("[Checkpoint] Saved: step=%s, version=%d, path=%s",
                    step, cp.world_version, path)
        return cp

    def load_latest(self) -> Checkpoint | None:
        """加载最新的 Checkpoint."""
        path = self.workspace.latest_checkpoint_path()
        if not path:
            return None
        return self._load_file(path)

    def load_for_step(self, step: str) -> Checkpoint | None:
        """加载特定步骤的 Checkpoint."""
        import glob
        cp_dir = self.workspace.project_path / "checkpoints"
        if not cp_dir.exists():
            return None

        files = sorted(cp_dir.glob(f"{step}_*.json"), reverse=True)
        if not files:
            return None
        return self._load_file(str(files[0]))

    def get_resume_point(self) -> dict | None:
        """获取恢复点信息.

        Returns:
            {"step": "image", "episode": 2, "checkpoint": Checkpoint} or None
        """
        cp = self.load_latest()
        if not cp:
            return None
        return {
            "step": cp.step,
            "episode": cp.episode,
            "scene": cp.scene,
            "checkpoint": cp,
        }

    def _load_file(self, path: str) -> Checkpoint | None:
        """从文件加载 Checkpoint."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Checkpoint.from_dict(data)
        except Exception as e:
            logger.error("[Checkpoint] Failed to load %s: %s", path, e)
            return None

    def list_all(self) -> list[dict]:
        """列出所有 Checkpoint."""
        return self.workspace.list_checkpoints()