"""Voice Agent — generate speech via cloud TTS API (DashScope TTS / Mock).

All cloud APIs, no local deployment required.
"""

import asyncio
import base64
import logging
from pathlib import Path

import httpx

from configs.settings import settings

logger = logging.getLogger(__name__)

SPEAKER_MAP = {
    "男": "male", "male": "male", "男性": "male",
    "女": "female", "female": "female", "女性": "female",
}


async def voice_agent(state: dict, context: dict) -> dict:
    """Voice generation agent.

    Args:
        state: Pipeline state with storyboard, characters, story_id
        context: Runtime context

    Returns:
        dict with audios list and status
    """
    story_id = state.get("story_id", "unknown")
    storyboard = state.get("storyboard", [])
    characters = state.get("characters", [])

    logger.info("voice_agent started | story_id=%s", story_id)

    if not storyboard:
        logger.error("No storyboard scenes | story_id=%s", story_id)
        return {"audios": [], "status": "error", "error": "No storyboard scenes."}

    audios: list[dict] = []
    errors: list[str] = []

    save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "audio"
    save_dir.mkdir(parents=True, exist_ok=True)

    provider = settings.VOICE_API_PROVIDER

    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)
        dialogue = scene.get("dialogue", "")

        if not dialogue.strip():
            continue

        # Determine speaker gender from first character
        speaker = "female"
        scene_chars = scene.get("characters", [])
        if scene_chars:
            for char in characters:
                if char.get("name") == scene_chars[0]:
                    speaker = SPEAKER_MAP.get(char.get("gender", ""), "female")
                    break

        output_path = str(save_dir / f"scene_{scene_no}.wav")

        if provider == "mock" or not settings.VOICE_API_KEY:
            _create_silent_wav(output_path, float(scene.get("duration", 3)))
            audios.append(_make_audio_entry(story_id, scene_no, output_path, speaker, dialogue))
            continue

        try:
            if provider in ("dashscope_tts", "dashscope"):
                await _dashscope_tts(dialogue, speaker, output_path)
            else:
                logger.warning("Unknown voice provider '%s', using silent fallback", provider)
                _create_silent_wav(output_path, float(scene.get("duration", 3)))

            audios.append(_make_audio_entry(story_id, scene_no, output_path, speaker, dialogue))
            logger.info("Voice generated for scene %d (speaker=%s) via %s", scene_no, speaker, provider)

        except Exception as exc:
            logger.error("Voice generation failed for scene %d: %s", scene_no, exc)
            errors.append(f"Scene {scene_no}: {exc}")
            # Fallback to silent
            try:
                _create_silent_wav(output_path, float(scene.get("duration", 3)))
                audios.append(_make_audio_entry(story_id, scene_no, output_path, speaker, dialogue))
            except Exception:
                pass

    error_msg = ""
    status = "voice_done"
    if not audios:
        status = "error"
        error_msg = "All voice generations failed or no dialogues found."
    elif errors:
        status = "voice_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    logger.info("voice_agent completed | %d/%d audios | status=%s | story_id=%s",
                len(audios), len(storyboard), status, story_id)

    return {"audios": audios, "status": status, "error": error_msg}


def _make_audio_entry(story_id: str, scene_no: int, audio_path: str,
                       speaker: str, text: str) -> dict:
    return {
        "scene_no": scene_no,
        "audio_path": audio_path,
        "audio_url": f"/storage/stories/{story_id}/audio/scene_{scene_no}.wav",
        "speaker": speaker,
        "text": text,
    }


# ── DashScope TTS (Cloud) ──

async def _dashscope_tts(text: str, speaker: str, output_path: str):
    """Generate speech via DashScope TTS API (async task + poll)."""
    api_key = settings.VOICE_API_KEY
    base_url = settings.VOICE_API_BASE_URL
    model = settings.VOICE_MODEL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # DashScope TTS supports these model-specific params
    payload = {
        "model": model,
        "input": {"text": text},
        "parameters": {
            "voice": f"longxiaochun" if speaker == "female" else "longlaotie",
            "sample_rate": settings.VOICE_SAMPLE_RATE,
        },
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/services/aigc/text2audio/generation",
            json=payload, headers=headers,
        )
        resp.raise_for_status()
        result = resp.json()

    task_id = result.get("output", {}).get("task_id")
    if not task_id:
        # Synchronous mode — response contains audio URL directly
        audio_url = result.get("output", {}).get("audio_url", "")
        if audio_url:
            await _download_file(audio_url, output_path)
            return
        raise RuntimeError(f"DashScope TTS: no task_id or audio_url: {result}")

    # Poll for async task
    poll_url = f"{base_url}/tasks/{task_id}"
    timeout = 120
    poll_interval = 3

    for _ in range(timeout // poll_interval):
        await asyncio.sleep(poll_interval)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(poll_url, headers=headers)
            resp_data = resp.json()

        task_status = resp_data.get("output", {}).get("task_status", "")
        if task_status == "SUCCEEDED":
            audio_url = resp_data.get("output", {}).get("audio_url", "")
            if audio_url:
                await _download_file(audio_url, output_path)
                return
            raise RuntimeError(f"DashScope TTS: no audio_url in result: {resp_data}")

        elif task_status == "FAILED":
            error_msg = resp_data.get("output", {}).get("message", "unknown error")
            raise RuntimeError(f"DashScope TTS task failed: {error_msg}")

    raise RuntimeError(f"DashScope TTS: task {task_id} timed out")


# ── Helpers ──

async def _download_file(url: str, output_path: str):
    """Download a file from URL to local path."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(resp.content)


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