<div align="center">

# 🎬 StoryFlow AI

**基于 Multi-Agent Runtime 的 AI 漫剧自动生成平台**

用户输入一段创意，系统通过 7 个 AI Agent + Runtime 层协作，自动完成
**剧本生成 → 角色设计 → 分镜编排 → 图片生成 → 图生视频 → 配音合成 → 视频导出**，
最终输出可播放的 MP4 漫剧视频。

全部使用云端 API（LLM / 图片 / 语音 / 视频），零本地 GPU 依赖。

[系统架构](#系统架构) · [Runtime 体系](#runtime-体系) · [V1.5 路线图](#v15-迭代路线图) · [快速开始](#快速开始) · [配置说明](#配置项)

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
│                  Agent OS Runtime                           │
│                                                             │
│  Director Runtime ── Planner Runtime ── Dynamic Workflow    │
│  Reflection Runtime ── Prompt Runtime ── Memory Graph       │
│  Quality Runtime ── Retry Runtime ── Agent Message Bus      │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│              Agent Message Bus (7 Agents)                   │
│                                                             │
│  Script → Character → Storyboard → Image → Image-to-Video  │
│                                               → Voice → Video │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                    Adapter Layer                            │
│  ┌──────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐ │
│  │LLMAdapter│  │ImageAdapt.│  │I2VAdapter │  │VoiceAdpt.│ │
│  │(OpenAI)  │  │(DashScope│  │(Kling/   │  │(DashScope│ │
│  │          │  │ /DALL-E) │  │ Runway)  │  │  TTS)    │ │
│  └──────────┘  └───────────┘  └───────────┘  └──────────┘ │
│  ┌──────────┐                                              │
│  │VideoAdpt.│  Mock 降级: 未配置 API 时自动使用              │
│  │(FFmpeg)  │  占位图 / 静默音频 / 静态图视频                 │
│  └──────────┘                                              │
└─────────────────────────────────────────────────────────────┘
```

### 核心设计

- **纯 API 架构** — 图片生成走 DashScope/DALL-E API，语音走 DashScope TTS API，图生视频走 Kling/Runway API，零本地 GPU 依赖，可部署在任何服务器上
- **7 个 Agent 串行协作** — Script / Character / Storyboard / Image / Image-to-Video / Voice / Video，每个 Agent 职责单一，通过 Runtime 统一调度
- **5 类 Adapter** — LLM / Image / I2V / Voice / Video 适配器隔离 API 差异，同一类型支持多个 Provider 切换
- **Mock 降级策略** — 未配置某类 API 时自动降级：图片→占位图，语音→静默音频，视频→FFmpeg 静态图合成，不影响流程完整性
- **实时进度推送** — Redis PubSub + WebSocket，前端 7 步进度条实时更新
- **数据库持久化** — 每个 Agent 完成后立即写入 PostgreSQL，支持增量持久化
- **LLM 工厂模式** — `get_creative_llm()` (temp=0.8) / `get_precise_llm()` (temp=0.4) 按场景选用，实例缓存复用
- **结构化输出** — Script/Character Agent 用 `PydanticOutputParser`；Storyboard Agent 双策略（Pydantic 优先 + JSON fallback）
- **Prompt 外部化** — 所有 Agent Prompt 集中在 `prompts/` 模块，与 Agent 逻辑解耦

### Workflow DSL v2.0

```yaml
name: comic
version: "2.0"
description: 漫剧生成管线

steps:
  - name: script
    agent: script_agent
    retry: { max_attempts: 3, backoff: exponential }

  - name: character
    agent: character_agent
    depends_on: [script]
    retry: { max_attempts: 3, backoff: exponential }

  - name: storyboard
    agent: storyboard_agent
    depends_on: [script, character]
    retry: { max_attempts: 3, backoff: exponential }

  - name: image
    agent: image_agent
    depends_on: [storyboard, character]
    retry: { max_attempts: 2 }
    parallel: per_scene

  - name: image_to_video
    agent: image_to_video_agent
    depends_on: [image]
    retry: { max_attempts: 2 }
    parallel: per_scene

  - name: voice
    agent: voice_agent
    depends_on: [storyboard]
    retry: { max_attempts: 2 }
    parallel: per_scene

  - name: video
    agent: video_agent
    depends_on: [image_to_video, voice]
    retry: { max_attempts: 1 }
```

## Runtime 体系

当前 Runtime 已具备以下基础设施：

| 能力 | 状态 | 说明 |
|------|------|------|
| **Hook 事件系统** | ✅ 已实现 | 14 种生命周期事件，支持 Logger / QualityGate / Langfuse Handler |
| **Memory 记忆** | ✅ 已实现 | 4 层 Memory（working / session / conversation / long-term）+ CharacterMemoryService |
| **Skill 技能引擎** | ✅ 已实现 | YAML Skill 定义 + 约束校验 + 自动加载 |
| **Session 会话管理** | ✅ 已实现 | 状态管理 + 超时恢复 |
| **A2A Message Bus** | ✅ 已实现 | InMemory / Redis Stream 双传输层 |
| **MCP 协议** | ✅ 已实现 | Envelope / Router / Validator |
| **Execution 调度器** | ✅ 已实现 | LLM / Tool / GPU 线程池 |
| **Langfuse 可观测性** | ✅ 已实现 | 配置即启用 |
| **Quality Gate** | ✅ 已实现 | 6 Agent 专用校验器，不合格自动重试 |
| **Reflection Runtime** | ✅ 已接入 | 每步执行后生成 good/bad/suggestion，注入 Image Agent prompt |
| **Prompt Runtime** | ✅ 已接入 | 动态组合角色外观 + Reflection + 世界观 → enriched prompt |

## V1.5 迭代路线图

> 当前系统已经是一个工程质量很高的 Workflow Multi-Agent 系统，Runtime、EventBus、Memory、Retry、Trace 等基础设施已具备，Agent 也实现了解耦。但它还不是一个「会思考、会协商、会反思」的 Multi-Agent 系统。下一阶段不再增加业务 Agent，而是让现有 Agent 建立协作关系，并让 Runtime 增加七项核心能力。

### 整体架构升级

```
当前架构:
  Workflow → Agent → Result

升级为:
                    Director Runtime
                            │
                            ▼
                    Planner Runtime
                            │
                            ▼
                 Dynamic Workflow Runtime
                            │
                            ▼
                    Reflection Runtime
                            │
                            ▼
        Prompt Runtime ←→ Memory Graph
                            │
                            ▼
                    Quality Runtime
                            │
                            ▼
                    Retry Runtime
                            │
                            ▼
                     Agent Message Bus
                            │
                            ▼
 Script  Character  Storyboard  Image  I2V  Voice  Video
```

### 1. Reflection Runtime ✅ 已接入 Image Agent

**问题**：当前每个 Agent 执行完毕后直接结束，没有反思和反馈机制。产出的质量只能靠 Quality Gate 做简单校验，无法自我改进。

**状态**：Reflection Runtime 已完整实现并实际接入 Image Agent。每步执行后自动生成 good/bad/suggestion 结构化反馈，通过 PromptRuntime 注入到后续 Agent 的 prompt 中。

**已实现的数据流**：
```storyboard/character 步骤执行完毕
    │
    ▼
Reflection Runtime (rule-based 或 LLM)
    │
    ├─ good:    ["3 scenes created"]
    ├─ bad:     ["Scene prompts lack character appearance details"]
    └─ suggestion: ["Add character hair and clothing to every scene prompt"]
        │
        ▼
PromptRuntime.build_image_prompt()
  → 将 suggestion + character appearance + world settings 注入 prompt
        │
        ▼
WorkflowEngine._enrich_image_prompts()
  → 为每个场景生成 enriched prompt
        │
        ▼
Image Agent
  → 优先使用 enriched prompt（含 reflection 建议）
  → 返回 enrichment 元数据（enriched_count / total_count）
```

**集成测试**：19 个端到端测试全部通过，覆盖：
- Reflection 生成 suggestion
- PromptRuntime 注入 suggestion 到 prompt
- WorkflowEngine 调用 PromptRuntime 生成 enriched prompt
- Image Agent 读取并使用 enriched prompt
- 完整 E2E 流程：script → character → storyboard → reflection → image(enriched)

**机制**：
```
Image Agent (使用 enriched prompt)
    │
    ▼
Reflection Runtime
    │
    ├─ good:    ["人物一致性保持良好"]
    ├─ bad:     ["背景风格与前一张不统一"]
    └─ suggestion: ["增加古风建筑描述", "参考第 3 张图的色调"]
        │
        ▼
Quality Runtime (评分)
        │
        ▼
Director Runtime (决策: 是否需要重做)
        │
        ▼
Retry Runtime (执行重做)
        │
        ▼
Image Agent (带着 Suggestion 重新生成)
```

Reflection 输出结构化 JSON：
```json
{
  "step": "image",
  "good": ["人物一致"],
  "bad": ["背景风格不统一"],
  "suggestion": ["增加古风建筑描述"]
}
```

### 2. Prompt Runtime

**问题**：当前所有 Prompt 基本写死在模板中，无法根据上下文动态调整。

**目标**：所有 Prompt 由 Prompt Runtime 动态构建，综合多种信息源，让 Prompt 越来越长、越来越准确。

**机制**：
```
Template (基础模板)
  + Character Memory (角色外观/状态)
  + World Memory (世界观/场景设定)
  + Timeline (时间线/剧情进度)
  + Quality Suggestion (上一步的反思建议)
  + Director Instruction (导演指令)
        │
        ▼
   Prompt Builder
        │
        ▼
  最终 Prompt:
  "少女, 黑长发, 第一章衣服, 第三章受伤状态,
   古代河边, 避免现代建筑, 保持上一张画风"
```

### 3. Memory Graph ⭐ 非常重要

**问题**：当前 Memory 本质还是 JSON 键值对（hair, cloth, face），无法表达角色状态的演化。

**目标**：从静态属性升级到带时间线的图结构记忆，Runtime 知道当前角色应该处于什么状态。

**机制**：
```
林晓
  │
  ├─ 穿白衣 (第 1-2 章)
  ├─ 第二章受伤
  ├─ 第三章换红衣
  ├─ 第四章恢复
  └─ 第五章黑化

Runtime 查询:
  "当前第 3 章, 林晓应穿红衣, 且带有第 2 章受伤痕迹"
  → Image Agent 永远不会画错角色状态
```

### 4. Director Runtime (真正导演)

**问题**：当前 Director 只是简单的 if-else 逻辑（超时就重试），无法理解失败的根因。

**目标**：Director 观察整个 Pipeline，诊断失败原因，决定哪个 Agent 需要重做。

**机制**：
```
Image 失败
    │
    ▼
Director 诊断:
  → Prompt 问题？ → 让 Storyboard Agent 重新写分镜
  → 角色描述问题？ → 让 Character Agent 补充描述
  → 模型问题？ → 切换 Provider 重试
  → 偶发错误？ → 直接重试

不是 "Image 重试 N 次"
而是 "找到根因, 指向正确的 Agent 重做"
```

### 5. Agent Conversation (Agent Bus 协作)

**问题**：当前 Agent 之间没有直接通信，只能通过 State 字典传递数据。

**目标**：引入 Agent Message Bus，Agent 之间可以像团队一样讨论和协商。

**机制**：
```
Director:  ImageAgent, 为什么失败？
Image:     人物不像。
Director:  Storyboard, Prompt 是不是太简单？
Storyboard: 建议增加 "长发" "白裙" "夏日"。
Director:  Image, 重新画（带新 Prompt）。
```

### 6. Dynamic Workflow (动态工作流)

**问题**：当前 Workflow 固定为 7 步 YAML，无法根据故事特征调整。

**目标**：Planner 在运行时根据故事特征动态生成 Workflow。

**机制**：
```
故事很长 → 自动增加 Summary Agent（章节摘要）
人物很多 → 自动增加 Character Review Agent（角色一致性审查）
有战斗场景 → 自动增加 Action Choreography Agent

Workflow 由 Runtime 运行时决定，而非固定 YAML
```

### 7. Model Router (智能模型路由)

**问题**：当前所有 LLM 调用使用同一个配置的模型，无法根据任务特征选择最优模型。

**目标**：Runtime 根据任务类型、速度要求、成本预算自动选择最合适的模型/Provider。

**机制**：
```
剧本生成  → Claude (长文本创意能力强)
Prompt 构建 → Gemini (多模态理解)
图片生成  → Flux / DALL-E 3 (视觉质量)
视频生成  → Veo3 / Kling (动态质量)
配音合成  → FishSpeech / DashScope TTS (语音自然度)

根据速度、价格、质量三个维度自动选优
```

### 精力分配

| 方向 | 比例 | 说明 |
|------|------|------|
| Runtime 核心能力 | 40% | Reflection / Prompt / Memory Graph / Director / Retry / Quality / Trace |
| Director Runtime | 25% | 真正的根因诊断和跨 Agent 协调 |
| Quality Pipeline | 20% | 独立 Checker，返回 Score + Issues + Suggestion |
| Agent 改进 | 10% | 接入新 Runtime 能力，不增加新 Agent |
| 前端 | 5% | 进度展示和结果可视化 |

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18, TypeScript, Vite 5, Ant Design 5, Axios | SPA，3 页面 |
| **后端** | Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic 2.0 | 异步全栈 |
| **Agent 框架** | LangChain, ChatOpenAI | 7-Agent 管线 + Runtime 层 |
| **Runtime** | Agent OS Runtime | Hook / Memory / Skill / Session / A2A / Langfuse |
| **数据库** | PostgreSQL 16 (asyncpg) | 故事 / 角色 / 场景 / 任务 |
| **缓存** | Redis 7 | 任务状态 + PubSub + A2A 传输 |
| **向量数据库** | Qdrant | 角色 / 剧情记忆检索 |
| **LLM** | OpenAI 兼容 API (GPT-4o / Qwen / DeepSeek / Claude) | 剧本 / 角色 / 分镜 |
| **图片生成** | DashScope (通义万相) / DALL-E 3 API | 1024x1024, 云端生成 |
| **图生视频** | Kling / Runway API | 图片转动态视频 |
| **语音合成** | DashScope TTS API | 男/女声自动映射 |
| **视频合成** | FFmpeg | 视频+音频→字幕烧录→拼接 |
| **部署** | Docker Compose, Nginx | 一键部署 |

## 项目结构

```
storyflow-ai/
├── backend/
│   ├── main.py                        # FastAPI 入口
│   ├── requirements.txt
│   ├── Dockerfile
│   │
│   ├── configs/
│   │   └── settings.py                # Pydantic Settings (纯 API 配置)
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
│   ├── agents/                        # ⭐ 7 个 Agent
│   │   ├── script_agent.py            # 剧本 (tenacity 3x, PydanticOutputParser)
│   │   ├── character_agent.py         # 角色视觉卡片 (AppearanceCard 强类型)
│   │   ├── storyboard_agent.py        # 分镜 (双策略: Pydantic + JSON fallback)
│   │   ├── image_agent.py             # 图片 (DashScope/DALL-E API, 逐场景重试)
│   │   ├── image_to_video_agent.py    # 图生视频 (Kling/Runway API)
│   │   ├── voice_agent.py             # 配音 (DashScope TTS API, 性别→音色)
│   │   └── video_agent.py             # 视频 (FFmpeg 合成+字幕+拼接)
│   │
│   ├── workflows/
│   │   ├── state.py                   # StoryState TypedDict
│   │   ├── story_workflow.py          # LangGraph 编排
│   │   ├── runtime_workflow.py        # Agent OS Runtime 适配层
│   │   └── comic.yaml                 # ⭐ Workflow DSL v2.0 定义
│   │
│   ├── runtime/
│   │   ├── core.py                     # Runtime 核心 (Agent 注册)
│   │   ├── planner.py                 # Planner (YAML → Runtime 步骤)
│   │   ├── adapters/                  # ⭐ 5 类 Adapter
│   │   │   ├── __init__.py            #   LLM / Image / I2V / Voice / Video
│   │   │   ├── llm_adapter.py
│   │   │   ├── image_adapter.py
│   │   │   ├── i2v_adapter.py
│   │   │   ├── voice_adapter.py
│   │   │   └── video_adapter.py
│   │   ├── app.py                     # RuntimeApp (Hook+Skill+Memory 组装)
│   │   ├── adapter.py                 # 适配器 (Memory注入+质量重试+Skill约束)
│   │   ├── agent_runtime/             # Agent 运行时上下文
│   │   ├── execution/                 # 调度器 (LLM/Tool 线程池)
│   │   ├── conversation/              # 对话管理
│   │   ├── skill_engine/              # 技能注册/选择/校验/执行
│   │   ├── memory/                    # 4 层记忆 + CharacterMemoryService
│   │   ├── session/                   # 会话管理 (超时/恢复)
│   │   ├── hook/                      # 事件钩子 (14 种生命周期事件)
│   │   ├── handlers/                  # Logger / QualityGate / Langfuse
│   │   ├── mcp/                       # MCP 协议 (Envelope/Router/Validator)
│   │   └── message_bus/               # A2A 通信 (InMemory/Redis Stream)
│   │
│   ├── tools/
│   │   └── ffmpeg_tool.py             # FFmpeg 视频合成
│   │
│   ├── tasks/
│   │   └── runner.py                  # 任务运行器 (增量持久化)
│   │
│   ├── app/
│   │   ├── database.py
│   │   ├── redis.py
│   │   └── llm.py                     # LLM 工厂 (creative / precise)
│   │
│   ├── memory/
│   │   └── vector_store.py            # Qdrant 向量记忆
│   │
│   ├── utils/
│   │   └── json_helper.py
│   │
│   └── skills/                        # ⭐ Skill 定义 (YAML)
│       ├── script_writer/
│       ├── character_designer/
│       ├── storyboard_designer/
│       ├── image_generator/
│       ├── image_to_video/
│       ├── voice_generator/
│       └── video_composer/
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── api/index.ts               # API + WebSocket
│       ├── types/index.ts             # TypeScript 类型
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
│ Character Agent  │  LLM → 丰富角色视觉描述
│  temp=0.4        │  → AppearanceCard (hair/body/cloth/face)
│  tenacity 3x     │  失败 fallback 原始角色
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Storyboard Agent │  剧本+角色 → 分镜 (逐集)
│  temp=0.4        │  策略1: PydanticOutputParser
│  tenacity 3x/集  │  策略2: JSON 解析 fallback
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Image Agent     │  DashScope/DALL-E API 逐镜生成
│  逐场景独立      │  1024x1024, 云端 API
│  2x 重试/镜      │  部分失败 → image_partial (Mock 降级)
└────────┬─────────┘
         ▼
┌──────────────────────┐
│ Image-to-Video Agent  │  Kling/Runway API 图生视频
│  逐场景独立          │  图片 → 3-5s 动态视频
│  2x 重试/镜          │  未配置 → Mock: FFmpeg 静态图
└────────┬───────────────┘
         ▼
┌──────────────────┐
│  Voice Agent     │  DashScope TTS API 逐镜配音
│  性别→音色映射   │  base64/URL 双格式
│  部分容错        │  未配置 → Mock: 静默音频
└────────┬─────────┘
         ▼
┌──────────────────┐
│  Video Agent     │  FFmpeg 合成
│                  │  1. 视频+音频 → 逐场景合成 (时长对齐)
│                  │  2. ASS 字幕 (基于实际视频时长)
│                  │  3. 字幕烧录 → concat 拼接 → story.mp4
└──────────────────┘
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- FFmpeg
- **外部 API**（至少配置 LLM，其余可选 — 未配置自动 Mock 降级）：
  - OpenAI 兼容 LLM API（GPT-4o / Qwen / DeepSeek / Claude 等）**必填**
  - DashScope API（图片生成 + TTS，可选）
  - DALL-E API（图片生成，可选）
  - Kling / Runway API（图生视频，可选）

### 方式一：本地开发

```bash
git clone https://github.com/xiaozhang-art/storyflow-ai.git
cd storyflow-ai

# 配置
cp deploy/.env.example backend/.env
# 编辑 backend/.env，至少填入 LLM_API_KEY
# 图片/语音/视频 API 按需配置，未配置自动 Mock 降级

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

## 数据库设计

```
story          ─── 故事 (title, prompt, genre, status)
  ├─ character ─── 角色 (name, gender, age, appearance JSONB, personality JSONB)
  ├─ episode   ─── 剧集 (episode_no, title, summary, script)
  └─ scene     ─── 场景 (scene_no, prompt, camera, duration, dialogue, image_url, audio_url, video_url)
task           ─── 任务 (status, progress, current_step, error_message)
```

## 配置项

### 基础配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | — | LLM API Key (**必填**) |
| `LLM_MODEL` | `gpt-4o` | 模型名称 |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | LLM API 地址 |
| `LLM_TEMPERATURE` | `0.7` | 默认温度 |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis |
| `QDRANT_URL` | `http://localhost:6333` | Qdrant |
| `STORAGE_PATH` | `./storage` | 文件存储 |

### 图片生成配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE_PROVIDER` | `dashscope` | 图片 Provider (`dashscope` / `dall_e` / `mock`) |
| `DASHSCOPE_API_KEY` | — | DashScope API Key (图片+TTS) |
| `DASHSCOPE_IMAGE_MODEL` | `wanx-v1` | 通义万相模型 |
| `DALL_E_API_KEY` | — | DALL-E API Key (可选, 与 LLM 共用也可) |
| `IMAGE_MAX_RETRIES` | `2` | 单张图重试次数 |
| `IMAGE_SIZE` | `1024x1024` | 图片尺寸 |

### 图生视频配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `I2V_PROVIDER` | `mock` | 图生视频 Provider (`kling` / `runway` / `mock`) |
| `KLING_ACCESS_KEY` | — | Kling API Access Key |
| `KLING_SECRET_KEY` | — | Kling API Secret Key |
| `RUNWAY_API_KEY` | — | Runway API Key |
| `I2V_DURATION` | `5` | 生成视频时长 (秒) |

### 语音合成配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TTS_PROVIDER` | `mock` | TTS Provider (`dashscope` / `mock`) |
| `VOICE_MALE` | `longxiaochun` | 男声音色 |
| `VOICE_FEMALE` | `zhiyan_emo` | 女声音色 |

### 生成参数

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_EPISODES` | `6` | 最大集数 |
| `SCENES_PER_EPISODE` | `(5, 10)` | 每集场景数范围 |

### Runtime 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse 公钥 |
| `LANGFUSE_SECRET_KEY` | — | Langfuse 密钥 |
| `A2A_TRANSPORT` | `memory` | Agent 通信 (`memory` / `redis`) |
| `LLM_WORKER_CONCURRENCY` | `10` | LLM 并发数 |
| `SESSION_IDLE_TIMEOUT` | `86400` | 会话超时 (秒) |
| `MEMORY_WORKING_TTL` | `300` | 工作记忆 TTL (秒) |
| `MEMORY_SESSION_TTL` | `86400` | 会话记忆 TTL (秒) |
| `MEMORY_CONFIDENCE_THRESHOLD` | `0.7` | 记忆存储最低置信度 |

### Mock 降级策略

未配置某类 API 时，系统自动降级，不影响流程完整性：

| API 类型 | 未配置时降级行为 |
|----------|------------------|
| 图片生成 | 使用纯色占位图 + 文字标注 |
| 图生视频 | FFmpeg 将静态图合成为视频（Ken Burns 效果） |
| 语音合成 | 生成静默音频文件 |

## License

MIT