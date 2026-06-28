"""Image-to-Video Agent — convert images to video clips via cloud API (Kling / Mock).

All cloud APIs, no local GPU required. Takes images from image_agent and
produces video clips for video_agent to assemble.
"""

import asyncio
import base64
import logging
from pathlib import Path

import httpx

from configs.settings import settings

logger = logging.getLogger(__name__)


async def image_to_video_agent(state: dict, context: dict) -> dict:
    """Image-to-video generation agent.

    Args:
        state: Pipeline state with images, storyboard, story_id
        context: Runtime context

    Returns:
        dict with video_clips list and status
    """
    story_id = state.get("story_id", "unknown")
    images = state.get("images", [])
    storyboard = state.get("storyboard", [])

    logger.info("image_to_video_agent started | story_id=%s, %d images", story_id, len(images))

    if not images:
        logger.error("No images | story_id=%s", story_id)
        return {"video_clips": [], "status": "error", "error": "No images to convert."}

    video_clips: list[dict] = []
    errors: list[str] = []

    save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "video_clips"
    save_dir.mkdir(parents=True, exist_ok=True)

    # Build scene duration map from storyboard
    storyboard_map = {s.get("scene_no"): s for s in storyboard}
    image_map = {img["scene_no"]: img for img in images}

    provider = settings.I2V_API_PROVIDER

    for img in images:
        scene_no = img.get("scene_no", 0)
        image_path = img.get("image_path", "")
        output_path = str(save_dir / f"scene_{scene_no}.mp4")

        if not image_path or not Path(image_path).exists():
            errors.append(f"Scene {scene_no}: image file not found")
            continue

        if provider == "mock" or not settings.I2V_API_KEY:
            # Mock: create a static image video via FFmpeg
            scene_info = storyboard_map.get(scene_no, {})
            duration = float(scene_info.get("duration", settings.I2V_DURATION))
            await _mock_i2v(image_path, output_path, duration)
            video_clips.append(_make_clip_entry(story_id, scene_no, output_path, duration))
            continue

        try:
            if provider == "kling":
                duration = await _kling_generate(image_path, output_path, scene_no)
            elif provider == "runway":
                duration = await _runway_generate(image_path, output_path, scene_no)
            else:
                logger.warning("Unknown i2v provider '%s', using mock", provider)
                scene_info = storyboard_map.get(scene_no, {})
                duration = float(scene_info.get("duration", settings.I2V_DURATION))
                await _mock_i2v(image_path, output_path, duration)

            video_clips.append(_make_clip_entry(story_id, scene_no, output_path, duration))
            logger.info("I2V completed for scene %d via %s", scene_no, provider)

        except Exception as exc:
            logger.error("I2V failed for scene %d: %s", scene_no, exc)
            errors.append(f"Scene {scene_no}: {exc}")
            # Fallback to mock
            try:
                scene_info = storyboard_map.get(scene_no, {})
                duration = float(scene_info.get("duration", settings.I2V_DURATION))
                await _mock_i2v(image_path, output_path, duration)
                video_clips.append(_make_clip_entry(story_id, scene_no, output_path, duration))
            except Exception:
                pass

    error_msg = ""
    status = "i2v_done"
    if errors and not video_clips:
        status = "error"
        error_msg = f"All I2V generations failed: {'; '.join(errors)}"
    elif errors:
        status = "i2v_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    logger.info("image_to_video_agent completed | %d/%d clips | status=%s | story_id=%s",
                len(video_clips), len(images), status, story_id)

    return {"video_clips": video_clips, "status": status, "error": error_msg}


def _make_clip_entry(story_id: str, scene_no: int, video_path: str, duration: float) -> dict:
    return {
        "scene_no": scene_no,
        "video_path": video_path,
        "video_url": f"/storage/stories/{story_id}/video_clips/scene_{scene_no}.mp4",
        "duration": duration,
    }


# ── Kling (可灵) Image-to-Video ──

async def _kling_generate(image_path: str, output_path: str, scene_no: int) -> float:
    """Generate video from image via Kling API (async task + poll)."""
    api_key = settings.I2V_API_KEY
    base_url = settings.I2V_API_BASE_URL
    model = settings.I2V_MODEL
    duration = settings.I2V_DURATION

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Read image and encode as base64
    img_bytes = Path(image_path).read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    payload = {
        "model": model,
        "input": {
            "image": f"data:image/png;base64,{img_b64}",
        },
        "parameters": {
            "duration": str(duration),
            "aspect_ratio": "1:1",
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{base_url}/images/generations",
                                 json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    task_id = result.get("data", [{}])[0].get("task_id")
    if not task_id:
        task_id = result.get("task_id")
    if not task_id:
        raise RuntimeError(f"Kling: no task_id returned: {result}")

    # Poll for completion
    poll_url = f"{base_url}/images/generations/{task_id}"
    timeout = settings.I2V_POLL_TIMEOUT
    poll_interval = settings.I2V_POLL_INTERVAL

    for _ in range(timeout // poll_interval):
        await asyncio.sleep(poll_interval)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(poll_url, headers=headers)
            resp_data = resp.json()

        task_status = resp_data.get("data", [{}])[0].get("status", "")
        if not task_status:
            task_status = resp_data.get("status", "")

        if task_status in ("succeed", "SUCCEEDED", "completed"):
            video_url = ""
            data = resp_data.get("data", [{}])
            if data:
                video_url = data[0].get("url", "")
            if not video_url:
                video_url = resp_data.get("output", {}).get("video_url", "")
            if not video_url:
                raise RuntimeError(f"Kling: no video_url in result: {resp_data}")

            await _download_file(video_url, output_path)
            return float(duration)

        elif task_status in ("failed", "FAILED"):
            error_msg = resp_data.get("data", [{}])[0].get("error", {}).get("message", "unknown")
            raise RuntimeError(f"Kling task failed: {error_msg}")

    raise RuntimeError(f"Kling: task {task_id} timed out after {timeout}s")


# ── Runway ──

async def _runway_generate(image_path: str, output_path: str, scene_no: int) -> float:
    """Generate video from image via Runway API (async task + poll)."""
    api_key = settings.I2V_API_KEY
    base_url = settings.I2V_API_BASE_URL
    duration = settings.I2V_DURATION

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    img_bytes = Path(image_path).read_bytes()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")

    payload = {
        "model": "gen3a_turbo",
        "promptImage": f"data:image/png;base64,{img_b64}",
        "duration": int(duration),
        "ratio": "1:1",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{base_url}/v1/image_to_video",
                                 json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    task_id = result.get("id")
    if not task_id:
        raise RuntimeError(f"Runway: no task_id returned: {result}")

    poll_url = f"{base_url}/v1/image_to_video/{task_id}"
    timeout = settings.I2V_POLL_TIMEOUT
    poll_interval = settings.I2V_POLL_INTERVAL

    for _ in range(timeout // poll_interval):
        await asyncio.sleep(poll_interval)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(poll_url, headers=headers)
            resp_data = resp.json()

        status = resp_data.get("status", "")
        if status == "completed":
            video_url = resp_data.get("output", [{}])[0].get("url", "") if isinstance(resp_data.get("output"), list) else resp_data.get("output", {}).get("url", "")
            if video_url:
                await _download_file(video_url, output_path)
                return float(duration)
            raise RuntimeError(f"Runway: no video_url in result: {resp_data}")

        elif status == "failed":
            raise RuntimeError(f"Runway task failed: {resp_data.get('error', 'unknown')}")

    raise RuntimeError(f"Runway: task {task_id} timed out")


# ── Mock: FFmpeg static image → video ──

async def _mock_i2v(image_path: str, output_path: str, duration: float):
    """Create a video from a static image via FFmpeg (no GPU needed)."""
    import asyncio as _asyncio

    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-r", "1",
        str(output_path),
    ]

    proc = await _asyncio.create_subprocess_exec(
        *cmd, stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE)
    _, stderr = await _asyncio.wait_for(proc.communicate(), timeout=120)

    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg mock I2V failed: {stderr.decode()[:200]}")


# ── Helper ──

async def _download_file(url: str, output_path: str):
    """Download a file from URL to local path."""
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(resp.content)