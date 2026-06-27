"""Character Agent — enrich character visual descriptions via LLM."""

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel, Field

from prompts import CHARACTER_SYSTEM_PROMPT, CHARACTER_USER_PROMPT
from app.llm import get_precise_llm

logger = logging.getLogger(__name__)


class AppearanceCard(BaseModel):
    hair: str = Field(default="", description="发型、发色、长度（英文）")
    body: str = Field(default="", description="身高、体型、体态（英文）")
    cloth: str = Field(default="", description="服装风格、穿着、配饰（英文）")
    face: str = Field(default="", description="五官、肤色、标记（英文）")


class EnrichedCharacter(BaseModel):
    name: str
    gender: str = "unknown"
    age: int | None = None
    appearance: AppearanceCard
    personality: dict = Field(default_factory=dict)
    catchphrase: str = ""


class EnrichedCharacterOutput(BaseModel):
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

    result = await chain.ainvoke({
        "character_list": "\n".join(character_summaries),
        "format_instructions": parser.get_format_instructions(),
    })

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

    # Merge with original data, ensure all appearance keys exist
    merged = []
    for original, enriched in zip(characters, enriched_list):
        merged_char = {**original, **enriched}
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


async def character_agent(state: dict, context: dict) -> dict:
    """Character enrichment agent.

    v3 signature: (state, context) -> dict partial update.
    """
    story_id = state.get("story_id", "")
    logger.info("character_agent started | story_id=%s", story_id)

    try:
        characters = state.get("characters", [])
        if not characters:
            raise ValueError("No characters found — script agent may have failed.")

        enriched = await _enrich_characters(characters)

        logger.info(
            "character_agent completed | %d characters enriched | story_id=%s",
            len(enriched), story_id,
        )

        return {"characters": enriched}

    except Exception as exc:
        logger.exception("character_agent failed | story_id=%s", story_id)
        # Fallback: return original characters
        original = state.get("characters", [])
        if original:
            logger.warning("Falling back to original characters (%d)", len(original))
            return {"characters": original}
        return {"status": "error", "error": f"Character enrichment failed: {exc}"}