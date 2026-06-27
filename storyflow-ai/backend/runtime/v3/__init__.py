"""Runtime v3 — 围绕三个核心问题设计.

① 长篇一致性 → StoryWorld (Story Bible)
② 质量可控   → QualityEngine + Human Review + Patch
③ 长任务可恢复 → Project + Checkpoint

Agent → Capability → Workspace → Quality → Event → Next Agent
"""
from runtime.v3.project import Project, ProjectRuntime, ProjectStatus
from runtime.v3.world.story_world import StoryWorld
from runtime.v3.quality.engine import QualityEngine
from runtime.v3.capability.registry import CapabilityRegistry
from runtime.v3.hook.manager import HookManager
from runtime.v3.event_bus import EventBus, get_event_bus
from runtime.v3.workspace import Workspace
from runtime.v3.checkpoint.store import CheckpointStore

__all__ = [
    "Project",
    "ProjectRuntime",
    "ProjectStatus",
    "StoryWorld",
    "QualityEngine",
    "CapabilityRegistry",
    "HookManager",
    "EventBus",
    "get_event_bus",
    "Workspace",
    "CheckpointStore",
]
__version__ = "3.1.0"