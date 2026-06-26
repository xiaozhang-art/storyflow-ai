"""Character Agent - enriches character visual descriptions with Pydantic validation."""

import json
import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential

from pydantic import BaseModel, Field

from prompts import CHARACTER_SYSTEM_PROMPT, CHARACTER_USER_PROMPT
from workflows.state import StoryState
from app.llm import get_precise_llm

logger = logging.getLogger(__name__)


class AppearanceCard(BaseModel):
    """Structured visual description for SD image generation."""
    hair: str = Field(default="", description="发型、发色、长度（英文）")
    body: str = Field(default="", description="身高、体型、体态（英文）")
    cloth: str = Field(default="", description="服装风格、穿着、配饰（英文）")
    face: str = Field(default="", description="五官、肤色、标记（英文）")


class EnrichedCharacter(BaseModel):
    """A single enriched character."""
    name: str
    gender: str = "unknown"
    age: int | None = None
    appearance: AppearanceCard
    personality: dict[str, Any] = Field(default_factory=dict)
    catchphrase: str = ""


class EnrichedCharacterOutput(BaseModel):
    """Pydantic model for LLM structured output of character enrichment."""
    characters: list[EnrichedCharacter]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=lambda retry_state: logger.warning(
        "Character agent retry %d/3", retry_state.attempt_number,
    ),
)
async def _enrich_characters(characters: list[dict]) -> list[dict]:
    """Call the LLM to enrich character visual descriptions."""
    llm = get_precise_llm()

    parser = PydanticOutputParser(pydantic_object=EnrichedCharacterOutput)

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", CHARACTER_SYSTEM_PROMPT),
        ("human", CHARACTER_USER_PROMPT),
    ])

    chain = chat_prompt | llm | parser

    character_summaries = []
    for i, char in enumerate(characters, 1):
        summary = (
            f"{i}. {char.get('name', '未命名')}\n"
            f"   性别：{char.get('gender', '未知')}\n"
            f"   年龄：{char.get('age', '未知')}\n"
            f"   性格：{char.get('personality', '未知')}\n"
            f"   当前外观描述：{json.dumps(char.get('appearance', {}), ensure_ascii=False)}\n"
        )
        character_summaries.append(summary)

    character_list_text = "\n".join(character_summaries)

    result = await chain.ainvoke({
        "character_list": character_list_text,
        "format_instructions": parser.get_format_instructions(),
    })

    # Convert Pydantic models to plain dicts
    enriched_list = []
    for ec in result.characters:
        enriched_list.append({
            "name": ec.name,
            "gender": ec.gender,
            "age": ec.age,
            "appearance": ec.appearance.model_dump(),
            "personality": ec.personality,
            "catchphrase": ec.catchphrase,
        })

    # Merge with original character data to preserve any fields not overwritten
    merged = []
    for original, enriched in zip(characters, enriched_list):
        merged_char = {**original, **enriched}
        # Ensure appearance has all four keys
        appearance = merged_char.get("appearance", {})
        if isinstance(appearance, str):
            appearance = {"hair": "", "body": "", "cloth": "", "face": appearance}
        elif isinstance(appearance, dict):
            for key in ("hair", "body", "cloth", "face"):
                appearance.setdefault(key, "")
        else:
            appearance = {"hair": "", "body": "", "cloth": "", "face": ""}
        merged_char["appearance"] = appearance
        merged.append(merged_char)

    return merged


async def character_agent(state: StoryState) -> dict:
    """
    Character enrichment agent.
    Takes the character list produced by the script agent, asks the LLM to
    generate detailed visual appearance cards for each character, and returns
    an updated characters list.
    """
    logger.info(
        "character_agent started | task_id=%s story_id=%s",
        state.get("task_id"),
        state.get("story_id"),
    )

    try:
        characters = state.get("characters", [])
        if not characters:
            raise ValueError("No characters found in state – script agent may have failed.")

        enriched = await _enrich_characters(characters)

        logger.info(
            "character_agent completed | %d characters enriched | task_id=%s",
            len(enriched),
            state.get("task_id"),
        )

        return {
            "characters": enriched,
            "current_step": "character",
            "status": "character_done",
            "error": "",
        }

    except Exception as exc:
        logger.exception("character_agent failed | task_id=%s", state.get("task_id"))
        # Fallback: return original characters if enrichment fails
        original = state.get("characters", [])
        if original:
            logger.warning("Falling back to original characters (%d) after failure", len(original))
            return {
                "characters": original,
                "current_step": "character",
                "status": "character_done",
                "error": f"Character enrichment failed, using originals: {exc}",
            }
        return {
            "current_step": "character",
            "status": "error",
            "error": f"Character enrichment failed: {exc}",
        }