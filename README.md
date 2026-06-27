<div align="center">

# StoryFlow AI

**AI 漫剧自动生成平台 — Project Runtime v3**

用户输入一段创意，系统通过 6 个 Agent 串联协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 配音合成 → 视频导出**。

[核心设计](#核心设计) · [架构](#架构) · [项目结构](#项目结构) · [快速开始](#快速开始) · [API](#api) · [配置](#配置)

</div>

---

## 核心设计

StoryFlow AI 围绕 AI 漫剧生成中的三个根本性难题设计，每个难题对应一个核心子系统：

### ① 长篇一致性 — StoryWorld

**问题**：第 5 集的女主和第 1 集长得完全不一样，因为 Agent 没有记忆、每次独立生成。

**方案**：不是 Chat History，不是 RAG Memory，而是结构化的 **Story Bible** — 参考影视编剧的专业做法，建立全局唯一的"世界模型"。

```
StoryWorld
├── Story Bible         故事圣经：标题 / 类型 / 风格 / 总集数 / 视觉风格
├── Character Library   角色库：四维外观(hair/body/cloth/face) / 性格 / 口头禅 / 当前状态
├── Location Library    地点库：视觉描述 / 氛围风格
├── Timeline            时间线：Git 式状态变更记录，每次修改自动版本递增
├── Relationship Graph  关系图：角色间关系（friend/enemy/lover/...）
└── Lore                世界观设定：魔法体系 / 科技水平 / 文化规则
```

所有 Agent **只读** StoryWorld。Image Agent 不需要"记住"上一张图长什么样 — 它直接从 Character Library 获取完整的四维外观描述拼入 Prompt。角色状态变更像 Git commit 一样记录在 Timeline 中，女主第 3 集受伤后，第 4 集的 Agent 自然能看到 `current_state: {injured: true}`。

**用户 Patch 机制**：用户说"女主太胖"，系统调用 `apply_patch("林晓", "appearance.cloth", "white dress", "black armor")` 精确修改字段。StoryWorld 版本递增，后续所有生成自动采用新外观，无需重跑全部。

```python
# Patch 一次，后续自动生效
world.apply_patch("林晓", "appearance.cloth", "white dress", "black armor")
# 第 4 集及之后的 Image Agent 自动使用 "black armor"
```

### ② 质量可控 — QualityEngine

**问题**：一个 LLM Prompt 做质检，判断模糊且无法结构化处理，也不知道该重试还是该问人。

**方案**：不是 Reviewer Agent，而是**结构化的多 Checker 审核引擎**。每个管线步骤配置独立的 Checker 集合，每个 Checker 确定性返回四种判定之一：

| 判定 | 含义 | Runtime 行为 |
|------|------|-------------|
| `PASS` | 通过 | 继续下一步 |
| `FAIL` | 不可恢复的错误 | 终止当前步骤 |
| `RETRY` | 可修复，附修复提示 | 用 hint 重试（最多 2 次） |
| `ASK_USER` | 需要人工判断 | 暂停，触发 Human Review |

**7 个内置 Checker，按步骤灵活组合：**

| Checker | 检查内容 | 默认启用步骤 |
|---------|---------|-------------|
| `CharacterConsistencyChecker` | 角色 hair/body/cloth/face 是否在 Prompt 中完整出现 | character, image |
| `SceneContinuityChecker` | 场景是否尊重 Timeline 中的最近状态变更 | storyboard |
| `ScriptStructureChecker` | 剧本结构完整性（集数 / 标题 / 摘要长度 / 角色数量） | script |
| `DialogueChecker` | 台词与角色 personality 是否匹配 | — |
| `StyleChecker` | 产出物 Prompt 是否包含 Story Bible 定义的 visual_style | storyboard, image |
| `SafetyChecker` | 内容安全关键词过滤 | script, character, storyboard |
| `FileExistenceChecker` | 产出物文件是否真实存在于磁盘 | image, voice, video |

**Human Review Checkpoint**：`script` 和 `character` 步骤完成后自动暂停，推送审核摘要给用户。用户可以 Approve 继续，或提交 Patch（如修改角色外观），系统自动应用后继续生成。

### ③ 长任务可恢复 — Project + Checkpoint

**问题**：生成 6 集漫剧需要 30+ 分钟，浏览器关闭、服务重启就全丢了。

**方案**：不是 Session，而是 **Project**。每个故事是一个独立 Project，拥有独立的 Runtime 实例和完整的生命周期管理。

```
Project
├── StoryWorld        知识资产，随项目持久化
├── Workspace         所有生成物按 {project}/episodes/ep01/{images,audio,subtitles}/ 组织
├── CheckpointStore   每步完成后自动存档（StoryWorld 快照 + 产出物路径 + 元信息）
└── Status            created → running → paused → completed / failed
```

**Checkpoint 像游戏存档**：每完成一个管线步骤（script → character → storyboard → image → voice → video），自动保存当前 StoryWorld 完整快照、所有已生成的文件路径、当前进度。今天生成 1-3 集后关闭浏览器，明天通过 `POST /api/story/{id}/resume` 从第 4 集继续。Checkpoint 恢复时自动还原 StoryWorld 状态，Agent 拿到的是和上次结束时完全一致的知识。

```bash
# 查看所有存档
curl /api/story/{id}/checkpoints

# 从存档恢复，继续生成
curl -X POST /api/story/{id}/resume
```

## 架构

```
Agent → Capability → Workspace → Quality → Hook → EventBus → Next Agent
```

**ProjectRuntime** 是顶层编排器，每个 Project 拥有独立实例：

```
ProjectRuntime
│
├── StoryWorld          结构化世界模型 (Story Bible + Character + Location + Timeline)
├── Workspace           文件管理 (按 project/episode/scene 组织)
├── CheckpointStore     存档 / 恢复 (StoryWorld 快照 + 产出物)
├── QualityEngine       质量审核 (7 个 Checker, PASS/FAIL/RETRY/ASK_USER)
├── CapabilityRegistry  能力驱动 (Agent 声明需求, Runtime 提供实现)
├── HookManager         生命周期扩展 (16 种事件, 优先级, 同步/异步)
└── EventBus            轻量本地事件总线 (Python 进程内)
```

### 关键设计决策

**Agent 只做 Planner，能力由 Capability 提供。** Image Agent 不直接调用 ComfyUI API，而是声明 `use_capability("generate_image", {...})`。以后从 Stable Diffusion 切换到 FLUX，只需实现新的 `GenerateImageCapability` 并注册，不动 Agent 代码。

**所有横切逻辑走 Hook，不污染 Agent。** 日志、Token 统计、Langfuse Tracing、进度推送、自动重试 — 全部通过 HookManager 监听 16 种生命周期事件挂接：

| 事件分类 | 事件 |
|---------|------|
| Agent 生命周期 | `BEFORE_AGENT` / `AFTER_AGENT` |
| Capability 生命周期 | `BEFORE_CAPABILITY` / `AFTER_CAPABILITY` |
| 质量审核 | `QUALITY_CHECK` / `QUALITY_PASSED` / `QUALITY_FAILED` / `QUALITY_ASK_USER` |
| 存档 | `CHECKPOINT_SAVE` / `CHECKPOINT_RESTORE` |
| 人工审核 | `HUMAN_REVIEW_REQUEST` / `HUMAN_FEEDBACK` |
| 世界状态 | `WORLD_UPDATE` |
| 项目生命周期 | `PROJECT_START` / `PROJECT_COMPLETE` / `PROJECT_RESUME` / `PROJECT_ERROR` |

**4 个内置 Capability：**

| Capability | 底层服务 | 说明 |
|-----------|---------|------|
| `generate_image` | ComfyUI (SDXL) | 文生图，支持 SDXL workflow + poll |
| `generate_voice` | CosyVoice | TTS 语音合成，支持 base64/URL/raw 三种响应 |
| `merge_video` | FFmpeg | Scene 级视频拼接 + 字幕烧录 |
| `generate_storyboard` | LLM | 通过 `context["llm_caller"]` 注入，不直接耦合 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18, TypeScript, Vite 5, Ant Design 5 |
| 后端 | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 |
| Agent | LangChain ChatOpenAI, 6-Agent 串行管线 |
| Runtime | Project Runtime v3 (StoryWorld + QualityEngine + Checkpoint + Capability + Hook) |
| 数据库 | PostgreSQL 16, Redis 7 |
| 图像 | Stable Diffusion XL via ComfyUI |
| 语音 | CosyVoice TTS |
| 视频 | FFmpeg |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                          # FastAPI 入口 (v3.0.0)
│   ├── .env                             # 环境变量
│   ├── configs/settings.py              # 配置管理
│   ├── models/                          # SQLAlchemy ORM
│   │   ├── story.py                     # Story
│   │   ├── episode.py                   # Episode
│   │   ├── character.py                 # Character
│   │   ├── scene.py                     # Scene
│   │   └── task.py                      # Task
│   ├── api/                             # API 路由
│   │   ├── story.py                     # 故事 CRUD + world/patch/checkpoints/resume
│   │   └── task.py                      # 任务状态 + WebSocket 进度
│   ├── agents/                          # 6 个 Agent
│   │   ├── script_agent.py              # 剧本生成
│   │   ├── character_agent.py           # 角色设计
│   │   ├── storyboard_agent.py          # 分镜编排
│   │   ├── image_agent.py               # 图片生成
│   │   ├── voice_agent.py               # 配音合成
│   │   └── video_agent.py               # 视频导出
│   ├── tasks/runner.py                  # 管线编排 → ProjectRuntime
│   ├── app/                             # database / redis / llm 基础设施
│   ├── schemas/                         # Pydantic 请求/响应模型
│   ├── services/                        # 业务逻辑
│   ├── repositories/                    # 数据访问层
│   ├── prompts/                         # Prompt 模板
│   └── runtime/v3/                      # Project Runtime 核心
│       ├── __init__.py                  # 统一导出, __version__ = "3.0.0"
│       ├── project.py                   # Project + ProjectRuntime (顶层编排)
│       ├── world/
│       │   └── story_world.py           # StoryWorld (Story Bible + Character + Location + Timeline)
│       ├── quality/
│       │   └── engine.py                # QualityEngine + 7 个 Checker
│       ├── capability/
│       │   └── registry.py              # CapabilityRegistry + 4 个内置 Capability
│       ├── hook/
│       │   └── manager.py               # HookManager (16 种事件)
│       ├── checkpoint/
│       │   └── store.py                 # CheckpointStore (存档/恢复)
│       ├── event_bus.py                 # EventBus (轻量本地事件总线)
│       └── workspace.py                 # Workspace (文件工作区)
├── frontend/
│   └── src/
│       ├── pages/                       # HomePage / StoryPage / ResultPage
│       └── api/                         # API + WebSocket 客户端
└── deploy/
    ├── docker-compose.yml               # PostgreSQL + Redis + ComfyUI + CosyVoice
    └── .env.example                     # 环境变量模板
```

## 快速开始

### 前提

- Python 3.11+, Node.js 18+, FFmpeg
- Docker（用于 PostgreSQL + Redis）
- **LLM API Key**：兼容 OpenAI API 格式（推荐 [DeepSeek](https://platform.deepseek.com/)，几毛钱就能跑通）

> **ComfyUI 和 CosyVoice 是可选的。** 系统会自动检测这些服务是否可用，不可用时使用占位图/静默音频跑通全流程，方便你先验证 LLM 管线（剧本→角色→分镜）是否正常。接入真实服务后自动切换，无需改代码。

### 运行模式

| 模式 | 需要什么 | 能跑通哪些步骤 |
|------|---------|---------------|
| **LLM Only** | LLM API Key + PostgreSQL + Redis | 剧本 → 角色 → 分镜 → 占位图 → 静默音 → 视频 |
| **全功能** | 上面全部 + ComfyUI + CosyVoice | 剧本 → 角色 → 分镜 → SD 出图 → 真实配音 → 视频 |

### 1. 基础服务（PostgreSQL + Redis）

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

# 配置 .env（必填 LLM_API_KEY，推荐用 DeepSeek 测试）
cat > .env << 'EOF'
LLM_API_KEY=sk-your-key-here
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
DATABASE_URL=postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow
REDIS_URL=redis://localhost:6379/0
STORAGE_PATH=./storage
EOF

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 前端

```bash
cd frontend && npm install && npm run dev
```

### 4. （可选）接入 ComfyUI 和 CosyVoice

系统启动时会自动检测 `COMFYUI_URL`（默认 `http://localhost:8188`）和 `COSYVOICE_URL`（默认 `http://localhost:50000`）。如果检测到服务在线，图片和语音步骤会自动使用真实服务；否则使用 Mock 生成占位内容。

```bash
# ComfyUI（SDXL 图像生成）
# 参考官方文档部署：https://github.com/comfyanonymous/ComfyUI
# 确保加载了 SDXL 模型，启动后默认监听 8188 端口

# CosyVoice（TTS 语音合成）
# 参考官方文档部署：https://github.com/FunAudioLLM/CosyVoice
# 启动 API 服务后默认监听 50000 端口
```

### 验证

| 地址 | 说明 |
|------|------|
| http://localhost:3000 | 前端界面 |
| http://localhost:8000/docs | Swagger API 文档 |
| http://localhost:8000/health | 健康检查 |

## API

### 故事管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/story` | 创建故事项目 |
| `GET` | `/api/story` | 故事列表 |
| `GET` | `/api/story/{id}` | 故事详情 |
| `POST` | `/api/story/{id}/generate` | 启动生成管线 |
| `GET` | `/api/story/{id}/result` | 获取生成结果 |

### StoryWorld 与 Patch

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/story/{id}/world` | 查看当前 StoryWorld 完整状态 |
| `POST` | `/api/story/{id}/patch` | 应用 Patch 修改角色/世界观 |

### 存档与恢复

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/story/{id}/checkpoints` | 查看所有存档 |
| `POST` | `/api/story/{id}/resume` | 从最新存档恢复生成 |

### 任务与进度

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/task/{id}` | 任务状态 |
| `WS` | `/api/task/{id}/ws` | WebSocket 实时进度推送 |

### 示例

```bash
# 创建故事
curl -X POST /api/story -H "Content-Type: application/json" -d '{
  "title": "星际迷途",
  "genre": "sci-fi",
  "prompt": "一群年轻宇航员在超空间跳跃后迷失在未知星系..."
}'

# 启动生成
curl -X POST /api/story/{id}/generate

# 修改角色服装 — 后续图片自动使用新外观
curl -X POST /api/story/{id}/patch -H "Content-Type: application/json" -d '{
  "character_name": "林晓",
  "field_path": "appearance.cloth",
  "old_value": "white dress",
  "new_value": "black armor with silver trim"
}'

# 查看存档列表
curl /api/story/{id}/checkpoints

# 中断后恢复生成
curl -X POST /api/story/{id}/resume
```

## 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | **必填** LLM API 密钥 |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `DATABASE_URL` | `postgresql+asyncpg://storyflow:storyflow@localhost:5432/storyflow` | PostgreSQL 连接 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接 |
| `COMFYUI_URL` | `http://localhost:8188` | ComfyUI 服务地址 |
| `COSYVOICE_URL` | `http://localhost:50000` | CosyVoice 服务地址 |
| `STORAGE_PATH` | `./storage` | 文件存储根目录 |
| `MAX_EPISODES` | `6` | 单次生成最大集数 |
| `COMFYUI_POLL_TIMEOUT` | `300` | 单图最大等待时间（秒） |
| `COMFYUI_MAX_RETRIES` | `2` | 单图生成重试次数 |

## License

MIT