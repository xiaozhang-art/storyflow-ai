<div align="center">

# 🎬 StoryFlow AI

**基于 Multi-Agent Workflow 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 6 个 AI Agent 串联协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**，
最终输出可播放的 MP4 漫剧视频。

[系统架构](#系统架构) · [快速开始](#快速开始) · [API 文档](#api-接口) · [配置说明](#配置项)

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
          ┌───────────────┴───────────────┐
          ▼                               ▼
┌─────────────────────┐       ┌──────────────────────┐
│  LangGraph Pipeline  │       │  Agent OS Runtime    │
│     (v1.0 默认)      │       │    (v2.0 可选)       │
│                      │       │                      │
│  Script Agent        │       │  Hook · Memory       │
│    ↓                 │       │  Skill · Session     │
│  Character Agent     │       │  A2A · Scheduler     │
│    ↓                 │       │  Langfuse 可观测性   │
│  Storyboard Agent    │       └──────────────────────┘
│    ↓                 │
│  Image Agent         │       ┌──────────────────────┐
│    ↓                 │       │  LangGraph           │
│  Voice Agent         │       │  Checkpointing       │
│    ↓                 │       │  (SQLite 崩溃恢复)    │
│  Video Agent         │       └──────────────────────┘
└─────────┬───────────┘
          │
┌─────────▼───────────────────────────────────────────────────┐
│                      Tool Layer                             │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐ │
│  │ ChatOpenAI│  │  ComfyUI  │  │ CosyVoice │  │  FFmpeg  │ │
│  │ (LLM)    │  │ (SDXL)    │  │  (TTS)    │  │ (Video)  │ │
│  └──────────┘  └───────────┘  └───────────┘  └──────────┘ │
│  ┌──────────┐  ┌───────────┐                               │
│  │  Qdrant  │  │  Redis    │  (PubSub 推送 + 任务状态)     │
│  │ (Memory) │  │           │                               │
│  └──────────┘  └───────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

### 双后端引擎

| | LangGraph Pipeline (v1.0) | Agent OS Runtime (v2.0) |
|--|--|--|
| **触发方式** | 默认 | `USE_RUNTIME=true` |
| **编排** | `StateGraph` + `StoryState` | `RuntimeWorkflowRunner` + `ConversationManager` |
| **可观测性** | 日志 + DB 持久化 | Hook (BEFORE_AGENT / AFTER_AGENT / ON_ERROR) |
| **记忆** | Qdrant 向量库 | 4 层 Memory (working / session / long-term / episodic) |
| **通信** | 状态字典传递 | MCP Envelope + A2A Message Bus (memory / Redis Stream) |
| **技能** | 硬编码 | Skill Engine (注册 / 选择 / 校验 / 执行) |
| **会话** | 无 | Session Manager (状态管理 + 超时) |
| **追踪** | 无 | Langfuse Handler (配置即启用) |
| **调度** | LangGraph executor | Execution Scheduler (LLM / Tool / GPU 线程池) |

默认使用 LangGraph 管线，可通过环境变量 `USE_RUNTIME=true` 切换到 Agent OS Runtime。Runtime 会自动将现有 6 个 Agent 通过 `wrap_legacy_agent()` 适配器包装，无需重写 Agent 代码即可获得 Hook / Memory / Skill / A2A 能力。Runtime 初始化失败时自动 fallback 回 LangGraph。

### 核心设计

- **实时进度推送** — Redis PubSub + WebSocket，前端 6 步进度条实时更新
- **数据库持久化** — 每个 Agent 完成后立即写入 PostgreSQL（5 个 `_persist_*` 函数），中间结果不丢失
- **崩溃恢复** — LangGraph `AsyncSqliteSaver` Checkpoint，进程重启后从断点续跑
- **容错与降级** — 图片/配音/视频 Agent 按场景粒度 try/catch，部分失败不中断整体流程
- **自动重试** — Script/Character/Storyboard Agent 使用 tenacity 3 次指数退避重试；Image Agent 每张图最多 2 次重试
- **LLM 工厂模式** — `get_creative_llm()` (temp=0.8) / `get_precise_llm()` (temp=0.4) 按场景选用，实例缓存复用
- **结构化输出** — Script/Character Agent 用 `PydanticOutputParser`；Storyboard Agent 双策略（Pydantic 优先 + JSON fallback）
- **Prompt 外部化** — 所有 Agent Prompt 集中在 `prompts/` 模块，与 Agent 逻辑解耦

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18, TypeScript, Vite 5, Ant Design 5, Axios | SPA，3 页面 |
| **后端** | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 | 异步全栈 |
| **Agent 框架** | LangGraph, LangChain, ChatOpenAI | 6-Agent 串行管线 |
| **Runtime (v2)** | Agent OS Runtime | Hook / Memory / Skill / Session / A2A / Langfuse |
| **数据库** | PostgreSQL 16 (asyncpg) | 故事 / 角色 / 场景 / 任务 |
| **缓存** | Redis 7 | 任务状态 + PubSub + A2A 传输 |
| **向量数据库** | Qdrant | 角色 / 剧情记忆检索 |
| **图像生成** | Stable Diffusion XL via ComfyUI API | 1024x1024, KSampler DPM++ 2M Karras |
| **语音合成** | CosyVoice TTS | 男/女声自动映射 |
| **视频合成** | FFmpeg | 图片+音频→视频→字幕烧录→拼接 |
| **部署** | Docker Compose, Nginx | 一键部署 |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                        # FastAPI 入口 (Runtime 初始化 + CORS + 路由)
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── configs/
│   │   └── settings.py                # Pydantic Settings (含 Runtime 参数)
│   │
│   ├── prompts/                       # ⭐ 集中管理的 Prompt 模板
│   │   └── __init__.py                # Script / Character / Storyboard prompts
│   │
│   ├── models/                        # SQLAlchemy ORM
│   │   ├── base.py
│   │   ├── story.py
│   │   ├── character.py
│   │   ├── episode.py
│   │   ├── scene.py                   # (prompt/camera/duration/dialogue/image/audio)
│   │   └── task.py
│   │
│   ├── schemas/
│   │   ├── story.py
│   │   ├── agent.py
│   │   └── task.py
│   │
│   ├── api/
│   │   ├── story.py
│   │   └── task.py
│   │
│   ├── services/
│   │   └── story_service.py
│   │
│   ├── repositories/
│   │   ├── story_repo.py
│   │   └── task_repo.py
│   │
│   ├── agents/                        # ⭐ 6 个 LangGraph Agent
│   │   ├── script_agent.py            # 剧本 (tenacity 3x, PydanticOutputParser)
│   │   ├── character_agent.py         # 角色视觉卡片 (AppearanceCard 强类型)
│   │   ├── storyboard_agent.py        # 分镜 (双策略: Pydantic + JSON fallback)
│   │   ├── image_agent.py             # ComfyUI (随机 seed, 逐场景重试, 部分容错)
│   │   ├── voice_agent.py             # CosyVoice (性别→音色, 部分容错)
│   │   └── video_agent.py             # FFmpeg (实际时长对齐字幕, 烧录, 拼接)
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict
│   │   ├── story_workflow.py          # LangGraph 编排 + Checkpoint
│   │   └── runtime_workflow.py        # Agent OS Runtime 适配层
│   │
│   ├── tools/
│   │   ├── comfyui_client.py
│   │   ├── cosyvoice_client.py
│   │   └── ffmpeg_tool.py
│   │
│   ├── tasks/
│   │   └── runner.py                  # 双后端任务运行器 (5 个 _persist_* 函数)
│   │
│   ├── app/
│   │   ├── database.py
│   │   ├── redis.py
│   │   └── llm.py                     # LLM 工厂 (creative / precise)
│   │
│   ├── memory/
│   │   └── vector_store.py            # Qdrant 向量记忆
│   │
│   ├── utils/
│   │   └── json_helper.py
│   │
│   └── runtime/                       # ⭐ Agent OS Runtime (v2.0)
│       ├── app.py                     # RuntimeApp 入口 (初始化 + 组装)
│       ├── adapter.py                 # Legacy Agent → Runtime 适配器
│       ├── agent_runtime/             # Agent 运行时上下文
│       ├── execution/                 # 调度器 (LLM/Tool/GPU 线程池)
│       ├── conversation/              # 对话管理 (线性管线编排)
│       ├── skill_engine/              # 技能注册/选择/校验/执行
│       ├── memory/                    # 4 层记忆管理
│       ├── session/                   # 会话管理 (超时/恢复)
│       ├── hook/                      # 事件钩子 (BEFORE/AFTER/ON_ERROR)
│       ├── handlers/                  # 日志 / Langfuse 追踪
│       ├── mcp/                       # MCP 协议 (Envelope/Router/Validator)
│       └── message_bus/               # A2A 通信 (InMemory/Redis Stream)
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── api/index.ts               # API + WebSocket (完整类型约束)
│       ├── types/index.ts             # TypeScript 类型 (与后端对齐)
│       └── pages/
│           ├── HomePage.tsx           # 创意输入 + 历史列表
│           ├── StoryPage.tsx          # 6 步进度 + WebSocket
│           └── ResultPage.tsx         # 视频 + 剧本 + 分镜 + 角色
│
├── deploy/
│   ├── docker-compose.yml
│   ├── nginx/default.conf
│   ├── init.sql
│   └── .env.example
│
└── scripts/
    └── init_db.py
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- FFmpeg
- **外部依赖**（自行部署或使用远程服务）：
  - OpenAI 兼容 LLM API（GPT-4o / Qwen / DeepSeek 等）
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (SDXL)
  - [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) (TTS)

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

| 地址 | 说明 |
|------|------|
| http://localhost:5173 | 前端 |
| http://localhost:8000/docs | Swagger API |
| http://localhost:8000/health | 健康检查 |

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

```bash
# 创建并生成
curl -X POST http://localhost:8000/api/story \
  -H "Content-Type: application/json" \
  -d '{"title":"逆袭校花","prompt":"胖子甄大卫逆袭校花莲花的故事","genre":"校园"}'
curl -X POST http://localhost:8000/api/story/{story_id}/generate
curl http://localhost:8000/api/task/{task_id}
```

## Agent 工作流

```
用户创意 (prompt + genre)
        │
        ▼
┌──────────────────┐
│  Script Agent    │  LLM → 剧情大纲 + 角色设定 + 分集剧本
│  temp=0.8        │  PydanticOutputParser → ScriptOutput
│  tenacity 3x     │
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Character Agent  │  丰富角色视觉描述
│  temp=0.4        │  → AppearanceCard (hair/body/cloth/face)
│  tenacity 3x     │  失败 fallback 原始角色
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Storyboard Agent │  剧本 → 分镜 (逐集)
│  temp=0.4        │  策略1: PydanticOutputParser
│  tenacity 3x/集  │  策略2: JSON 解析 fallback
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Image Agent     │  ComfyUI 逐镜生成
│  随机 seed/镜    │  SDXL 1024x1024
│  2x 重试/镜      │  部分失败 → image_partial
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Voice Agent     │  CosyVoice 逐镜配音
│  性别→音色映射   │  base64/URL 双格式
│  部分容错        │
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Video Agent     │  FFmpeg 合成
│                  │  1. 图片+音频 → 逐场景视频 (记录实际时长)
│                  │  2. ASS 字幕 (基于实际视频时长)
│                  │  3. 字幕烧录 → concat 拼接 → story.mp4
└──────────────────┘
```

## 数据库设计

```
story          ─── 故事 (title, prompt, genre, status)
  ├─ character ─── 角色 (name, gender, age, appearance JSONB, personality JSONB)
  ├─ episode   ─── 剧集 (episode_no, title, summary, script)
  └─ scene     ─── 场景 (scene_no, prompt, camera, duration, dialogue, image_url, audio_url)
task           ─── 任务 (status, progress, current_step, error_message)
```

## 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | LLM API Key (**必填**) |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `LLM_TEMPERATURE` | `0.7` | 默认温度 |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI |
| `COSYVOICE_URL` | `http://localhost:50000` | CosyVoice |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant |
| `STORAGE_PATH` | `./storage` | 文件存储 |
| `USE_RUNTIME` | `false` | 设为 `true` 启用 Agent OS Runtime |
| `COMFYUI_POLL_TIMEOUT` | `300` | 单张图最大等待秒数 |
| `COMFYUI_MAX_RETRIES` | `2` | 单张图重试次数 |
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |

### Runtime v2.0 额外配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse 公钥 |
| `LANGFUSE_SECRET_KEY` | — | Langfuse 密钥 |
| `A2A_TRANSPORT` | `memory` | Agent 通信 (`memory` / `redis`) |
| `LLM_WORKER_CONCURRENCY` | `10` | LLM 并发数 |
| `GPU_WORKER_CONCURRENCY` | `2` | GPU 并发数 |
| `SESSION_IDLE_TIMEOUT` | `86400` | 会话超时 (秒) |
| `MEMORY_WORKING_TTL` | `300` | 工作记忆 TTL (秒) |

## License

MIT