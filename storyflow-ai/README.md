<div align="center">

# 🎬 StoryFlow AI

**基于 Multi-Agent Workflow 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 7 个 AI Agent 串联协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 图生视频 → 配音合成 → 视频导出**，
最终输出可播放的 MP4 漫剧视频。

[系统架构](#系统架构) · [快速开始](#api-接口) · [API 文档](#api-接口) · [配置说明](#配置项)

</div>

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                          │
│              (Vite + TypeScript + Ant Design 5)              │
│                                                             │
│  HomePage ──→ StoryPage (WebSocket 进度) ──→ ResultPage     │
└─────────────────────────┬───────────────────────────────────┘
                          │  REST API / WebSocket
┌─────────────────────────▼───────────────────────────────────┐
│                   FastAPI Gateway                           │
│              (CORS · 路由 · 静态文件 · WebSocket)            │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                 V1.5 Runtime (V5.0)                         │
│                                                             │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │  Director   │  │WorkflowEngine │  │ AgentConversation │  │
│  │ (决策大脑)  │  │  (管线编排)   │  │    Bus (A2A)      │  │
│  └─────┬──────┘  └──────┬───────┘  └────────┬───────────┘  │
│        │                │                    │              │
│  ┌─────▼────────────────▼────────────────────▼───────────┐  │
│  │              StoryMemory (统一记忆)                    │  │
│  │  7 维: Scene/Visual/Style/World/Character/Timeline    │  │
│  │  4 层: Working / Session / Conversation / Long-term   │  │
│  └──────────────────────┬───────────────────────────────┘  │
│                         │                                  │
│  ┌──────────┐  ┌───────▼───────┐  ┌──────────────────┐    │
│  │Reflection │  │ PromptRuntime │  │  MemoryGraph     │    │
│  │ Runtime   │  │ (动态 Prompt) │  │(时间线角色状态)  │    │
│  └──────────┘  └───────────────┘  └──────────────────┘    │
│                                                             │
│  ModelRouter · QualityEngine · RetryEngine · TraceRuntime  │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│              Agent Pipeline (7 Agents)                      │
│  Script → Character → Storyboard → Image → I2V → Voice     │
│                                                        → Video│
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                      Adapter Layer                          │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐ │
│  │   LLM    │  │  Image    │  │  Voice    │  │   I2V    │ │
│  │(OpenAI兼容)│ │(DashScope)│  │(Montage)  │  │(Kling)  │ │
│  └──────────┘  └───────────┘  └───────────┘  └──────────┘ │
│  ┌──────────┐  ┌───────────┐  ┌───────────────────┐       │
│  │  Video   │  │  Mock    │  │  Montage Engine   │       │
│  │(Montage) │  │  降级    │  │ (OpenMontage 渲染) │       │
│  └──────────┘  └───────────┘  └───────────────────┘       │
└─────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│              Montage Engine (渲染引擎层)                     │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │TTSEngine │  │Subtitle  │  │AudioMixer│  │  Video   │   │
│  │多供应商TTS│  │Engine    │  │Ducking/  │  │Composer  │   │
│  │          │  │SRT/VTT   │  │BGM/归一化│  │转场/字幕 │   │
│  └──────────┘  └──────────┘  └──────────┘  │/音轨合成 │   │
│                                              └──────────┘   │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐     │
│  │FFmpegOps │  │ Quality  │  │   MediaProfiles      │     │
│  │转码/裁切 │  │Checker   │  │ YouTube/TikTok/...    │     │
│  │转场/探测 │  │7项检测   │  │ 10 种平台预设         │     │
│  └──────────┘  └──────────┘  └──────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### Montage Engine — OpenMontage 渲染引擎集成 ✅

从 [OpenMontage](https://github.com/calesthio/OpenMontage) 提取的纯媒体渲染组件，作为 StoryFlow 的下层剪辑引擎。**分层解耦，互不侵入** — Montage Engine 不依赖任何 StoryFlow 业务逻辑，通过 MontageAdapter 单点桥接数据流。

| 组件 | 来源 | 能力 |
|------|------|------|
| **TTSEngine** | OpenMontage tools/audio/ | 多供应商 TTS：OpenAI / ElevenLabs / Google / DashScope / Piper，自动降级 |
| **SubtitleEngine** | OpenMontage tools/subtitle/ | SRT/VTT 字幕生成，词级时间轴对齐，自动断行 |
| **FFmpegOps** | OpenMontage tools/video/ | 转码 / 裁切 / 转场(xfade) / 探测 / 静音注入 |
| **AudioMixer** | OpenMontage tools/audio/ | 多轨混合 / sidechain ducking / BGM 分段配乐 / loudnorm 归一化 |
| **VideoComposer** | OpenMontage tools/video/ | 转场拼接 + 字幕烧录 + 多音轨合成 + 统一转码 |
| **QualityChecker** | OpenMontage video_compose | 7 项自动检测：探测 / 黑帧 / 音量 / 时长 / 分辨率 / 编码 / 文件大小 |
| **MediaProfiles** | OpenMontage lib/media_profiles | 10 种平台预设：YouTube / TikTok / Instagram / LinkedIn / Cinematic |
| **RenderQueue** | StoryFlow 新增 | 批量渲染队列，优先级排序，进度跟踪 |

**升级效果：**

- **Voice Agent** — 从单一 DashScope TTS 升级为 5 供应商自动选择，优先 OpenAI TTS (gpt-4o-mini-tts)，中文场景自动选 DashScope CosyVoice
- **Video Agent** — 从基础 FFmpeg concat 升级为专业级合成：crossfade/fade-through-black 转场、SRT 字幕烧录、多轨音频 ducking、BGM 分段配乐、成片质量检测
- **原有逻辑完全保留为 fallback** — `MONTAGE_ENABLED=False` 时自动降级为原始实现

### V1.5 Runtime 三阶段升级 ✅ 已完成

V1.5 Runtime 已完成全部三阶段升级，所有架构变更均为 Runtime 层面，**未新增任何业务 Agent**，原有 7 个 Agent 保持不变。

#### Phase 1: Director Brain — LLM 驱动的管线决策 ✅

Director 重写为真正的"决策大脑"，读取 **全部管线产出物** (ArtifactManager)，通过 LLM 分析做出 5 种智能决策：

| 决策 | 动作 |
|------|------|
| `PROCEED` | 继续下一步 |
| `RETRY` | 重试当前步骤（含重试上下文） |
| `ROLLBACK` | 移除产出物 + 重置管线索引 |
| `REWRITE_PROMPT` | 用 LLM 重写当前步骤 prompt 后重试 |
| `SKIP` | 跳过当前步骤 |

#### Phase 2: A2A 富上下文传递 ✅

AgentConversationBus 升级为结构化富上下文（非纯文本摘要），A2A 消息携带：角色档案、场景数据、生成统计、产出物引用、约束模板、质量反馈。

#### Phase 3: StoryMemory 统一记忆系统 ✅

全新 7 维记忆架构（Scene/Visual/Style/World + Character/Timeline），4 层记忆层级（Working / Session / Conversation / Long-term）支持 TTL 自动过期。

### 核心设计

- **Director 5-决策循环** — 每步执行后 Director 分析全部产出物，做出 PROCEED/RETRY/ROLLBACK/REWRITE_PROMPT/SKIP 决策
- **A2A 结构化消息** — Agent 间通过携带角色档案、场景数据、约束模板、质量反馈的结构化消息通信
- **Montage 渲染引擎** — 专业级视频合成：转场 / ducking / BGM / 字幕 / 质量检测
- **实时进度推送** — Redis PubSub + WebSocket，前端 7 步进度条实时更新
- **容错与降级** — 多层降级：Montage → Legacy FFmpeg → Mock
- **自动重试** — Script/Character/Storyboard Agent 使用 tenacity 3x；Director 持久性失败 2x 后 SKIP
- **LLM 工厂模式** — `get_creative_llm()` / `get_precise_llm()` 按场景选用

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18, TypeScript, Vite 5, Ant Design 5, Axios | SPA，3 页面 |
| **后端** | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 | 异步全栈 |
| **Agent 框架** | LangChain, ChatOpenAI | 7-Agent 串行管线 |
| **Runtime** | Agent OS Runtime V5.0 | Director / A2A / StoryMemory / Reflection / PromptRuntime / MemoryGraph / ModelRouter |
| **渲染引擎** | Montage Engine (OpenMontage) | TTSEngine / SubtitleEngine / FFmpegOps / AudioMixer / VideoComposer / QualityChecker |
| **数据库** | PostgreSQL 16 (asyncpg) | 故事 / 角色 / 场景 / 任务 |
| **缓存** | Redis 7 | 任务状态 + PubSub |
| **向量数据库** | Qdrant | 角色记忆检索 |
| **LLM** | OpenAI 兼容 API (GPT-4o/Qwen/DeepSeek) | 多供应商路由 |
| **图像生成** | DashScope (通义万相) / DALL-E 3 | ComfyUI (SDXL) 可选回退 |
| **语音合成** | OpenAI TTS / DashScope TTS / ElevenLabs / Google / Piper | Montage TTSEngine 自动选择 |
| **图生视频** | Kling / Runway | 3-5 秒动态视频 |
| **视频合成** | FFmpeg + Montage VideoComposer | 转场 / 字幕 / ducking / BGM / 质量检测 |
| **部署** | Docker Compose, Nginx | 一键部署 |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                        # FastAPI 入口
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── configs/
│   │   └── settings.py                # Pydantic Settings (含 Montage 配置)
│   │
│   ├── prompts/                       # Prompt 模板
│   │
│   ├── models/                        # SQLAlchemy ORM
│   ├── schemas/                       # Pydantic schemas
│   ├── api/                           # FastAPI routers
│   ├── services/                      # Business logic
│   ├── repositories/                  # Data access
│   │
│   ├── agents/                        # ⭐ 7 个 AI Agent
│   │   ├── script_agent.py
│   │   ├── character_agent.py
│   │   ├── storyboard_agent.py
│   │   ├── image_agent.py
│   │   ├── image_to_video_agent.py
│   │   ├── voice_agent.py             # ✅ 升级: Montage TTSEngine (多供应商)
│   │   └── video_agent.py             # ✅ 升级: Montage VideoComposer (转场/字幕/BGM)
│   │
│   ├── workflows/
│   ├── tools/
│   ├── tasks/
│   ├── app/
│   ├── memory/
│   ├── utils/
│   ├── skills/
│   │
│   └── runtime/                       # ⭐ V1.5 Runtime (V5.0)
│       ├── core.py
│       ├── director.py
│       ├── workflow_engine.py
│       ├── agent_conversation.py
│       ├── prompt_runtime.py
│       ├── adapters/__init__.py       # ✅ 新增 MontageAdapterType
│       ├── montage_adapter.py         # ⭐ StoryFlow ↔ Montage 数据桥接
│       ├── montage/                   # ⭐ Montage Engine (OpenMontage 渲染引擎)
│       │   ├── __init__.py
│       │   ├── tts_engine.py          # 多供应商 TTS
│       │   ├── subtitle_engine.py     # SRT/VTT 字幕
│       │   ├── ffmpeg_ops.py          # FFmpeg 操作
│       │   ├── audio_mixer.py         # 音频混合
│       │   ├── video_composer.py      # 视频合成
│       │   ├── quality_checker.py     # 质量检测
│       │   ├── media_profiles.py      # 平台预设
│       │   └── render_queue.py        # 批量渲染
│       ├── memory/
│       └── ...
│
├── frontend/
│   └── src/
│       ├── pages/
│       ├── api/
│       └── types/
│
└── deploy/
    ├── docker-compose.yml
    └── .env.example
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- FFmpeg
- **外部 API**（远程服务）：
  - OpenAI 兼容 LLM API（GPT-4o / Qwen / DeepSeek 等）— **必填**
  - DashScope API（图片生成 + TTS）— 推荐
  - Kling / Runway API（图生视频）— 推荐
  - ComfyUI (SDXL) — 可选本地回退

### 方式一：本地开发

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 配置
cp deploy/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY 等

# 基础服务
cd deploy && docker compose up -d postgres redis qdrant && cd ..

# 后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端 (新终端)
cd frontend && npm install && npm run dev
```

### 方式二：Docker Compose

```bash
cd storyflow-ai/deploy
# 编辑 .env，填入 LLM_API_KEY
docker compose up -d
# 访问 http://localhost
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成 |
| `GET` | `/api/story/{id}/result` | 生成结果 |
| `GET` | `/api/task/{id}` | 任务状态 |
| `WS` | `/api/task/{id}/ws` | WebSocket 进度 |
| `GET` | `/api/runtime/stats` | Runtime 统计 |
| `GET` | `/health` | 健康检查 |

## 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | LLM API Key (**必填**) |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `IMAGE_API_PROVIDER` | `dashscope` | 图片生成供应商 |
| `IMAGE_API_KEY` | — | DashScope API Key |
| `I2V_API_PROVIDER` | `kling` | 图生视频供应商 |
| `I2V_API_KEY` | — | Kling API Key |
| `VOICE_API_PROVIDER` | `dashscope_tts` | TTS 供应商 (legacy) |
| `VOICE_API_KEY` | — | DashScope TTS API Key |
| **Montage 引擎** | | |
| `MONTAGE_ENABLED` | `True` | 启用 Montage 渲染引擎 |
| `MONTAGE_TTS_PROVIDER` | `auto` | TTS 优先供应商 |
| `MONTAGE_TRANSITION` | `crossfade` | 镜头转场类型 |
| `MONTAGE_TRANSITION_DURATION` | `0.5` | 转场时长 (秒) |
| `MONTAGE_BURN_SUBTITLES` | `True` | 烧录字幕 |
| `MONTAGE_QUALITY_CHECK` | `True` | 成片质量检测 |
| `MONTAGE_BGM_PATH` | `""` | BGM 文件路径 |
| `MONTAGE_MEDIA_PROFILE` | `storyflow_default` | 输出平台预设 |
| **基础设施** | | |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant |
| `STORAGE_PATH` | `./storage` | 文件存储 |
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |

## License

MIT