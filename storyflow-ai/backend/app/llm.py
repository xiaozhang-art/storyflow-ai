"""LLM factory - centralized LLM instance creation."""

import logging
from langchain_openai import ChatOpenAI
from configs.settings import settings

logger = logging.getLogger(__name__)

# Cache LLM instances by (model, temperature)
_llm_cache: dict[tuple, ChatOpenAI] = {}


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """Get a cached ChatOpenAI instance.

    Reusing instances avoids creating new HTTP connections for every agent call.
    """
    model = model or settings.LLM_MODEL
    temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
    max_tokens = max_tokens or settings.LLM_MAX_TOKENS

    cache_key = (model, temperature)
    if cache_key not in _llm_cache:
        _llm_cache[cache_key] = ChatOpenAI(
            model=model,
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.debug("Created new LLM instance: model=%s, temp=%.2f", model, temperature)

    return _llm_cache[cache_key]


def get_creative_llm() -> ChatOpenAI:
    """LLM for creative tasks (script, storyboard) - higher temperature."""
    return get_llm(temperature=0.8, max_tokens=8192)


def get_precise_llm() -> ChatOpenAI:
    """LLM for precise tasks (character design, analysis) - lower temperature."""
    return get_llm(temperature=0.4, max_tokens=4096)