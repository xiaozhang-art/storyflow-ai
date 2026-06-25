import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Character(Base, TimestampMixin):
    __tablename__ = "character"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    story_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("story.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    appearance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    personality: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)