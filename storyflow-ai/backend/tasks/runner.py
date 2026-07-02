"""Task runner - executes the story generation workflow with progress tracking and DB persistence.

Uses the StoryFlow Runtime (V3) as the sole execution backend.
Features: EventBus, Blackboard, Artifacts, Director, Quality Engine, DSL Workflows.
"""

import logging
import os
import traceback
from uuid import UUID

from app.redis import set_task_status

logger = logging.getLogger(__name__)

# Progress mapping for each step
STEP_PROGRESS = {
    "init": 0,
    "script": 10,
    "character": 20,
    "storyboard": 30,
    "image": 45,
    "image_to_video": 60,
    "voice": 75,
    "video": 95,
    "done": 100,
}

STEP_MESSAGE = {
    "init": "初始化工作流...",
    "script": "正在生成剧本...",
    "character": "正在设计角色形象...",
    "storyboard": "正在生成分镜...",
    "image": "正在生成图片 ({current}/{total})...",
    "image_to_video": "正在生成视频片段 ({current}/{total})...",
    "voice": "正在生成配音 ({current}/{total})...",
    "video": "正在合成最终视频...",
    "done": "漫剧生成完成！",
}

# Story status mapping for each step
STEP_STORY_STATUS = {
    "init": "generating",
    "script": "script_done",
    "character": "character_done",
    "storyboard": "storyboard_done",
    "image": "image_done",
    "image_to_video": "image_done",
    "voice": "voice_done",
    "video": "completed",
}


async def _update_progress(task_id: str, step: str, message: str = "", **kwargs):
    """Update task progress in Redis and publish via PubSub."""
    progress = STEP_PROGRESS.get(step, 0)
    msg = message or STEP_MESSAGE.get(step, f"正在执行: {step}")
    msg = msg.format(**kwargs) if kwargs else msg
    await set_task_status(task_id, {
        "task_id": task_id,
        "status": "running",
        "progress": progress,
        "current_step": step,
        "message": msg,
    })
    logger.info("Task %s: step=%s, progress=%d%%", task_id, step, progress)


async def _update_db_progress(task_id: str, story_id: str, step: str, error: str = ""):
    """Update task and story progress in PostgreSQL."""
    from app.database import async_session_factory
    from repositories import task_repo, story_repo

    async with async_session_factory() as db:
        status = "failed" if error else ("completed" if step == "done" else "running")
        progress = STEP_PROGRESS.get(step, 0)
        await task_repo.update_task_progress(
            db, UUID(task_id), status=status, progress=progress,
            current_step=step, error_message=error or None,
        )
        if not error and step in STEP_STORY_STATUS:
            await story_repo.update_story_status(db, UUID(story_id), STEP_STORY_STATUS[step])
        if error:
            await story_repo.update_story_status(db, UUID(story_id), "failed")
        await db.commit()


async def _persist_characters(story_id: str, characters: list[dict]):
    """Save enriched characters to the database."""
    from app.database import async_session_factory
    from models.character import Character
    from sqlalchemy import delete

    async with async_session_factory() as db:
        await db.execute(delete(Character).where(Character.story_id == UUID(story_id)))

        for char in characters:
            character = Character(
                story_id=UUID(story_id),
                name=char.get("name", "未命名"),
                gender=char.get("gender", "unknown"),
                age=char.get("age"),
                appearance=char.get("appearance", {}),
                personality=char.get("personality", {}),
            )
            db.add(character)
        await db.commit()
        logger.info("Persisted %d characters for story %s", len(characters), story_id)


async def _persist_episodes(story_id: str, episodes: list[dict]):
    """Save episode scripts to the database."""
    from app.database import async_session_factory
    from models.episode import Episode
    from sqlalchemy import delete

    async with async_session_factory() as db:
        await db.execute(delete(Episode).where(Episode.story_id == UUID(story_id)))

        for ep in episodes:
            episode = Episode(
                story_id=UUID(story_id),
                episode_no=ep.get("episode_no", 0),
                title=ep.get("title", ""),
                summary=ep.get("summary", ""),
                script=ep.get("script", ""),
            )
            db.add(episode)
        await db.commit()
        logger.info("Persisted %d episodes for story %s", len(episodes), story_id)


async def _persist_scenes(story_id: str, scenes: list[dict]):
    """Save storyboard scenes to the database."""
    from app.database import async_session_factory
    from models.scene import Scene
    from sqlalchemy import delete

    async with async_session_factory() as db:
        await db.execute(delete(Scene).where(Scene.story_id == UUID(story_id)))

        for sc in scenes:
            scene = Scene(
                story_id=UUID(story_id),
                episode_id=None,
                scene_no=sc.get("scene_no", 0),
                prompt=sc.get("prompt", ""),
                camera=sc.get("camera", "中景"),
                duration=sc.get("duration", 5),
                dialogue=sc.get("dialogue", ""),
            )
            db.add(scene)
        await db.commit()
        logger.info("Persisted %d scenes for story %s", len(scenes), story_id)


async def _persist_image_urls(story_id: str, images: list[dict]):
    """Update scene image URLs after image generation."""
    from app.database import async_session_factory
    from models.scene import Scene

    if not images:
        return

    async with async_session_factory() as db:
        image_map = {img["scene_no"]: img for img in images}
        from sqlalchemy import select
        result = await db.execute(
            select(Scene).where(Scene.story_id == UUID(story_id))
        )
        for scene in result.scalars().all():
            if scene.scene_no in image_map:
                scene.image_url = image_map[scene.scene_no].get("image_url")
        await db.commit()
        logger.info("Updated %d scene image URLs for story %s", len(images), story_id)


async def _persist_audio_urls(story_id: str, audios: list[dict]):
    """Update scene audio URLs after voice generation."""
    from app.database import async_session_factory
    from models.scene import Scene

    if not audios:
        return

    async with async_session_factory() as db:
        audio_map = {aud["scene_no"]: aud for aud in audios}
        from sqlalchemy import select
        result = await db.execute(
            select(Scene).where(Scene.story_id == UUID(story_id))
        )
        for scene in result.scalars().all():
            if scene.scene_no in audio_map:
                scene.audio_url = audio_map[scene.scene_no].get("audio_url")
        await db.commit()
        logger.info("Updated %d scene audio URLs for story %s", len(audios), story_id)


async def _persist_step_results(story_id: str, step: str, state: dict):
    """Persist results of a single step to the database."""
    if not state:
        return

    if step == "script":
        episodes = state.get("episodes", [])
        if episodes:
            await _persist_episodes(story_id, episodes)
    elif step == "character":
        characters = state.get("characters", [])
        if characters:
            await _persist_characters(story_id, characters)
    elif step == "storyboard":
        scenes = state.get("storyboard", [])
        if scenes:
            await _persist_scenes(story_id, scenes)
    elif step == "image":
        images = state.get("images", [])
        if images:
            await _persist_image_urls(story_id, images)
    elif step == "voice":
        audios = state.get("audios", [])
        if audios:
            await _persist_audio_urls(story_id, audios)


async def run_story_generation(
    task_id: str,
    story_id: str,
    prompt: str,
    genre: str,
):
    """Run the full story generation workflow via the StoryFlow Runtime.

    This is the sole execution path. The Runtime handles:
    - Session management (partial regeneration)
    - Step execution (linear or parallel per DSL)
    - Quality checking
    - Director intervention
    - Artifact storage
    - Event-driven progress
    """
    logger.info("Starting Runtime generation: task=%s, story=%s", task_id, story_id)

    try:
        await _update_progress(task_id, "init")
        await _update_db_progress(task_id, story_id, "init")

        # Build callbacks
        async def progress_callback(step: str, info: dict):
            await _update_progress(task_id, step, info.get("message", ""))

        async def persist_callback(step: str, state: dict):
            await _persist_step_results(story_id, step, state)
            await _update_db_progress(task_id, story_id, step)

        # Check for DSL workflow
        dsl_path = None
        dsl_file = os.path.join(
            os.path.dirname(__file__), "..", "workflows", "comic.yaml"
        )
        if os.path.exists(dsl_file):
            dsl_path = os.path.abspath(dsl_file)

        # Check feature flags
        enable_quality = os.environ.get("ENABLE_QUALITY", "true").lower() in ("true", "1", "yes")
        enable_director = os.environ.get("ENABLE_DIRECTOR", "false").lower() in ("true", "1", "yes")

        from workflows.runtime_workflow import run_story_with_runtime
        result = await run_story_with_runtime(
            task_id=task_id,
            story_id=story_id,
            prompt=prompt,
            genre=genre,
            progress_callback=progress_callback,
            persist_callback=persist_callback,
            dsl_path=dsl_path,
            enable_quality=enable_quality,
            enable_director=enable_director,
        )

        # Ensure all results are persisted
        await _persist_step_results(story_id, "script", result)
        await _persist_step_results(story_id, "character", result)
        await _persist_step_results(story_id, "storyboard", result)
        await _persist_step_results(story_id, "image", result)
        await _persist_step_results(story_id, "voice", result)

        await _update_progress(task_id, "done")
        await _update_db_progress(task_id, story_id, "done")
        logger.info("Runtime generation completed: task=%s, story=%s", task_id, story_id)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error("Runtime generation failed: task=%s, error=%s", task_id, error_msg)
        logger.error(traceback.format_exc())
        await set_task_status(task_id, {
            "task_id": task_id,
            "status": "failed",
            "progress": STEP_PROGRESS.get("video", 95),
            "current_step": "error",
            "message": error_msg,
        })
        await _update_db_progress(task_id, story_id, "init", error=error_msg)