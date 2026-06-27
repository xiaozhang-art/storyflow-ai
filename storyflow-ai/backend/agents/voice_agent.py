"""Voice Agent — generate speech via Capability Registry (CosyVoice or Mock)."""

import logging
from pathlib import Path

from configs.settings import settings

logger = logging.getLogger(__name__)

SPEAKER_MAP = {
    "男": "male", "male": "male", "男性": "male",
    "女": "female", "female": "female", "女性": "female",
}


async def voice_agent(state: dict, context: dict) -> dict:
    """Voice generation agent.

    v3 signature: (state, context) -> dict partial update.
    Uses context["use_capability"]("generate_voice", ...) for TTS.
    Falls back to silent WAV if capability unavailable.
    """
    story_id = state.get("story_id", "unknown")
    storyboard = state.get("storyboard", [])
    characters = state.get("characters", [])
    use_capability = context.get("use_capability")

    logger.info("voice_agent started | story_id=%s", story_id)

    if not storyboard:
        logger.error("No storyboard scenes | story_id=%s", story_id)
        return {"audios": [], "status": "error", "error": "No storyboard scenes."}

    audios: list[dict] = []
    errors: list[str] = []

    save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "audio"
    save_dir.mkdir(parents=True, exist_ok=True)

    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)
        dialogue = scene.get("dialogue", "")

        if not dialogue.strip():
            continue

        # Determine speaker from first character in scene
        speaker = "female"
        scene_chars = scene.get("characters", [])
        if scene_chars:
            for char in characters:
                if char.get("name") == scene_chars[0]:
                    speaker = SPEAKER_MAP.get(char.get("gender", ""), "female")
                    break

        output_path = str(save_dir / f"scene_{scene_no}.wav")

        if use_capability and dialogue.strip():
            try:
                result = await use_capability("generate_voice", {
                    "text": dialogue,
                    "speaker": speaker,
                    "output_path": output_path,
                }, context)

                if result.get("success"):
                    audios.append({
                        "scene_no": scene_no,
                        "audio_path": result.get("file_path", output_path),
                        "audio_url": f"/storage/stories/{story_id}/audio/scene_{scene_no}.wav",
                        "speaker": speaker,
                        "text": dialogue,
                    })
                    logger.info("Voice generated for scene %d (speaker=%s)", scene_no, speaker)
                    continue
                else:
                    logger.warning("Voice capability failed for scene %d: %s",
                                   scene_no, result.get("error"))
            except Exception as exc:
                logger.warning("Voice capability error for scene %d: %s", scene_no, exc)

        # Fallback: create a silent WAV
        try:
            _create_silent_wav(output_path, 3.0)
            audios.append({
                "scene_no": scene_no,
                "audio_path": output_path,
                "audio_url": f"/storage/stories/{story_id}/audio/scene_{scene_no}.wav",
                "speaker": speaker,
                "text": dialogue,
            })
        except Exception as exc:
            errors.append(f"Scene {scene_no}: {exc}")

    error_msg = ""
    status = "voice_done"
    if not audios:
        status = "error"
        error_msg = "All voice generations failed or no dialogues found."
    elif errors:
        status = "voice_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    logger.info("voice_agent completed | %d/%d audios | story_id=%s",
                len(audios), len(storyboard), story_id)

    return {"audios": audios, "status": status, "error": error_msg}


def _create_silent_wav(path: str, duration: float = 3.0):
    """Create a minimal silent WAV file."""
    import struct, wave

    sample_rate = 22050
    n_frames = int(sample_rate * duration)
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)