"""Video Agent — merge video clips + audio into final MP4.

Pipeline change: images are already converted to video clips by image_to_video_agent.
This agent only does:
  1. Merge each clip's audio track
  2. Burn subtitles (ASS)
  3. Concat all clips into final video
"""

import asyncio
import logging
from pathlib import Path

from configs.settings import settings

logger = logging.getLogger(__name__)


def _get_media_duration(path: str) -> float:
    import subprocess
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


def _write_ass_file(scenes: list[dict], clip_durations: dict[int, float], save_path: Path):
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
        duration = clip_durations.get(scene_no, float(scene.get("duration", 5)))
        if not dialogue.strip():
            cumulative_time += duration
            continue
        start = _fmt_ass_time(cumulative_time)
        end = _fmt_ass_time(cumulative_time + duration)
        speaker = scene.get("characters", ["旁白"])[0] if scene.get("characters") else "旁白"
        safe = dialogue.replace("\\", "\\\\").replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{{\\b1}}{speaker}: {safe}")
        cumulative_time += duration

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(ass_header + "\n".join(events), encoding="utf-8")


async def _merge_audio_to_clip(video_path: str, audio_path: str | None,
                              output_path: str, duration: float) -> bool:
    """Merge audio into a video clip (replace or add audio track)."""
    cmd = ["ffmpeg", "-y", "-i", video_path]
    if audio_path and Path(audio_path).exists():
        cmd.extend(["-i", audio_path, "-c:v", "copy", "-c:a", "aac",
                     "-b:a", "128k", "-shortest"])
    else:
        cmd.extend(["-c", "copy"])
    cmd.append(output_path)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        return proc.returncode == 0 and Path(output_path).exists()
    except Exception as e:
        logger.error("Merge audio error: %s", e)
        return False


async def video_agent(state: dict, context: dict) -> dict:
    """Video assembly agent.

    v3 signature: (state, context) -> dict partial update.
    Merges video clips + audio into final MP4 with subtitles.
    """
    story_id = state.get("story_id", "unknown")
    storyboard = state.get("storyboard", [])
    video_clips = state.get("video_clips", [])
    audios = state.get("audios", [])
    use_capability = context.get("use_capability")

    logger.info("video_agent started | story_id=%s, %d clips", story_id, len(video_clips))

    if not video_clips:
        # Legacy fallback: no i2v step, use images directly
        return await _legacy_video_assembly(state, context)

    story_dir = Path(settings.STORAGE_PATH) / "stories" / story_id
    merged_dir = story_dir / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    final_dir = story_dir / "video"
    final_dir.mkdir(parents=True, exist_ok=True)

    clip_map = {c["scene_no"]: c for c in video_clips}
    audio_map = {a["scene_no"]: a for a in audios}

    # Step 1: Merge audio into each clip
    merged_clips: list[dict] = []
    clip_durations: dict[int, float] = {}

    for clip in video_clips:
        scene_no = clip.get("scene_no", 0)
        video_path = clip.get("video_path", "")
        audio_path = audio_map[scene_no]["audio_path"] if scene_no in audio_map else None

        if not video_path or not Path(video_path).exists():
            continue

        merged_path = str(merged_dir / f"scene_{scene_no:03d}.mp4")
        if video_path != merged_path:
            success = await _merge_audio_to_clip(video_path, audio_path, merged_path,
                                                  clip.get("duration", 5))
        else:
            success = True

        if success or Path(video_path).exists():
            final_clip = merged_path if Path(merged_path).exists() else video_path
            clip_durations[scene_no] = _get_media_duration(final_clip)
            merged_clips.append({
                "scene_no": scene_no,
                "video_path": final_clip,
                "audio_path": audio_path,
            })

    if not merged_clips:
        return {"video_path": "", "status": "error", "error": "No valid clips to merge."}

    # Step 2: Generate ASS subtitles
    ass_path = merged_dir / "subtitles.ass"
    _write_ass_file(storyboard, clip_durations, ass_path)

    # Step 3: Merge via Capability or direct FFmpeg
    final_path = str(final_dir / "story.mp4")

    if use_capability:
        result = await use_capability("merge_video", {
            "clips": merged_clips,
            "output_path": final_path,
            "subtitle_path": str(ass_path),
        }, context)

        if result.get("success"):
            video_url = f"/storage/stories/{story_id}/video/story.mp4"
            logger.info("video_agent completed via capability | %s", final_path)
            return {"video_path": final_path, "video_url": video_url,
                    "status": "video_done", "error": ""}

    # Fallback: direct concat
    success = await _direct_concat(merged_clips, final_path)
    if not success and ass_path.exists():
        # Try without subtitles
        success = await _direct_concat(merged_clips, final_path)

    video_url = f"/storage/stories/{story_id}/video/story.mp4"
    status = "video_done" if success else "error"
    error = "" if success else "Final concat failed"

    logger.info("video_agent completed | success=%s | %s", success, final_path)
    return {"video_path": final_path, "video_url": video_url, "status": status, "error": error}


async def _direct_concat(clips: list[dict], output_path: str) -> bool:
    """Direct FFmpeg concat without capability."""
    filelist = Path(output_path).parent / "_concat.txt"
    with open(filelist, "w") as f:
        for c in clips:
            f.write(f"file '{c['video_path']}'\n")

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(filelist), "-c", "copy", output_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode != 0:
            logger.error("Direct concat failed: %s", stderr.decode()[:300])
            return False
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        try:
            filelist.unlink(missing_ok=True)
        except Exception:
            pass


async def _legacy_video_assembly(state: dict, context: dict) -> dict:
    """Legacy path: images + audio -> video (when no i2v step)."""
    images = state.get("images", [])
    storyboard = state.get("storyboard", [])
    story_id = state.get("story_id", "unknown")

    logger.info("video_agent: legacy mode (no video_clips) | story_id=%s", story_id)

    story_dir = Path(settings.STORAGE_PATH) / "stories" / story_id
    scenes_dir = story_dir / "scenes"
    video_dir = story_dir / "video"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    image_map = {img["scene_no"]: img for img in images}
    audios = state.get("audios", [])
    audio_map = {a["scene_no"]: a for a in audios}

    scene_videos: list[Path] = []
    scene_durations: dict[int, float] = {}

    for scene in storyboard:
        scene_no = scene.get("scene_no", 0)
        img_info = image_map.get(scene_no)
        if not img_info:
            continue
        audio_path = audio_map[scene_no]["audio_path"] if scene_no in audio_map else None
        scene_video_path = scenes_dir / f"scene_{scene_no}.mp4"
        duration = scene.get("duration", 5)

        # Image -> video via ffmpeg
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img_info.get("image_path", "")]
        if audio_path and Path(audio_path).exists():
            cmd.extend(["-i", audio_path, "-shortest", "-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.extend(["-t", str(duration)])
        cmd.extend([
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-r", "1",
            str(scene_video_path),
        ])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            _, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            if scene_video_path.exists():
                scene_videos.append(scene_video_path)
                scene_durations[scene_no] = _get_media_duration(str(scene_video_path))
        except Exception as e:
            logger.error("Legacy scene video failed for %d: %s", scene_no, e)

    if not scene_videos:
        return {"video_path": "", "status": "error", "error": "No scene videos created."}

    ass_path = video_dir / "subtitles.ass"
    _write_ass_file(storyboard, scene_durations, ass_path)

    # Burn subtitles
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
            subtitled_videos.append(out if out.exists() else sv)
        except Exception:
            subtitled_videos.append(sv)

    # Concat
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
            logger.error("Legacy concat failed: %s", stderr.decode()[:300])
    except asyncio.TimeoutError:
        pass

    try:
        filelist_path.unlink(missing_ok=True)
    except Exception:
        pass

    video_url = f"/storage/stories/{story_id}/video/story.mp4"
    return {"video_path": str(final_path), "video_url": video_url,
            "status": "video_done", "error": ""}