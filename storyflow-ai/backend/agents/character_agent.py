import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from configs.settings import settings
from workflows.state import StoryState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一位专业的角色视觉设计师，专门为AI图像生成系统（如Stable Diffusion、Midjourney）编写精确的角色外观描述。
你需要根据角色基本信息，为每个角色生成详细的视觉描述卡片，确保：
1. 外观描述足够详细，可以用于AI图像生成
2. 每个角色的视觉特征具有高度辨识度
3. 描述用词精确，避免模糊表达

输出必须是一个合法的JSON对象，格式如下：
{
  "characters": [
    {
      "name": "角色名",
      "gender": "男/女",
      "age": 25,
      "appearance": {
        "hair": "黑色短发，微卷，刘海略微遮住右眼",
        "body": "身高180cm，体型偏瘦，肩膀略窄",
        "cloth": "白色衬衫，袖子挽到手肘，黑色修身西裤，棕色皮带",
        "face": "剑眉星目，高鼻梁，薄唇，下颌线分明，左眼下方有一颗小痣"
      },
      "personality": "外冷内热，做事果断，不善言辞但行动力强",
      "catchphrase": "……没什么，我只是在想该怎么做。"
    }
  ]
}
"""

USER_PROMPT_TEMPLATE = """\
请为以下角色生成详细的视觉描述卡片：

{character_list}

请确保每个角色的外观描述包含以下四个维度：
- hair：发型、发色、长度、特殊造型
- body：身高、体型、体态特征
- cloth：服装风格、具体穿着、配饰
- face：五官特征、肤色、特殊标记（痣、疤痕等）

同时为每个角色补充一句经典的口头禅（catchphrase），体现角色个性。

请直接输出JSON，不要包含其他文字。
"""


async def _enrich_characters(characters: list[dict]) -> list[dict]:
    """Call the LLM to enrich character visual descriptions."""
    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        temperature=0.6,
        max_tokens=settings.LLM_MAX_TOKENS,
    )

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT_TEMPLATE),
    ])

    chain = chat_prompt | llm

    # Build a readable character summary for the prompt
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

    response = await chain.ainvoke({"character_list": character_list_text})

    # Extract JSON from the response – LLMs sometimes wrap it in markdown fences
    raw_text = response.content.strip()
    if raw_text.startswith("```"):
        # Remove leading ```json and trailing ```
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines)

    parsed = json.loads(raw_text)
    enriched_characters = parsed.get("characters", [])

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
        return {
            "current_step": "character",
            "status": "error",
            "error": f"Character enrichment failed: {exc}",
        }