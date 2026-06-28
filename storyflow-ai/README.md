<div align="center">

# 🎬 StoryFlow AI

**基于 StoryFlow Runtime V3 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 7 个 AI Agent 协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 图生视频 → 配音合成 → 视频导出**，
最终输出可播放的 MP4 漫剧视频。

**纯云端 API 架构，零本地 GPU 依赖。不只是漫剧项目，更是一个支持 Workflow 编排、多 Agent 协作、事件驱动、可插拔模型和质量闭环的通用 AI Runtime 平台。**

[系统架构](#系统架构) · [Runtime 架构](#runtime-架构) · [快速开始](#快速开始) · [API 文档](#api-接口) · [配置说明](#配置项) · [详细文档](项目介绍.md)

</div>

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend                          │
│              (Vite 5 + TypeScript + Ant Design 5)           │
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
              │       (V3 核心)       │
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
              │     7 个 Agent        │
              │  (零改动，Runtime 调度) │
              └───────────┬───────────┘
                          │
          ┌───────┬───────┼───────┬───────┐
          ▼       ▼       ▼       ▼       ▼
    ┌──────────┐ ┌─────────┐ ┌────────┐ ┌────────┐
    │  LLM     │ │ DashScope│ │DashScope│ │ Kling/ │
    │  API     │ │ 万相 API │ │ TTS API│ │ Runway │
    │ (GPT-4o) │ │ / DALL-E │ │        │ │I2V API │
    └──────────┘ └─────────┘ └────────┘ └────────┘
```

### Runtime 能力矩阵

| 能力 | 实现 | 说明 |
|------|------|------|
| **编排** | WorkflowEngine + YAML DSL | 支持线性/并行/DAG 执行 |
| **通信** | EventBus (pub/sub) | 13 种事件类型，组件完全解耦 |
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
| **策略重试** | RetryEngine | 策略化重试：超时/限流/降级/模型切换 |
| **四层记忆** | MemoryRuntime | Session/Character/World/Timeline 共享记忆 |
| **全链路追踪** | TraceRuntime | Span/Token/Cost/Duration 可视化 |

> **核心原则：Agent 只接收输入、返回输出，禁止互相调用。Runtime 拥有唯一调度权。**

## Runtime 架构

### 设计理念

```
                    StoryFlow Runtime V3.5

                    ┌────────────────────────────┐
                    │      Director Agent        │
                    │ 全局导演 / 调度 / 决策     │
                    └────────────┬───────────────┘
                                 │
                    ┌────────────▼───────────────┐
                    │      WorkflowEngine        │
                    │  DSL + EventBus + Hooks     │
                    │  并行执行 + 检查点         │
                    └────────────┬───────────────┘
                                 │
                    ┌────────────▼───────────────┐
                    │      RetryEngine         │
                    │  策略化重试 / 降级 / 切换  │
                    └────────────┬───────────────┘
                                 │
        ┌────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
 Planner Agent           Blackboard               QualityEngine
 (动态 DAG)            (共享状态)               (质量闭环+Suggestion)
        │                        │                        │
        ▼                        ▼                        ▼
    ┌───────┐              ┌──────────┐           ┌──────────┐
    │  7    │              │ Artifacts│           │Director │
    │ Agent │              │ (文件化) │           │ (决策)   │
    └───┬───┘              └──────────┘           └──────────┘
        │
  ┌─────┼──────────────────────────────────────┐
  │     ▼                                      │
  │  ┌──────────┐  ┌──────────┐  ┌─────────────┐  │
  │  │ Memory   │  │  Trace   │  │ Adapter     │  │
  │  │ Runtime  │  │  Runtime │  │ Registry    │  │
  │  │ (4层)   │  │ (Span)   │  │ (云端API)   │  │
  │  └──────────┘  └──────────┘  └─────────────┘  │
  └──────────────────────────────────────────┘
```

### 关键特性

**1. 部分重生成（Artifact + Session）**
```
用户：重新生成第 3 幕的图片

Runtime：
  Session.reset_from_step("image")
  → 只重跑 image/image_to_video/voice/video
  → 不重跑 script/character/storyboard
```

**2. 事件驱动（EventBus）**
```python
# 任何 Agent 完成后，所有订阅者自动收到通知
event_bus.subscribe(EventType.STEP_COMPLETED, on_step_done)
```

**3. Agent 零耦合（Blackboard）**
```python
# Agent 不直接调用其他 Agent
blackboard.set("scenes.0.image_url", "/storage/scene_001.png")
# 下游 Agent 通过 Blackboard 读取上游数据
```

**4. Director 决策**
```python
# Image 失败 → Director 决定重试
# Quality 检查不通过 → Director 决定回退到 Storyboard 修改 Prompt
```

**5. 策略化重试（RetryEngine）**
```python
# Agent 永远不要自己 retry —— Runtime retry
# 内置 7 种策略：timeout / rate_limit / api_error / quality_fail / auth / content_filter / default
# 每种策略定义：max_retries, backoff, actions
# Actions: RETRY_SAME → MODIFY_PROMPT → SWITCH_MODEL → FALLBACK → ABORT
retry_engine.register_policy(RetryPolicy(
    name="image_api", max_retries=3,
    actions=[RetryAction.RETRY_SAME, RetryAction.FALLBACK],
))
```

**6. 四层记忆（MemoryRuntime）**
```python
# 所有 Agent 不只收到 prompt，而是 prompt + memory
memory.character.upsert_character("林晓", {
    "appearance": {"hair": "long black", "body": "slender", ...}
})
memory.world.set("era", "ancient China")

# Image Agent 自动获得角色外观描述
ctx = memory.build_context("image")  # → 包含 [Character Appearances] 块
```

**7. 全链路追踪（TraceRuntime）**
```
ScriptAgent    2.3s  1200 tokens
  ↓
Storyboard    5.6s  2800 tokens
  ↓
Image        32s   (7 API calls)
  ↓
Voice        12s   (7 API calls)
  ↓
Video        180s  → Total: $2.35
```

**8. 模型热切换（Adapter）**
```python
IMAGE_API_PROVIDER=dashscope  # 或 openai, 或 mock
I2V_API_PROVIDER=kling        # 或 runway, 或 mock
```

**9. 一行代码扩展 Agent（SDK）**
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
  - id: image_to_video
    agent: image_to_video
    depends_on: [image]
  - id: voice
    agent: voice
    depends_on: [storyboard]
  - id: video
    agent: video
    depends_on: [image_to_video, voice]
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
│   │   └── settings.py                # Pydantic Settings (纯 API 配置)
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
│   ├── agents/                        # 7 个 Agent (纯 API 调用)
│   │   ├── script_agent.py            # 剧本生成 (LLM)
│   │   ├── character_agent.py         # 角色视觉描述 (LLM)
│   │   ├── storyboard_agent.py        # 分镜编排 (LLM)
│   │   ├── image_agent.py             # 图片生成 (DashScope/DALL-E API)
│   │   ├── image_to_video_agent.py    # 图生视频 (Kling/Runway API)
│   │   ├── voice_agent.py             # 配音合成 (DashScope TTS API)
│   │   └── video_agent.py             # 视频合成 (FFmpeg)
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict
│   │   ├── runtime_workflow.py        # Runtime 执行入口
│   │   ├── comic.yaml                 # 漫剧 Workflow DSL (7 步)
│   │   └── novel.yaml                 # 小说 Workflow DSL
│   │
│   ├── tasks/
│   │   └── runner.py                  # 任务运行器
│   ├── app/                           # Database / Redis / LLM
│   ├── prompts/                       # Prompt 模板
│   ├── utils/                         # 工具函数
│   │
│   └── runtime/                       # ★ Runtime 核心 (V3.5)
│       ├── core.py                    # StoryFlowRuntime 主入口
│       ├── event_bus.py               # EventBus (13 种事件)
│       ├── blackboard.py              # Blackboard (点号路径)
│       ├── artifact_manager.py        # ArtifactManager (Checkpoint)
│       ├── session_manager.py         # SessionManager (部分重生成)
│       ├── hooks.py                   # HookFramework
│       ├── workflow_engine.py         # WorkflowEngine (DSL + 并行)
│       ├── director.py                # DirectorAgent (决策)
│       ├── planner.py                 # PlannerAgent (任务 DAG)
│       ├── agent_sdk.py               # BaseAgent + AgentRegistry
│       ├── retry_engine.py            # ★ RetryEngine (策略化重试)
│       ├── memory/                    # ★ MemoryRuntime (四层记忆)
│       │   ├── __init__.py            # MemoryRuntime 门面
│       │   ├── base.py                # BaseMemory 抽象基类
│       │   ├── session_memory.py      # SessionMemory (执行上下文)
│       │   ├── character_memory.py    # CharacterMemory (角色数据)
│       │   ├── world_memory.py        # WorldMemory (世界观)
│       │   └── timeline_memory.py     # TimelineMemory (事件历史)
│       ├── trace/                     # ★ TraceRuntime (全链路追踪)
│       │   └── __init__.py            # Span / TraceTree / TraceRuntime
│       ├── quality/                   # QualityEngine (6 种 Checker)
│       └── adapters/                  # 5 类 Adapter (纯云端 API)
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
│   ├── docker-compose.yml             # PostgreSQL + Redis
│   ├── nginx/default.conf
│   └── init.sql
│
├── scripts/
│   └── init_db.py
│
├── README.md                          # 本文档
└── 项目介绍.md                        # 详细技术文档
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- FFmpeg（视频合成）
- Docker & Docker Compose（可选，用于 PostgreSQL + Redis）
- **只需一个 LLM API Key 即可跑通全流程**（图片/视频/语音未配置时自动 Mock 降级）

### 方式一：本地开发

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 配置
cp deploy/.env.example backend/.env
# 编辑 backend/.env，至少填入 LLM_API_KEY

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

## 7 个 Agent 工作流

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
│  Image Agent     │  云端 API 逐镜生成
│  DashScope/DALL-E│  异步任务 + 轮询 + 下载
│  自动 Mock 降级  │  部分失败 → image_partial
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Image-to-Video   │  图片 → 动态视频片段
│  Kling / Runway  │  base64 提交 + 异步轮询
│  FFmpeg Mock 降级│  部分失败 → i2v_partial
└────────┬─────────┘
         ▼ (可与上方并行)
┌──────────────────┐
│  Voice Agent     │  云端 TTS 逐镜配音
│  DashScope TTS   │  性别→音色自动映射
│  自动 Mock 降级  │  部分容错
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Video Agent     │  FFmpeg 合成最终视频
│                  │  1. 视频片段 + 配音合并
│                  │  2. ASS 字幕烧录
│                  │  3. Concat 拼接 → story.mp4
└──────────────────┘
```

### 5 种预置管线

| 类型 | 步骤 |
|------|------|
| `comic`（漫剧） | script → character → storyboard → image → **image_to_video** → voice → video |
| `novel`（小说） | script → character → chapter_outline → text_generation |
| `animation`（动画） | script → character → storyboard → image → **image_to_video** → voice → video |
| `ad`（广告） | script → storyboard → image → **image_to_video** → voice → video |
| `movie`（电影） | script → character → storyboard → image → **image_to_video** → voice → video |

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
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `STORAGE_PATH` | `./storage` | 文件存储 |

### 云端 API 配置（全部可选，未配置自动 Mock 降级）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE_API_PROVIDER` | `dashscope` | 图片后端 (`dashscope` / `openai` / `mock`) |
| `IMAGE_API_KEY` | `''` | 图片 API Key |
| `I2V_API_PROVIDER` | `kling` | 图生视频后端 (`kling` / `runway` / `mock`) |
| `I2V_API_KEY` | `''` | 图生视频 API Key |
| `VOICE_API_PROVIDER` | `dashscope_tts` | TTS 后端 (`dashscope_tts` / `mock`) |
| `VOICE_API_KEY` | `''` | TTS API Key |

### Runtime 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_QUALITY` | `true` | 启用质量检查 |
| `ENABLE_DIRECTOR` | `false` | 启用 Director 自动决策 |
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |

### Mock 降级策略

| 未配置的服务 | 降级行为 |
|-------------|----------|
| 图片 API | 彩色占位 PNG（6 色轮转） |
| 图生视频 API | FFmpeg 静态图转视频片段 |
| TTS API | 静默 WAV 文件 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/runtime/stats` | Runtime 统计信息 |
| `POST` | `/api/runtime/session/{id}/rerun/{step}` | 部分重生成 |
| `POST` | `/api/story/` | 创建故事 |
| `GET` | `/api/story/{id}` | 获取故事详情 |
| `POST` | `/api/story/{id}/generate` | 触发生成管线 |
| `GET` | `/api/story/{id}/result` | 获取生成结果 |
| `GET` | `/api/story/{id}/world` | 查看 Session 状态快照 |
| `POST` | `/api/story/{id}/patch` | 修改角色属性 |
| `GET` | `/api/story/{id}/checkpoints` | 列出所有 Checkpoint |
| `WS` | `/api/task/{id}/ws` | 实时进度推送 |

## License

MIT