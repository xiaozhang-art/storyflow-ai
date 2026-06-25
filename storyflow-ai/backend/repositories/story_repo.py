"""Story repository for async CRUD operations."""

import uuid
from uuid import UUID
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from models.story import Story


async def create_story(db: AsyncSession, title: str, prompt: str, genre: str) -> Story:
    """Create a new story record."""
    story = Story(
        id=uuid.uuid4(),
        title=title,
        prompt=prompt,
        genre=genre,
        status="created",
    )
    db.add(story)
    await db.flush()
    await db.refresh(story)
    return story


async def get_story(db: AsyncSession, story_id: UUID) -> Story | None:
    """Get a story by ID."""
    result = await db.execute(select(Story).where(Story.id == story_id))
    return result.scalar_one_or_none()


async def list_stories(db: AsyncSession, skip: int = 0, limit: int = 20) -> list[Story]:
    """List stories ordered by creation time, newest first."""
    result = await db.execute(
        select(Story).order_by(desc(Story.created_at)).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def update_story_status(db: AsyncSession, story_id: UUID, status: str) -> Story | None:
    """Update story status."""
    story = await get_story(db, story_id)
    if story:
        story.status = status
        await db.flush()
        await db.refresh(story)
    return story