import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Scene(Base, TimestampMixin):
    __tablename__ = "scene"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    story_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("story.id", ondelete="CASCADE"), nullable=True
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("episode.id", ondelete="CASCADE"), nullable=True
    )
    scene_no: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration: Mapped[int] = mapped_column(Integer, default=5)
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)