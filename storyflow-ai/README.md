<div align="center">

# 🎬 StoryFlow AI

**基于 StoryFlow Runtime 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 6 个 AI Agent 协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**，
最终输出可播放的 MP4 漫剧视频。

**不只是漫剧项目，而是一个支持 Workflow 编排、多 Agent 协作、事件驱动、可插拔模型和质量闭环的 AI Runtime 平台。**

[系统架构](#系统架构) · [Runtime 架构](#runtime-架构) · [快速开始](#快速开始) · [API 文档](#api-接口) · [配置说明](#配置项)

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
                          ▼
              ┌───────────────────────┐
              │   StoryFlow Runtime    │
              │                       │
              │  WorkflowEngine       │
              │  EventBus             │
              │  Blackboard           │
              │  ArtifactManager      │
              │  SessionManager       │
              │  HookFramework        │
              │  DirectorAgent        │
              │  PlannerAgent         │
              │  QualityEngine        │
              │  AdapterRegistry      │
              │  Agent SDK            │
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │     6 个 Agent        │
              │  (零改动，Runtime 调度) │
              └───────────┬───────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐   ┌───────────┐   ┌───────────┐
    │  LLM     │   │ ComfyUI / │   │ CosyVoice│
    │  API     │   │ SDXL API  │   │ / TTS API │
    └──────────┘   └───────────┘   └───────────┘
```

### Runtime 能力矩阵

| 能力 | 实现 | 说明 |
|------|------|------|
| **编排** | WorkflowEngine + YAML DSL | 支持线性/并行/DAG 执行 |
| **通信** | EventBus (pub/sub) | 所有组件通过事件解耦 |
| **共享状态** | Blackboard | 点号路径读写 + 变更通知 |
| **中间产物** | ArtifactManager | 文件化存储，支持局部重生成 |
| **会话管理** | SessionManager | 从任意步骤恢复/重跑 |
| **质量门禁** | QualityEngine | 6 种 Checker 自动质检 |
| **决策** | DirectorAgent | 观察-思考-决策（不生成内容） |
| **规划** | PlannerAgent | 需求拆解为可执行任务 DAG |
| **Hook** | HookFramework | Before/After/Error 横切关注点 |
| **模型切换** | AdapterRegistry | 改配置换模型，Agent 代码不动 |
| **扩展 Agent** | Agent SDK | 继承 BaseAgent，一行注册 |
| **Workflow** | YAML DSL | 声明式定义，支持并行组 |

> **核心原则：Agent 只接收输入、返回输出，禁止互相调用。Runtime 拥有唯一调度权。**

## Runtime 架构

### 设计理念

```
                    StoryFlow Runtime V3

                    ┌────────────────────────────┐
                    │      Director Agent        │
                    │ 全局导演 / 调度 / 重试 / 决策 │
                    └────────────┬───────────────┘
                                 │
                    ┌────────────▼───────────────┐
                    │      WorkflowEngine        │
                    │  DSL + EventBus + Hooks     │
                    │  并行执行 + 重试 + 检查点   │
                    └────────────┬───────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
 Planner Agent           Blackboard               QualityEngine
 (动态 DAG)            (共享状态)               (质量闭环)
        │                        │                        │
        ▼                        ▼                        ▼
    ┌───────┐              ┌──────────┐           ┌──────────┐
    │  6    │              │ Artifacts│           │Director │
    │ Agent │              │ (文件化) │           │ (决策)   │
    └───────┘              └──────────┘           └──────────┘
        │
  AdapterRegistry (可插拔模型)
```

### 关键特性

**1. 部分重生成（Artifact + Session）**
```
用户：重新生成第 3 幕的图片

Runtime：
  Session.reset_from_step("image")
  → 只重跑 image/voice/video
  → 不重跑 script/character/storyboard
```

**2. 事件驱动（EventBus）**
```python
# Image Agent 完成后自动触发 Voice Agent
event_bus.subscribe(EventType.STEP_COMPLETED, on_image_done)
```

**3. Agent 零耦合（Blackboard）**
```python
# Agent 不直接调用其他 Agent
blackboard.set("scenes.0.image_url", "/storage/scene_001.png")
# Voice Agent 通过订阅 Blackboard 变化获取通知
```

**4. Director 决策**
```python
# Image 失败 → Director 决定回退到 Storyboard 修改 Prompt
# Quality 检查不通过 → Director 决定重试或回退
```

**5. 模型热切换（Adapter）**
```python
# 切换图片生成后端：改一行配置，Agent 代码不动
IMAGE_API_PROVIDER=dashscope  # 或 comfyui, 或 mock
```

**6. 一行代码扩展 Agent（SDK）**
```python
class MusicAgent(BaseAgent):
    name = "music"
    async def execute(self, state): ...

agent_registry.register(MusicAgent())  # Runtime 自动发现
```

**7. Workflow DSL（声明式）**
```yaml
steps:
  - id: image
    agent: image
    depends_on: [storyboard]
    parallel_group: media_generation
  - id: voice
    agent: voice
    depends_on: [storyboard]
    parallel_group: media_generation  # 与 image 并行
```

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                        # FastAPI 入口 (v4.0.0)
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── configs/
│   │   └── settings.py                # Pydantic Settings
│   │
│   ├── prompts/                       # 集中管理的 Prompt 模板
│   │   └── __init__.py
│   │
│   ├── models/                        # SQLAlchemy ORM
│   │   ├── base.py, story.py, character.py
│   │   ├── episode.py, scene.py, task.py
│   │
│   ├── schemas/                        # Pydantic 请求/响应
│   ├── api/                           # FastAPI 路由
│   ├── services/                      # 业务逻辑
│   ├── repositories/                  # 数据访问
│   │
│   ├── agents/                        # 6 个 Agent (零改动)
│   │   ├── script_agent.py
│   │   ├── character_agent.py
│   │   ├── storyboard_agent.py
│   │   ├── image_agent.py
│   │   ├── voice_agent.py
│   │   └── video_agent.py
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict
│   │   ├── runtime_workflow.py        # Runtime 执行入口
│   │   ├── comic.yaml                 # 漫剧 Workflow DSL
│   │   └── novel.yaml                 # 小说 Workflow DSL
│   │
│   ├── tools/                         # ComfyUI / CosyVoice / FFmpeg
│   ├── tasks/
│   │   └── runner.py                  # 任务运行器 (Runtime only)
│   ├── app/                           # Database / Redis / LLM
│   ├── utils/                         # 工具函数
│   │
│   └── runtime/                       # Runtime 核心
│       ├── __init__.py                # 统一导出
│       ├── core.py                    # StoryFlowRuntime 主入口
│       ├── event_bus.py               # EventBus (异步 pub/sub, 13 种事件)
│       ├── blackboard.py              # Blackboard (共享状态, 点号路径)
│       ├── artifact_manager.py        # ArtifactManager (文件化 + 检查点)
│       ├── session_manager.py         # SessionManager (会话 + 部分重生成)
│       ├── hooks.py                   # HookFramework (Before/After/Error)
│       ├── workflow_engine.py         # WorkflowEngine (DSL + 并行 + Hook)
│       ├── director.py                # DirectorAgent (决策: retry/rollback/skip)
│       ├── planner.py                 # PlannerAgent (任务 DAG 拆解)
│       ├── agent_sdk.py               # BaseAgent + AgentRegistry
│       ├── quality/                   # QualityEngine (6 种 Checker)
│       │   └── __init__.py
│       └── adapters/                  # Model Adapters (可插拔)
│           └── __init__.py
│
├── frontend/                          # React 18 + TypeScript + Ant Design 5
│   └── src/
│       ├── App.tsx
│       ├── api/index.ts
│       ├── types/index.ts
│       └── pages/
│           ├── HomePage.tsx
│           ├── StoryPage.tsx
│           └── ResultPage.tsx
│
├── deploy/
│   ├── docker-compose.yml
│   ├── nginx/default.conf
│   └── init.sql
│
└── scripts/
    └── init_db.py
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (可选)
- FFmpeg
- OpenAI 兼容 LLM API（GPT-4o / Qwen / DeepSeek 等）
- ComfyUI 或其他 SDXL 服务（图片生成）
- CosyVoice 或其他 TTS 服务（语音合成）

### 方式一：本地开发

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 配置
cp deploy/.env.example backend/.env
# 编辑 backend/.env，填入 LLM_API_KEY 等

# 基础服务
cd deploy && docker compose up -d postgres redis && cd ..

# 后端
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd frontend && npm install && npm run dev
```

### 方式二：Docker Compose

```bash
cd storyflow-ai/deploy
docker compose up -d
```

| 地址 | 说明 |
|------|------|
| http://localhost:5173 | 前端 |
| http://localhost:8000/docs | Swagger API |
| http://localhost:8000/health | 健康检查 |

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
         ▼ (可并行)
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

### 基础配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | LLM API Key (**必填**) |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI |
| `COSYVOICE_URL` | `http://localhost:50000` | CosyVoice |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `STORAGE_PATH` | `./storage` | 文件存储 |

### Runtime 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_QUALITY` | `true` | 启用质量检查 |
| `ENABLE_DIRECTOR` | `false` | 启用 Director 自动决策 |
| `IMAGE_API_PROVIDER` | `comfyui` | 图片后端 (`comfyui` / `mock`) |
| `VOICE_API_PROVIDER` | `cosyvoice` | 语音后端 (`cosyvoice` / `mock`) |
| `VIDEO_API_PROVIDER` | `ffmpeg` | 视频后端 (`ffmpeg` / `mock`) |
| `ARTIFACT_PATH` | `./artifacts` | 中间产物存储目录 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/runtime/stats` | Runtime 统计信息 |
| `POST` | `/api/runtime/session/{id}/rerun/{step}` | 部分重生成 |
| `POST` | `/api/story/` | 创建故事 |
| `GET` | `/api/story/{id}` | 获取故事详情 |
| `POST` | `/api/task/generate` | 触发生成任务 |
| `WS` | `/api/task/{id}/ws` | 实时进度推送 |

## License

MIT