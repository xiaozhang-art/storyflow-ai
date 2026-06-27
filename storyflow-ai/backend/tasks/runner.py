"""Task runner - executes the story generation workflow via Project Runtime.

Pipeline: script → character → storyboard → image → voice → video
Each step runs through: Agent → Capability → Workspace → Quality → Hook → Next Agent
"""

import logging
import os
import traceback
from uuid import UUID

from app.redis import set_task_status

logger = logging.getLogger(__name__)

STEP_PROGRESS = {
    "init": 0, "script": 10, "character": 22, "storyboard": 35,
    "image": 50, "image_to_video": 70, "voice": 85, "video": 95, "done": 100,
}

STEP_MESSAGE = {
    "init": "初始化...",
    "script": "正在生成剧本...",
    "character": "正在设计角色...",
    "storyboard": "正在生成分镜...",
    "image": "正在生成图片 ({current}/{total})...",
    "image_to_video": "正在生成视频片段 ({current}/{total})...",
    "voice": "正在生成配音 ({current}/{total})...",
    "video": "正在合成最终视频...",
    "done": "漫剧生成完成！",
}

STEP_STORY_STATUS = {
    "init": "generating", "script": "script_done", "character": "character_done",
    "storyboard": "storyboard_done", "image": "image_done",
    "image_to_video": "i2v_done",
    "voice": "voice_done", "video": "completed",
}


async def _update_progress(task_id: str, step: str, message: str = "", **kwargs):
    progress = STEP_PROGRESS.get(step, 0)
    msg = message or STEP_MESSAGE.get(step, f"正在执行: {step}")
    msg = msg.format(**kwargs) if kwargs else msg
    await set_task_status(task_id, {
        "task_id": task_id, "status": "running",
        "progress": progress, "current_step": step, "message": msg,
    })


async def _update_db_progress(task_id: str, story_id: str, step: str, error: str = ""):
    from app.database import async_session_factory
    from repositories import task_repo, story_repo
    async with async_session_factory() as db:
        status = "failed" if error else ("completed" if step == "done" else "running")
        progress = STEP_PROGRESS.get(step, 0)
        await task_repo.update_task_progress(db, UUID(task_id), status=status,
                                              progress=progress, current_step=step,
                                              error_message=error or None)
        if not error and step in STEP_STORY_STATUS:
            await story_repo.update_story_status(db, UUID(story_id), STEP_STORY_STATUS[step])
        if error:
            await story_repo.update_story_status(db, UUID(story_id), "failed")
        await db.commit()


async def _persist_characters(story_id: str, characters: list[dict]):
    from app.database import async_session_factory
    from models.character import Character
    from sqlalchemy import delete
    async with async_session_factory() as db:
        await db.execute(delete(Character).where(Character.story_id == UUID(story_id)))
        for c in characters:
            db.add(Character(story_id=UUID(story_id), name=c.get("name", "未命名"),
                             gender=c.get("gender", "unknown"), age=c.get("age"),
                             appearance=c.get("appearance", {}), personality=c.get("personality", {})))
        await db.commit()


async def _persist_episodes(story_id: str, episodes: list[dict]):
    from app.database import async_session_factory
    from models.episode import Episode
    from sqlalchemy import delete
    async with async_session_factory() as db:
        await db.execute(delete(Episode).where(Episode.story_id == UUID(story_id)))
        for ep in episodes:
            db.add(Episode(story_id=UUID(story_id), episode_no=ep.get("episode_no", 0),
                            title=ep.get("title", ""), summary=ep.get("summary", ""),
                            script=ep.get("script", "")))
        await db.commit()


async def _persist_scenes(story_id: str, scenes: list[dict]):
    from app.database import async_session_factory
    from models.scene import Scene
    from sqlalchemy import delete
    async with async_session_factory() as db:
        await db.execute(delete(Scene).where(Scene.story_id == UUID(story_id)))
        for sc in scenes:
            db.add(Scene(story_id=UUID(story_id), scene_no=sc.get("scene_no", 0),
                         prompt=sc.get("prompt", ""), camera=sc.get("camera", "中景"),
                         duration=sc.get("duration", 5), dialogue=sc.get("dialogue", "")))
        await db.commit()


async def _persist_image_urls(story_id: str, images: list[dict]):
    if not images:
        return
    from app.database import async_session_factory
    from models.scene import Scene
    from sqlalchemy import select
    async with async_session_factory() as db:
        image_map = {img["scene_no"]: img for img in images}
        result = await db.execute(select(Scene).where(Scene.story_id == UUID(story_id)))
        for scene in result.scalars().all():
            if scene.scene_no in image_map:
                scene.image_url = image_map[scene.scene_no].get("image_url")
        await db.commit()


async def _persist_audio_urls(story_id: str, audios: list[dict]):
    if not audios:
        return
    from app.database import async_session_factory
    from models.scene import Scene
    from sqlalchemy import select
    async with async_session_factory() as db:
        audio_map = {a["scene_no"]: a for a in audios}
        result = await db.execute(select(Scene).where(Scene.story_id == UUID(story_id)))
        for scene in result.scalars().all():
            if scene.scene_no in audio_map:
                scene.audio_url = audio_map[scene.scene_no].get("audio_url")
        await db.commit()


async def _persist_all_results(story_id: str, state: dict):
    """Persist all intermediate results."""
    if state.get("episodes"):
        await _persist_episodes(story_id, state["episodes"])
    if state.get("characters"):
        await _persist_characters(story_id, state["characters"])
    if state.get("storyboard"):
        await _persist_scenes(story_id, state["storyboard"])
    if state.get("images"):
        await _persist_image_urls(story_id, state["images"])
    if state.get("audios"):
        await _persist_audio_urls(story_id, state["audios"])


async def run_story_generation(task_id: str, story_id: str, prompt: str, genre: str):
    """Run the full story generation workflow via Project Runtime."""
    from configs.settings import settings
    from runtime.v3 import Project, ProjectRuntime

    logger.info("Starting generation: task=%s, story=%s", task_id, story_id)

    try:
        await _update_progress(task_id, "init")
        await _update_db_progress(task_id, story_id, "init")

        project = Project(id=story_id, title="", genre=genre, prompt=prompt,
                          total_episodes=settings.MAX_EPISODES)

        runtime = ProjectRuntime(project=project, storage_path=settings.STORAGE_PATH)

        # Register agents
        from agents.script_agent import script_agent
        from agents.character_agent import character_agent
        from agents.storyboard_agent import storyboard_agent
        from agents.image_agent import image_agent
        from agents.image_to_video_agent import image_to_video_agent
        from agents.voice_agent import voice_agent
        from agents.video_agent import video_agent

        for step, agent in [("script", script_agent), ("character", character_agent),
                            ("storyboard", storyboard_agent), ("image", image_agent),
                            ("image_to_video", image_to_video_agent),
                            ("voice", voice_agent), ("video", video_agent)]:
            runtime.register_agent(step, agent)

        # Progress callback → Redis + WebSocket
        async def on_progress(progress, step, message):
            await set_task_status(task_id, {"task_id": task_id, "status": "running",
                                           "progress": progress, "current_step": step, "message": message})
            await _update_db_progress(task_id, story_id, step)
        runtime.set_progress_callback(on_progress)

        # Run
        result = await runtime.run()

        # Persist to DB
        await _persist_all_results(story_id, result)

        if result.get("status") == "completed":
            await _update_progress(task_id, "done")
            await _update_db_progress(task_id, story_id, "done")
        else:
            error = result.get("error", "Unknown error")
            await set_task_status(task_id, {"task_id": task_id, "status": "failed",
                                           "progress": 95, "current_step": "error", "message": error})
            await _update_db_progress(task_id, story_id, "init", error=error)

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error("Generation failed: task=%s, error=%s", task_id, error_msg)
        logger.error(traceback.format_exc())
        await set_task_status(task_id, {"task_id": task_id, "status": "failed",
                                       "progress": 95, "current_step": "error", "message": error_msg})
        await _update_db_progress(task_id, story_id, "init", error=error_msg)