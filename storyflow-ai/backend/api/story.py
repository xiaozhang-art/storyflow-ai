"""Story API routes."""

import json
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


@router.get("/{story_id}/world")
async def get_story_world(story_id: UUID):
    """Get Session state snapshot (Runtime V3)."""
    from runtime.session_manager import get_session_manager
    from runtime.artifact_manager import ArtifactManager

    session_mgr = get_session_manager()
    sessions = session_mgr.get_by_story(str(story_id))
    if not sessions:
        raise HTTPException(status_code=404, detail="No session found for this story")

    session = sessions[-1]  # latest session
    artifact_mgr = ArtifactManager()

    world_data = {
        "session_id": session.id,
        "status": session.status.value,
        "completed_steps": session.completed_steps,
        "current_step": session.current_step,
        "artifacts": {},
    }
    for step in session.completed_steps:
        artifact = artifact_mgr.load_json(session.id, step)
        if artifact:
            world_data["artifacts"][step] = artifact

    return world_data


@router.post("/{story_id}/patch")
async def apply_world_patch(story_id: UUID, patch: dict):
    """Apply user Patch to Session state.

    Body: {"character_name": "name", "field_path": "appearance.cloth", "new_value": "black armor"}
    """
    from runtime.session_manager import get_session_manager
    from runtime.artifact_manager import ArtifactManager

    session_mgr = get_session_manager()
    sessions = session_mgr.get_by_story(str(story_id))
    if not sessions:
        raise HTTPException(status_code=404, detail="No session found for this story")

    session = sessions[-1]
    artifact_mgr = ArtifactManager()

    name = patch.get("character_name", "")
    field_path = patch.get("field_path", "")
    new_value = patch.get("new_value", "")

    if not name or not field_path:
        raise HTTPException(status_code=400, detail="character_name and field_path required")

    character_data = artifact_mgr.load_json(session.id, "character")
    if not character_data:
        raise HTTPException(status_code=404, detail="Character data not found for this session")

    characters = character_data.get("characters", [])
    patched = False
    for char in characters:
        if char.get("name") == name:
            keys = field_path.split(".")
            obj = char
            for key in keys[:-1]:
                if key in obj:
                    obj = obj[key]
                else:
                    obj[key] = {}
                    obj = obj[key]
            obj[keys[-1]] = new_value
            patched = True
            break

    if not patched:
        raise HTTPException(status_code=404, detail=f"Character '{name}' not found")

    artifact_mgr.save_json(session.id, "character", character_data, "characters_patched.json")

    return {"status": "patched", "session_id": session.id, "character": name, "field": field_path}


@router.get("/{story_id}/checkpoints")
async def list_checkpoints(story_id: UUID):
    """List all Checkpoints for a Session (Runtime V3)."""
    from runtime.session_manager import get_session_manager
    from runtime.artifact_manager import ArtifactManager

    session_mgr = get_session_manager()
    sessions = session_mgr.get_by_story(str(story_id))
    if not sessions:
        raise HTTPException(status_code=404, detail="No session found for this story")

    session = sessions[-1]
    artifact_mgr = ArtifactManager()

    checkpoint_dir = artifact_mgr.get_session_dir(session.id) / "_checkpoints"
    checkpoints = []
    if checkpoint_dir.exists():
        for cp_file in sorted(checkpoint_dir.glob("*.json")):
            try:
                data = json.loads(cp_file.read_text())
                checkpoints.append({
                    "file": cp_file.name,
                    "step": data.get("step", "unknown"),
                    "timestamp": data.get("timestamp", ""),
                })
            except Exception:
                checkpoints.append({"file": cp_file.name, "error": "unreadable"})

    return {"session_id": session.id, "checkpoints": checkpoints}


@router.post("/{story_id}/resume")
async def resume_generation(story_id: UUID, db: AsyncSession = Depends(get_db)):
    """Resume generation from latest checkpoint (Runtime V3)."""
    story = await story_service.get_story(db, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    try:
        task = await story_service.start_generation(db, story_id, resume=True)
        return {"task_id": str(task.id), "message": "Generation resumed from checkpoint"}
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
                "dialogue": sc.dialogue,
                "image_url": sc.image_url,
                "audio_url": sc.audio_url,
            }
            for sc in scenes
        ],
    }