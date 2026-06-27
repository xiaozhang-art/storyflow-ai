"""JSON parsing utilities for LLM responses."""

import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_json_response(text: str) -> list | dict | None:
    """Parse a JSON response from LLM output.

    Handles common issues:
    - Markdown code blocks (```json ... ```)
    - Leading/trailing whitespace
    - Trailing commas
    """
    if not text:
        return None

    # Strip markdown code blocks
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try fixing trailing commas
    try:
        fixed = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON array from surrounding text
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try extracting JSON object
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse JSON from LLM response (first 200 chars): %s", text[:200])
    return None