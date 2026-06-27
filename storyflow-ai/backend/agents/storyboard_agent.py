"""Storyboard Agent — convert script to scene-by-scene storyboard via LLM."""

import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, Field

from prompts import STORYBOARD_SYSTEM_PROMPT, STORYBOARD_USER_PROMPT
from utils.json_helper import parse_json_response
from app.llm import get_precise_llm
from configs.settings import settings

logger = logging.getLogger(__name__)


class StoryboardScene(BaseModel):
    scene: int = Field(description="场景序号（从1开始）")
    camera: str = Field(default="中景", description="镜头类型")
    duration: int = Field(default=5, ge=3, le=15, description="场景时长（秒）")
    prompt: str = Field(description="英文图像生成 prompt")
    characters: list[str] = Field(default_factory=list, description="出场角色名")
    dialogue: str = Field(default="", description="该场景台词")


class StoryboardOutput(BaseModel):
    scenes: list[StoryboardScene]


def _build_character_descriptions(characters: list[dict]) -> str:
    """Build formatted character appearance descriptions."""
    parts = []
    for char in characters:
        name = char.get("name", "未命名")
        appearance = char.get("appearance", {})
        if isinstance(appearance, dict):
            hair = appearance.get("hair", "")
            body = appearance.get("body", "")
            cloth = appearance.get("cloth", "")
            face = appearance.get("face", "")
            desc = f"{name}: {hair}, {face}, {body}, wearing {cloth}"
        else:
            desc = f"{name}: {appearance}"
        parts.append(desc)
    return "\n".join(parts)


def _normalize_scene(scene: dict, index: int) -> dict:
    return {
        "scene_no": scene.get("scene", index + 1),
        "camera": scene.get("camera", "中景"),
        "duration": max(3, min(15, int(scene.get("duration", 5)))),
        "prompt": scene.get("prompt", ""),
        "characters": scene.get("characters", []),
        "dialogue": scene.get("dialogue", ""),
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=lambda retry_state: logger.warning(
        "Storyboard retry %d/3", retry_state.attempt_number,
    ),
)
async def _generate_storyboard_for_episode(
    episode: dict, character_descriptions: str, llm,
) -> list[dict]:
    """Generate storyboard scenes for a single episode."""
    min_scenes, max_scenes = settings.SCENES_PER_EPISODE

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", STORYBOARD_SYSTEM_PROMPT),
        ("human", STORYBOARD_USER_PROMPT),
    ])

    # Strategy 1: PydanticOutputParser
    try:
        parser = PydanticOutputParser(pydantic_object=StoryboardOutput)
        chain = chat_prompt | llm | parser

        result = await chain.ainvoke({
            "episode_no": episode.get("episode_no", 1),
            "title": episode.get("title", ""),
            "summary": episode.get("summary", ""),
            "script": episode.get("script", ""),
            "character_descriptions": character_descriptions,
            "min_scenes": min_scenes,
            "max_scenes": max_scenes,
            "format_instructions": parser.get_format_instructions(),
        })

        scenes = [_normalize_scene(s.model_dump(), i) for i, s in enumerate(result.scenes)]
        if scenes:
            return scenes
    except Exception as e:
        logger.warning("PydanticOutputParser failed, falling back to raw JSON: %s", e)

    # Strategy 2: Raw LLM output + json_helper
    chain = chat_prompt | llm
    response = await chain.ainvoke({
        "episode_no": episode.get("episode_no", 1),
        "title": episode.get("title", ""),
        "summary": episode.get("summary", ""),
        "script": episode.get("script", ""),
        "character_descriptions": character_descriptions,
        "min_scenes": min_scenes,
        "max_scenes": max_scenes,
        "format_instructions": "",
    })

    parsed = parse_json_response(response.content.strip())
    if isinstance(parsed, dict) and "scenes" in parsed:
        parsed = parsed["scenes"]
    if not isinstance(parsed, list):
        parsed = [parsed] if isinstance(parsed, dict) else []

    return [_normalize_scene(s, i) for i, s in enumerate(parsed)]


async def storyboard_agent(state: dict, context: dict) -> dict:
    """Storyboard generation agent.

    v3 signature: (state, context) -> dict partial update.
    Uses StoryWorld from context to inject character consistency.
    """
    story_id = state.get("story_id", "")
    logger.info("storyboard_agent started | story_id=%s", story_id)

    try:
        episodes = state.get("episodes", [])
        characters = state.get("characters", [])

        if not episodes:
            raise ValueError("No episodes found in state.")
        if not characters:
            raise ValueError("No characters found in state.")

        character_descriptions = _build_character_descriptions(characters)

        # If StoryWorld has richer character data, use it
        story_world = context.get("story_world")
        if story_world and story_world.characters:
            world_descriptions = story_world.build_image_prompt_context(
                [c["name"] for c in characters]
            )
            if world_descriptions:
                character_descriptions = world_descriptions

        llm = get_precise_llm()

        all_scenes: list[dict] = []
        for episode in episodes:
            logger.info("Generating storyboard for episode %d | story_id=%s",
                        episode.get("episode_no", 0), story_id)
            scenes = await _generate_storyboard_for_episode(episode, character_descriptions, llm)
            all_scenes.extend(scenes)

        # Assign global scene numbers
        for idx, scene in enumerate(all_scenes, 1):
            scene["scene_no"] = idx
            scene["episode_no"] = episode.get("episode_no", 1) if episodes else 1

        logger.info("storyboard_agent completed | %d scenes | story_id=%s",
                    len(all_scenes), story_id)

        return {"storyboard": all_scenes}

    except Exception as exc:
        logger.exception("storyboard_agent failed | story_id=%s", story_id)
        return {"status": "error", "error": f"Storyboard generation failed: {exc}"}