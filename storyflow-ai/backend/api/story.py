"""Story API routes."""

import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from schemas.story import StoryCreate, StoryResponse, StoryListResponse
from schemas.task import TaskStatusResponse
from services.story_service import story_service
from repositories import story_repo, task_repo

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=StoryResponse, status_code=201)
async def create_story(data: StoryCreate, db: AsyncSession = Depends(get_db)):
    """Create a new story project."""
    story = await story_service.create_story(db, data)
    return story


@router.get("", response_model=StoryListResponse)
async def list_stories(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List all stories, newest first."""
    stories = await story_service.list_stories(db, skip=skip, limit=limit)
    return stories


@router.get("/{story_id}", response_model=StoryResponse)
async def get_story(story_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get story detail by ID."""
    story = await story_service.get_story(db, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.post("/{story_id}/generate")
async def start_generation(story_id: UUID, db: AsyncSession = Depends(get_db)):
    """Start the AI generation workflow for a story."""
    try:
        task = await story_service.start_generation(db, story_id)
        return {"task_id": str(task.id), "message": "Generation started"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{story_id}/result")
async def get_story_result(story_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get the generation result for a story."""
    story = await story_service.get_story(db, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    if story.status != "completed":
        raise HTTPException(status_code=400, detail=f"Story is not completed yet (status: {story.status})")

    from configs.settings import settings
    video_url = f"/storage/stories/{story_id}/video/story.mp4"

    # Fetch episodes, characters, scenes
    from models.episode import Episode
    from models.character import Character
    from models.scene import Scene
    from sqlalchemy import select

    episodes_result = await db.execute(
        select(Episode).where(Episode.story_id == story_id).order_by(Episode.episode_no)
    )
    episodes = episodes_result.scalars().all()

    characters_result = await db.execute(
        select(Character).where(Character.story_id == story_id)
    )
    characters = characters_result.scalars().all()

    scenes_result = await db.execute(
        select(Scene).where(Scene.story_id == story_id).order_by(Scene.scene_no)
    )
    scenes = scenes_result.scalars().all()

    return {
        "story_id": str(story_id),
        "title": story.title,
        "genre": story.genre,
        "video_url": video_url,
        "episodes": [
            {
                "episode_no": ep.episode_no,
                "title": ep.title,
                "summary": ep.summary,
                "script": ep.script,
            }
            for ep in episodes
        ],
        "characters": [
            {
                "name": ch.name,
                "gender": ch.gender,
                "age": ch.age,
                "appearance": ch.appearance,
                "personality": ch.personality,
                "avatar_url": ch.avatar_url,
            }
            for ch in characters
        ],
        "scenes": [
            {
                "scene_no": sc.scene_no,
                "prompt": sc.prompt,
                "camera": sc.camera,
                "duration": sc.duration,
                "image_url": sc.image_url,
            }
            for sc in scenes
        ],
    }