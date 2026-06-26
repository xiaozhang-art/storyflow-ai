import asyncio
import logging
import os
import subprocess
from pathlib import Path

from configs.settings import settings
from workflows.state import StoryState

logger = logging.getLogger(__name__)


def _fmt_ass_time(seconds: float) -> str:
    """Format seconds to ASS time string H:MM:SS.cc."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{int(s):02d}.{int((s % 1) * 100):02d}"


def _get_media_duration(path: str) -> float:
    """Get duration in seconds using ffprobe (works for audio and video)."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        logger.warning("Could not get duration for %s, defaulting to 5.0", path)
        return 5.0


def _write_ass_file(
    scenes: list[dict],
    scene_durations: dict[int, float],
    save_path: Path,
) -> None:
    """Write ASS subtitle file with timing based on actual scene video durations.

    Args:
        scenes: List of storyboard scene dicts.
        scene_durations: Map of scene_no -> actual duration in seconds.
        save_path: Output path for the .ass file.
    """
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
    cumulative_time = 0.0

    for scene in scenes:
        scene_no = scene.get("scene_no", 0)
        dialogue = scene.get("dialogue", "")

        # Use actual duration from the generated video, fallback to storyboard value
        duration = scene_durations.get(scene_no, float(scene.get("duration", 5)))

        if not dialogue.strip():
            # No subtitle for this scene, but still advance time
            cumulative_time += duration
            continue

        start = _fmt_ass_time(cumulative_time)
        end = _fmt_ass_time(cumulative_time + duration)

        speaker = "旁白"
        scene_characters = scene.get("characters", [])
        if scene_characters:
            speaker = scene_characters[0]

        safe_dialogue = dialogue.replace("\\", "\\\\").replace("\n", "\\N")
        events.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,"
            f"{{\\b1}}{speaker}：{safe_dialogue}"
        )

        cumulative_time += duration

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(ass_header + "\n".join(events), encoding="utf-8")
    logger.info(
        "ASS subtitles written: %d dialogue lines, total %.1fs",
        len(events), cumulative_time,
    )


async def _create_scene_video(
    scene_no: int,
    image_path: str,
    audio_path: str | None,
    output_path: Path,
) -> tuple[bool, float]:
    """Create a video for a single scene using ffmpeg.

    Returns:
        (success, actual_duration) - the real duration of the output video.
    """
    if not Path(image_path).exists():
        logger.warning("Image not found, skipping scene %d: %s", scene_no, image_path)
        return False, 0.0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
    ]

    if audio_path and Path(audio_path).exists():
        cmd.extend(["-i", audio_path, "-shortest", "-c:a", "aac", "-b:a", "128k"])
    else:
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
            logger.error("ffmpeg failed for scene %d: %s", scene_no, stderr.decode())
            return False, 0.0

        # Measure actual video duration
        actual_duration = _get_media_duration(str(output_path))
        logger.info("Scene %d video: %.1fs", scene_no, actual_duration)
        return True, actual_duration

    except asyncio.TimeoutError:
        logger.error("ffmpeg timed out for scene %d", scene_no)
        return False, 0.0


async def video_agent(state: StoryState) -> dict:
    """
    Video assembly agent.
    For each scene, creates a video clip from the generated image and audio
    using ffmpeg. Then generates ASS subtitles with timing based on actual
    scene video durations, burns subtitles, and concatenates into final MP4.
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

    # --- Step 1: Create per-scene video clips, track actual durations ---
    scene_videos: list[Path] = []
    scene_durations: dict[int, float] = {}  # scene_no -> actual duration

    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)
        img_info = image_map.get(scene_no)
        if not img_info:
            logger.warning("No image for scene %d, skipping | task_id=%s", scene_no, task_id)
            continue

        image_path = img_info.get("image_path", "")
        aud_info = audio_map.get(scene_no)
        audio_path = aud_info.get("audio_path") if aud_info else None

        scene_video_path = scenes_dir / f"scene_{scene_no}.mp4"
        success, duration = await _create_scene_video(
            scene_no, image_path, audio_path, scene_video_path
        )

        if success and scene_video_path.exists():
            scene_videos.append(scene_video_path)
            scene_durations[scene_no] = duration
            logger.info("Scene video created: %s (%.1fs)", scene_video_path, duration)
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

    # --- Step 2: Generate ASS subtitle file (timed by actual video durations) ---
    ass_path = video_dir / "subtitles.ass"
    _write_ass_file(storyboard, scene_durations, ass_path)
    logger.info("Subtitles written to %s", ass_path)

    # --- Step 3: Burn subtitles into each scene video ---
    subtitled_dir = story_dir / "subtitled"
    subtitled_dir.mkdir(parents=True, exist_ok=True)
    subtitled_videos: list[Path] = []

    for sv in scene_videos:
        out = subtitled_dir / sv.name
        cmd = [
            "ffmpeg", "-y",
            "-i", str(sv),
            "-vf", f"ass={ass_path}",
            "-c:a", "copy",
            str(out),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0 and out.exists():
                subtitled_videos.append(out)
            else:
                # Fallback: use unsubtitled version
                subtitled_videos.append(sv)
                logger.warning("Subtitle burn failed for %s, using unsubtitled", sv.name)
        except Exception:
            subtitled_videos.append(sv)

    # --- Step 4: Concatenate all scene videos ---
    final_path = video_dir / "story.mp4"
    filelist_path = scenes_dir / "filelist.txt"

    with open(filelist_path, "w", encoding="utf-8") as f:
        for sv in subtitled_videos:
            f.write(f"file '{sv}'\n")

    concat_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(filelist_path),
        "-c", "copy",
        str(final_path),
    ]

    logger.info("Concatenating %d scene videos into final video", len(subtitled_videos))

    try:
        proc = await asyncio.create_subprocess_exec(
            *concat_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            logger.error("Concat ffmpeg failed: %s | task_id=%s", stderr.decode(), task_id)
            video_path = str(subtitled_videos[0]) if subtitled_videos else ""
            return {
                "video_path": video_path,
                "current_step": "video",
                "status": "video_partial",
                "error": f"Concatenation failed: {stderr.decode()[:500]}",
            }

    except asyncio.TimeoutError:
        logger.error("Concat ffmpeg timed out | task_id=%s", task_id)
        video_path = str(subtitled_videos[0]) if subtitled_videos else ""
        return {
            "video_path": video_path,
            "current_step": "video",
            "status": "video_partial",
            "error": "Video concatenation timed out.",
        }

    # Cleanup temp files
    try:
        filelist_path.unlink(missing_ok=True)
    except Exception:
        pass

    video_url = f"/storage/stories/{story_id}/video/story.mp4"
    logger.info("video_agent completed | final video: %s | task_id=%s", final_path, task_id)

    return {
        "video_path": str(final_path),
        "current_step": "video",
        "status": "video_done",
        "error": "",
    }