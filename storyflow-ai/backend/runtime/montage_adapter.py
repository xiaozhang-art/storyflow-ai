"""Montage Adapter — StoryFlow state ↔ Montage engine 数据桥接.

这是 StoryFlow 上层和 Montage 下层之间的唯一桥梁。
负责：
1. 将 StoryFlow pipeline state 转换为 Montage 引擎输入格式
2. 将 Montage 引擎输出转换回 StoryFlow state 格式
3. 统一配置管理（从 Settings 读取 API key 等）
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MontageAdapter:
    """StoryFlow ↔ Montage 数据适配器.

    Usage:
        adapter = MontageAdapter()
        tts_results = adapter.generate_voices(state)  # StoryFlow state → Montage TTS
        video_result = adapter.compose_video(state)     # StoryFlow state → Montage VideoComposer
    """

    def __init__(self):
        self._tts_engine = None
        self._subtitle_engine = None
        self._audio_mixer = None
        self._video_composer = None

    # ---- 初始化 ----

    def _get_tts_engine(self):
        """延迟初始化 TTS 引擎（读取 Settings 配置）."""
        if self._tts_engine is None:
            from configs.settings import settings
            from runtime.montage.tts_engine import TTSEngine

            self._tts_engine = TTSEngine(
                preferred_provider=getattr(settings, "MONTAGE_TTS_PROVIDER", "auto"),
                allowed_providers=getattr(settings, "MONTAGE_TTS_PROVIDERS", None),
                openai_api_key=settings.LLM_API_KEY,  # Reuse LLM key for OpenAI TTS
                openai_base_url=settings.LLM_BASE_URL,
                dashscope_api_key=settings.VOICE_API_KEY,
                dashscope_base_url=settings.VOICE_API_BASE_URL,
                dashscope_model=settings.VOICE_MODEL,
                dashscope_sample_rate=settings.VOICE_SAMPLE_RATE,
            )
        return self._tts_engine

    def _get_subtitle_engine(self):
        if self._subtitle_engine is None:
            from runtime.montage.subtitle_engine import SubtitleEngine
            self._subtitle_engine = SubtitleEngine()
        return self._subtitle_engine

    def _get_audio_mixer(self):
        if self._audio_mixer is None:
            from runtime.montage.audio_mixer import AudioMixer
            self._audio_mixer = AudioMixer()
        return self._audio_mixer

    def _get_video_composer(self):
        if self._video_composer is None:
            from runtime.montage.video_composer import VideoComposer
            self._video_composer = VideoComposer()
        return self._video_composer

    # ---- Voice: StoryFlow state → Montage TTS ----

    def generate_voices(self, state: dict) -> list[dict]:
        """用 Montage TTS 引擎为所有场景生成语音.

        Args:
            state: StoryFlow pipeline state，需包含:
                - story_id
                - storyboard: [{scene_no, dialogue, characters}, ...]
                - characters: [{name, gender}, ...]

        Returns:
            与 voice_agent 兼容的 audios 列表
        """
        from configs.settings import settings

        story_id = state.get("story_id", "unknown")
        storyboard = state.get("storyboard", [])
        characters = state.get("characters", [])

        save_dir = Path(settings.STORAGE_PATH) / "stories" / story_id / "audio"
        save_dir.mkdir(parents=True, exist_ok=True)

        engine = self._get_tts_engine()
        audios: list[dict] = []

        for scene in storyboard:
            scene_no = scene.get("scene_no", 0)
            dialogue = scene.get("dialogue", "")
            if not dialogue.strip():
                continue

            # Determine gender
            gender = "female"
            scene_chars = scene.get("characters", [])
            if scene_chars:
                for char in characters:
                    if char.get("name") == scene_chars[0]:
                        g = char.get("gender", "")
                        if g in ("男", "male", "男性"):
                            gender = "male"
                        break

            output_path = str(save_dir / f"scene_{scene_no}.mp3")

            result = engine.generate(
                text=dialogue,
                output_path=output_path,
                gender=gender,
            )

            audios.append({
                "scene_no": scene_no,
                "audio_path": result.output_path,
                "audio_url": f"/storage/stories/{story_id}/audio/scene_{scene_no}.mp3",
                "speaker": gender,
                "text": dialogue,
                "provider": result.provider,
                "audio_duration": result.audio_duration_seconds,
            })

            logger.info(
                "MontageAdapter: voice for scene %d via %s (%s)",
                scene_no, result.provider,
                f"{result.audio_duration_seconds:.1f}s" if result.audio_duration_seconds else "unknown dur",
            )

        return audios

    # ---- Subtitle: StoryFlow state → Montage SubtitleEngine ----

    def generate_subtitles(
        self,
        state: dict,
        output_path: str = "",
        fmt: str = "srt",
    ) -> str:
        """从 StoryFlow state 生成字幕文件.

        Args:
            state: 需包含 storyboard + audios（含 audio_duration）
            output_path: 输出路径
            fmt: "srt" / "vtt"

        Returns:
            字幕文件路径
        """
        from configs.settings import settings

        story_id = state.get("story_id", "unknown")
        storyboard = state.get("storyboard", [])
        audios = state.get("audios", [])

        if not output_path:
            output_path = str(
                Path(settings.STORAGE_PATH) / "stories" / story_id / "subtitles.srt"
            )

        # Build dialogue list with durations
        audio_durations: dict[int, float] = {}
        for a in audios:
            if a.get("audio_duration"):
                audio_durations[a["scene_no"]] = a["audio_duration"]
            elif a.get("audio_path"):
                from runtime.montage.ffmpeg_ops import FFmpegOps
                audio_durations[a["scene_no"]] = FFmpegOps.get_duration(a["audio_path"])

        # Fallback to storyboard duration
        for scene in storyboard:
            sn = scene.get("scene_no", 0)
            if sn not in audio_durations:
                audio_durations[sn] = float(scene.get("duration", 5.0))

        engine = self._get_subtitle_engine()
        return engine.generate_from_dialogues(
            dialogues=storyboard,
            audio_durations=audio_durations,
            output_path=output_path,
            fmt=fmt,
        )

    # ---- Audio: StoryFlow state → Montage AudioMixer ----

    def mix_audio(
        self,
        state: dict,
        bgm_path: str = "",
        output_path: str = "",
        ducking: Optional[dict] = None,
    ) -> dict[str, Any]:
        """混合语音 + BGM.

        Args:
            state: 需包含 audios 列表
            bgm_path: BGM 文件路径
            output_path: 输出路径
            ducking: ducking 参数

        Returns:
            {output, speech_tracks, music_tracks, ...}
        """
        from configs.settings import settings

        story_id = state.get("story_id", "unknown")
        audios = state.get("audios", [])

        if not output_path:
            output_path = str(
                Path(settings.STORAGE_PATH) / "stories" / story_id / "mixed_audio.wav"
            )

        if not audios:
            return {"output": "", "error": "No audio tracks"}

        # Build speech tracks with cumulative start time
        tracks: list[dict[str, Any]] = []
        cumulative = 0.0
        for a in audios:
            if a.get("audio_path") and Path(a["audio_path"]).exists():
                tracks.append({
                    "path": a["audio_path"],
                    "role": "speech",
                    "start_seconds": cumulative,
                    "fade_in_seconds": 0.1,
                    "fade_out_seconds": 0.1,
                })
                # Use actual duration or estimate
                dur = a.get("audio_duration") or 5.0
                cumulative += dur

        # Add BGM
        if bgm_path and Path(bgm_path).exists():
            tracks.append({
                "path": bgm_path,
                "role": "music",
                "volume": 0.2,
            })

        if not tracks:
            return {"output": "", "error": "No valid audio files"}

        mixer = self._get_audio_mixer()
        return mixer.full_mix(
            tracks=tracks,
            output_path=output_path,
            ducking=ducking or {"enabled": bool(bgm_path)},
            normalize=True,
        )

    # ---- Video: StoryFlow state → Montage VideoComposer ----

    def compose_video(
        self,
        state: dict,
        transition: str = "crossfade",
        transition_duration: float = 0.5,
        bgm_path: str = "",
        burn_subtitles: bool = True,
        run_quality_check: bool = True,
    ) -> dict[str, Any]:
        """合成最终视频（完整流程）.

        完整流程：
        1. 生成 SRT 字幕
        2. 混合语音（多轨 + ducking）
        3. 合成视频（转场 + 字幕烧录 + 音频合成）

        Args:
            state: 完整的 StoryFlow pipeline state
            transition: 转场类型
            transition_duration: 转场时长
            bgm_path: BGM 路径
            burn_subtitles: 是否烧录字幕
            run_quality_check: 是否运行质量检测

        Returns:
            {output, duration, method, quality_report?}
        """
        from configs.settings import settings

        story_id = state.get("story_id", "unknown")
        video_clips = state.get("video_clips", [])
        images = state.get("images", [])
        storyboard = state.get("storyboard", [])
        audios = state.get("audios", [])

        story_dir = Path(settings.STORAGE_PATH) / "stories" / story_id
        output_dir = story_dir / "video"
        output_dir.mkdir(parents=True, exist_ok=True)
        final_path = str(output_dir / "story.mp4")

        # Determine clip sources
        clips: list[str] = []
        if video_clips:
            clips = [c.get("video_path", "") for c in video_clips if c.get("video_path")]
        elif images:
            # Legacy: images → videos
            from runtime.montage.ffmpeg_ops import FFmpegOps
            scenes_dir = story_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            audio_map = {a["scene_no"]: a for a in audios}

            for scene in storyboard:
                scene_no = scene.get("scene_no", 0)
                img_info = next((i for i in images if i.get("scene_no") == scene_no), None)
                if not img_info:
                    continue

                audio_path = audio_map.get(scene_no, {}).get("audio_path")
                scene_video = str(scenes_dir / f"scene_{scene_no}.mp4")
                duration = scene.get("duration", 5)

                try:
                    FFmpegOps.image_to_video(
                        img_info.get("image_path", ""),
                        scene_video,
                        duration=duration,
                        audio_path=audio_path,
                    )
                    clips.append(scene_video)
                except Exception as e:
                    logger.error("image_to_video failed for scene %d: %s", scene_no, e)

        if not clips:
            return {"output": "", "status": "error", "error": "No video clips or images."}

        # Step 1: Generate subtitles
        subtitle_path = ""
        if burn_subtitles:
            try:
                subtitle_path = self.generate_subtitles(state, fmt="srt")
                logger.info("MontageAdapter: subtitles generated at %s", subtitle_path)
            except Exception as e:
                logger.warning("MontageAdapter: subtitle generation failed: %s", e)

        # Step 2: Mix audio
        mixed_audio_path = ""
        if audios:
            try:
                mix_result = self.mix_audio(state, bgm_path=bgm_path)
                mixed_audio_path = mix_result.get("output", "")
                logger.info("MontageAdapter: audio mixed at %s", mixed_audio_path)
            except Exception as e:
                logger.warning("MontageAdapter: audio mix failed: %s", e)

        # Step 3: Compose video
        from runtime.montage.video_composer import VideoComposer, ComposeConfig

        config = ComposeConfig(
            output_path=final_path,
            profile="storyflow_default",
            transition=transition,
            transition_duration=transition_duration,
            mixed_audio_path=mixed_audio_path,
            subtitle_path=subtitle_path,
            burn_subtitles=burn_subtitles,
            bgm_path=bgm_path if not mixed_audio_path else "",  # Already in mixed audio
            ducking={"enabled": bool(bgm_path) and bool(mixed_audio_path)},
            run_quality_check=run_quality_check,
        )

        composer = self._get_video_composer()
        result = composer.compose(clips, config)

        video_url = f"/storage/stories/{story_id}/video/story.mp4"
        result["video_url"] = video_url
        result["status"] = "video_done" if Path(final_path).exists() else "error"

        return result

    # ---- Info ----

    def get_tts_info(self) -> dict[str, Any]:
        """获取 TTS 引擎状态."""
        return self._get_tts_engine().get_info()

    def health_check(self) -> dict[str, bool]:
        """检查 montage 引擎健康状态."""
        import shutil
        return {
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None,
            "tts": len(self._get_tts_engine().list_available()) > 0,
            "tts_providers": self._get_tts_engine().list_available(),
        }