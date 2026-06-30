"""多轨音频混合引擎.

从 OpenMontage tools/audio/audio_mixer.py 提取，剥离 BaseTool 依赖。
支持：多轨混合 / ducking / BGM / SFX / 归一化 / 分段配乐。
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Optional

from runtime.montage.ffmpeg_ops import FFmpegOps

logger = logging.getLogger(__name__)


class AudioMixer:
    """多轨音频混合器.

    Usage:
        mixer = AudioMixer()
        mixer.full_mix(
            tracks=[
                {"path": "narration.mp3", "role": "speech", "start_seconds": 0},
                {"path": "music.mp3", "role": "music", "volume": 0.3},
            ],
            ducking={"enabled": True, "music_volume_during_speech": 0.15},
            output_path="mixed.wav",
        )
    """

    # ---- 基础混合 ----

    def mix(
        self,
        tracks: list[dict[str, Any]],
        output_path: str,
        normalize: bool = True,
    ) -> dict[str, Any]:
        """混合多轨音频.

        Args:
            tracks: [{path, role, volume, start_seconds, fade_in_seconds, fade_out_seconds}]
            output_path: 输出路径
            normalize: 是否响度归一化

        Returns:
            {output, track_count, normalized}
        """
        if not tracks:
            raise ValueError("No tracks provided")

        for t in tracks:
            if not Path(t["path"]).exists():
                raise FileNotFoundError(f"Track not found: {t['path']}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        input_args, filter_parts = self._build_track_filters(tracks)

        # Amix all streams
        mix_inputs = "".join(f"[a{i}]" for i in range(len(tracks)))
        if normalize:
            filter_parts.append(
                f"{mix_inputs}amix=inputs={len(tracks)}:duration=longest:"
                f"dropout_transition=2,loudnorm=I=-16:LRA=11:TP=-1.5[out]"
            )
            out_label = "[out]"
        else:
            filter_parts.append(
                f"{mix_inputs}amix=inputs={len(tracks)}:duration=longest:dropout_transition=2[out]"
            )
            out_label = "[out]"

        filter_complex = ";".join(filter_parts)
        cmd = ["ffmpeg", "-y"] + input_args + [
            "-filter_complex", filter_complex,
            "-map", out_label,
            output_path,
        ]
        FFmpegOps.run(cmd)

        return {
            "output": str(output_path),
            "track_count": len(tracks),
            "normalized": normalize,
        }

    # ---- Ducking ----

    def duck(
        self,
        speech_path: str,
        music_path: str,
        output_path: str,
        duck_level_db: float = -12,
        attack_ms: float = 200,
        release_ms: float = 500,
    ) -> dict[str, Any]:
        """Speech/Music ducking（语音说话时音乐自动降低）.

        Args:
            speech_path: 语音文件
            music_path: 音乐文件
            output_path: 输出路径
            duck_level_db: 鸭音衰减量（dB，负值）
            attack_ms: 起音时间
            release_ms: 释放时间
        """
        music_vol = round(math.pow(10, duck_level_db / 20), 4)
        attack = attack_ms / 1000
        release = release_ms / 1000

        filter_complex = (
            f"[1:a]sidechaincompress="
            f"threshold=0.02:ratio=9:attack={attack}:release={release}:"
            f"level_sc=1:mix=0.9[ducked];"
            f"[ducked]volume={music_vol * 3}[music_out];"
            f"[0:a][music_out]amix=inputs=2:duration=longest[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", speech_path, "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            output_path,
        ]
        FFmpegOps.run(cmd)

        return {"output": str(output_path), "method": "sidechain_duck"}

    # ---- Full Mix（首选 API） ----

    def full_mix(
        self,
        tracks: list[dict[str, Any]],
        output_path: str,
        ducking: Optional[dict[str, Any]] = None,
        normalize: bool = True,
    ) -> dict[str, Any]:
        """一站式混合：语音 + 音乐 + 音效 + ducking + 归一化.

        Args:
            tracks: [
                {path, role: "speech"|"music"|"sfx", volume, start_seconds, fade_in/out_seconds}
            ]
            output_path: 输出路径
            ducking: {enabled, music_volume_during_speech, attack_ms, release_ms}
            normalize: 是否归一化
        """
        if not tracks:
            raise ValueError("No tracks provided for full_mix")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        ducking = ducking or {"enabled": True}
        speech_tracks = [t for t in tracks if t.get("role") in ("speech", "primary")]
        music_tracks = [t for t in tracks if t.get("role") in ("music", "secondary")]
        sfx_tracks = [t for t in tracks if t.get("role") == "sfx"]
        all_tracks = speech_tracks + music_tracks + sfx_tracks

        if not all_tracks:
            raise ValueError("No valid tracks (need speech/music/sfx roles)")

        for t in all_tracks:
            if not Path(t["path"]).exists():
                raise FileNotFoundError(f"Track not found: {t['path']}")

        input_args, filter_parts = self._build_track_filters(all_tracks)

        duck_enabled = ducking.get("enabled", True) if isinstance(ducking, dict) else bool(ducking)

        if duck_enabled and speech_tracks and music_tracks:
            # Build speech mix
            speech_indices = list(range(len(speech_tracks)))
            speech_labels = "".join(f"[a{i}]" for i in speech_indices)

            if len(speech_tracks) > 1:
                filter_parts.append(
                    f"{speech_labels}amix=inputs={len(speech_tracks)}:duration=longest[speech_mix]"
                )
                speech_out = "[speech_mix]"
            else:
                speech_out = f"[a{speech_indices[0]}]"

            # Build music mix
            music_start = len(speech_tracks)
            music_indices = list(range(music_start, music_start + len(music_tracks)))
            music_labels = "".join(f"[a{i}]" for i in music_indices)

            if len(music_tracks) > 1:
                filter_parts.append(
                    f"{music_labels}amix=inputs={len(music_tracks)}:duration=longest[music_mix]"
                )
                music_in = "[music_mix]"
            else:
                music_in = f"[a{music_indices[0]}]"

            # Sidechain ducking
            duck_params = ducking if isinstance(ducking, dict) else {}
            attack = duck_params.get("attack_ms", 200) / 1000
            release = duck_params.get("release_ms", 500) / 1000
            music_vol = duck_params.get("music_volume_during_speech", 0.15)

            filter_parts.append(
                f"{music_in}{speech_out}sidechaincompress="
                f"threshold=0.02:ratio=9:attack={attack}:release={release}:"
                f"level_sc=1:mix=0.9[ducked_music];"
                f"[ducked_music]volume={music_vol * 3}[music_out]"
            )

            # Rebuild speech for output (sidechain uses it as key)
            if len(speech_tracks) > 1:
                filter_parts.append(
                    f"{speech_labels}amix=inputs={len(speech_tracks)}:duration=longest[speech_out]"
                )
            else:
                filter_parts.append(f"[a{speech_indices[0]}]acopy[speech_out]")

            # Final mix
            mix_label = "[speech_out][music_out]amix=inputs=2:duration=longest[premix]"

            # Add SFX
            sfx_start = len(speech_tracks) + len(music_tracks)
            if sfx_tracks:
                sfx_labels = "".join(f"[a{i}]" for i in range(sfx_start, sfx_start + len(sfx_tracks)))
                filter_parts.append(mix_label.replace("[premix]", "[pressfx]"))
                filter_parts.append(
                    f"[pressfx]{sfx_labels}amix=inputs={1 + len(sfx_tracks)}:duration=longest[premix]"
                )
            else:
                filter_parts.append(mix_label)
        else:
            # No ducking: simple amix
            all_labels = "".join(f"[a{i}]" for i in range(len(all_tracks)))
            filter_parts.append(
                f"{all_labels}amix=inputs={len(all_tracks)}:duration=longest:dropout_transition=2[premix]"
            )

        # Normalize
        if normalize:
            filter_parts.append("[premix]loudnorm=I=-16:LRA=11:TP=-1.5[out]")
            out_label = "[out]"
        else:
            out_label = "[premix]"

        filter_complex = ";".join(p for p in filter_parts if p)

        cmd = ["ffmpeg", "-y"] + input_args + [
            "-filter_complex", filter_complex,
            "-map", out_label,
            output_path,
        ]
        FFmpegOps.run(cmd)

        return {
            "output": str(output_path),
            "speech_tracks": len(speech_tracks),
            "music_tracks": len(music_tracks),
            "sfx_tracks": len(sfx_tracks),
            "ducking_enabled": duck_enabled,
            "normalized": normalize,
        }

    # ---- 分段配乐 ----

    def segmented_music(
        self,
        video_path: str,
        music_path: str,
        segments: list[dict[str, float]],
        output_path: str,
        music_volume: float = 0.20,
        fade_duration: float = 0.5,
    ) -> dict[str, Any]:
        """在视频指定时间段内混入 BGM（带淡入淡出）.

        Args:
            video_path: 输入视频
            music_path: BGM 文件
            segments: [{start, end}, ...] 音乐播放时间段
            output_path: 输出路径
            music_volume: 音乐音量
            fade_duration: 淡入淡出时长
        """
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        if not Path(music_path).exists():
            raise FileNotFoundError(f"Music not found: {music_path}")
        if not segments:
            raise ValueError("No segments specified")

        total_dur = FFmpegOps.get_duration(video_path)

        # Build volume expression per segment
        parts = []
        for seg in sorted(segments, key=lambda s: s["start"]):
            s = seg["start"]
            e = seg["end"]
            fade_in_end = s + fade_duration
            fade_out_start = e - fade_duration
            parts.append(
                f"if(lt(t,{s}),0,"
                f"if(lt(t,{fade_in_end}),{music_volume}*(t-{s})/{fade_duration},"
                f"if(lt(t,{fade_out_start}),{music_volume},"
                f"if(lt(t,{e}),{music_volume}*({e}-t)/{fade_duration},"
                f"0))))"
            )

        vol_expr = "+".join(f"({p})" for p in parts) if len(parts) > 1 else parts[0]

        filter_complex = (
            f"[1:a]atrim=0:{total_dur},asetpts=PTS-STARTPTS,"
            f"volume='{vol_expr}':eval=frame[music_shaped];"
            f"[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[speech];"
            f"[music_shaped]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[music_fmt];"
            f"[speech][music_fmt]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1",
            "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
        FFmpegOps.run(cmd)

        return {
            "output": str(output_path),
            "segments": segments,
            "music_volume": music_volume,
        }

    # ---- 提取音频 ----

    @staticmethod
    def extract_audio(
        input_path: str,
        output_path: str = "",
        codec: str = "pcm_s16le",
        sample_rate: int = 16000,
    ) -> str:
        """从视频提取音频."""
        if not output_path:
            output_path = str(Path(input_path).with_suffix(".wav"))

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vn", "-acodec", codec,
            "-ar", str(sample_rate), "-ac", "1",
            output_path,
        ]
        FFmpegOps.run(cmd)
        return output_path

    # ---- 内部方法 ----

    @staticmethod
    def _build_track_filters(tracks: list[dict]) -> tuple[list[str], list[str]]:
        """为每条音轨构建 FFmpeg input args 和 filter parts."""
        input_args: list[str] = []
        filter_parts: list[str] = []

        for i, track in enumerate(tracks):
            input_args.extend(["-i", track["path"]])
            volume = track.get("volume", 1.0)
            delay_ms = int(track.get("start_seconds", 0) * 1000)
            fade_in = track.get("fade_in_seconds", 0)
            fade_out = track.get("fade_out_seconds", 0)

            filters = []
            if volume != 1.0:
                filters.append(f"volume={volume}")
            if delay_ms > 0:
                filters.append(f"adelay={delay_ms}|{delay_ms}")
            if fade_in > 0:
                filters.append(f"afade=t=in:d={fade_in}")
            if fade_out > 0:
                filters.append(f"afade=t=out:d={fade_out}")

            if filters:
                filter_chain = ",".join(filters)
                filter_parts.append(f"[{i}:a]{filter_chain}[a{i}]")
            else:
                filter_parts.append(f"[{i}:a]acopy[a{i}]")

        return input_args, filter_parts