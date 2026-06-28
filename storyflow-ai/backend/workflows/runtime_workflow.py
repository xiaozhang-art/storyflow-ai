"""Runtime Workflow - Executes story generation through the StoryFlow Runtime.

This is the ONLY execution backend. The old V2 RuntimeApp and LangGraph
fallback have been removed.

Execution flow:
    1. Runtime creates a Session
    2. WorkflowEngine executes steps (linear or parallel per DSL)
    3. Each step: before-hooks → agent → artifacts → quality → after-hooks
    4. Director observes and intervenes on failures/quality issues
    5. Progress events are published via EventBus
    6. Results are persisted incrementally to DB
"""

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


async def run_story_with_runtime(
    task_id: str,
    story_id: str,
    prompt: str,
    genre: str,
    progress_callback: Callable | None = None,
    persist_callback: Callable | None = None,
    dsl_path: str | None = None,
    enable_quality: bool = True,
    enable_director: bool = False,
) -> dict:
    """Execute story generation using the StoryFlow Runtime.

    Args:
        task_id: Task ID for progress tracking
        story_id: Story ID for database operations
        prompt: User's creative prompt
        genre: Story genre
        progress_callback: Optional async callback(step, progress_dict)
        persist_callback: Optional async callback(step, state) for DB persistence
        dsl_path: Optional YAML DSL path for workflow definition
        enable_quality: Whether to enable quality checks
        enable_director: Whether to enable Director intervention

    Returns:
        Final state dict with all pipeline results
    """
    from runtime.core import get_runtime

    runtime = get_runtime()

    # Load DSL if provided
    if dsl_path:
        try:
            runtime.workflow_engine.load_dsl(dsl_path)
        except Exception as e:
            logger.warning("Failed to load DSL %s: %s, using default pipeline", dsl_path, e)

    # Configure quality and director
    if runtime.quality_engine:
        runtime.quality_engine.enabled = enable_quality
    if runtime.director:
        runtime.director.enabled = enable_director

    # Subscribe to events for progress tracking
    from runtime.event_bus import EventType

    async def on_step_started(event):
        step = event.data.get("step", "")
        if progress_callback:
            await progress_callback(step, {
                "task_id": task_id,
                "current_step": step,
                "message": f"正在执行: {step}",
            })

    async def on_step_completed(event):
        step = event.data.get("step", "")
        session_id = event.session_id
        if persist_callback:
            # Load the artifact for this step and persist
            artifact = runtime.artifact_manager.load_json(session_id, step)
            if artifact:
                await persist_callback(step, artifact)

    async def on_step_failed(event):
        step = event.data.get("step", "")
        error = event.data.get("error", "Unknown error")
        if progress_callback:
            await progress_callback("error", {
                "task_id": task_id,
                "current_step": step,
                "message": f"步骤 {step} 失败: {error}",
            })

    runtime.event_bus.subscribe(EventType.STEP_STARTED, on_step_started)
    runtime.event_bus.subscribe(EventType.STEP_COMPLETED, on_step_completed)
    runtime.event_bus.subscribe(EventType.STEP_FAILED, on_step_failed)

    # Create session and run
    session = runtime.create_session(
        story_id=story_id,
        task_id=task_id,
        prompt=prompt,
        genre=genre,
    )

    result = await runtime.run(session.id)
    logger.info("Runtime pipeline completed: task=%s, session=%s", task_id, session.id)

    return result