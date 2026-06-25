"""Story service - business logic for story operations."""

import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from schemas.story import StoryCreate
from models.story import Story
from repositories import story_repo, task_repo
from tasks.runner import run_story_generation

logger = logging.getLogger(__name__)


class StoryService:
    async def create_story(self, db: AsyncSession, data: StoryCreate) -> Story:
        """Create a new story project with associated task."""
        story = await story_repo.create_story(
            db, title=data.title, prompt=data.prompt, genre=data.genre
        )
        await task_repo.create_task(db, story.id)
        return story

    async def get_story(self, db: AsyncSession, story_id: UUID) -> Story | None:
        """Get story detail by ID."""
        return await story_repo.get_story(db, story_id)

    async def list_stories(
        self, db: AsyncSession, skip: int = 0, limit: int = 20
    ) -> list[Story]:
        """List all stories, newest first."""
        return await story_repo.list_stories(db, skip=skip, limit=limit)

    async def start_generation(self, db: AsyncSession, story_id: UUID):
        """Start the story generation workflow."""
        story = await story_repo.get_story(db, story_id)
        if not story:
            raise ValueError(f"Story {story_id} not found")
        if story.status == "generating":
            raise ValueError(f"Story {story_id} is already generating")

        await story_repo.update_story_status(db, story_id, "generating")

        task = await task_repo.get_task_by_story(db, story_id)
        if not task:
            task = await task_repo.create_task(db, story_id)

        await task_repo.update_task_progress(
            db, task.id, status="running", progress=0, current_step="init"
        )

        # Launch workflow in background
        import asyncio
        asyncio.create_task(
            run_story_generation(
                task_id=str(task.id),
                story_id=str(story.id),
                prompt=story.prompt or "",
                genre=story.genre or "校园",
            )
        )
        return task


story_service = StoryService()