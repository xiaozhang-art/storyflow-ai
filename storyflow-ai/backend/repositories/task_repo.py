"""Task repository for async CRUD operations."""

import uuid
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models.task import TaskRecord


async def create_task(db: AsyncSession, story_id: UUID) -> TaskRecord:
    """Create a new task record."""
    task = TaskRecord(
        id=uuid.uuid4(),
        story_id=story_id,
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: UUID) -> TaskRecord | None:
    """Get a task by ID."""
    result = await db.execute(select(TaskRecord).where(TaskRecord.id == task_id))
    return result.scalar_one_or_none()


async def get_task_by_story(db: AsyncSession, story_id: UUID) -> TaskRecord | None:
    """Get the latest task for a story."""
    from sqlalchemy import desc
    result = await db.execute(
        select(TaskRecord)
        .where(TaskRecord.story_id == story_id)
        .order_by(desc(TaskRecord.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_task_progress(
    db: AsyncSession,
    task_id: UUID,
    status: str,
    progress: int,
    current_step: str,
    error_message: str | None = None,
) -> TaskRecord | None:
    """Update task progress and status."""
    task = await get_task(db, task_id)
    if task:
        task.status = status
        task.progress = progress
        task.current_step = current_step
        if error_message:
            task.error_message = error_message
        await db.flush()
        await db.refresh(task)
    return task