"""FFmpeg 底层操作封装.

从 OpenMontage tools/video/video_stitch.py 提取。
提供：转码 / 裁切 / 探测 / 静音注入 / concat 拼接。
所有方法为同步调用，返回 dict 或抛 RuntimeError。
"""

from __future__ import annotations

import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FFmpegOps:
    """FFmpeg 操作工具集.

    每个方法都是独立的 FFmpeg 操作，可自由组合。
    """

    @staticmethod
    def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        """执行 FFmpeg/FFprobe 命令."""
        import subprocess
        logger.debug("Running: %s", " ".join(cmd[:10]) + ("..." if len(cmd) > 10 else ""))
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr[:500] if result.stderr else "no stderr"
            raise RuntimeError(f"FFmpeg command failed (rc={result.returncode}): {stderr}")
        return result

    # ---- 探测 ----

    @staticmethod
    def probe(path: str) -> Optional[dict[str, Any]]:
        """探测媒体文件属性."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            path,
        ]
        try:
            result = FFmpegOps.run(cmd, timeout=30)
            data = json.loads(result.stdout)
        except Exception:
            return None

        info: dict[str, Any] = {"path": str(path)}

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width")
                info["height"] = stream.get("height")
                info["video_codec"] = stream.get("codec_name")
                info["pixel_format"] = stream.get("pix_fmt")
                rfr = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = rfr.split("/")
                    info["fps"] = round(int(num) / int(den), 2)
                except (ValueError, ZeroDivisionError):
                    info["fps"] = None
                break

        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                info["audio_codec"] = stream.get("codec_name")
                info["sample_rate"] = stream.get("sample_rate")
                info["audio_channels"] = stream.get("channels")
                break

        fmt = data.get("format", {})
        try:
            info["duration"] = float(fmt.get("duration", 0))
        except (TypeError, ValueError):
            info["duration"] = 0.0

        return info

    @staticmethod
    def get_duration(path: str) -> float:
        """获取媒体文件时长."""
        info = FFmpegOps.probe(path)
        return info.get("duration", 0.0) if info else 0.0

    @staticmethod
    def has_audio(path: str) -> bool:
        """检查视频是否包含音频流."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "json",
            path,
        ]
        try:
            result = FFmpegOps.run(cmd, timeout=15)
            data = json.loads(result.stdout)
            return len(data.get("streams", [])) > 0
        except Exception:
            return False

    # ---- 转码 ----

    @staticmethod
    def normalize_clip(
        input_path: str,
        output_path: str,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
        codec: str = "libx264",
        audio_codec: str = "aac",
        crf: int = 23,
        preset: str = "medium",
    ) -> None:
        """转码视频到统一格式（分辨率/帧率/编码）."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"setsar=1,fps={fps}"
            ),
            "-c:v", codec, "-crf", str(crf), "-preset", preset,
            "-c:a", audio_codec, "-ar", "44100", "-ac", "2",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        FFmpegOps.run(cmd)

    @staticmethod
    def ensure_audio(input_path: str, output_path: str) -> None:
        """为无声视频注入静默 AAC 音频轨."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            output_path,
        ]
        FFmpegOps.run(cmd)

    # ---- 裁切 ----

    @staticmethod
    def cut(
        input_path: str,
        output_path: str,
        start: float = 0.0,
        duration: float = 0.0,
        codec: str = "copy",
    ) -> None:
        """裁切视频片段."""
        cmd = ["ffmpeg", "-y", "-ss", str(start)]
        if duration > 0:
            cmd.extend(["-t", str(duration)])
        cmd.extend(["-i", input_path])
        if codec == "copy":
            cmd.extend(["-c", "copy"])
        else:
            cmd.extend([
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
            ])
        cmd.append(output_path)
        FFmpegOps.run(cmd)

    @staticmethod
    def speed_change(input_path: str, output_path: str, factor: float) -> None:
        """调整视频速度."""
        import math
        # Build atempo chain (each supports 0.5-100)
        atempo_parts = []
        remaining = factor
        while remaining > 2.0:
            atempo_parts.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            atempo_parts.append("atempo=0.5")
            remaining /= 0.5
        atempo_parts.append(f"atempo={remaining:.4f}")
        atempo_chain = ",".join(atempo_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-filter:v", f"setpts={1/factor}*PTS",
            "-filter:a", atempo_chain,
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            output_path,
        ]
        FFmpegOps.run(cmd)

    # ---- 拼接 ----

    @staticmethod
    def concat_demuxer(clips: list[str], output_path: str) -> None:
        """FFmpeg concat demuxer 拼接（要求格式一致）."""
        tmp_dir = Path(output_path).parent / ".concat_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        concat_list = tmp_dir / "concat.txt"

        try:
            with open(concat_list, "w", encoding="utf-8") as f:
                for clip in clips:
                    safe = str(Path(clip).resolve()).replace("\\", "/")
                    f.write(f"file '{safe}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy",
                output_path,
            ]
            FFmpegOps.run(cmd)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- 转场 ----

    @staticmethod
    def xfade_stitch(
        clips: list[str],
        output_path: str,
        transition: str = "fade",
        duration: float = 0.5,
        probes: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """带 xfade 转场的视频拼接.

        Args:
            clips: 视频文件路径列表
            output_path: 输出路径
            transition: "fade" / "fadeblack" / "slideleft" / "slideright" 等
            duration: 转场时长（秒）
            probes: 预探测的 clip 信息（避免重复探测）
        """
        n = len(clips)
        if n < 2:
            if n == 1:
                shutil.copy2(clips[0], output_path)
            return

        # Probe if not provided
        if probes is None:
            probes = [FFmpegOps.probe(c) or {"duration": 5.0} for c in clips]

        # For 2 clips, simple xfade
        if n == 2:
            clip_dur = probes[0].get("duration", 5.0)
            offset = max(0, clip_dur - duration)
            cmd = [
                "ffmpeg", "-y",
                "-i", clips[0], "-i", clips[1],
                "-filter_complex",
                (
                    f"[0:v][1:v]xfade=transition={transition}:duration={duration}"
                    f":offset={offset:.3f}[v];"
                    f"[0:a][1:a]acrossfade=d={duration}[a]"
                ),
                "-map", "[v]", "-map", "[a]",
                output_path,
            ]
            FFmpegOps.run(cmd)
            return

        # N > 2: chain xfade
        input_args: list[str] = []
        for clip in clips:
            input_args.extend(["-i", clip])

        video_filters: list[str] = []
        audio_filters: list[str] = []
        cumulative_offset = 0.0

        for i in range(n - 1):
            clip_dur = probes[i].get("duration", 5.0)
            offset = round(cumulative_offset + clip_dur - duration, 3)
            offset = max(0, offset)

            v_in1 = "[0:v]" if i == 0 else f"[vfade{i-1}]"
            a_in1 = "[0:a]" if i == 0 else f"[afade{i-1}]"
            v_in2 = f"[{i+1}:v]"
            a_in2 = f"[{i+1}:a]"

            if i < n - 2:
                v_out = f"[vfade{i}]"
                a_out = f"[afade{i}]"
            else:
                v_out = "[vout]"
                a_out = "[aout]"

            video_filters.append(
                f"{v_in1}{v_in2}xfade=transition={transition}"
                f":duration={duration}:offset={offset}{v_out}"
            )
            audio_filters.append(
                f"{a_in1}{a_in2}acrossfade=d={duration}{a_out}"
            )

            cumulative_offset = offset

        filter_complex = ";".join(video_filters + audio_filters)
        cmd = ["ffmpeg", "-y"] + input_args + [
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            output_path,
        ]
        FFmpegOps.run(cmd)

    # ---- 字幕烧录 ----

    @staticmethod
    def burn_subtitles(
        input_path: str,
        subtitle_path: str,
        output_path: str,
        style: str = "",
    ) -> None:
        """将字幕烧录到视频中.

        Args:
            input_path: 视频文件
            subtitle_path: SRT/ASS 字幕文件
            output_path: 输出路径
            style: 可选的 ASS 风格覆写
        """
        if subtitle_path.endswith(".ass"):
            vf = f"ass={subtitle_path}"
        else:
            # SRT: add default style
            default_style = (
                "FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,BackColour=&H80000000,"
                "Outline=2,Shadow=1,MarginV=30,Alignment=2"
            )
            s = style or default_style
            escaped_path = subtitle_path.replace("'", "\\'").replace(":", "\\:")
            vf = f"subtitles='{escaped_path}':force_style='{s}'"

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:a", "copy",
            output_path,
        ]
        FFmpegOps.run(cmd)

    # ---- 音视频合并 ----

    @staticmethod
    def merge_audio_to_video(
        video_path: str,
        audio_path: str,
        output_path: str,
        audio_codec: str = "aac",
        audio_bitrate: str = "192k",
    ) -> None:
        """将音频合并到视频中."""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path, "-i", audio_path,
            "-c:v", "copy",
            "-c:a", audio_codec, "-b:a", audio_bitrate,
            "-shortest",
            output_path,
        ]
        FFmpegOps.run(cmd)

    # ---- 验证 ----

    @staticmethod
    def validate_clips(clips: list[str]) -> dict[str, Any]:
        """验证一组视频片段的兼容性."""
        probes = []
        missing = []
        errors = []

        for clip in clips:
            if not Path(clip).exists():
                missing.append(clip)
                continue
            info = FFmpegOps.probe(clip)
            if info is None:
                errors.append(clip)
            else:
                probes.append(info)

        if missing or errors:
            return {
                "compatible": False,
                "missing": missing,
                "errors": errors,
                "valid_clips": len(probes),
            }

        if len(probes) < 2:
            return {"compatible": True, "clips": probes}

        # Check mismatches
        ref = probes[0]
        mismatches = []
        for i, p in enumerate(probes[1:], 1):
            for key in ("width", "height", "fps", "video_codec", "audio_codec"):
                if ref.get(key) != p.get(key) and ref.get(key) is not None:
                    mismatches.append(f"clip[{i}].{key}: {p.get(key)} vs ref {ref.get(key)}")

        total_duration = sum(p.get("duration", 0) for p in probes)

        return {
            "compatible": len(mismatches) == 0,
            "mismatches": mismatches,
            "total_duration": round(total_duration, 2),
            "clips": probes,
        }

    # ---- 静态图片 → 视频 ----

    @staticmethod
    def image_to_video(
        image_path: str,
        output_path: str,
        duration: float = 5.0,
        audio_path: Optional[str] = None,
        fps: int = 1,
        codec: str = "libx264",
    ) -> None:
        """将静态图片合成为视频（可选附加音频）."""
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", image_path]
        if audio_path and Path(audio_path).exists():
            cmd.extend(["-i", audio_path, "-shortest", "-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.extend(["-t", str(duration)])
        cmd.extend([
            "-c:v", codec, "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-r", str(fps),
            output_path,
        ])
        FFmpegOps.run(cmd)


# Fix: need subprocess import at top
import subprocess