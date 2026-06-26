"""JSON parsing utilities for handling LLM output."""

import json
import re
import logging

logger = logging.getLogger(__name__)


def parse_json_response(text: str) -> dict:
    """Extract and parse JSON from LLM response text.

    Handles:
    - Plain JSON
    - JSON wrapped in ```json ... ``` markdown blocks
    - JSON with leading/trailing text
    """
    # Try to extract from markdown code block
    pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
    matches = re.findall(pattern, text)
    if matches:
        text = matches[-1].strip()

    # Try to find JSON object
    # Find the first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    # Parse
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e}\nText: {text[:500]}")
        # Attempt common fixes
        try:
            # Remove trailing commas before } or ]
            fixed = re.sub(r",\s*([}\]])", r"\1", text)
            return json.loads(fixed)
        except json.JSONDecodeError:
            raise ValueError(f"Failed to parse JSON from LLM response: {e}")


def validate_script_output(data: dict) -> bool:
    """Validate that data has the required ScriptOutput structure."""
    required_keys = ["outline", "characters", "episodes"]
    for key in required_keys:
        if key not in data:
            logger.warning(f"ScriptOutput missing key: {key}")
            return False
    if not isinstance(data["characters"], list):
        return False
    if not isinstance(data["episodes"], list):
        return False
    return True


def safe_json_dumps(obj: dict, indent: int = 2) -> str:
    """Serialize dict to JSON string with Chinese support."""
    return json.dumps(obj, ensure_ascii=False, indent=indent)