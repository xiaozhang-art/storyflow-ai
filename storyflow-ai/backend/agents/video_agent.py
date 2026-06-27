"""Video Agent — assemble images + audio into final MP4 via FFmpeg."""

import asyncio
import logging
import subprocess
from pathlib import Path

from configs.settings import settings

logger = logging.getLogger(__name__)


def _get_media_duration(path: str) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        return 5.0


def _fmt_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{int(s):02d}.{int((s % 1) * 100):02d}"


def _write_ass_file(scenes: list[dict], scene_durations: dict[int, float], save_path: Path):
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
        duration = scene_durations.get(scene_no, float(scene.get("duration", 5)))
        if not dialogue.strip():
            cumulative_time += duration
            continue
        start = _fmt_ass_time(cumulative_time)
        end = _fmt_ass_time(cumulative_time + duration)
        speaker = scene.get("characters", ["旁白"])[0] if scene.get("characters") else "旁白"
        safe = dialogue.replace("\\", "\\\\").replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\b1}}{speaker}：{safe}")
        cumulative_time += duration

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(ass_header + "\n".join(events), encoding="utf-8")


async def _create_scene_video(scene_no, image_path, audio_path, output_path) -> tuple[bool, float]:
    if not Path(image_path).exists():
        logger.warning("Image not found for scene %d: %s", scene_no, image_path)
        return False, 0.0

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", image_path]
    if audio_path and Path(audio_path).exists():
        cmd.extend(["-i", audio_path, "-shortest", "-c:a", "aac", "-b:a", "128k"])
    else:
        cmd.extend(["-t", "5"])
    cmd.extend([
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", "1",
        str(output_path),
    ])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            logger.error("ffmpeg failed for scene %d: %s", scene_no, stderr.decode()[:300])
            return False, 0.0
        return True, _get_media_duration(str(output_path))
    except asyncio.TimeoutError:
        logger.error("ffmpeg timed out for scene %d", scene_no)
        return False, 0.0


async def video_agent(state: dict, context: dict) -> dict:
    """Video assembly agent.

    v3 signature: (state, context) -> dict partial update.
    Assembles per-scene clips, burns subtitles, concatenates into final MP4.
    """
    story_id = state.get("story_id", "unknown")
    storyboard = state.get("storyboard", [])
    images = state.get("images", [])
    audios = state.get("audios", [])

    logger.info("video_agent started | story_id=%s", story_id)

    if not images:
        return {"video_path": "", "status": "error", "error": "No images."}

    story_dir = Path(settings.STORAGE_PATH) / "stories" / story_id
    scenes_dir = story_dir / "scenes"
    video_dir = story_dir / "video"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    image_map = {img["scene_no"]: img for img in images}
    audio_map = {aud["scene_no"]: aud for aud in audios}

    # Step 1: Per-scene video clips
    scene_videos: list[Path] = []
    scene_durations: dict[int, float] = {}

    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)
        img_info = image_map.get(scene_no)
        if not img_info:
            continue
        audio_path = audio_map[scene_no]["audio_path"] if scene_no in audio_map else None
        scene_video_path = scenes_dir / f"scene_{scene_no}.mp4"
        success, duration = await _create_scene_video(
            scene_no, img_info.get("image_path", ""), audio_path, scene_video_path)
        if success and scene_video_path.exists():
            scene_videos.append(scene_video_path)
            scene_durations[scene_no] = duration

    if not scene_videos:
        return {"video_path": "", "status": "error", "error": "No scene videos created."}

    # Step 2: ASS subtitles
    ass_path = video_dir / "subtitles.ass"
    _write_ass_file(storyboard, scene_durations, ass_path)

    # Step 3: Burn subtitles
    subtitled_dir = story_dir / "subtitled"
    subtitled_dir.mkdir(parents=True, exist_ok=True)
    subtitled_videos: list[Path] = []

    for sv in scene_videos:
        out = subtitled_dir / sv.name
        cmd = ["ffmpeg", "-y", "-i", str(sv), "-vf", f"ass={ass_path}", "-c:a", "copy", str(out)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0 and out.exists():
                subtitled_videos.append(out)
            else:
                subtitled_videos.append(sv)
        except Exception:
            subtitled_videos.append(sv)

    # Step 4: Concatenate
    final_path = video_dir / "story.mp4"
    filelist_path = scenes_dir / "filelist.txt"
    with open(filelist_path, "w") as f:
        for sv in subtitled_videos:
            f.write(f"file '{sv}'\n")

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(filelist_path), "-c", "copy", str(final_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            logger.error("Concat failed: %s", stderr.decode()[:300])
            return {
                "video_path": str(subtitled_videos[0]) if subtitled_videos else "",
                "status": "video_partial",
                "error": "Concatenation failed.",
            }
    except asyncio.TimeoutError:
        return {"video_path": "", "status": "error", "error": "Video concat timed out."}

    try:
        filelist_path.unlink(missing_ok=True)
    except Exception:
        pass

    video_url = f"/storage/stories/{story_id}/video/story.mp4"
    logger.info("video_agent completed | %s", final_path)

    return {"video_path": str(final_path), "status": "video_done", "error": ""}