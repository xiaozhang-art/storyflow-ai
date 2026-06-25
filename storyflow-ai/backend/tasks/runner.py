"""Task runner - executes the LangGraph workflow with progress tracking."""

import logging
import traceback
from workflows.story_workflow import build_story_workflow
from app.redis import set_task_status, delete_task_status

logger = logging.getLogger(__name__)

# Progress mapping for each step
STEP_PROGRESS = {
    "init": 0,
    "script": 10,
    "character": 25,
    "storyboard": 40,
    "image": 65,
    "voice": 80,
    "video": 95,
    "done": 100,
}

# Story status mapping for each step
STEP_STORY_STATUS = {
    "init": "generating",
    "script": "script_done",
    "character": "character_done",
    "storyboard": "storyboard_done",
    "image": "image_done",
    "voice": "voice_done",
    "video": "completed",
}


async def _update_progress(
    task_id: str,
    step: str,
    message: str = "",
):
    """Update task progress in Redis and publish via PubSub."""
    progress = STEP_PROGRESS.get(step, 0)
    await set_task_status(task_id, {
        "task_id": task_id,
        "status": "running",
        "progress": progress,
        "current_step": step,
        "message": message or f"正在执行: {step}",
    })
    logger.info(f"Task {task_id}: step={step}, progress={progress}%, msg={message}")


async def _update_db_progress(task_id: str, story_id: str, step: str, error: str = ""):
    """Update task and story progress in PostgreSQL."""
    from app.database import async_session_factory
    from repositories import task_repo, story_repo
    from uuid import UUID

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


async def run_story_generation(
    task_id: str,
    story_id: str,
    prompt: str,
    genre: str,
):
    """Run the full story generation workflow with progress tracking.

    This is designed to run as a background asyncio task.
    """
    logger.info(f"Starting generation: task={task_id}, story={story_id}")

    try:
        await _update_progress(task_id, "init", "初始化工作流...")
        await _update_db_progress(task_id, story_id, "init")

        workflow = build_story_workflow()

        initial_state = {
            "task_id": task_id,
            "story_id": story_id,
            "prompt": prompt,
            "genre": genre,
            "outline": "",
            "characters": [],
            "episodes": [],
            "storyboard": [],
            "images": [],
            "audios": [],
            "video_path": "",
            "current_step": "script",
            "status": "running",
            "error": "",
        }

        # Stream through the workflow to track progress
        final_state = None
        async for event in workflow.astream_events(initial_state, version="v1"):
            event_name = event.get("event", "")
            event_data = event.get("data", {})

            if event_name == "on_chain_end":
                name = event.get("name", "")
                if name in STEP_PROGRESS:
                    await _update_progress(task_id, name, f"{name} 完成")
                    await _update_db_progress(task_id, story_id, name)
                    final_state = event_data.get("output")

        # If streaming didn't capture final state, run ainvoke as fallback
        if not final_state:
            final_state = await workflow.ainvoke(initial_state)

        # Final update
        await _update_progress(task_id, "done", "漫剧生成完成！")
        await _update_db_progress(task_id, story_id, "done")
        logger.info(f"Generation completed: task={task_id}")

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Generation failed: task={task_id}, error={error_msg}")
        logger.error(traceback.format_exc())
        await set_task_status(task_id, {
            "task_id": task_id,
            "status": "failed",
            "progress": 0,
            "current_step": "error",
            "message": error_msg,
        })
        await _update_db_progress(task_id, story_id, "init", error=error_msg)
        await delete_task_status(task_id)