"""Runtime-based workflow - Executes story generation through the Agent OS Runtime.

This module provides the new execution path that replaces the LangGraph
pipeline with the full Agent OS Runtime, gaining:
- Hook observability (every step is traced)
- Session management (crash recovery via session restore)
- Memory injection (character consistency)
- Skill validation (output structure enforcement)
- A2A communication (future: multi-agent collaboration)
- Execution scheduling (worker pools, backpressure)

The old LangGraph workflow (story_workflow.py) is kept for backward compatibility.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


async def run_with_runtime(
    task_id: str,
    story_id: str,
    prompt: str,
    genre: str,
    progress_callback=None,
) -> dict:
    """Execute story generation using the Agent OS Runtime.

    This is the new execution path that uses:
    1. RuntimeWorkflowRunner (wraps legacy agents)
    2. Conversation Manager (orchestrates the pipeline)
    3. Hook System (observability on every step)
    4. Memory System (injects character/story context)

    Falls back to LangGraph if Runtime is not initialized.
    """
    try:
        from runtime.app import get_runtime_app
        runtime_app = get_runtime_app()

        if not runtime_app._initialized:
            logger.info("Runtime not initialized, falling back to LangGraph workflow")
            return await _fallback_langgraph(task_id, story_id, prompt, genre, progress_callback)

        # Register all agents with the Runtime
        runner = runtime_app.get_workflow_runner()
        _register_all_agents(runner)

        # Execute through Runtime
        result = await runner.run_pipeline(
            task_id=task_id,
            story_id=story_id,
            prompt=prompt,
            genre=genre,
            progress_callback=progress_callback,
        )

        logger.info("Runtime pipeline completed | task=%s", task_id)
        return result

    except Exception as e:
        logger.error("Runtime execution failed, falling back to LangGraph: %s", e)
        return await _fallback_langgraph(task_id, story_id, prompt, genre, progress_callback)


def _register_all_agents(runner):
    """Register all legacy agents with the RuntimeWorkflowRunner."""
    from agents.script_agent import script_agent
    from agents.character_agent import character_agent
    from agents.storyboard_agent import storyboard_agent
    from agents.image_agent import image_agent
    from agents.voice_agent import voice_agent
    from agents.video_agent import video_agent

    runner.register_agent("script", script_agent)
    runner.register_agent("character", character_agent)
    runner.register_agent("storyboard", storyboard_agent)
    runner.register_agent("image", image_agent)
    runner.register_agent("voice", voice_agent)
    runner.register_agent("video", video_agent)

    logger.info("All 6 agents registered with Runtime")


async def _fallback_langgraph(
    task_id: str,
    story_id: str,
    prompt: str,
    genre: str,
    progress_callback=None,
) -> dict:
    """Fallback: execute via the original LangGraph workflow."""
    from workflows.story_workflow import build_story_workflow
    from workflows.state import StoryState

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

    final_state = await workflow.ainvoke(initial_state)
    return final_state