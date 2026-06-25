from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    id: UUID
    story_id: UUID
    status: str
    progress: int
    current_step: str | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskProgressEvent(BaseModel):
    task_id: UUID
    status: str
    progress: int
    current_step: str
    message: str = ""