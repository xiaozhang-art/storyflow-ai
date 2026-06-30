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
│  │(OpenAI兼容)│ │(DashScope)│  │(DashScope)│  │(Kling)  │ │
│  └──────────┘  └───────────┘  └───────────┘  └──────────┘ │
│  ┌──────────┐  ┌───────────┐                               │
│  │  Video   │  │ Mock 降级  │  ComfyUI (SDXL) 可选回退     │
│  │ (FFmpeg) │  │           │                               │
│  └──────────┘  └───────────┘                               │
└─────────────────────────────────────────────────────────────┘
```

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

Director prompt 包含：管线位置、全部产出物摘要、重试上下文、历史决策记录。无 LLM 时自动降级为规则引擎。ArtifactManager 跟踪所有管线输出并支持 rollback。

Bug 修复：WorkflowEngine 正确处理 SKIP（推进管线索引，避免死循环）；持久性失败在 2 次重试后自动跳过。

#### Phase 2: A2A 富上下文传递 ✅

AgentConversationBus 升级为结构化富上下文（非纯文本摘要），A2A 消息携带：

- 角色档案（Character Profiles）
- 场景数据 + 角色-场景映射
- 生成统计（Generation Stats）
- 产出物引用（Artifact References）
- 约束：模板约束（按转换类型）+ 动态约束（按状态，如角色一致性、集数检查）
- 反馈：质量门禁错误、警告和修复建议

WorkflowEngine 在每个步骤执行前自动将 A2A 消息注入 Agent 状态。

#### Phase 3: StoryMemory 统一记忆系统 ✅

全新 7 维记忆架构（Scene/Visual/Style/World + Character/Timeline），全部异步 API：

| 维度 | 内容 |
|------|------|
| Scene Memory | 场景剧情、对话、过渡 |
| Visual Memory | 角色外观、场景视觉描述 |
| Style Memory | 叙事风格、镜头语言、节奏 |
| World Memory | 世界观设定、规则、背景知识 |
| Character Memory | 角色档案、性格、关系 |
| Timeline Memory | 剧情时间线、事件顺序 |
| Meta Memory | 生成统计、质量评分 |

4 层记忆层级（Working / Session / Conversation / Long-term）支持 TTL 自动过期。MemoryGraph 提供时间线感知的角色状态追踪。WorkflowEngine 每步执行前自动查询并注入记忆上下文，执行后自动存储产出物。

### 核心设计

- **Director 5-决策循环** — 每步执行后 Director 分析全部产出物，做出 PROCEED/RETRY/ROLLBACK/REWRITE_PROMPT/SKIP 决策，实现根因驱动的智能管线控制
- **A2A 结构化消息** — Agent 间通过携带角色档案、场景数据、约束模板、质量反馈的结构化消息通信，而非纯文本摘要
- **实时进度推送** — Redis PubSub + WebSocket，前端 7 步进度条实时更新
- **数据库持久化** — 每个 Agent 完成后立即写入 PostgreSQL，WorkflowEngine 支持增量持久化
- **容错与降级** — 图片/配音/视频 Agent 按场景粒度 try/catch，部分失败不中断整体流程；Adapter 层 Mock 降级
- **自动重试** — Script/Character/Storyboard Agent 使用 tenacity 3 次指数退避重试；Image Agent 每张图最多 2 次重试；Director 持久性失败 2 次后 SKIP
- **LLM 工厂模式** — `get_creative_llm()` (temp=0.8) / `get_precise_llm()` (temp=0.4) 按场景选用，实例缓存复用
- **结构化输出** — Script/Character Agent 用 `PydanticOutputParser`；Storyboard Agent 双策略（Pydantic 优先 + JSON fallback）
- **Prompt 外部化** — 所有 Agent Prompt 集中在 `prompts/` 模块，与 Agent 逻辑解耦；PromptRuntime 动态组装记忆+反思+指令
- **零本地 GPU** — 全部使用云端 API（LLM/Image/Voice/I2V），ComfyUI 仅作可选本地回退

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18, TypeScript, Vite 5, Ant Design 5, Axios | SPA，3 页面 |
| **后端** | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 | 异步全栈 |
| **Agent 框架** | LangChain, ChatOpenAI | 7-Agent 串行管线 |
| **Runtime** | Agent OS Runtime V5.0 | Director / A2A / StoryMemory / Reflection / PromptRuntime / MemoryGraph / ModelRouter |
| **数据库** | PostgreSQL 16 (asyncpg) | 故事 / 角色 / 场景 / 任务 |
| **缓存** | Redis 7 | 任务状态 + PubSub |
| **向量数据库** | Qdrant | 角色记忆检索 |
| **图像生成** | DashScope (通义万相) / DALL-E 3 | ComfyUI (SDXL) 可选回退 |
| **语音合成** | DashScope TTS (CosyVoice) | 男/女声自动映射 |
| **图生视频** | Kling / Runway | 3-5 秒动态视频 |
| **视频合成** | FFmpeg | 图片+音频→视频→字幕烧录→拼接 |
| **部署** | Docker Compose, Nginx | 一键部署 |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                        # FastAPI 入口 (Runtime 初始化 + CORS + 路由)
│   ├── core.py                        # V5.0 核心组装 (Director + WorkflowEngine + StoryMemory)
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
│   ├── agents/                        # ⭐ 7 个 AI Agent
│   │   ├── script_agent.py            # 剧本 (tenacity 3x, PydanticOutputParser)
│   │   ├── character_agent.py         # 角色视觉卡片 (AppearanceCard 强类型)
│   │   ├── storyboard_agent.py        # 分镜 (双策略: Pydantic + JSON fallback)
│   │   ├── image_agent.py             # 图片生成 (逐场景重试, 部分容错)
│   │   ├── image_to_video_agent.py    # 图生视频 (Kling/Runway)
│   │   ├── voice_agent.py             # 语音合成 (性别→音色, 部分容错)
│   │   └── video_agent.py             # FFmpeg (实际时长对齐字幕, 烧录, 拼接)
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict
│   │   ├── story_workflow.py          # LangGraph 编排
│   │   └── runtime_workflow.py        # V1.5 Runtime 适配层
│   │
│   ├── tools/
│   │   ├── comfyui_client.py          # ComfyUI (可选本地回退)
│   │   ├── cosyvoice_client.py        # CosyVoice TTS
│   │   └── ffmpeg_tool.py
│   │
│   ├── adapters/                      # ⭐ 5 类 Adapter (LLM/Image/I2V/Voice/Video)
│   │
│   ├── tasks/
│   │   └── runner.py                  # 任务运行器 (持久化)
│   │
│   ├── app/
│   │   ├── database.py
│   │   ├── redis.py
│   │   └── llm.py                     # LLM 工厂 (creative / precise)
│   │
│   ├── memory/
│   │   ├── vector_store.py            # Qdrant 向量记忆
│   │   ├── models.py                  # MemoryEntry / MemoryQuery / MemoryType
│   │   └── manager.py                 # MemoryManager (4 层 + TTL)
│   │
│   ├── utils/
│   │   └── json_helper.py
│   │
│   ├── skills/                        # Skill 定义
│   │
│   └── runtime/                       # ⭐ V1.5 Runtime (V5.0)
│       ├── core.py                    # Director + WorkflowEngine + StoryMemory 组装
│       ├── director.py                # Director (LLM 5-决策大脑 + 规则降级)
│       ├── workflow_engine.py         # WorkflowEngine (Director 集成 + A2A + 记忆)
│       ├── agent_conversation.py      # AgentConversationBus (A2A 富上下文)
│       ├── prompt_runtime.py          # PromptRuntime (动态 Prompt 构建)
│       ├── reflection_runtime.py      # ReflectionRuntime (good/bad/suggestion)
│       ├── quality_engine.py          # QualityEngine (6 个 Checker)
│       ├── retry_engine.py            # RetryEngine (策略化重试)
│       ├── trace_runtime.py           # TraceRuntime (全链路追踪)
│       ├── model_router.py            # ModelRouter (智能模型选择)
│       ├── memory/                    # StoryMemory (7 维统一记忆)
│       │   ├── story_memory.py
│       │   └── memory_graph.py        # MemoryGraph (时间线角色状态)
│       └── ...                        # AdapterRegistry / EventBus / Session
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
│           ├── StoryPage.tsx          # 7 步进度 + WebSocket
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
- **外部 API**（远程服务，零本地 GPU 依赖）：
  - OpenAI 兼容 LLM API（GPT-4o / Qwen / DeepSeek 等）
  - DashScope API（图片生成 + TTS）
  - Kling / Runway API（图生视频）
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
┌───────────────────────────────────────────────────────────┐
│                   Director 决策循环                         │
│                                                           │
│  ArtifactManager (全部产出物) ──→ Director (LLM 分析)     │
│                                    │                      │
│                    ┌───────────────┼───────────┐          │
│                    ▼               ▼           ▼          │
│                PROCEED        RETRY/ROLLBACK  REWRITE     │
│                    │          /REWRITE_PROMPT  _PROMPT     │
│                    │               │            │          │
│                    ▼               ▼            ▼          │
│  StoryMemory (注入记忆) ──→ Agent 执行 ──→ A2A 消息传递   │
│                                    │                      │
│                            Reflection 反思               │
│                           (good/bad/suggestion)           │
│                                    │                      │
│                              QualityEngine                 │
│                                    │                      │
│                            Director 下一轮决策             │
└─────────────────────────┬─────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Script Agent  │→│Character Agent│→│Storyboard    │
│ temp=0.8      │  │ temp=0.4     │  │ Agent        │
│ tenacity 3x   │  │ tenacity 3x  │  │ tenacity 3x/集│
└──────────────┘  └──────────────┘  └──────┬───────┘
                                          │
                    ┌─────────────────────┼──────────────┐
                    ▼                     ▼              ▼
            ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
            │ Image Agent  │  │I2V Agent     │  │ Voice Agent  │
            │ DashScope/   │  │ Kling/Runway │  │ DashScope    │
            │ DALL-E 3     │  │ 3-5s/场景    │  │ TTS          │
            │ 2x 重试/镜   │  │ 部分容错     │  │ 部分容错     │
            └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                   │                 │                 │
                   └─────────────────┼─────────────────┘
                                     ▼
                           ┌──────────────────┐
                           │  Video Agent     │
                           │  FFmpeg 合成     │
                           │  图片+音频+字幕  │
                           │  → story.mp4     │
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
| `DASHSCOPE_API_KEY` | — | DashScope API Key（图片 + TTS） |
| `KLING_API_KEY` | — | Kling API Key（图生视频） |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant |
| `STORAGE_PATH` | `./storage` | 文件存储 |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI（可选本地回退） |
| `COMFYUI_POLL_TIMEOUT` | `300` | 单张图最大等待秒数 |
| `COMFYUI_MAX_RETRIES` | `2` | 单张图重试次数 |
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse 公钥（可选，启用可观测性） |
| `LANGFUSE_SECRET_KEY` | — | Langfuse 密钥 |
| `MEMORY_WORKING_TTL` | `300` | 工作记忆 TTL (秒) |
| `MEMORY_SESSION_TTL` | `86400` | 会话记忆 TTL (秒) |

> **注意：** V1.5 Runtime 是默认且唯一的运行时，无需设置 `USE_RUNTIME` 环境变量。旧版 LangGraph 管线已移除。

## License

MIT