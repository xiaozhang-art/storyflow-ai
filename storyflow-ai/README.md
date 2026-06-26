<div align="center">

# 🎬 StoryFlow AI

**基于 LangGraph Multi-Agent 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 6 个 AI Agent 串联协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**，
最终输出可播放的 MP4 漫剧视频。

[系统架构](#系统架构) · [快速开始](#快速开始) · [API 文档](#api-接口) · [配置说明](#配置项)

</div>

---

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                  React Frontend                      │
│           (Vite + TypeScript + Ant Design 5)         │
│                                                     │
│  HomePage ──→ StoryPage (WebSocket 进度) ──→ Result  │
└─────────────────────┬───────────────────────────────┘
                      │  REST API / WebSocket
┌─────────────────────▼───────────────────────────────┐
│                 FastAPI Gateway                      │
│          (CORS · 路由 · 静态文件 · WebSocket)        │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│            LangGraph Workflow Engine                 │
│                                                     │
│  StoryState (TypedDict)  ──→  串行管线:              │
│                                                     │
│   Script Agent ──→ Character Agent ──→ Storyboard    │
│        │                      │             │       │
│        ▼                      ▼             ▼       │
│   Image Agent ──→ Voice Agent ──→ Video Agent       │
│                                                     │
│  · AsyncSqliteSaver Checkpoint (崩溃恢复)           │
│  · astream_events 实时进度追踪                      │
│  · 每个 Agent 完成后 DB 持久化中间结果               │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│                    Tool Layer                        │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐         │
│  │ ChatOpenAI│  │  ComfyUI  │  │ CosyVoice │         │
│  │ (LLM)    │  │ (SDXL)    │  │  (TTS)    │         │
│  └──────────┘  └───────────┘  └───────────┘         │
│  ┌──────────┐  ┌───────────┐                         │
│  │  FFmpeg  │  │  Qdrant   │                         │
│  │ (Video)  │  │ (Memory)  │                         │
│  └──────────┘  └───────────┘                         │
│                                                     │
│  Redis: 任务状态缓存 + PubSub 实时推送              │
│  PostgreSQL: 故事/角色/场景/任务 持久化              │
└─────────────────────────────────────────────────────┘
```

### 核心设计

- **LangGraph 串行管线** — 6 个 Agent 通过 `StateGraph` 编排，`StoryState` TypedDict 在节点间传递状态
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
| **数据库** | PostgreSQL 16 (asyncpg) | 故事 / 角色 / 场景 / 任务 |
| **缓存** | Redis 7 | 任务状态 + PubSub 实时推送 |
| **向量数据库** | Qdrant | 角色 / 剧情记忆检索 |
| **图像生成** | Stable Diffusion XL via ComfyUI API | 1024x1024, KSampler DPM++ 2M Karras |
| **语音合成** | CosyVoice TTS | 男/女声自动映射 |
| **视频合成** | FFmpeg | 图片+音频→视频→字幕烧录→拼接 |
| **部署** | Docker Compose, Nginx | 一键部署 |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                        # FastAPI 入口 (lifespan, CORS, 路由)
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── configs/
│   │   └── settings.py                # Pydantic Settings 配置中心
│   │
│   ├── prompts/                       # ⭐ 集中管理的 Prompt 模板
│   │   └── __init__.py                # Script / Character / Storyboard prompts
│   │
│   ├── models/                        # SQLAlchemy ORM
│   │   ├── base.py                    # Base + TimestampMixin
│   │   ├── story.py                   # 故事表
│   │   ├── character.py               # 角色表 (appearance JSONB)
│   │   ├── episode.py                 # 剧集表
│   │   ├── scene.py                   # 场景表 (prompt/camera/duration/dialogue/image/audio)
│   │   └── task.py                    # 任务表 (status/progress/error)
│   │
│   ├── schemas/                       # Pydantic 请求/响应
│   │   ├── story.py
│   │   ├── agent.py                   # ScriptOutput / CharacterCard / StoryboardScene
│   │   └── task.py
│   │
│   ├── api/                           # API 路由
│   │   ├── story.py                   # CRUD + 生成触发 + 结果查询
│   │   └── task.py                    # 任务状态 + WebSocket 进度
│   │
│   ├── services/
│   │   └── story_service.py           # 业务逻辑
│   │
│   ├── repositories/                  # 数据访问层
│   │   ├── story_repo.py
│   │   └── task_repo.py
│   │
│   ├── agents/                        # ⭐ 6 个 LangGraph Agent
│   │   ├── script_agent.py            # 剧本 (tenacity 3x, PydanticOutputParser)
│   │   ├── character_agent.py         # 角色视觉卡片 (AppearanceCard 结构化)
│   │   ├── storyboard_agent.py        # 分镜 (双策略: Pydantic + JSON fallback)
│   │   ├── image_agent.py             # ComfyUI (随机 seed, 逐场景重试, 部分容错)
│   │   ├── voice_agent.py             # CosyVoice (性别→音色, 部分容错)
│   │   └── video_agent.py             # FFmpeg (实际时长对齐字幕, 烧录, 拼接)
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict
│   │   └── story_workflow.py          # LangGraph 编排 + Checkpoint
│   │
│   ├── tools/                         # 外部服务客户端
│   │   ├── comfyui_client.py
│   │   ├── cosyvoice_client.py
│   │   └── ffmpeg_tool.py
│   │
│   ├── tasks/
│   │   └── runner.py                  # 后台任务运行器 (5 个 _persist_* 函数)
│   │
│   ├── app/
│   │   ├── database.py                # 异步连接池
│   │   ├── redis.py                   # Redis + PubSub
│   │   └── llm.py                     # LLM 工厂 (creative / precise)
│   │
│   ├── memory/
│   │   └── vector_store.py            # Qdrant 向量记忆
│   │
│   └── utils/
│       └── json_helper.py             # LLM JSON 解析 + 校验
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx                    # 路由 (首页 / 进度 / 结果)
│       ├── api/index.ts               # API + WebSocket (完整类型约束)
│       ├── types/index.ts             # TypeScript 类型 (与后端 Schema 对齐)
│       └── pages/
│           ├── HomePage.tsx           # 创意输入 + 历史列表
│           ├── StoryPage.tsx          # 6 步进度 + WebSocket
│           └── ResultPage.tsx         # 视频 + 剧本 + 分镜(台词/配音状态) + 角色
│
├── deploy/
│   ├── docker-compose.yml             # Postgres + Redis + Qdrant + Backend + Nginx
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
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (SDXL 模型)
  - [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) (TTS)

### 方式一：本地开发

```bash
# 1. 克隆
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 2. 配置环境变量
cp deploy/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY 和外部服务地址

# 3. 基础服务
cd deploy && docker compose up -d postgres redis qdrant && cd ..

# 4. 后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 5. 前端 (新终端)
cd frontend && npm install && npm run dev
```

| 地址 | 说明 |
|------|------|
| http://localhost:5173 | 前端界面 |
| http://localhost:8000/docs | Swagger API 文档 |
| http://localhost:8000/health | 健康检查 |

### 方式二：Docker Compose 一键部署

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai/deploy
# 编辑 .env，填入 LLM_API_KEY
docker compose up -d
# 访问 http://localhost
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事项目 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成管线 |
| `GET` | `/api/story/{id}/result` | 获取生成结果 (视频/剧本/分镜/角色) |
| `GET` | `/api/task/{id}` | 查询任务状态 |
| `WS` | `/api/task/{id}/ws` | WebSocket 实时进度 |
| `GET` | `/health` | 健康检查 |

```bash
# 创建故事
curl -X POST http://localhost:8000/api/story \
  -H "Content-Type: application/json" \
  -d '{"title":"逆袭校花","prompt":"胖子甄大卫逆袭校花莲花的故事","genre":"校园"}'

# 启动生成 (使用返回的 story_id)
curl -X POST http://localhost:8000/api/story/{story_id}/generate

# 查询进度
curl http://localhost:8000/api/task/{task_id}
```

## Agent 工作流

```
用户创意 (prompt + genre)
        │
        ▼
┌──────────────────┐
│  Script Agent    │  LLM 生成剧情大纲 + 角色设定 + 分集剧本
│  tenacity 3x 重试 │  PydanticOutputParser → ScriptOutput
│  temp=0.8        │
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Character Agent  │  丰富角色视觉描述
│  tenacity 3x 重试 │  → AppearanceCard (hair/body/cloth/face)
│  temp=0.4        │  失败时 fallback 到原始角色
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Storyboard Agent │  剧本 → 分镜
│  逐集生成         │  策略1: PydanticOutputParser (StoryboardScene)
│  tenacity 3x/集  │  策略2: JSON 解析 + 校验 (fallback)
│  temp=0.4        │  每集 5-10 场，注入角色外观
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Image Agent     │  ComfyUI 逐镜生成图片
│  随机 seed/镜    │  SDXL 1024x1024
│  2x 重试/镜      │  部分失败 → image_partial，不中断
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Voice Agent     │  CosyVoice 逐镜配音
│  性别→音色映射   │  支持 base64/URL 两种格式
│  部分容错        │  无台词场景自动跳过
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Video Agent     │  FFmpeg 合成
│                  │  1. 图片+音频 → 逐场景视频 (记录实际时长)
│                  │  2. ASS 字幕 (基于实际视频时长，非分镜估值)
│                  │  3. 字幕烧录
│                  │  4. concat 拼接 → story.mp4
└────────┬─────────┘
         ▼
    输出 MP4 漫剧
```

### 实时进度

| 步骤 | 进度 | 消息 |
|------|------|------|
| init | 0% | 初始化工作流... |
| script | 10% | 正在生成剧本... |
| character | 25% | 正在设计角色形象... |
| storyboard | 40% | 正在生成分镜... |
| image | 65% | 正在生成图片 (2/8)... |
| voice | 80% | 正在生成配音 (5/8)... |
| video | 95% | 正在合成视频... |
| done | 100% | 漫剧生成完成! |

## 数据库设计

```
story          ─── 故事项目 (title, prompt, genre, status)
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
| `DATABASE_URL` | `postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant |
| `STORAGE_PATH` | `./storage` | 文件存储 |
| `COMFYUI_POLL_TIMEOUT` | `300` | 单张图最大等待秒数 |
| `COMFYUI_MAX_RETRIES` | `2` | 单张图重试次数 |
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |

## License

MIT