import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from configs.settings import settings
from workflows.state import StoryState

logger = logging.getLogger(__name__)


def _build_ass_subtitle(
    scene_no: int,
    dialogue: str,
    duration_seconds: float,
    scene_characters: list[str],
) -> str:
    """Build an ASS subtitle entry for a single scene."""
    # Map scene characters to readable speaker labels
    speaker = scene_characters[0] if scene_characters else "旁白"

    # Escape ASS special characters
    safe_dialogue = dialogue.replace("\\", "\\\\").replace("\n", "\\N")

    start = "0:00:00.00"
    end_h = int(duration_seconds // 3600)
    end_m = int((duration_seconds % 3600) // 60)
    end_s = int(duration_seconds % 60)
    end_ms = int((duration_seconds % 1) * 100)
    end = f"{end_h}:{end_m:02d}:{end_s:02d}.{end_ms:02d}"

    # Style: centered, white text with black outline, at bottom
    return (
        f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
        f"{{\\b1}}{speaker}：{safe_dialogue}"
    )


def _write_ass_file(
    scenes: list[dict],
    audios_map: dict[int, dict],
    save_path: Path,
) -> None:
    """Write a complete ASS subtitle file from all scenes."""
    ass_header = """\
[Script Info]
Title: StoryFlow AI Subtitles
ScriptType: v4.00+
PlayResX: 1024
PlayResY: 1024
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events = []
    for scene in scenes:
        scene_no = scene.get("scene_no", 0)
        dialogue = scene.get("dialogue", "")
        if not dialogue.strip():
            continue

        # Determine duration from audio if available, otherwise from storyboard
        duration = 5.0
        if scene_no in audios_map:
            audio_path = audios_map[scene_no].get("audio_path", "")
            if audio_path and Path(audio_path).exists():
                duration = _get_audio_duration(audio_path)
        else:
            duration = float(scene.get("duration", 5))

        scene_characters = scene.get("characters", [])
        line = _build_ass_subtitle(scene_no, dialogue, duration, scene_characters)
        events.append(line)

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(ass_header + "\n".join(events), encoding="utf-8")


def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return 5.0


async def _create_scene_video(
    scene_no: int,
    image_path: str,
    audio_path: str | None,
    output_path: Path,
) -> bool:
    """Create a video for a single scene using ffmpeg."""
    if not Path(image_path).exists():
        logger.warning("Image not found, skipping scene %d: %s", scene_no, image_path)
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
    ]

    if audio_path and Path(audio_path).exists():
        cmd.extend(["-i", audio_path, "-shortest"])
    else:
        # If no audio, use a fixed duration from the storyboard (default 5s)
        cmd.extend(["-t", "5"])

    cmd.extend([
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-r", "1",
        str(output_path),
    ])

    logger.debug("Running ffmpeg for scene %d: %s", scene_no, " ".join(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            logger.error(
                "ffmpeg failed for scene %d: %s", scene_no, stderr.decode()
            )
            return False

        return True

    except asyncio.TimeoutError:
        logger.error("ffmpeg timed out for scene %d", scene_no)
        return False


async def video_agent(state: StoryState) -> dict:
    """
    Video assembly agent.
    For each scene, creates a video clip from the generated image and audio
    using ffmpeg.  Then generates ASS subtitles and finally concatenates all
    scene clips into a single story video.
    """
    logger.info(
        "video_agent started | task_id=%s story_id=%s",
        state.get("task_id"),
        state.get("story_id"),
    )

    story_id = state.get("story_id", "unknown")
    task_id = state.get("task_id", "")
    storyboard = state.get("storyboard", [])
    images = state.get("images", [])
    audios = state.get("audios", [])

    if not images:
        logger.error("No images found | task_id=%s", task_id)
        return {
            "current_step": "video",
            "status": "error",
            "error": "No images to assemble video from.",
            "video_path": "",
        }

    story_dir = Path(settings.STORAGE_PATH) / "stories" / story_id
    scenes_dir = story_dir / "scenes"
    video_dir = story_dir / "video"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    # Build lookup maps
    image_map: dict[int, dict] = {img["scene_no"]: img for img in images}
    audio_map: dict[int, dict] = {aud["scene_no"]: aud for aud in audios}

    # --- Step 1: Create per-scene video clips ---
    scene_videos: list[Path] = []
    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)
        img_info = image_map.get(scene_no)
        if not img_info:
            logger.warning(
                "No image for scene %d, skipping | task_id=%s", scene_no, task_id
            )
            continue

        image_path = img_info.get("image_path", "")
        aud_info = audio_map.get(scene_no)
        audio_path = aud_info.get("audio_path") if aud_info else None

        scene_video_path = scenes_dir / f"scene_{scene_no}.mp4"
        success = await _create_scene_video(
            scene_no, image_path, audio_path, scene_video_path
        )

        if success and scene_video_path.exists():
            scene_videos.append(scene_video_path)
            logger.info("Scene video created: %s", scene_video_path)
        else:
            logger.warning("Failed to create video for scene %d", scene_no)

    if not scene_videos:
        error_msg = "No scene videos were created successfully."
        logger.error("%s | task_id=%s", error_msg, task_id)
        return {
            "current_step": "video",
            "status": "error",
            "error": error_msg,
            "video_path": "",
        }

    # --- Step 2: Generate ASS subtitle file ---
    ass_path = video_dir / "subtitles.ass"
    _write_ass_file(storyboard, audio_map, ass_path)
    logger.info("Subtitles written to %s", ass_path)

    # --- Step 3: Concatenate all scene videos ---
    final_path = video_dir / "story.mp4"
    filelist_path = scenes_dir / "filelist.txt"

    # Write concat file list
    with open(filelist_path, "w", encoding="utf-8") as f:
        for sv in scene_videos:
            f.write(f"file '{sv}'\n")

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(filelist_path),
        "-c", "copy",
        str(final_path),
    ]

    logger.info("Concatenating %d scene videos into final video", len(scene_videos))
    logger.debug("Concat command: %s", " ".join(concat_cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *concat_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            logger.error(
                "Concat ffmpeg failed: %s | task_id=%s",
                stderr.decode(),
                task_id,
            )
            # Return partial success – individual scene videos still exist
            video_path = str(scene_videos[0]) if scene_videos else ""
            return {
                "video_path": video_path,
                "current_step": "video",
                "status": "video_partial",
                "error": f"Concatenation failed: {stderr.decode()[:500]}",
            }

    except asyncio.TimeoutError:
        logger.error("Concat ffmpeg timed out | task_id=%s", task_id)
        video_path = str(scene_videos[0]) if scene_videos else ""
        return {
            "video_path": video_path,
            "current_step": "video",
            "status": "video_partial",
            "error": "Video concatenation timed out.",
        }

    video_url = f"/storage/stories/{story_id}/video/story.mp4"
    logger.info(
        "video_agent completed | final video: %s | task_id=%s",
        final_path,
        task_id,
    )

    return {
        "video_path": str(final_path),
        "current_step": "video",
        "status": "video_done",
        "error": "",
    }