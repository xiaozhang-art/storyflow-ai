"""Script Agent — generate structured drama script via LLM."""

import logging

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from schemas.agent import ScriptOutput
from app.llm import get_creative_llm
from prompts import SCRIPT_SYSTEM_PROMPT, SCRIPT_USER_PROMPT

logger = logging.getLogger(__name__)


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
        ("system", SCRIPT_SYSTEM_PROMPT),
        ("human", SCRIPT_USER_PROMPT),
    ])

    chain = chat_prompt | llm | parser

    result = await chain.ainvoke({
        "prompt": prompt,
        "genre": genre,
        "format_instructions": parser.get_format_instructions(),
    })

    return result


async def script_agent(state: dict, context: dict) -> dict:
    """Script generation agent.

    v3 signature: (state, context) -> dict partial update.
    Context provides story_world, workspace, use_capability, project_id.
    """
    story_id = state.get("story_id", "")
    logger.info("script_agent started | story_id=%s", story_id)

    try:
        prompt = state.get("prompt", "")
        genre = state.get("genre", "都市情感")

        if not prompt.strip():
            raise ValueError("User prompt is empty – nothing to generate a script from.")

        script_output = await _call_llm_for_script(prompt, genre)

        characters = [c.model_dump() for c in script_output.characters]
        episodes = [e.model_dump() for e in script_output.episodes]

        logger.info(
            "script_agent completed | %d characters, %d episodes | story_id=%s",
            len(characters), len(episodes), story_id,
        )

        return {
            "outline": script_output.outline,
            "characters": characters,
            "episodes": episodes,
        }

    except Exception as exc:
        logger.exception("script_agent failed | story_id=%s", story_id)
        return {"status": "error", "error": f"Script generation failed: {exc}"}