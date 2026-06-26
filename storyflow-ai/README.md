<div align="center">

# 🎬 StoryFlow AI

**基于 Multi-Agent Workflow 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 6 个 AI Agent 串联协作，自动完成 **剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**，最终输出可播放的 MP4 漫剧视频。

[技术架构](#系统架构) · [快速开始](#快速开始) · [API 文档](#api-接口) · [配置说明](#配置项)

</div>

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                          │
│              (Vite + TypeScript + Ant Design 5)              │
└─────────────────────────┬───────────────────────────────────┘
                          │  REST API / WebSocket (实时进度)
┌─────────────────────────▼───────────────────────────────────┐
│                   FastAPI Gateway                           │
│              (CORS · 路由 · 静态文件 · WebSocket)             │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┴───────────────┐
          ▼                               ▼
┌─────────────────────┐       ┌──────────────────────┐
│  LangGraph Workflow  │       │  Agent OS Runtime    │
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
│  │  Qdrant  │  │  Redis    │  (PubSub 推送 + 任务状态缓存) │
│  │ (Memory) │  │           │                               │
│  └──────────┘  └───────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

### 核心特性

- **双后端引擎** — 默认 LangGraph 线性管线，可切换 Agent OS Runtime（Hook / Memory / Skill / A2A）
- **实时进度推送** — Redis PubSub + WebSocket，前端 6 步进度条实时更新
- **数据库持久化** — 每个 Agent 完成后立即写入 PostgreSQL，中间结果不丢失
- **崩溃恢复** — LangGraph AsyncSqliteSaver Checkpoint，进程重启后从断点续跑
- **容错与降级** — 图片/配音/视频 Agent 按场景粒度 try/catch，部分失败不中断整体流程
- **自动重试** — Script Agent 使用 tenacity 3 次指数退避重试；Image Agent 每张图最多 2 次重试
- **LLM 工厂模式** — `get_creative_llm()` / `get_precise_llm()` 按场景选用不同温度，实例缓存复用
- **结构化输出** — Pydantic v2 Schema + PydanticOutputParser 保证 LLM 返回格式稳定

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18, TypeScript, Vite 5, Ant Design 5, Axios | SPA 单页应用 |
| **后端** | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 | 异步全栈 |
| **Agent 框架** | LangGraph, LangChain, ChatOpenAI | 6-Agent 串行管线 |
| **Runtime (v2)** | Agent OS Runtime | Hook / Memory / Skill / A2A / Langfuse |
| **数据库** | PostgreSQL 16 (asyncpg) | 故事 / 角色 / 场景 / 任务 |
| **缓存** | Redis 7 | 任务状态 + PubSub 实时推送 |
| **向量数据库** | Qdrant | 角色 / 剧情记忆检索 |
| **图像生成** | Stable Diffusion XL via ComfyUI API | 1024×1024，KSampler DPM++ 2M Karras |
| **语音合成** | CosyVoice TTS | 男/女声自动映射 |
| **视频合成** | FFmpeg | 图片+音频→视频→字幕烧录→拼接 |
| **部署** | Docker Compose, Nginx | 一键部署 |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                        # FastAPI 应用入口 (lifespan, CORS, 路由)
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── configs/
│   │   └── settings.py                # Pydantic Settings 配置中心
│   │
│   ├── models/                        # SQLAlchemy ORM 模型
│   │   ├── base.py                    # Base + TimestampMixin
│   │   ├── story.py                   # 故事表
│   │   ├── character.py               # 角色表 (appearance/personality JSONB)
│   │   ├── episode.py                 # 剧集表 (完整剧本)
│   │   ├── scene.py                   # 场景/分镜表 (图片/音频 URL)
│   │   └── task.py                    # 任务表 (进度/状态/错误)
│   │
│   ├── schemas/                       # Pydantic 请求/响应模型
│   │   ├── story.py
│   │   ├── agent.py                   # ScriptOutput / CharacterCard / StoryboardScene
│   │   └── task.py
│   │
│   ├── api/                           # API 路由
│   │   ├── story.py                   # 故事 CRUD + 触发生成 + 获取结果
│   │   └── task.py                    # 任务状态查询 + WebSocket 实时进度
│   │
│   ├── services/
│   │   └── story_service.py           # 业务逻辑层，启动 asyncio 后台任务
│   │
│   ├── repositories/                  # 数据访问层
│   │   ├── story_repo.py
│   │   └── task_repo.py
│   │
│   ├── agents/                        # 6 个 LangGraph Agent 节点
│   │   ├── script_agent.py            # 剧本生成 (tenacity 3x 重试, PydanticOutputParser)
│   │   ├── character_agent.py         # 角色视觉卡片 (外貌/服装/体型/发型)
│   │   ├── storyboard_agent.py        # 分镜设计 (注入角色描述, 景别/时长)
│   │   ├── image_agent.py             # ComfyUI 图片 (随机 seed, 逐场景重试, 部分容错)
│   │   ├── voice_agent.py             # CosyVoice 配音 (性别→音色映射, 部分容错)
│   │   └── video_agent.py             # FFmpeg 合成 (场景视频→ASS 字幕→烧录→拼接)
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict (LangGraph 状态)
│   │   ├── story_workflow.py          # LangGraph 管线编排 + Checkpoint 支持
│   │   └── runtime_workflow.py        # Agent OS Runtime 适配层
│   │
│   ├── tools/                         # 外部服务客户端
│   │   ├── comfyui_client.py          # ComfyUI API 封装 (KSampler + CLIPTextEncode)
│   │   ├── cosyvoice_client.py        # CosyVoice TTS 封装 (JSON/base64/raw audio)
│   │   └── ffmpeg_tool.py             # FFmpeg 视频操作 (create_scene_video/concat/subtitle)
│   │
│   ├── tasks/
│   │   └── runner.py                  # 后台任务运行器 (双后端 + 5 个 _persist_* 函数)
│   │
│   ├── app/
│   │   ├── database.py                # 异步数据库连接池
│   │   ├── redis.py                   # Redis + PubSub
│   │   └── llm.py                     # LLM 工厂 (creative/precise, 实例缓存)
│   │
│   ├── memory/
│   │   └── vector_store.py            # Qdrant 向量记忆
│   │
│   ├── utils/
│   │   └── json_helper.py             # LLM JSON 解析 + 校验
│   │
│   └── runtime/                       # Agent OS Runtime (v2.0, 可选)
│       ├── app.py                     # Runtime 入口
│       ├── adapter.py                 # LangGraph Agent → Runtime 适配
│       ├── agent_runtime/             # Agent 运行时上下文
│       ├── execution/                 # 调度器 (LLM/Tool/GPU 线程池)
│       ├── conversation/              # 对话管理
│       ├── skill_engine/              # 技能注册/选择/校验/执行
│       ├── memory/                    # Runtime 记忆管理
│       ├── session/                   # 会话管理
│       ├── hook/                      # 事件钩子分发
│       ├── mcp/                       # MCP 协议适配
│       ├── handlers/                  # 日志 / Langfuse 追踪
│       └── message_bus/               # 进程间通信 (memory/redis)
│
├── frontend/                          # React 前端
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── App.tsx                    # 路由 (首页 / 生成进度 / 结果)
│       ├── api/index.ts               # API + WebSocket 客户端
│       ├── types/index.ts             # TypeScript 类型定义
│       └── pages/
│           ├── HomePage.tsx           # 创意输入 + 历史列表
│           ├── StoryPage.tsx          # 6 步生成进度 + WebSocket 实时推送
│           └── ResultPage.tsx         # 视频播放 + 剧本/分镜/角色展示
│
├── deploy/
│   ├── docker-compose.yml             # 一键部署 (Postgres + Redis + Qdrant + Backend + Nginx)
│   ├── nginx/default.conf             # Nginx 反向代理 + 静态文件
│   ├── init.sql                       # 数据库初始化
│   └── .env.example                   # 环境变量模板
│
└── scripts/
    └── init_db.py                     # 数据库初始化脚本
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- FFmpeg (`apt install ffmpeg` 或 `brew install ffmpeg`)
- **外部依赖**（需要自行部署或使用远程服务）：
  - OpenAI 兼容的 LLM API（GPT-4o / Qwen / DeepSeek 等）
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (SDXL 模型)
  - [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) (TTS 服务)

### 方式一：本地开发

```bash
# 1. 克隆项目
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 2. 配置环境变量
cp deploy/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY 和外部服务地址

# 3. 启动基础服务 (PostgreSQL + Redis + Qdrant)
cd deploy && docker compose up -d postgres redis qdrant && cd ..

# 4. 启动后端
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 5. 启动前端 (新终端)
cd frontend
npm install
npm run dev
```

| 访问地址 | 说明 |
|---------|------|
| http://localhost:5173 | 前端界面 |
| http://localhost:8000/docs | Swagger API 文档 |
| http://localhost:8000/health | 健康检查 |

### 方式二：Docker Compose 一键部署

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai/deploy

# 编辑 .env 文件，至少填入 LLM_API_KEY
# LLM_API_KEY=sk-xxx
# COMFYUI_URL=http://host.docker.internal:8188
# COSYVOICE_URL=http://host.docker.internal:50000

docker compose up -d
```

访问 http://localhost 即可使用。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事项目 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成流水线 |
| `GET` | `/api/story/{id}/result` | 获取生成结果 (视频/剧本/分镜) |
| `GET` | `/api/task/{id}` | 查询任务状态与进度 |
| `WS` | `/api/task/{id}/ws` | WebSocket 实时进度推送 |
| `GET` | `/health` | 健康检查 |

### 示例：创建并生成一部漫剧

```bash
# 1. 创建故事
curl -X POST http://localhost:8000/api/story \
  -H "Content-Type: application/json" \
  -d '{"title":"逆袭校花","prompt":"胖子甄大卫逆袭校花莲花的故事","genre":"校园"}'

# 2. 使用返回的 story_id 启动生成
curl -X POST http://localhost:8000/api/story/{story_id}/generate

# 3. 通过 WebSocket 实时监听进度 (返回 task_id)
# 或轮询任务状态
curl http://localhost:8000/api/task/{task_id}
```

## Agent 工作流详解

```
用户创意输入 (prompt + genre)
         │
         ▼
┌─────────────────┐
│  Script Agent   │  LLM 生成剧情大纲 + 角色设定 + 分集剧本
│  (tenacity 3x)  │  → PydanticOutputParser 保证结构化输出
└────────┬────────┘
         ▼
┌─────────────────┐
│ Character Agent │  丰富角色视觉描述 (发型/体型/服装/五官)
│                 │  → 为后续图片生成提供一致性角色参考
└────────┬────────┘
         ▼
┌─────────────────┐
│Storyboard Agent │  剧本 → 分镜 (景别/时长/画面描述/出场角色)
│                 │  → 自动注入角色外观描述到每镜 prompt
└────────┬────────┘
         ▼
┌─────────────────┐
│  Image Agent    │  ComfyUI 逐镜生成图片 (SDXL 1024x1024)
│  (随机 seed     │  → 每镜随机 seed, 单图最多 2 次重试
│   + 逐场景容错) │  → 部分失败不中断，返回 image_partial 状态
└────────┬────────┘
         ▼
┌─────────────────┐
│  Voice Agent    │  CosyVoice 逐镜配音
│  (性别→音色映射) │  → 自动根据角色性别选择 male/female 音色
│  (逐场景容错)    │  → 支持 base64/URL 两种音频返回格式
└────────┬────────┘
         ▼
┌─────────────────┐
│  Video Agent    │  FFmpeg 合成最终视频
│                 │  1. 图片+音频 → 逐场景视频
│                 │  2. 生成 ASS 字幕 (累计时间轴)
│                 │  3. 字幕烧录到场景视频
│                 │  4. concat 拼接为完整 MP4
└────────┬────────┘
         ▼
    输出 MP4 漫剧
```

### 实时进度推送

每个 Agent 完成后通过 **Redis PubSub → WebSocket** 推送进度到前端，前端 StoryPage 以 6 步进度条实时展示：

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

### 数据库持久化机制

每个 Agent 完成后，Task Runner 通过 5 个 `_persist_*` 函数将中间结果立即写入 PostgreSQL：

- `_persist_characters()` — 角色视觉卡片
- `_persist_episodes()` — 分集剧本
- `_persist_scenes()` — 分镜场景
- `_persist_image_urls()` — 场景图片 URL
- `_persist_audio_urls()` — 场景音频 URL

即使后续 Agent 失败，前端仍可查看已完成的中间结果。

## 数据库设计

```
story          ─── 故事项目主表 (title, prompt, genre, status)
  ├─ character ─── 角色表 (name, gender, age, appearance JSONB, personality JSONB)
  ├─ episode   ─── 剧集表 (episode_no, title, summary, script)
  └─ scene     ─── 场景表 (scene_no, prompt, camera, duration, image_url, audio_url)
task           ─── 生成任务表 (status, progress, current_step, error_message)
```

## 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | LLM API Key (**必填**) |
| `LLM_MODEL` | `gpt-4o` | 模型名称 (也支持 Qwen / DeepSeek 等) |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `LLM_TEMPERATURE` | `0.7` | 默认温度 (creative=0.8, precise=0.4) |
| `LLM_MAX_TOKENS` | `4096` | 默认最大 token |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI 服务地址 |
| `COSYVOICE_URL` | `http://localhost:50000` | CosyVoice TTS 服务地址 |
| `DATABASE_URL` | `postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow` | PostgreSQL 连接串 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant 向量数据库地址 |
| `STORAGE_PATH` | `./storage` | 文件存储根目录 |
| `USE_RUNTIME` | `false` | 设为 `true` 启用 Agent OS Runtime (v2.0) |

### Runtime v2.0 额外配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse 公钥 (可观测性) |
| `LANGFUSE_SECRET_KEY` | — | Langfuse 密钥 |
| `A2A_TRANSPORT` | `memory` | Agent 间通信方式 (`memory` / `redis`) |
| `LLM_WORKER_CONCURRENCY` | `10` | LLM 任务并发数 |
| `GPU_WORKER_CONCURRENCY` | `2` | GPU 任务并发数 |

## 开发路线

- [x] 基础框架搭建 (FastAPI + React + Docker)
- [x] 6-Agent LangGraph 线性管线
- [x] ComfyUI / CosyVoice / FFmpeg 工具集成
- [x] Redis PubSub + WebSocket 实时进度
- [x] PostgreSQL 数据库持久化 (5 个 _persist_* 函数)
- [x] LangGraph Checkpoint 崩溃恢复 (AsyncSqliteSaver)
- [x] Agent 容错机制 (逐场景 try/catch, 部分结果降级)
- [x] Script Agent tenacity 重试 + PydanticOutputParser
- [x] Image Agent 随机 seed + 单图重试
- [x] LLM 工厂模式 (creative / precise)
- [x] Agent OS Runtime v2.0 适配层
- [ ] Prompt 模板管理 (外部化 / 版本化)
- [ ] 角色一致性 LoRA / IP-Adapter 集成
- [ ] 多集批量生成与剧集管理
- [ ] 用户认证与配额管理
- [ ] 前端 TypeScript 类型完善
- [ ] 单元测试与集成测试
- [ ] CI/CD 流水线

## License

MIT