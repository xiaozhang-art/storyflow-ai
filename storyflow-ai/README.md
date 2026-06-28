<div align="center">

# 🎬 StoryFlow AI

**基于 Multi-Agent Runtime 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 6 个 AI Agent 协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**，
最终输出可播放的 MP4 漫剧视频。

**不只是漫剧项目，而是一个支持 Workflow 编排、多 Agent 协作、事件驱动、可插拔模型和质量闭环的 AI Runtime 平台。**

[系统架构](#系统架构) · [Runtime V3](#runtime-v3-新架构) · [快速开始](#快速开始) · [API 文档](#api-接口) · [配置说明](#配置项)

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
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────────┐
│  LangGraph  │  │  Agent OS    │  │  StoryFlow       │
│  Pipeline   │  │  Runtime v2  │  │  Runtime V3      │
│  (v1 默认)  │  │  (可选)      │  │  (新架构)        │
│             │  │              │  │                  │
│  串行 6 步  │  │  Hook/Memory │  │  EventBus        │
│  StateGraph │  │  Skill/A2A   │  │  Blackboard      │
│             │  │  Scheduler   │  │  Artifacts       │
│             │  │              │  │  Director        │
│             │  │              │  │  Planner         │
│             │  │              │  │  Quality Engine  │
│             │  │              │  │  AdapterRegistry  │
│             │  │              │  │  Agent SDK       │
└─────────────┘  └──────────────┘  └──────────────────┘
          │               │               │
          └───────────────┼───────────────┘
                          ▼
              ┌───────────────────┐
              │   6 个 Agent      │
              │  (完全不改)       │
              └───────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐   ┌───────────┐   ┌───────────┐
    │  LLM     │   │ ComfyUI / │   │ CosyVoice│
    │  API     │   │ SDXL API  │   │ / TTS API │
    └──────────┘   └───────────┘   └───────────┘
```

### 三后端引擎

| | LangGraph (v1) | Agent OS Runtime (v2) | **StoryFlow Runtime (v3)** |
|--|--|--|--|
| **触发** | 默认 | `USE_RUNTIME=true` | `USE_V3_RUNTIME=true` |
| **编排** | StateGraph 串行 | RuntimeWorkflowRunner | **WorkflowEngine + EventBus** |
| **通信** | 状态字典 | MCP + A2A MessageBus | **EventBus (pub/sub)** |
| **共享状态** | TypedDict | Memory Manager | **Blackboard (读写 + 通知)** |
| **中间产物** | 无 | 无 | **ArtifactManager (文件化)** |
| **会话管理** | 无 | SessionManager (V2) | **SessionManager (部分重生成)** |
| **质量门禁** | 无 | QualityGate Hook | **QualityEngine (6 种 Checker)** |
| **决策** | 无 | 无 | **DirectorAgent (观察-思考-决策)** |
| **规划** | 固定 6 步 | 固定 6 步 | **PlannerAgent (动态 DAG)** |
| **Hook** | 无 | 14 种生命周期事件 | **Before/After/Error Hook** |
| **模型切换** | 硬编码 | 硬编码 | **AdapterRegistry (改配置换模型)** |
| **扩展 Agent** | 改代码 | 改代码 | **Agent SDK (继承 BaseAgent)** |
| **Workflow** | 代码定义 | 代码定义 | **YAML DSL 声明式** |
| **Agent 改动** | — | — | **零改动** |

> **核心原则：所有 Runtime 版本都不修改任何现有 Agent 代码。**

## Runtime V3 新架构

### 设计理念：渐进式重构

从串行 Pipeline 逐步演化为真正的 AI Runtime，每个阶段都可以独立运行。

```
                    StoryFlow Runtime V3

                    ┌────────────────────────────┐
                    │      Director Agent        │
                    │ 全局导演 / 调度 / 重试 / 决策 │
                    └────────────┬───────────────┘
                                 │
                    ┌────────────▼───────────────┐
                    │      WorkflowEngine        │
                    │  EventBus + Hooks + Retry   │
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

### 新增文件说明

| 文件 | 阶段 | 职责 |
|------|------|------|
| `runtime/event_bus.py` | V1 | 异步事件总线，所有组件通过发布/订阅事件通信 |
| `runtime/blackboard.py` | V1.5 | 共享状态空间，Agent 读写不直接调用 |
| `runtime/artifact_manager.py` | V1 | 文件化中间产物管理，支持部分重生成 |
| `runtime/session_manager.py` | V1 | 会话跟踪，支持从任意步骤恢复/重跑 |
| `runtime/hooks.py` | V1.5 | Before/After/Error Hook 框架 |
| `runtime/workflow_engine.py` | V1 | 步骤执行引擎，集成 EventBus + Blackboard + Artifacts |
| `runtime/core.py` | V1 | StoryFlowRuntime 主类，组装所有组件 |
| `runtime/director.py` | V2 | Director Agent：观察、思考、决策（不生成内容） |
| `runtime/planner.py` | V2.5 | Planner Agent：需求拆解为可执行任务 DAG |
| `runtime/quality/` | V3 | 质量引擎：6 种 Checker（Script/Character/Storyboard/Image/Voice/Consistency） |
| `runtime/adapters/` | V3 | 模型适配器：LLM/Image/Voice/Video 可插拔切换 |
| `runtime/agent_sdk.py` | V3 | Agent SDK：BaseAgent 基类 + AgentRegistry 自动发现 |
| `workflows/comic.yaml` | V3 | 漫剧 Workflow DSL 声明式定义 |
| `workflows/novel.yaml` | V3 | 小说 Workflow DSL 声明式定义 |

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
│   ├── main.py                        # FastAPI 入口 (v3.0.0)
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
│   ├── agents/                        # ⭐ 6 个 Agent (完全不改)
│   │   ├── script_agent.py
│   │   ├── character_agent.py
│   │   ├── storyboard_agent.py
│   │   ├── image_agent.py
│   │   ├── voice_agent.py
│   │   └── video_agent.py
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict
│   │   ├── story_workflow.py          # LangGraph 编排
│   │   ├── runtime_workflow.py        # V2 Runtime 适配层
│   │   ├── comic.yaml                 # ⭐ 漫剧 Workflow DSL
│   │   └── novel.yaml                 # ⭐ 小说 Workflow DSL
│   │
│   ├── tools/                         # ComfyUI / CosyVoice / FFmpeg
│   ├── tasks/
│   │   └── runner.py                  # 三后端任务运行器
│   ├── app/                           # Database / Redis / LLM
│   ├── memory/                        # Qdrant 向量记忆
│   ├── utils/                         # 工具函数
│   ├── skills/                        # V2 Skill YAML 定义
│   │
│   └── runtime/                       # ⭐⭐ Runtime 核心
│       ├── __init__.py                # V2+V3 统一导出
│       ├── core.py                    # ⭐ StoryFlowRuntime (V3 主入口)
│       ├── event_bus.py               # ⭐ EventBus (异步 pub/sub)
│       ├── blackboard.py              # ⭐ Blackboard (共享状态)
│       ├── artifact_manager.py        # ⭐ ArtifactManager (文件化)
│       ├── session_manager.py         # ⭐ SessionManager (会话跟踪)
│       ├── hooks.py                   # ⭐ HookFramework
│       ├── workflow_engine.py         # ⭐ WorkflowEngine (步骤执行)
│       ├── director.py                # ⭐ DirectorAgent (决策)
│       ├── planner.py                 # ⭐ PlannerAgent (DAG 拆解)
│       ├── agent_sdk.py               # ⭐ BaseAgent + AgentRegistry
│       ├── quality/                   # ⭐ QualityEngine (6 种 Checker)
│       ├── adapters/                  # ⭐ Model Adapters (可插拔)
│       │
│       ├── app.py                     # V2 RuntimeApp (legacy)
│       ├── adapter.py                 # V2 适配器 (legacy)
│       ├── agent_runtime/             # V2 Agent 运行时 (legacy)
│       ├── execution/                 # V2 调度器 (legacy)
│       ├── conversation/              # V2 对话管理 (legacy)
│       ├── skill_engine/              # V2 Skill 引擎 (legacy)
│       ├── memory/                    # V2 记忆系统 (legacy)
│       ├── session/                   # V2 会话管理 (legacy)
│       ├── hook/                      # V2 事件钩子 (legacy)
│       ├── handlers/                  # V2 Handler (legacy)
│       ├── mcp/                       # V2 MCP 协议 (legacy)
│       └── message_bus/               # V2 消息总线 (legacy)
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
│   ├── .env.example                  # 含 V3 新配置项
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

# 后端 (LangGraph 模式，默认)
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 后端 (V3 Runtime 模式)
USE_V3_RUNTIME=true python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

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

### Runtime 后端选择

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `USE_RUNTIME` | `false` | Agent OS Runtime v2.0 |
| `USE_V3_RUNTIME` | `false` | ⭐ StoryFlow Runtime V3 (推荐) |

### V3 Runtime 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE_API_PROVIDER` | `comfyui` | 图片后端 (`comfyui` / `mock`) |
| `VOICE_API_PROVIDER` | `cosyvoice` | 语音后端 (`cosyvoice` / `mock`) |
| `VIDEO_API_PROVIDER` | `ffmpeg` | 视频后端 (`ffmpeg` / `mock`) |
| `ARTIFACT_PATH` | `./artifacts` | 中间产物存储目录 |

## 演进路线

| 阶段 | 目标 | Agent 改动 | 状态 |
|------|------|-----------|------|
| **V1** | Runtime 接管调度 + Session + Artifact | ❌ 零改动 | ✅ |
| **V1.5** | EventBus + Blackboard + Hook 事件驱动 | ❌ 零改动 | ✅ |
| **V2** | Director Agent 失败重试/质量回流 | ❌ 零改动 | ✅ |
| **V2.5** | Planner Agent 动态 DAG 拆解 | ❌ 零改动 | ✅ |
| **V3** | Quality Engine + Adapter + SDK + DSL | ⚠️ 少量 | ✅ |

**整个演进过程：不推翻已有代码，在 StoryFlow AI 基础上逐层抽象 Runtime 能力。**

## License

MIT