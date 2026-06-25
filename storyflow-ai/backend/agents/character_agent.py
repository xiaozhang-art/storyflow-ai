"""Character Agent - enriches character visual descriptions with Pydantic validation."""

import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import PydanticOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential

from workflows.state import StoryState
from app.llm import get_precise_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一位专业的角色视觉设计师，专门为AI图像生成系统（如Stable Diffusion、Midjourney）编写精确的角色外观描述。
你需要根据角色基本信息，为每个角色生成详细的视觉描述卡片，确保：
1. 外观描述足够详细，可以用于AI图像生成
2. 每个角色的视觉特征具有高度辨识度
3. 描述用词精确，避免模糊表达
4. 所有描述最终会转为英文 prompt，所以细节要具体到可被 SD 理解
"""

USER_PROMPT_TEMPLATE = """\
请为以下角色生成详细的视觉描述卡片：

{character_list}

请确保每个角色的外观描述包含以下四个维度：
- hair：发型、发色、长度、特殊造型（英文描述）
- body：身高、体型、体态特征（英文描述）
- cloth：服装风格、具体穿着、配饰（英文描述）
- face：五官特征、肤色、特殊标记（英文描述）

同时为每个角色补充：
- personality：性格特征的中文描述（字符串）
- catchphrase：一句经典口头禅（中文）

{format_instructions}
"""


class EnrichedCharacterOutput(BaseModel):
    """Pydantic model for LLM structured output of character enrichment."""
    characters: list[dict]


# Avoid circular import - define locally
from pydantic import BaseModel as _BaseModel


class EnrichedCharacterOutput(_BaseModel):
    characters: list[dict]


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
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT_TEMPLATE),
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

    enriched_characters = result.characters

    # Merge with original character data to preserve any fields not overwritten
    merged = []
    for original, enriched in zip(characters, enriched_characters):
        merged_char = {**original, **enriched}
        # Ensure appearance is a dict with all four keys
        appearance = merged_char.get("appearance", {})
        if isinstance(appearance, str):
            appearance = {"hair": "", "body": "", "cloth": "", "face": appearance}
        for key in ("hair", "body", "cloth", "face"):
            appearance.setdefault(key, "")
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