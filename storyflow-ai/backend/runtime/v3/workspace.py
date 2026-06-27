"""Workspace — 生成物统一管理.

Project 粒度的文件组织:
    workspace/
    └── {project_id}/
        ├── world.json          # StoryWorld 快照
        ├── checkpoints/        # Checkpoint 文件
        ├── episodes/
        │   ├── ep01/
        │   │   ├── images/
        │   │   ├── audio/
        │   │   └── subtitles/
        │   └── ep02/
        └── output/
            └── final.mp4
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Workspace:
    """Project 级别的文件工作区."""

    def __init__(self, base_path: str, project_id: str):
        self.base_path = Path(base_path)
        self.project_id = project_id
        self.project_path = self.base_path / project_id
        self._ensure_dirs()

    def _ensure_dirs(self):
        """创建项目目录结构."""
        dirs = [
            self.project_path,
            self.project_path / "checkpoints",
            self.project_path / "output",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def episode_path(self, episode_no: int) -> Path:
        """获取某集的路径，自动创建."""
        ep_dir = self.project_path / "episodes" / f"ep{episode_no:02d}"
        ep_dir.mkdir(parents=True, exist_ok=True)
        return ep_dir

    def ensure_episode_dirs(self, episode_no: int):
        """确保某集的子目录存在."""
        ep = self.episode_path(episode_no)
        for sub in ["images", "audio", "subtitles"]:
            (ep / sub).mkdir(parents=True, exist_ok=True)

    def image_path(self, episode_no: int, scene_no: int, ext: str = ".png") -> str:
        """生成图片文件路径."""
        self.ensure_episode_dirs(episode_no)
        p = self.episode_path(episode_no) / "images" / f"scene_{scene_no:03d}{ext}"
        return str(p)

    def audio_path(self, episode_no: int, scene_no: int, ext: str = ".wav") -> str:
        """生成音频文件路径."""
        self.ensure_episode_dirs(episode_no)
        p = self.episode_path(episode_no) / "audio" / f"scene_{scene_no:03d}{ext}"
        return str(p)

    def subtitle_path(self, episode_no: int, ext: str = ".ass") -> str:
        """生成字幕文件路径."""
        self.ensure_episode_dirs(episode_no)
        p = self.episode_path(episode_no) / "subtitles" / f"ep{episode_no:02d}{ext}"
        return str(p)

    def video_path(self, episode_no: int | None = None, ext: str = ".mp4") -> str:
        """生成视频文件路径."""
        if episode_no is not None:
            self.ensure_episode_dirs(episode_no)
            p = self.episode_path(episode_no) / f"episode_{episode_no:02d}{ext}"
        else:
            (self.project_path / "output").mkdir(parents=True, exist_ok=True)
            p = self.project_path / "output" / f"story{ext}"
        return str(p)

    def world_path(self) -> str:
        """StoryWorld 快照路径."""
        return str(self.project_path / "world.json")

    def checkpoint_path(self, step: str) -> str:
        """Checkpoint 文件路径."""
        import time
        filename = f"{step}_{int(time.time())}.json"
        return str(self.project_path / "checkpoints" / filename)

    def latest_checkpoint_path(self) -> str:
        """最新 Checkpoint 的路径."""
        cp_dir = self.project_path / "checkpoints"
        if not cp_dir.exists():
            return ""
        files = sorted(cp_dir.glob("*.json"))
        return str(files[-1]) if files else ""

    def list_checkpoints(self) -> list[dict]:
        """列出所有 Checkpoint."""
        cp_dir = self.project_path / "checkpoints"
        if not cp_dir.exists():
            return []
        result = []
        for f in sorted(cp_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                result.append({
                    "file": str(f),
                    "step": data.get("step", ""),
                    "timestamp": data.get("timestamp", 0),
                    "version": data.get("world_version", 0),
                })
            except Exception:
                result.append({"file": str(f), "step": "unknown"})
        return result

    def save_world(self, world_data: dict):
        """保存 StoryWorld 快照."""
        path = self.world_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(world_data, f, ensure_ascii=False, indent=2)
        logger.debug("[Workspace] World saved: %s", path)

    def load_world(self) -> dict | None:
        """加载 StoryWorld 快照."""
        path = self.world_path()
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def exists(self) -> bool:
        """项目目录是否存在（用于判断是否为恢复场景）."""
        return self.project_path.exists()