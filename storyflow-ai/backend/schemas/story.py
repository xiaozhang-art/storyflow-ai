from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class StoryCreate(BaseModel):
    title: str
    prompt: str
    genre: str = "校园"


class StoryResponse(BaseModel):
    id: UUID
    title: str | None
    prompt: str | None
    genre: str | None
    total_episode: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class StoryListResponse(BaseModel):
    items: list[StoryResponse]