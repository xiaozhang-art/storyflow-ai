"""Image-to-Video Agent — convert each scene image into a short video clip.

Uses context["use_capability"]("image_to_video", ...) for generation.
Falls back to FFmpeg static-image video if capability fails.
"""

import logging
from pathlib import Path

from configs.settings import settings

logger = logging.getLogger(__name__)


async def image_to_video_agent(state: dict, context: dict) -> dict:
    """Image-to-Video agent.

    v3 signature: (state, context) -> dict partial update.
    Takes each generated image and creates a short video clip (3-10s).
    """
    story_id = state.get("story_id", "unknown")
    images = state.get("images", [])
    storyboard = state.get("storyboard", [])
    use_capability = context.get("use_capability")

    logger.info("image_to_video_agent started | story_id=%s, %d images", story_id, len(images))

    if not images:
        logger.error("No images | story_id=%s", story_id)
        return {"video_clips": [], "status": "error", "error": "No images."}

    # Build storyboard lookup
    sb_map = {s.get("scene_no", 0): s for s in storyboard}

    clips: list[dict] = []
    errors: list[str] = []

    story_dir = Path(settings.STORAGE_PATH) / "stories" / story_id
    clips_dir = story_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    total = len(images)
    for idx, img_info in enumerate(images):
        scene_no = img_info.get("scene_no", 0)
        image_path = img_info.get("image_path", "")

        if not image_path or not Path(image_path).exists():
            errors.append(f"Scene {scene_no}: image not found")
            continue

        # Get motion hint from storyboard
        sb = sb_map.get(scene_no, {})
        duration = str(sb.get("duration", 5))
        motion_hint = sb.get("motion_hint", "") or sb.get("camera", "")

        clip_path = str(clips_dir / f"scene_{scene_no:03d}.mp4")

        if use_capability:
            try:
                result = await use_capability("image_to_video", {
                    "image_path": image_path,
                    "prompt": motion_hint,
                    "duration": duration,
                    "output_path": clip_path,
                }, context)

                if result.get("success") and Path(clip_path).exists():
                    clips.append({
                        "scene_no": scene_no,
                        "video_path": clip_path,
                        "video_url": f"/storage/stories/{story_id}/clips/scene_{scene_no:03d}.mp4",
                        "duration": int(duration),
                    })
                    logger.info("Video clip generated for scene %d (%d/%d)", scene_no, idx + 1, total)
                    continue
                else:
                    logger.warning("I2V capability failed for scene %d: %s",
                                   scene_no, result.get("error"))
            except Exception as exc:
                logger.warning("I2V capability error for scene %d: %s", scene_no, exc)

        # Fallback: FFmpeg static image -> video (with Ken Burns zoom)
        try:
            success = await _ffmpeg_image_to_video(image_path, clip_path, duration)
            if success:
                clips.append({
                    "scene_no": scene_no,
                    "video_path": clip_path,
                    "video_url": f"/storage/stories/{story_id}/clips/scene_{scene_no:03d}.mp4",
                    "duration": int(duration),
                })
                logger.info("FFmpeg fallback clip for scene %d", scene_no)
            else:
                errors.append(f"Scene {scene_no}: FFmpeg fallback failed")
        except Exception as exc:
            errors.append(f"Scene {scene_no}: {exc}")

    error_msg = ""
    status = "i2v_done"
    if errors and not clips:
        status = "error"
        error_msg = f"All I2V failed: {'; '.join(errors)}"
    elif errors:
        status = "i2v_partial"
        error_msg = f"Partial failures: {'; '.join(errors)}"

    logger.info("image_to_video_agent completed | %d/%d clips | story_id=%s",
                len(clips), total, story_id)

    return {"video_clips": clips, "status": status, "error": error_msg}


async def _ffmpeg_image_to_video(image_path: str, output_path: str, duration: str = "5") -> bool:
    """FFmpeg: static image -> short video with Ken Burns zoom effect."""
    import asyncio

    frames = int(float(duration)) * 24
    vf = f"zoompan=z='min(zoom+0.0005,1.1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1024x1024:fps=24"

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", image_path,
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", str(duration),
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

    if proc.returncode != 0:
        logger.error("FFmpeg zoompan failed, trying simple loop: %s", stderr.decode()[:200])
        proc2 = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-t", str(duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", "24",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _ = await asyncio.wait_for(proc2.communicate(), timeout=60)

    return Path(output_path).exists()
