import json
import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import PydanticOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from schemas.agent import ScriptOutput
from workflows.state import StoryState
from app.llm import get_creative_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一位顶级短剧编剧，擅长创作引人入胜、节奏紧凑、情感张力十足的竖屏短剧剧本。
你的作品在抖音、快手等平台有极高的观众留存率和分享率。

编剧原则：
1. **黄金三秒**：每集开头必须在3秒内抓住观众注意力（冲突、悬念、反转）
2. **情绪过山车**：每集要有明确的情绪起伏——从平静到紧张、从绝望到希望
3. **悬念钩子**：每集结尾必须有强烈的悬念或反转，让观众忍不住看下一集
4. **人物鲜明**：每个角色都要有独特的说话方式、性格标签和行为习惯
5. **对话精炼**：每句台词都要推动剧情或揭示人物，拒绝废话
6. **场景具体**：每个场景都要有明确的时间、地点、氛围描写

输出格式要求：
- 剧集数量：根据故事复杂度，生成3-6集短剧
- 每集时长：适合1-3分钟的视频呈现（约200-500字对话/旁白）
- 人物数量：3-6个主要角色

请严格按照JSON Schema输出，确保数据完整、格式正确。
"""

USER_PROMPT = """\
请根据以下需求创作一部短剧剧本：

**用户需求**：{prompt}
**题材类型**：{genre}

请生成完整的短剧剧本，包括：
1. 剧情大纲（200-300字，包含主线和关键转折）
2. 角色设定（每个角色的详细描述）
3. 分集剧本（每集的完整对话和舞台指示）

{format_instructions}
"""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((Exception,)),
    before_sleep=lambda retry_state: logger.warning(
        "Script agent retry %d/3 after error: %s",
        retry_state.attempt_number,
        str(retry_state.outcome.exception()) if retry_state.outcome else "unknown",
    ),
)
async def _call_llm_for_script(prompt: str, genre: str) -> ScriptOutput:
    """Call the LLM to generate a complete short drama script."""
    parser = PydanticOutputParser(pydantic_object=ScriptOutput)

    llm = get_creative_llm()

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])

    chain = chat_prompt | llm | parser

    result = await chain.ainvoke({
        "prompt": prompt,
        "genre": genre,
        "format_instructions": parser.get_format_instructions(),
    })

    return result


async def script_agent(state: StoryState) -> dict:
    """
    Script generation agent.
    Takes the user prompt and genre, calls the LLM to produce a structured
    short-drama script (outline, characters, episodes), and returns a partial
    state update.
    """
    logger.info(
        "script_agent started | task_id=%s story_id=%s",
        state.get("task_id"),
        state.get("story_id"),
    )

    try:
        prompt = state.get("prompt", "")
        genre = state.get("genre", "都市情感")

        if not prompt.strip():
            raise ValueError("User prompt is empty – nothing to generate a script from.")

        script_output = await _call_llm_for_script(prompt, genre)

        # Serialise Pydantic models to plain dicts so they are JSON-safe downstream
        characters = [c.model_dump() for c in script_output.characters]
        episodes = [e.model_dump() for e in script_output.episodes]

        logger.info(
            "script_agent completed | %d characters, %d episodes | task_id=%s",
            len(characters),
            len(episodes),
            state.get("task_id"),
        )

        return {
            "outline": script_output.outline,
            "characters": characters,
            "episodes": episodes,
            "current_step": "script",
            "status": "script_done",
            "error": "",
        }

    except Exception as exc:
        logger.exception("script_agent failed | task_id=%s", state.get("task_id"))
        return {
            "current_step": "script",
            "status": "error",
            "error": f"Script generation failed: {exc}",
        }