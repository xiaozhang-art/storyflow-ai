"""FFmpeg tool for video composition."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class FFmpegTool:
    """Utility class for FFmpeg operations."""

    @staticmethod
    async def create_scene_video(
        image_path: str,
        audio_path: str,
        output_path: str,
    ) -> str:
        """Create a video from a still image and audio file."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", image_path,
            "-i", audio_path,
            "-shortest",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-r", "1",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"FFmpeg scene video failed: {stderr.decode()}")
            raise RuntimeError(f"FFmpeg failed: {stderr.decode()[:500]}")

        logger.info(f"Scene video created: {output_path}")
        return output_path

    @staticmethod
    async def concat_videos(video_paths: list[str], output_path: str) -> str:
        """Concatenate multiple video files into one."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Write file list for concat demuxer
        list_content = "\n".join(f"file '{p}'" for p in video_paths)
        list_path = output_path + ".filelist.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            f.write(list_content)

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        # Cleanup file list
        if os.path.exists(list_path):
            os.remove(list_path)

        if proc.returncode != 0:
            logger.error(f"FFmpeg concat failed: {stderr.decode()}")
            raise RuntimeError(f"FFmpeg concat failed: {stderr.decode()[:500]}")

        logger.info(f"Final video created: {output_path}")
        return output_path

    @staticmethod
    async def generate_subtitle(
        scene_no: int,
        text: str,
        start_time: float,
        end_time: float,
        output_path: str,
    ) -> str:
        """Generate an ASS subtitle file for a scene."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Format times as H:MM:SS.cc
        def fmt_time(t: float) -> str:
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = t % 60
            return f"{h}:{m:02d}:{s:05.2f}"

        ass_content = f"""[Script Info]
Title: StoryFlow Subtitle
ScriptType: v4.00+
PlayResX: 1024
PlayResY: 1024
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,{fmt_time(start_time)},{fmt_time(end_time)},Default,,0,0,0,,{text}
"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        return output_path