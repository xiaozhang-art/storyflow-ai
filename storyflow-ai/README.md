<div align="center">

# StoryFlow AI

**AI 漫剧自动生成平台**

输入一段创意文字，系统自动完成剧本、角色、分镜、图片、视频、配音、剪辑全流程，输出完整的 MP4 漫剧视频。

</div>

## 它是怎么工作的

StoryFlow 通过 7 个 AI Agent 串行协作，将一段文字创意转化为视频：

```
用户创意 → 剧本 → 角色 → 分镜 → 图片 → 动态视频 → 配音 → 成片
            Agent   Agent   Agent   Agent    Agent    Agent   Agent
```

每个 Agent 负责一个环节，产出作为下一个 Agent 的输入，最终由渲染引擎合成完整视频。

## 系统架构

```
┌─────────────────────────────────────────────┐
│              React Frontend                  │
│         Vite + TypeScript + Ant Design       │
└──────────────────┬──────────────────────────┘
                   │ REST / WebSocket
┌──────────────────▼──────────────────────────┐
│              FastAPI Gateway                 │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│             Runtime 核心                     │
│                                              │
│  Director ── 管线决策大脑                    │
│  WorkflowEngine ── 步骤编排与执行            │
│  AgentConversationBus ── Agent 间通信        │
│  StoryMemory ── 多维记忆系统                 │
│  EventBus ── 事件驱动解耦                    │
│  QualityEngine ── 质量门控                   │
│  RetryEngine ── 自动重试                     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│           7-Agent Pipeline                   │
│                                              │
│  Script → Character → Storyboard → Image    │
│         → Image-to-Video → Voice → Video    │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│           Montage 渲染引擎                   │
│                                              │
│  TTSEngine ── 多供应商语音合成               │
│  SubtitleEngine ── SRT/VTT 字幕生成          │
│  FFmpegOps ── 转码/裁切/转场/探测            │
│  AudioMixer ── 多轨混合/Ducking/BGM          │
│  VideoComposer ── 转场拼接/字幕烧录/成片      │
│  QualityChecker ── 7 项自动质量检测           │
│  MediaProfiles ── 平台输出预设               │
│  RenderQueue ── 批量渲染队列                 │
└──────────────────────────────────────────────┘
```

### Agent 职责

| Agent | 输入 | 输出 | 说明 |
|-------|------|------|------|
| **Script** | 用户创意 + 类型 | 大纲、角色表、分集剧本 | LLM 生成结构化剧本 |
| **Character** | 角色表 | 视觉化角色档案 | 4 维外貌描述（发型/体型/服装/面部） |
| **Storyboard** | 剧本 + 角色 | 分镜场景列表 | 每场景含镜头、时长、画面描述、台词 |
| **Image** | 分镜场景 | 场景图片 | 通义万相 / DALL-E 生成 |
| **Image-to-Video** | 场景图片 | 3-5 秒动态视频 | Kling / Runway / FFmpeg 静态回退 |
| **Voice** | 分镜台词 | 场景语音 | 5 供应商 TTS 自动选择 |
| **Video** | 视频片段 + 语音 + 字幕 | 完整 MP4 | 转场 / BGM / 字幕烧录 / 质量检测 |

### Runtime 核心

- **Director** — 每步执行后分析产出物，做出 5 种决策：继续 / 重试 / 回滚 / 改写提示词 / 跳过
- **StoryMemory** — 7 维记忆（场景/视觉/风格/世界/角色/时间线），4 层存储（工作/会话/对话/长期）
- **AgentConversationBus** — Agent 间结构化消息传递，携带角色档案、约束模板、质量反馈
- **实时进度** — Redis PubSub + WebSocket，前端 7 步进度条实时更新

### Montage 渲染引擎

从 [OpenMontage](https://github.com/calesthio/OpenMontage) 提取的纯媒体渲染组件，作为下层剪辑引擎，通过 MontageAdapter 单点桥接数据流，与 StoryFlow 业务逻辑完全解耦。

**语音合成** — OpenAI / ElevenLabs / Google / DashScope CosyVoice / Piper 本地，按可用性自动选择，无可用供应商时生成静默占位。

**视频合成流程**：探测验证 → 统一转码 → 转场拼接 → 多轨音频混合 → BGM Ducking → SRT 字幕烧录 → 7 项质量检测。

**平台预设** — YouTube (16:9/4K/Shorts)、TikTok、Instagram (Reels/Feed)、LinkedIn、Cinematic 21:9。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18, TypeScript, Vite 5, Ant Design 5 |
| 后端 | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 |
| LLM | OpenAI 兼容 API (GPT-4o / Qwen / DeepSeek)，LangChain |
| 图片生成 | DashScope 通义万相 / DALL-E 3 |
| 图生视频 | Kling / Runway |
| 语音合成 | OpenAI TTS / DashScope CosyVoice / ElevenLabs / Google / Piper |
| 视频合成 | FFmpeg + Montage VideoComposer |
| 数据库 | PostgreSQL 16 (asyncpg) |
| 缓存 | Redis 7 (PubSub) |
| 向量数据库 | Qdrant |
| 部署 | Docker Compose, Nginx |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- FFmpeg
- OpenAI 兼容 LLM API（必填，GPT-4o / Qwen / DeepSeek 等）

### 本地开发

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 配置环境变量
cp deploy/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY

# 启动基础设施
cd deploy && docker compose up -d postgres redis qdrant && cd ..

# 启动后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 启动前端（新终端）
cd frontend && npm install && npm run dev
```

### Docker Compose 一键部署

```bash
cd storyflow-ai/deploy
# 编辑 .env，填入 LLM_API_KEY
docker compose up -d
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成 |
| `GET` | `/api/story/{id}/result` | 生成结果 |
| `GET` | `/api/task/{id}` | 任务状态 |
| `WS` | `/api/task/{id}/ws` | WebSocket 实时进度 |
| `GET` | `/health` | 健康检查 |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                     # FastAPI 入口
│   ├── configs/settings.py         # 配置
│   ├── prompts/                    # LLM Prompt 模板
│   ├── models/                     # SQLAlchemy ORM
│   ├── schemas/                    # Pydantic 请求/响应
│   ├── api/                        # 路由
│   ├── services/                   # 业务逻辑
│   ├── repositories/               # 数据访问
│   ├── agents/                     # 7 个 AI Agent
│   ├── runtime/                    # Runtime 核心
│   │   ├── core.py                 # 统一入口
│   │   ├── director.py             # 管线决策
│   │   ├── workflow_engine.py      # 步骤编排
│   │   ├── agent_conversation.py   # A2A 通信
│   │   ├── montage_adapter.py      # StoryFlow ↔ 渲染引擎桥接
│   │   ├── montage/                # Montage 渲染引擎
│   │   │   ├── tts_engine.py
│   │   │   ├── subtitle_engine.py
│   │   │   ├── ffmpeg_ops.py
│   │   │   ├── audio_mixer.py
│   │   │   ├── video_composer.py
│   │   │   ├── quality_checker.py
│   │   │   ├── media_profiles.py
│   │   │   └── render_queue.py
│   │   └── memory/                 # 记忆系统
│   └── workflows/                  # 管线定义
├── frontend/src/                   # React 前端
└── deploy/                         # Docker 部署
    ├── docker-compose.yml
    └── .env.example
```

## 配置

### 必填

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | LLM API Key |
| `LLM_MODEL` | 模型名称，默认 `gpt-4o` |
| `LLM_BASE_URL` | API 地址，默认 `https://api.openai.com/v1` |

### 图片生成

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE_API_PROVIDER` | `dashscope` | 供应商：dashscope / openai / mock |
| `IMAGE_API_KEY` | — | DashScope API Key |

### 图生视频

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `I2V_API_PROVIDER` | `kling` | 供应商：kling / runway / mock |
| `I2V_API_KEY` | — | API Key |

### 语音合成

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MONTAGE_TTS_PROVIDER` | `auto` | 优先供应商：auto / openai / dashscope / elevenlabs / google / piper |
| `VOICE_API_KEY` | — | DashScope TTS API Key（DashScope 供应商时需要） |

### 视频合成

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MONTAGE_ENABLED` | `True` | 启用 Montage 渲染引擎 |
| `MONTAGE_TRANSITION` | `crossfade` | 转场类型：cut / crossfade / fade |
| `MONTAGE_TRANSITION_DURATION` | `0.5` | 转场时长（秒） |
| `MONTAGE_BURN_SUBTITLES` | `True` | 烧录字幕到视频 |
| `MONTAGE_QUALITY_CHECK` | `True` | 成片质量检测 |
| `MONTAGE_BGM_PATH` | — | BGM 文件路径 |
| `MONTAGE_MEDIA_PROFILE` | `storyflow_default` | 输出预设：youtube_landscape / tiktok / instagram_reels / cinematic 等 |

### 基础设施

| 变量 | 默认值 |
|------|--------|
| `DATABASE_URL` | `postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `QDRANT_URL` | `http://localhost:6333` |
| `STORAGE_PATH` | `./storage` |

### 生成控制

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |

## 容错机制

系统设计多层降级策略，确保在各种条件下都能产出结果：

- **TTS**：OpenAI → DashScope → ElevenLabs → Google → Piper → 静默 WAV
- **图片**：DashScope → DALL-E → Mock 占位图
- **图生视频**：Kling → Runway → FFmpeg 静态图转视频
- **视频合成**：Montage 引擎 → Legacy FFmpeg concat
- **Agent 失败**：tenacity 3 次重试 → Director 分析决策（SKIP / ROLLBACK）

## License

MIT