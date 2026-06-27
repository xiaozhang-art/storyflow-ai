<div align="center">

# StoryFlow AI

**AI 漫剧自动生成平台**

用户输入一段创意，系统通过 6 个 Agent 串联协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**。

[核心设计](#核心设计) · [快速开始](#快速开始) · [API](#api) · [配置](#配置)

</div>

---

## 核心设计

StoryFlow AI 围绕 AI 漫剧的三个核心痛点设计：

### ① 长篇一致性 — StoryWorld

不是 Chat History，不是 Memory，而是结构化的 **Story Bible**。

```
StoryWorld
├── Story Bible        （故事圣经：标题/类型/风格/集数）
├── Character Library  （角色库：四维外观/性格/口头禅/当前状态）
├── Location Library   （地点库：视觉风格/氛围描述）
├── Timeline           （时间线：Git 式状态变更记录）
├── Relationship Graph （关系图：角色间关系）
└── Lore               （世界观设定）
```

所有 Agent 只读 StoryWorld，不自己总结。Image Agent 根据 Character Library 生成 Prompt，而非"根据上一张图"。角色状态变更像 Git commit 一样记录，女主受伤后后续所有 Image 自然知道。

**用户 Patch 机制**：用户说"女主太胖"，系统生成 Patch 修改 `appearance.cloth`，StoryWorld 更新后后续生成自动采用，不需要重跑全部。

### ② 质量可控 — QualityEngine

不是 Reviewer Agent（一个 Prompt 判断质量），而是**结构化的多 Checker 审核引擎**。

每个产出物经过多个独立 Checker，每个返回 PASS / FAIL / RETRY / ASK_USER：

| Checker | 检查内容 |
|---------|---------|
| CharacterConsistencyChecker | 角色四维外观是否在 Prompt 中完整 |
| SceneContinuityChecker | 场景是否尊重 Timeline 最近状态变更 |
| ScriptStructureChecker | 剧本结构完整性（集数/角色数/摘要长度） |
| DialogueChecker | 台词与角色人设是否匹配 |
| StyleChecker | 产出物是否符合 Story Bible 定义的视觉风格 |
| SafetyChecker | 内容安全过滤 |
| FileExistenceChecker | 产出物文件是否真实生成 |

**Human Review Checkpoint**：关键节点（剧本/角色）自动暂停，等用户确认后继续。

### ③ 长任务可恢复 — Project + Checkpoint

不是 Session，而是 **Project**。

```
Project
├── StoryWorld     （知识资产，随项目持久化）
├── Workspace      （所有生成物，按项目组织）
├── Checkpoint     （每步自动存档，像游戏存档）
└── Status         （created → running → paused → completed）
```

今天生成 1-3 集，明天从第 4 集继续。关闭网页再回来，Checkpoint 自动恢复。

## 架构

```
Agent → Capability → Workspace → Quality → Hook → Event → Next Agent
```

```
ProjectRuntime
│
├── StoryWorld          长期知识（Story Bible）
├── Workspace           文件管理（图片/音频/视频/字幕）
├── CheckpointStore     存档/恢复
├── QualityEngine       质量审核（7 个 Checker）
├── CapabilityRegistry  能力驱动（Agent 不硬编码 ComfyUI/CosyVoice）
├── HookManager         生命周期扩展（16 种事件）
└── EventBus            轻量事件总线
```

**Agent 只做 Planner，能力由 Capability 提供。** 以后换 SD → FLUX，只改 Capability 实现，不动 Agent。

**所有横切逻辑走 Hook，不污染 Agent。** Langfuse Tracing / Token 统计 / 自动重试 / 进度推送都通过 Hook 挂接。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18, TypeScript, Vite 5, Ant Design 5 |
| 后端 | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 |
| Agent | LangChain ChatOpenAI, 6-Agent 串行管线 |
| Runtime | Project Runtime（StoryWorld + Quality + Checkpoint + Capability + Hook） |
| 数据库 | PostgreSQL 16, Redis 7 |
| 图像 | Stable Diffusion XL via ComfyUI |
| 语音 | CosyVoice TTS |
| 视频 | FFmpeg |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                     # FastAPI 入口
│   ├── .env                        # 环境变量
│   ├── configs/settings.py         # 配置
│   ├── models/                     # SQLAlchemy ORM (Story/Episode/Character/Scene/Task)
│   ├── api/                        # API 路由
│   ├── agents/                     # 6 个 Agent
│   │   ├── script_agent.py
│   │   ├── character_agent.py
│   │   ├── storyboard_agent.py
│   │   ├── image_agent.py
│   │   ├── voice_agent.py
│   │   └── video_agent.py
│   ├── tasks/runner.py             # 任务运行器
│   ├── app/                        # database / redis / llm
│   ├── schemas/                    # Pydantic schemas
│   ├── services/                   # 业务逻辑
│   ├── repositories/               # 数据访问
│   ├── prompts/                    # Prompt 模板
│   └── runtime/v3/                 # Project Runtime
│       ├── project.py              # Project + ProjectRuntime
│       ├── world/                  # StoryWorld (Story Bible)
│       ├── quality/                # QualityEngine + 7 Checkers
│       ├── capability/             # Capability Registry
│       ├── hook/                   # HookManager (16 事件)
│       ├── checkpoint/             # Checkpoint Store
│       ├── event_bus.py            # EventBus
│       └── workspace.py            # 文件工作区
├── frontend/                       # React + Ant Design
│   └── src/
│       ├── pages/                  # HomePage / StoryPage / ResultPage
│       └── api/                    # API + WebSocket
└── deploy/
    └── docker-compose.yml
```

## 快速开始

### 前提

- Python 3.11+, Node.js 18+, FFmpeg, Docker
- **必填**：LLM API Key（OpenAI / DeepSeek / 智谱 / Moonshot 等）
- **必填**：[ComfyUI](https://github.com/comfyanonymous/ComfyUI)（SDXL 图像生成）
- **必填**：[CosyVoice](https://github.com/FunAudioLLM/CosyVoice)（TTS 语音合成）

### 1. 基础服务

```bash
# PostgreSQL + Redis
docker run -d --name sf-pg -p 5432:5432 \
  -e POSTGRES_USER=storyflow -e POSTGRES_PASSWORD=storyflow -e POSTGRES_DB=storyflow \
  postgres:16-alpine

docker run -d --name sf-redis -p 6379:6379 redis:7-alpine
```

### 2. 后端

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 配置 .env（必填 LLM_API_KEY）
# 用 DeepSeek 测试最便宜：
#   LLM_API_KEY=sk-xxx  LLM_MODEL=deepseek-chat  LLM_BASE_URL=https://api.deepseek.com/v1

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 前端

```bash
cd frontend && npm install && npm run dev
```

| 地址 | 说明 |
|------|------|
| http://localhost:3000 | 前端 |
| http://localhost:8000/docs | API 文档 |
| http://localhost:8000/health | 健康检查 |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成 |
| `GET` | `/api/story/{id}/result` | 生成结果 |
| `GET` | `/api/story/{id}/world` | 查看 StoryWorld |
| `POST` | `/api/story/{id}/patch` | 应用 Patch（改角色外观等） |
| `GET` | `/api/story/{id}/checkpoints` | 查看存档列表 |
| `POST` | `/api/story/{id}/resume` | 从存档恢复生成 |
| `GET` | `/api/task/{id}` | 任务状态 |
| `WS` | `/api/task/{id}/ws` | WebSocket 实时进度 |

### Patch 示例

```bash
# 修改角色服装 — 以后所有图片自动使用新外观
curl -X POST /api/story/{id}/patch -H "Content-Type: application/json" -d '{
  "character_name": "林晓",
  "field_path": "appearance.cloth",
  "new_value": "black armor with silver trim"
}'

# 查看存档
curl /api/story/{id}/checkpoints

# 从存档恢复
curl -X POST /api/story/{id}/resume
```

## 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | **必填** |
| `LLM_MODEL` | `gpt-4o` | 模型名 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | API 地址 |
| `DATABASE_URL` | `postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow` | 数据库 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI |
| `COSYVOICE_URL` | `http://localhost:50000` | CosyVoice |
| `STORAGE_PATH` | `./storage` | 文件存储 |
| `MAX_EPISODES` | `6` | 最大集数 |
| `COMFYUI_POLL_TIMEOUT` | `300` | 单图最大等待秒数 |
| `COMFYUI_MAX_RETRIES` | `2` | 单图重试次数 |

## License

MIT