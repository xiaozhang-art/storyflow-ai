"""Montage Engine — OpenMontage 渲染能力剥离版.

从 OpenMontage (https://github.com/calesthio/OpenMontage) 提取的纯媒体渲染组件，
作为 StoryFlow 的下层剪辑引擎，不依赖任何 StoryFlow 业务逻辑。

提供的能力：
    - TTSEngine: 多供应商 TTS（OpenAI / ElevenLabs / Google / DashScope / Piper）
    - SubtitleEngine: SRT/VTT 字幕生成（词级时间轴对齐）
    - FFmpegOps: FFmpeg 底层操作（转码 / 裁切 / 转场 / 探测）
    - AudioMixer: 多轨音频混合（ducking / BGM / 音效 / 归一化）
    - VideoComposer: 高级视频合成（转场 / 字幕烧录 / 多音轨合成）
    - QualityChecker: 成片质量检测（7 项自动检查）
    - MediaProfiles: 输出格式配置（YouTube / TikTok / Instagram / Cinematic）
    - RenderQueue: 批量渲染队列

设计原则：
    - 纯媒体渲染组件，零业务依赖
    - 同步 FFmpeg 调用，由上层 Agent/适配器负责异步包装
    - 所有公共方法返回 MontageResult 数据类
"""

from runtime.montage.media_profiles import (
    MediaProfile,
    AspectRatio,
    ALL_PROFILES,
    get_profile,
    get_profiles_for_platform,
    ffmpeg_output_args,
)
from runtime.montage.tts_engine import TTSEngine, TTSResult
from runtime.montage.subtitle_engine import SubtitleEngine
from runtime.montage.ffmpeg_ops import FFmpegOps
from runtime.montage.audio_mixer import AudioMixer
from runtime.montage.video_composer import VideoComposer, ComposeConfig
from runtime.montage.quality_checker import QualityChecker, QualityReport
from runtime.montage.render_queue import RenderQueue, RenderJob

__all__ = [
    # Media Profiles
    "MediaProfile", "AspectRatio", "ALL_PROFILES",
    "get_profile", "get_profiles_for_platform", "ffmpeg_output_args",
    # TTS
    "TTSEngine", "TTSResult",
    # Subtitle
    "SubtitleEngine",
    # FFmpeg
    "FFmpegOps",
    # Audio
    "AudioMixer",
    # Video
    "VideoComposer", "ComposeConfig",
    # Quality
    "QualityChecker", "QualityReport",
    # Render Queue
    "RenderQueue", "RenderJob",
]