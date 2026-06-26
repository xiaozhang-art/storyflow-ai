"""SQLAlchemy models — import all subclasses so Base.metadata.create_all discovers them."""

# Base class (re-export for convenience)
from models.base import Base, TimestampMixin

# Sub-models — MUST be imported here so that create_all() sees the table definitions
from models.story import Story
from models.episode import Episode
from models.character import Character
from models.scene import Scene
from models.task import TaskRecord

__all__ = [
    "Base",
    "TimestampMixin",
    "Story",
    "Episode",
    "Character",
    "Scene",
    "TaskRecord",
]