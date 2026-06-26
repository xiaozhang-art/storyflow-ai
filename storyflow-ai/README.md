# StoryFlow AI

基于 Multi-Agent Workflow 的 AI 漫剧自动生成平台。

用户输入一段创意，系统通过 6 个 AI Agent 串联协作，自动完成 **剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**，最终输出可播放的 MP4 漫剧视频。

## 系统架构

```
┌─────────────────────────────────────────────────┐
│                  React Frontend                  │
│         (Vite + TypeScript + Ant Design)          │
└──────────────────────┬──────────────────────────┘
                       │  REST API / WebSocket
┌──────────────────────▼──────────────────────────┐
│                 FastAPI Gateway                   │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│              LangGraph Workflow Engine             │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐      │
│  │ Script   │→│Character  │→│ Storyboard   │      │
│  │ Agent    │ │ Agent    │ │ Agent        │      │
│  └─────────┘ └──────────┘ └──────────────┘      │
│  ┌─────────┐ ┌──────────┐ ┌──────────────┐      │
│  │ Image   │←│ Voice    │←│ (continues)  │      │
│  │ Agent   │ │ Agent    │ │              │      │
│  └────┬────┘ └──────────┘ └──────────────┘      │
│       ▼                                          │
│  ┌──────────┐                                     │
│  │  Video   │                                     │
│  │  Agent   │                                     │
│  └──────────┘                                     │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│                   Tool Layer                      │
│  ┌──────────┐ ┌───────────┐ ┌───────────────┐   │
│  │ ChatOpenAI│ │  ComfyUI  │ │  CosyVoice    │   │
│  │ (LLM)    │ │ (SDXL)    │ │  (TTS)        │   │
│  └──────────┘ └───────────┘ └───────────────┘   │
│  ┌──────────┐ ┌───────────┐                      │
│  │  FFmpeg  │ │  Qdrant   │                      │
│  │ (Video)  │ │ (Memory)  │                      │
│  └──────────┘ └───────────┘                      │
└─────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18, TypeScript, Vite 5, Ant Design 5, Axios |
| **后端** | Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic 2.0 |
| **Agent 框架** | LangGraph, LangChain, ChatOpenAI |
| **数据库** | PostgreSQL 16 (asyncpg) |
| **缓存** | Redis 7 (任务状态 + PubSub 推送) |
| **向量数据库** | Qdrant (角色/剧情记忆) |
| **图像生成** | Stable Diffusion XL (通过 ComfyUI API) |
| **语音合成** | CosyVoice (TTS) |
| **视频合成** | FFmpeg (图片+音频→视频→拼接+字幕) |
| **部署** | Docker Compose, Nginx |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                    # FastAPI 应用入口
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── configs/
│   │   └── settings.py            # Pydantic Settings 配置中心
│   ├── models/                    # SQLAlchemy ORM 模型
│   │   ├── base.py                # Base + TimestampMixin
│   │   ├── story.py               # 故事表
│   │   ├── character.py           # 角色表
│   │   ├── episode.py             # 剧集表
│   │   ├── scene.py               # 场景/分镜表
│   │   └── task.py                # 任务表
│   ├── schemas/                   # Pydantic 请求/响应模型
│   │   ├── story.py
│   │   ├── agent.py               # Agent 输入输出结构
│   │   └── task.py
│   ├── api/                       # API 路由
│   │   ├── story.py               # 故事 CRUD + 生成 + 结果
│   │   └── task.py                # 任务状态 + WebSocket 进度
│   ├── services/                  # 业务逻辑层
│   │   └── story_service.py
│   ├── repositories/              # 数据访问层
│   │   ├── story_repo.py
│   │   └── task_repo.py
│   ├── agents/                    # 6 个 LangGraph Agent
│   │   ├── script_agent.py        # 剧本生成 (含 Prompt + 重试)
│   │   ├── character_agent.py     # 角色视觉卡片生成
│   │   ├── storyboard_agent.py    # 分镜设计 (注入角色描述)
│   │   ├── image_agent.py         # ComfyUI 图片生成
│   │   ├── voice_agent.py         # CosyVoice 配音
│   │   └── video_agent.py         # FFmpeg 视频合成
│   ├── workflows/
│   │   ├── state.py               # StoryState 状态定义
│   │   └── story_workflow.py      # LangGraph 管线编排
│   ├── tools/                     # 外部服务客户端
│   │   ├── comfyui_client.py      # ComfyUI API 封装
│   │   ├── cosyvoice_client.py    # CosyVoice TTS 封装
│   │   └── ffmpeg_tool.py         # FFmpeg 视频操作封装
│   ├── tasks/
│   │   └── runner.py              # 后台任务运行器 + 进度追踪
│   ├── memory/
│   │   └── vector_store.py        # Qdrant 向量记忆
│   ├── app/
│   │   ├── database.py            # 异步数据库连接
│   │   └── redis.py               # Redis + PubSub
│   └── utils/
│       └── json_helper.py         # LLM JSON 解析 + 校验
├── frontend/                      # React 前端
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── App.tsx                # 路由 (首页/进度/结果)
│       ├── api/index.ts           # API + WebSocket 客户端
│       └── pages/
│           ├── HomePage.tsx       # 创意输入 + 历史列表
│           ├── StoryPage.tsx      # 生成进度 (6步 + 实时推送)
│           └── ResultPage.tsx     # 视频播放 + 剧本/分镜/角色
├── deploy/
│   ├── docker-compose.yml         # 一键部署编排
│   ├── nginx/default.conf         # Nginx 反向代理
│   └── .env.example               # 环境变量模板
└── scripts/
    └── init_db.py                 # 数据库初始化
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- FFmpeg (`apt install ffmpeg` 或 `brew install ffmpeg`)
- **外部依赖**（需要自行部署或使用远程服务）：
  - OpenAI 兼容的 LLM API（GPT-4o / Qwen / DeepSeek 等）
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (SDXL)
  - [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) (TTS)

### 1. 克隆并配置

```bash
git clone https://github.com/your-username/storyflow-ai.git
cd storyflow-ai

# 复制环境变量模板
cp deploy/.env.example backend/.env

# 编辑 .env，填入你的 LLM_API_KEY 和外部服务地址
# LLM_API_KEY=sk-xxx
# COMFYUI_URL=http://localhost:8188
# COSYVOICE_URL=http://localhost:50000
```

### 2. 启动基础服务 (PostgreSQL + Redis + Qdrant)

```bash
cd deploy
docker compose up -d postgres redis qdrant
```

### 3. 启动后端

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 初始化数据库
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

后端启动后访问：
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端访问: http://localhost:5173

### 5. 一键部署 (Docker Compose 全量)

```bash
cd deploy
# 编辑 .env 文件
docker compose up -d
```

访问 http://localhost 即可使用。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事项目 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成 |
| `GET` | `/api/story/{id}/result` | 获取生成结果 |
| `GET` | `/api/task/{id}` | 查询任务状态 |
| `WS` | `/api/task/{id}/ws` | WebSocket 实时进度 |
| `GET` | `/health` | 健康检查 |

### 创建并生成示例

```bash
# 创建故事
curl -X POST http://localhost:8000/api/story \
  -H "Content-Type: application/json" \
  -d '{"title":"逆袭校花","prompt":"胖子甄大卫逆袭校花莲花的故事","genre":"校园"}'

# 返回 story_id，启动生成
curl -X POST http://localhost:8000/api/story/{story_id}/generate

# 查询进度
curl http://localhost:8000/api/task/{task_id}
```

## Agent 工作流

```
用户创意输入
    ↓
[Script Agent]     → 生成剧情大纲 + 完整剧本 + 角色设定
    ↓
[Character Agent]  → 丰富角色视觉描述 (外貌/服装/体型/发型)
    ↓
[Storyboard Agent] → 剧本转分镜 (景别/时长/画面描述/角色)
    ↓
[Image Agent]      → ComfyUI 生成每镜图片 (SDXL, 1024×1024)
    ↓
[Voice Agent]      → CosyVoice 生成配音 (角色音色 + 情感)
    ↓
[Video Agent]      → FFmpeg 合成 (图片+音频→视频→字幕→拼接)
    ↓
输出 MP4 漫剧
```

每个 Agent 完成后通过 Redis PubSub 推送进度到前端，支持 WebSocket 实时展示。

## 数据库设计

```
story          ─── 故事项目主表
  ├─ character ─── 角色表 (appearance/personality 用 JSONB)
  ├─ episode   ─── 剧集表 (含完整剧本)
  └─ scene     ─── 场景表 (分镜/图片/音频)
task           ─── 生成任务表 (进度/状态/错误)
```

## 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | LLM API Key (必填) |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI 地址 |
| `COSYVOICE_URL` | `http://localhost:50000` | CosyVoice 地址 |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL 连接串 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant 地址 |
| `STORAGE_PATH` | `./storage` | 文件存储路径 |

## License

MIT