import logging
from pathlib import Path

import httpx

from configs.settings import settings
from workflows.state import StoryState

logger = logging.getLogger(__name__)

# Map character gender to CosyVoice speaker type
SPEAKER_MAP = {
    "男": "male",
    "male": "male",
    "男性": "male",
    "女": "female",
    "female": "female",
    "女性": "female",
}


def _resolve_speaker(character_name: str, characters: list[dict]) -> str:
    """Look up the character's gender and return the appropriate speaker type."""
    for char in characters:
        if char.get("name") == character_name:
            gender = char.get("gender", "").lower()
            return SPEAKER_MAP.get(gender, "female")
    return "female"


async def _generate_voice_for_scene(
    client: httpx.AsyncClient,
    scene_no: int,
    dialogue: str,
    speaker: str,
    story_id: str,
    task_id: str,
) -> dict | None:
    """Call CosyVoice API to generate audio for a single scene's dialogue."""
    if not dialogue.strip():
        logger.debug(
            "Scene %d has no dialogue, skipping voice generation | task_id=%s",
            scene_no,
            task_id,
        )
        return None

    payload = {
        "speaker": speaker,
        "emotion": "neutral",
        "text": dialogue,
    }

    resp = await client.post(
        f"{settings.COSYVOICE_URL}/voice/generate",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()

    result = resp.json()

    # CosyVoice may return the audio as base64-encoded data, a URL, or bytes
    audio_data = result.get("audio")
    audio_url = result.get("audio_url")

    save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "audio"
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"scene_{scene_no}.wav"

    if audio_data:
        # Base64-encoded audio bytes
        import base64
        audio_bytes = base64.b64decode(audio_data)
        save_path.write_bytes(audio_bytes)
    elif audio_url:
        # Download from the returned URL
        audio_resp = await client.get(audio_url, timeout=60.0)
        audio_resp.raise_for_status()
        save_path.write_bytes(audio_resp.content)
    else:
        # Maybe the response itself is binary audio – handle gracefully
        logger.warning(
            "Unexpected CosyVoice response for scene %d: %s | task_id=%s",
            scene_no,
            list(result.keys()),
            task_id,
        )
        return None

    voice_url = f"/storage/stories/{story_id}/audio/scene_{scene_no}.wav"

    return {
        "scene_no": scene_no,
        "audio_path": str(save_path),
        "audio_url": voice_url,
        "speaker": speaker,
        "text": dialogue,
    }


async def voice_agent(state: StoryState) -> dict:
    """
    Voice generation agent.
    For each storyboard scene that contains dialogue, calls the CosyVoice API
    to generate speech audio.  Character gender is used to select the speaker
    voice type (male / female).  Scenes without dialogue are skipped.
    Returns partial results on failure.
    """
    logger.info(
        "voice_agent started | task_id=%s story_id=%s",
        state.get("task_id"),
        state.get("story_id"),
    )

    story_id = state.get("story_id", "unknown")
    task_id = state.get("task_id", "")
    storyboard = state.get("storyboard", [])
    characters = state.get("characters", [])

    if not storyboard:
        logger.error("No storyboard scenes found | task_id=%s", task_id)
        return {
            "current_step": "voice",
            "status": "error",
            "error": "No storyboard scenes to generate voice for.",
            "audios": [],
        }

    audios: list[dict] = []
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for scene in storyboard:
            scene_no = scene.get("scene_no", 0)
            dialogue = scene.get("dialogue", "")
            scene_characters = scene.get("characters", [])

            # Determine the primary speaker: use the first character in the scene
            speaker = "female"  # default
            if scene_characters:
                speaker = _resolve_speaker(scene_characters[0], characters)

            try:
                result = await _generate_voice_for_scene(
                    client, scene_no, dialogue, speaker, story_id, task_id
                )
                if result:
                    audios.append(result)
                    logger.info(
                        "Voice generated for scene %d (speaker=%s) | task_id=%s",
                        scene_no,
                        speaker,
                        task_id,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to generate voice for scene %d: %s | task_id=%s",
                    scene_no,
                    exc,
                    task_id,
                )
                errors.append(f"Scene {scene_no}: {exc}")

    if not audios:
        error_msg = "All voice generations failed or no dialogues found."
        logger.error("%s | task_id=%s", error_msg, task_id)
        return {
            "current_step": "voice",
            "status": "error",
            "error": error_msg,
            "audios": [],
        }

    status_msg = "voice_done"
    error_msg = ""
    if errors:
        status_msg = "voice_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    logger.info(
        "voice_agent completed | %d/%d audios generated | task_id=%s",
        len(audios),
        len(storyboard),
        task_id,
    )

    return {
        "audios": audios,
        "current_step": "voice",
        "status": status_msg,
        "error": error_msg,
    }