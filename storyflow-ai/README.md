# StoryFlow AI

AI 漫剧自动生成平台。输入一段创意文字，系统自动完成剧本、角色设计、分镜、图片生成、图生视频、配音、视频剪辑全流程，输出完整 MP4 漫剧视频。

## 工作流程

```
创意文字
  │
  ▼
Script Agent ── 剧本生成（大纲 + 角色 + 分集剧本）
  │
  ▼
Character Agent ── 角色视觉化设计（4 维外貌描述）
  │
  ▼
Storyboard Agent ── 分镜拆解（镜头 + 时长 + 画面描述 + 台词）
  │
  ├──────────────────────┐
  ▼                      ▼
Image Agent          Voice Agent
（场景图片生成）    （多供应商 TTS 配音）
  │                      │
  ▼                      │
Image-to-Video Agent     │
（图片转动态视频）        │
  │                      │
  └──────────┬───────────┘
             ▼
       Video Agent
  （转场拼接 + 字幕 + BGM + 音频合成）
             │
             ▼
        story.mp4
```

Image-to-Video 和 Voice 并行执行，减少总生成时间。整个流程通过 DSL 工作定义文件 (`workflows/comic.yaml`) 驱动。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18, TypeScript, Vite 5, Ant Design 5, React Router 6 |
| 后端 | Python 3.11+, FastAPI 4.0, SQLAlchemy 2.0 (async), Pydantic 2.0 |
| LLM | OpenAI 兼容 API (GPT-4o / Qwen / DeepSeek), LangChain |
| 图片生成 | DashScope 通义万相 / DALL-E 3 |
| 图生视频 | Kling / Runway |
| 语音合成 | OpenAI TTS / DashScope CosyVoice / ElevenLabs / Google / Piper |
| 视频合成 | FFmpeg + Montage VideoComposer |
| 数据库 | PostgreSQL 16 (asyncpg) |
| 缓存/消息 | Redis 7 (PubSub) |
| 部署 | Docker Compose |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                          # FastAPI 入口
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── configs/
│   │   └── settings.py                  # Pydantic Settings 配置
│   ├── prompts/
│   │   └── __init__.py                  # 7 个 Agent 的 Prompt 模板
│   ├── models/                          # SQLAlchemy ORM（story/task/character/episode/scene）
│   ├── schemas/                         # Pydantic 请求/响应模型
│   ├── api/                             # REST + WebSocket 路由
│   │   ├── story.py                     #   故事 CRUD + 生成 + 产物查看 + 世界快照 + 修补 + 断点续传
│   │   └── task.py                      #   任务状态 + WebSocket 实时进度
│   ├── services/
│   │   └── story_service.py             # 业务逻辑层
│   ├── repositories/                    # 数据访问层
│   ├── tasks/
│   │   └── runner.py                    # 后台任务执行器（进度追踪 + DB 持久化）
│   │
│   ├── agents/                          # 7 个 AI Agent
│   │   ├── script_agent.py              #   剧本生成
│   │   ├── character_agent.py           #   角色视觉化设计
│   │   ├── storyboard_agent.py          #   分镜生成
│   │   ├── image_agent.py               #   场景图片生成
│   │   ├── image_to_video_agent.py      #   图片转动态视频
│   │   ├── voice_agent.py               #   配音合成
│   │   └── video_agent.py               #   最终视频合成
│   │
│   ├── workflows/                       # 管线定义
│   │   ├── comic.yaml                   #   漫剧管线 DSL（7 步 + 并行组）
│   │   ├── novel.yaml                   #   小说管线 DSL
│   │   ├── state.py                     #   StoryState TypedDict
│   │   └── runtime_workflow.py          #   Runtime 执行入口
│   │
│   └── runtime/                         # StoryFlow Runtime
│       ├── core.py                      #   统一入口（Session 创建/执行/单步重跑）
│       ├── workflow_engine.py           #   管线编排（DSL 驱动 + Director 决策）
│       ├── director.py                  #   LLM 决策大脑（6 种决策）
│       ├── montage_adapter.py           #   StoryFlow ↔ 渲染引擎数据桥接
│       ├── agent_conversation.py        #   Agent 间结构化消息（A2A）
│       ├── event_bus.py                 #   事件总线（发布/订阅）
│       ├── blackboard.py                #   共享状态黑板
│       ├── artifact_manager.py          #   产物/检查点存储
│       ├── session_manager.py           #   会话管理
│       ├── hooks.py                     #   前置/后置/异常钩子
│       ├── planner.py                   #   任务 DAG 分解
│       ├── reflection.py                #   执行后反思分析
│       ├── prompt_runtime.py            #   动态 Prompt 构建
│       ├── model_router.py              #   智能模型选择
│       ├── retry_engine.py              #   自动重试
│       ├── agent_sdk.py                 #   Agent 注册发现
│       ├── adapters/                    #   适配器注册表
│       ├── quality/                     #   质量门控引擎
│       ├── memory/                      #   多维记忆系统
│       └── trace/                       #   追踪
│
├── frontend/
│   └── src/
│       ├── App.tsx                      # 路由：首页 / 生成页 / 结果页
│       ├── api/index.ts                 # API + WebSocket 封装
│       ├── types/index.ts               # TypeScript 类型定义
│       └── pages/
│           ├── HomePage.tsx             #   故事创建 + 历史列表
│           ├── StoryPage.tsx            #   生成进度（WebSocket 实时）
│           └── ResultPage.tsx           #   结果展示（视频 + 剧本 + 角色 + 分镜）
│
├── deploy/
│   ├── docker-compose.yml               # PostgreSQL + Redis + Backend
│   ├── .env.example                     # 环境变量模板
│   ├── nginx/default.conf               # Nginx 反向代理配置
│   └── init.sql                         # 数据库初始化
│
└── scripts/
    └── init_db.py                       # 数据库表初始化脚本
```

## Runtime 核心

StoryFlow Runtime 负责管线的执行、决策和质量管控。

### Director

每步执行后分析全部产出物，通过 LLM 或规则引擎做出决策：

| 决策 | 动作 |
|------|------|
| `PROCEED` | 继续下一步 |
| `RETRY` | 重试当前步骤 |
| `ROLLBACK` | 回退到更早的步骤重新执行 |
| `REWRITE_PROMPT` | 重写提示词后重试 |
| `SKIP` | 跳过当前步骤 |
| `INSERT_STEP` | 插入修复步骤 |

默认关闭，通过 `ENABLE_DIRECTOR=true` 启用。

### 其他 Runtime 组件

- **EventBus** — 事件驱动，解耦步骤执行与进度通知
- **SessionManager** — 会话追踪，支持断点续传和单步重跑
- **ArtifactManager** — 产物和检查点的文件存储
- **QualityEngine** — 脚本/角色/分镜/图片/配音的质量门控（默认开启）
- **HookFramework** — 每步的前置/后置/异常钩子
- **AgentConversationBus** — Agent 间结构化通信（携带角色档案、约束、质量反馈）
- **StoryMemory** — 多维记忆系统（场景/视觉/风格/世界/角色/时间线）
- **ModelRouter** — 按场景智能选择 LLM 模型

## Montage 渲染引擎

从 [OpenMontage](https://github.com/calesthio/OpenMontage) 提取的纯媒体渲染组件，通过 `montage_adapter.py` 单点桥接，与业务逻辑完全解耦。通过 `MONTAGE_ENABLED=false` 可降级为原始 FFmpeg 实现。

| 组件 | 能力 |
|------|------|
| TTSEngine | 5 供应商自动选择 + 静默降级 |
| SubtitleEngine | SRT/VTT 生成，词级时间轴对齐 |
| FFmpegOps | 转码 / 裁切 / xfade 转场 / 字幕烧录 / 图片序列 / concat |
| AudioMixer | 多轨混合 / sidechain ducking / BGM 分段配乐 / loudnorm |
| VideoComposer | 转场拼接 + 字幕烧录 + 多音轨合成 + 7 步质量检测 |
| MediaProfiles | YouTube / TikTok / Instagram / LinkedIn / Cinematic 等 10 种预设 |
| RenderQueue | 批量渲染队列 |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- FFmpeg
- OpenAI 兼容 LLM API Key（必填）

### Docker Compose 部署

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai/deploy

# 编辑 .env，填入 LLM_API_KEY
cp .env.example .env

# 启动
docker compose up -d
```

Docker Compose 包含三个服务：PostgreSQL、Redis、Backend（内置 FFmpeg）。

### 本地开发

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 启动基础设施
cd deploy && docker compose up -d postgres redis && cd ..

# 后端
cd backend
cp ../deploy/.env.example .env
# 编辑 .env，填入 LLM_API_KEY
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端（新终端）
cd frontend && npm install && npm run dev
```

## API

### 故事

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成 |
| `GET` | `/api/story/{id}/result` | 生成结果（视频 + 剧本 + 角色 + 分镜） |
| `GET` | `/api/story/{id}/world` | 当前会话的世界快照 |
| `POST` | `/api/story/{id}/patch` | 修改角色属性 |
| `GET` | `/api/story/{id}/checkpoints` | 断点列表 |
| `POST` | `/api/story/{id}/resume` | 从断点续传 |

### 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/task/{id}` | 任务状态 |
| `GET` | `/api/task/by-story/{story_id}` | 按故事查任务 |
| `WS` | `/api/task/{id}/ws` | WebSocket 实时进度 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/runtime/stats` | Runtime 统计 |
| `POST` | `/api/runtime/session/{id}/rerun/{step}` | 重跑单步 |

## 配置

### 必填

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | LLM API Key |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | API 地址 |

### 图片 / 视频 / 语音

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE_API_PROVIDER` | `dashscope` | 图片供应商 |
| `IMAGE_API_KEY` | — | DashScope API Key |
| `I2V_API_PROVIDER` | `kling` | 图生视频供应商 |
| `I2V_API_KEY` | — | Kling API Key |
| `MONTAGE_TTS_PROVIDER` | `auto` | TTS 供应商（auto 自动选择） |
| `VOICE_API_KEY` | — | DashScope TTS API Key |

### 视频合成

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MONTAGE_ENABLED` | `True` | 启用 Montage 渲染引擎 |
| `MONTAGE_TRANSITION` | `crossfade` | 转场：cut / crossfade / fade |
| `MONTAGE_TRANSITION_DURATION` | `0.5` | 转场时长（秒） |
| `MONTAGE_BURN_SUBTITLES` | `True` | 烧录字幕 |
| `MONTAGE_QUALITY_CHECK` | `True` | 成片质量检测 |
| `MONTAGE_BGM_PATH` | — | BGM 文件路径 |
| `MONTAGE_MEDIA_PROFILE` | `storyflow_default` | 输出预设 |

### Runtime

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_QUALITY` | `true` | 质量门控 |
| `ENABLE_DIRECTOR` | `false` | Director 决策 |

### 基础设施

| 变量 | 默认值 |
|------|--------|
| `DATABASE_URL` | `postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `STORAGE_PATH` | `./storage` |

### 生成控制

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |

## 容错

- **TTS**：OpenAI → DashScope → ElevenLabs → Google → Piper → 静默占位
- **图片**：DashScope → DALL-E → Mock
- **图生视频**：Kling → Runway → FFmpeg 静态图转视频
- **视频合成**：Montage 引擎 → Legacy FFmpeg concat
- **Agent 失败**：tenacity 3 次重试 → Director 决策（SKIP / ROLLBACK）

## License

MIT