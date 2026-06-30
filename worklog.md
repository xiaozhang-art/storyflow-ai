---
Task ID: 1
Agent: main
Task: 整合 OpenMontage 渲染引擎到 StoryFlow AI

Work Log:
- 克隆并分析 OpenMontage (https://github.com/calesthio/OpenMontage) 项目结构
- 识别可复用模块: TTS/Subtitle/FFmpeg/AudioMixer/VideoCompose/QualityChecker/MediaProfiles
- 设计分层解耦架构: StoryFlow 上层 + MontageAdapter 桥接 + Montage Engine 下层
- 创建 backend/runtime/montage/ 目录，包含 8 个核心文件:
  - media_profiles.py: 10 种平台预设 (YouTube/TikTok/Instagram/LinkedIn/Cinematic)
  - tts_engine.py: 5 供应商 TTS (OpenAI/ElevenLabs/Google/DashScope/Piper)
  - subtitle_engine.py: SRT/VTT 字幕生成 (词级时间轴对齐)
  - ffmpeg_ops.py: FFmpeg 操作 (转码/裁切/转场/探测/静音注入)
  - audio_mixer.py: 多轨混合 (ducking/BGM/归一化/分段配乐)
  - video_composer.py: 高级视频合成 (转场/字幕烧录/多音轨合成)
  - quality_checker.py: 7 项成片质量检测
  - render_queue.py: 批量渲染队列
- 创建 backend/runtime/montage_adapter.py: StoryFlow state ↔ Montage engine 数据桥接
- 升级 voice_agent.py: 接入 Montage TTSEngine (保留 DashScope legacy fallback)
- 升级 video_agent.py: 接入 Montage VideoComposer (保留 legacy FFmpeg fallback)
- 更新 settings.py: 添加 MONTAGE_* 配置项
- 更新 adapters/__init__.py: 新增 MontageAdapterType
- 更新 README.md: 添加 Montage Engine 架构图和配置说明
- 更新 项目介绍.md: 添加 Montage Engine 集成说明

Stage Summary:
- 新增文件: 10 个 (montage/ 8 个 + montage_adapter.py + 修改 4 个现有文件)
- 分层解耦: Montage Engine 零业务依赖，通过 MontageAdapter 单点桥接
- 原有逻辑保留为 fallback: MONTAGE_ENABLED=False 时自动降级
- 所有模块导入验证通过
