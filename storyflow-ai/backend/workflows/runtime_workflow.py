"""Runtime-based workflow - Executes story generation through the Agent OS Runtime.

v2.0: Now with Memory, Hook quality gates, and Skill-driven execution.

Key capabilities:
1. Hook observability - every step is traced via AFTER_AGENT quality gates
2. Session management - conversation tracking for each generation
3. Memory injection - character profiles flow through the pipeline for consistency
4. Skill validation - output structure checked against skill definitions
5. Quality-gated retry - agents automatically retry when quality gate fails
6. Incremental persistence - results saved to DB after each step (like LangGraph)

Falls back to LangGraph if Runtime is not initialized.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Progress mapping (same as runner.py for consistency)
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


async def run_with_runtime(
    task_id: str,
    story_id: str,
    prompt: str,
    genre: str,
    progress_callback=None,
    persist_callback=None,
) -> dict:
    """Execute story generation using the Agent OS Runtime.

    v2.0: The Runtime pipeline now:
    1. Loads Skill definitions from YAML
    2. Initializes CharacterMemoryService
    3. Registers quality gate hooks
    4. Creates RuntimeWorkflowRunner with all components
    5. Executes with Memory injection + Hook validation + Skill constraints
    6. Persists incrementally to DB after each step

    Falls back to LangGraph if Runtime is not initialized.
    """
    try:
        from runtime.app import get_runtime_app
        runtime_app = get_runtime_app()

        if not runtime_app._initialized:
            logger.info("Runtime not initialized, falling back to LangGraph workflow")
            return await _fallback_langgraph(
                task_id, story_id, prompt, genre, progress_callback,
            )

        # ── Initialize CharacterMemoryService ──
        from runtime.memory.character_memory import CharacterMemoryService
        character_memory = CharacterMemoryService(
            memory_manager=runtime_app.memory_manager,
        )

        # ── Get workflow runner with all Runtime components ──
        runner = runtime_app.get_workflow_runner()
        # Override with the full-featured version that has character_memory
        from runtime.adapter import RuntimeWorkflowRunner
        runner = RuntimeWorkflowRunner(
            control_server=runtime_app.control_server,
            conversation_manager=runtime_app.conversation_manager,
            skill_registry=runtime_app.skill_registry,
            memory_manager=runtime_app.memory_manager,
            character_memory=character_memory,
            hook_dispatcher=runtime_app.hook_dispatcher,
        )

        # ── Register all agents ──
        _register_all_agents(runner)

        # ── Build persist callback for incremental DB saves ──
        async def _runtime_persist(step: str, state: dict):
            """Incrementally persist results after each agent step."""
            if not persist_callback:
                return
            await persist_callback(step, state)

        # ── Build progress callback ──
        async def _runtime_progress(agent_id: str, progress: dict):
            if not progress_callback:
                return
            pct = STEP_PROGRESS.get(agent_id, 0)
            await progress_callback(agent_id, {
                "task_id": task_id,
                "progress": pct,
                "current_step": agent_id,
                "message": f"{agent_id} 完成 (Runtime v2.0)",
            })

        # ── Execute through Runtime ──
        result = await runner.run_pipeline(
            task_id=task_id,
            story_id=story_id,
            prompt=prompt,
            genre=genre,
            progress_callback=_runtime_progress,
            persist_callback=_runtime_persist,
        )

        logger.info(
            "Runtime v2.0 pipeline completed | task=%s | memory_stats=%s",
            task_id,
            character_memory.get_stats() if character_memory else "N/A",
        )
        return result

    except Exception as e:
        logger.error("Runtime execution failed, falling back to LangGraph: %s", e)
        return await _fallback_langgraph(
            task_id, story_id, prompt, genre, progress_callback,
        )


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

    logger.info("All 6 agents registered with Runtime v2.0")


async def _fallback_langgraph(
    task_id: str,
    story_id: str,
    prompt: str,
    genre: str,
    progress_callback=None,
) -> dict:
    """Fallback: execute via the original LangGraph workflow."""
    from workflows.story_workflow import build_story_workflow

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