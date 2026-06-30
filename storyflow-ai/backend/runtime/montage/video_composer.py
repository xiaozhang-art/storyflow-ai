"""高级视频合成引擎.

从 OpenMontage tools/video/video_stitch.py + video_compose.py 提取。
支持：转场拼接 / 字幕烧录 / 多音轨合成 / 统一转码 / 成片输出。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from runtime.montage.ffmpeg_ops import FFmpegOps
from runtime.montage.audio_mixer import AudioMixer
from runtime.montage.media_profiles import MediaProfile, get_profile, GENERIC_HD

logger = logging.getLogger(__name__)


@dataclass
class ComposeConfig:
    """视频合成配置."""
    # 输出
    output_path: str = ""
    profile: str = "storyflow_default"

    # 转场
    transition: str = "cut"  # "cut" / "crossfade" / "fade"
    transition_duration: float = 0.5

    # 音频
    mixed_audio_path: str = ""  # 预混合音频路径
    bgm_path: str = ""  # BGM 文件路径
    bgm_volume: float = 0.15
    bgm_segments: list[dict] = field(default_factory=list)  # [{start, end}]
    ducking: Optional[dict] = field(default_factory=lambda: {
        "enabled": True, "music_volume_during_speech": 0.15,
        "attack_ms": 200, "release_ms": 500,
    })

    # 字幕
    subtitle_path: str = ""
    burn_subtitles: bool = True
    subtitle_style: str = ""

    # 转码
    auto_normalize: bool = True
    codec: str = "libx264"
    crf: int = 23
    preset: str = "medium"

    # 质量检测
    run_quality_check: bool = True


class VideoComposer:
    """高级视频合成器.

    Usage:
        composer = VideoComposer()
        result = composer.compose(
            clips=["scene1.mp4", "scene2.mp4"],
            config=ComposeConfig(
                output_path="final.mp4",
                transition="crossfade",
                subtitle_path="subs.srt",
                bgm_path="music.mp3",
            ),
        )
    """

    def __init__(self):
        self.ffmpeg = FFmpegOps()
        self.mixer = AudioMixer()

    def compose(
        self,
        clips: list[str],
        config: ComposeConfig,
        audio_tracks: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """合成最终视频（主入口）.

        完整流程：
        1. 验证 + 探测所有片段
        2. 转码到统一格式（如需要）
        3. 拼接（带转场）
        4. 混合音频（语音 + BGM）
        5. 烧录字幕
        6. 合成音视频
        7. 质量检测（可选）

        Args:
            clips: 视频片段路径列表
            config: 合成配置
            audio_tracks: 预分离的音频轨列表

        Returns:
            {output, duration, method, quality_report?}
        """
        if not clips:
            raise ValueError("No clips provided")

        profile = get_profile(config.profile)
        output_path = Path(config.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_dir = Path(output_path).parent / ".compose_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_files: list[Path] = []

        try:
            # Step 1: Probe all clips
            logger.info("VideoComposer: probing %d clips", len(clips))
            probes: list[dict[str, Any]] = []
            for clip in clips:
                if not Path(clip).exists():
                    raise FileNotFoundError(f"Clip not found: {clip}")
                info = FFmpegOps.probe(clip)
                if info is None:
                    raise RuntimeError(f"Failed to probe: {clip}")
                probes.append(info)

            # Step 2: Normalize if needed
            needs_norm = self._needs_normalization(probes)
            use_transition = config.transition in ("crossfade", "fade")

            working_clips: list[str] = []
            if needs_norm or config.auto_normalize or use_transition:
                logger.info("VideoComposer: normalizing clips")
                for i, clip in enumerate(clips):
                    norm_path = str(tmp_dir / f"norm_{i:04d}.mp4")
                    FFmpegOps.normalize_clip(
                        clip, norm_path,
                        width=profile.width, height=profile.height,
                        fps=profile.fps, codec=config.codec,
                        crf=config.crf, preset=config.preset,
                    )
                    working_clips.append(norm_path)
                    tmp_files.append(Path(norm_path))

                # Ensure audio for transition clips
                if use_transition:
                    audio_clips: list[str] = []
                    for i, wc in enumerate(working_clips):
                        if FFmpegOps.has_audio(wc):
                            audio_clips.append(wc)
                        else:
                            aug_path = str(tmp_dir / f"audio_aug_{i:04d}.mp4")
                            FFmpegOps.ensure_audio(wc, aug_path)
                            audio_clips.append(aug_path)
                            tmp_files.append(Path(aug_path))
                    working_clips = audio_clips
                    # Re-probe normalized clips
                    probes = [FFmpegOps.probe(c) or {"duration": 5.0} for c in working_clips]
            else:
                working_clips = list(clips)

            if len(working_clips) < 1:
                raise RuntimeError("No valid clips after normalization")

            # Step 3: Stitch
            stitched_path = str(tmp_dir / "stitched.mp4")
            if len(working_clips) == 1:
                shutil.copy2(working_clips[0], stitched_path)
                method = "single_clip"
            elif config.transition == "cut":
                FFmpegOps.concat_demuxer(working_clips, stitched_path)
                method = "concat_demuxer"
            else:
                transition_name = "fade" if config.transition == "crossfade" else "fadeblack"
                FFmpegOps.xfade_stitch(
                    working_clips, stitched_path,
                    transition=transition_name,
                    duration=config.transition_duration,
                    probes=probes,
                )
                method = f"xfade_{config.transition}"
            tmp_files.append(Path(stitched_path))

            # Step 4: Audio
            final_video = stitched_path
            if config.mixed_audio_path and Path(config.mixed_audio_path).exists():
                # Use pre-mixed audio
                muxed_path = str(tmp_dir / "muxed.mp4")
                FFmpegOps.merge_audio_to_video(
                    stitched_path, config.mixed_audio_path, muxed_path,
                )
                final_video = muxed_path
                tmp_files.append(Path(muxed_path))
            elif audio_tracks:
                # Mix audio tracks
                mixed_path = str(tmp_dir / "mixed.wav")
                self.mixer.full_mix(
                    tracks=audio_tracks,
                    output_path=mixed_path,
                    ducking=config.ducking,
                )
                muxed_path = str(tmp_dir / "muxed.mp4")
                FFmpegOps.merge_audio_to_video(
                    stitched_path, mixed_path, muxed_path,
                )
                final_video = muxed_path
                tmp_files.append(Path(mixed_path))
                tmp_files.append(Path(muxed_path))

            # Step 4b: BGM
            if config.bgm_path and Path(config.bgm_path).exists():
                if config.bgm_segments:
                    bgm_path = str(tmp_dir / "with_bgm.mp4")
                    self.mixer.segmented_music(
                        final_video, config.bgm_path,
                        segments=config.bgm_segments,
                        output_path=bgm_path,
                        music_volume=config.bgm_volume,
                    )
                    final_video = bgm_path
                    tmp_files.append(Path(bgm_path))
                elif config.ducking and config.ducking.get("enabled"):
                    # Extract audio, duck with BGM, re-mux
                    speech_path = str(tmp_dir / "speech.wav")
                    self.mixer.extract_audio(final_video, speech_path)
                    ducked_path = str(tmp_dir / "ducked.wav")
                    self.mixer.duck(
                        speech_path, config.bgm_path, ducked_path,
                        duck_level_db=-12,
                        attack_ms=config.ducking.get("attack_ms", 200),
                        release_ms=config.ducking.get("release_ms", 500),
                    )
                    muxed_path = str(tmp_dir / "with_bgm.mp4")
                    FFmpegOps.merge_audio_to_video(
                        final_video, ducked_path, muxed_path,
                    )
                    final_video = muxed_path
                    tmp_files.extend([
                        Path(speech_path), Path(ducked_path), Path(muxed_path),
                    ])

            # Step 5: Burn subtitles
            if config.burn_subtitles and config.subtitle_path and Path(config.subtitle_path).exists():
                subtitled_path = str(tmp_dir / "subtitled.mp4")
                FFmpegOps.burn_subtitles(
                    final_video, config.subtitle_path,
                    subtitled_path, config.subtitle_style,
                )
                final_video = subtitled_path
                tmp_files.append(Path(subtitled_path))

            # Step 6: Copy to final output
            shutil.copy2(final_video, str(output_path))

            # Get output info
            out_info = FFmpegOps.probe(str(output_path)) or {}
            duration = out_info.get("duration", 0)
            file_size = output_path.stat().st_size if output_path.exists() else 0

            # Step 7: Quality check
            quality_report = None
            if config.run_quality_check and output_path.exists():
                try:
                    from runtime.montage.quality_checker import QualityChecker
                    checker = QualityChecker()
                    quality_report = checker.check(str(output_path))
                except Exception as e:
                    logger.warning("Quality check failed: %s", e)

            logger.info(
                "VideoComposer: done | method=%s | duration=%.1fs | size=%d bytes",
                method, duration, file_size,
            )

            result: dict[str, Any] = {
                "output": str(output_path),
                "duration": round(duration, 2),
                "file_size_bytes": file_size,
                "method": method,
                "clip_count": len(clips),
                "transition": config.transition,
            }
            if quality_report:
                result["quality_report"] = quality_report

            return result

        finally:
            # Cleanup temp files
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def compose_simple(
        clips: list[str],
        output_path: str,
        transition: str = "crossfade",
        transition_duration: float = 0.5,
        subtitle_path: str = "",
        bgm_path: str = "",
    ) -> dict[str, Any]:
        """简化版合成接口."""
        config = ComposeConfig(
            output_path=output_path,
            transition=transition,
            transition_duration=transition_duration,
            subtitle_path=subtitle_path,
            bgm_path=bgm_path,
        )
        composer = VideoComposer()
        return composer.compose(clips, config)

    @staticmethod
    def _needs_normalization(probes: list[dict[str, Any]]) -> bool:
        """检查片段是否需要统一转码."""
        if len(probes) < 2:
            return False
        ref = probes[0]
        for p in probes[1:]:
            for key in ("width", "height", "fps", "video_codec", "audio_codec"):
                if ref.get(key) != p.get(key) and ref.get(key) is not None:
                    return True
        return False