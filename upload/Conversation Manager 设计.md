好，我们继续往上升级一层——这一层是把你现在的 A2A 从“能通信”升级到：

> **能组织协作、能拆任务、能形成多智能体群体行为的 Conversation Runtime**

---

# 📘 04 - Conversation Manager 设计（V1 / 群体智能核心）

---

# 1. 设计目标

Conversation Manager 不是“聊天记录管理器”，而是：

> **Multi-Agent 协作调度器（Swarm Coordinator）**

它解决的问题是：

### ❌ 没有 Conversation Manager 时

* A2A 只是点对点通信
* Agent 不知道“任务整体结构”
* 无法拆解复杂任务
* 无法形成 planner / reviewer / executor 模式
* 无法控制多轮协作节奏

---

### ✅ 有 Conversation Manager 后

你可以实现：

* 多 Agent 协作 DAG
* 自动任务拆解
* 子对话线程
* critic / reviewer 回路
* planner → executor → reviewer
* 动态引入新 Agent
* 会话级目标管理

---

# 2. 核心定义

---

## 2.1 Conversation = 目标驱动的多 Agent 图

```python id="conv_01"
class Conversation:
    conversation_id: str
    goal: str

    agents: list[str]
    edges: list[tuple[str, str]]

    state: dict
    status: str
```

---

## 2.2 Conversation ≠ Chat

| 概念 | Chat    | Conversation      |
| -- | ------- | ----------------- |
| 本质 | 记录      | 任务系统              |
| 单元 | message | goal + task graph |
| 控制 | 用户      | Runtime           |
| 结构 | 线性      | DAG / Graph       |

---

# 3. 系统架构

```text id="conv_02"
                ┌──────────────────────┐
                │  User / API Request  │
                └──────────┬───────────┘
                           ▼
            ┌──────────────────────────────┐
            │ Conversation Manager         │
            │                              │
            │ - Task Decomposition         │
            │ - Agent Planner             │
            │ - Graph Builder             │
            └──────────┬───────────────────┘
                       ▼
        ┌────────────────────────────┐
        │        A2A Message Bus      │
        └────────────────────────────┘
```

---

# 4. 核心职责

Conversation Manager 负责：

### 4.1 任务拆解（Task Decomposition）

### 4.2 Agent 编排（Graph Construction）

### 4.3 子对话管理（Sub-conversation）

### 4.4 节点状态管理

### 4.5 协作流程控制

---

# 5. 核心数据结构

---

## 5.1 Conversation Graph

```python id="conv_03"
class ConversationGraph:

    nodes: dict[str, AgentNode]
    edges: list[Edge]

class AgentNode:
    agent_id: str
    role: str   # planner / executor / reviewer / critic

    state: str
    context: dict
```

---

## 5.2 Edge（消息流）

```python id="conv_04"
class Edge:
    from_agent: str
    to_agent: str

    condition: str  # success / failure / always
```

---

# 6. Conversation 生命周期

---

```text id="conv_05"
CREATE_CONVERSATION
    ↓
TASK_ANALYSIS
    ↓
GRAPH_BUILD
    ↓
AGENT_DISPATCH
    ↓
A2A_EXECUTION_LOOP
    ↓
STATE_UPDATE
    ↓
EVALUATION
    ↓
CONVERSATION_COMPLETE
```

---

# 7. 关键能力1：Task Decomposition

---

## 7.1 Planner Agent

Conversation Manager 会自动生成 planner prompt：

```text id="conv_06"
Task:
"生成3集AI短剧"

Output:
1. 剧情拆解
2. 角色设计
3. 分镜任务
4. 视频生成任务
```

---

## 7.2 输出结构

```python id="conv_07"
class TaskPlan:
    tasks: list[Task]

class Task:
    id: str
    type: str
    agent: str
    input: dict
    depends_on: list[str]
```

---

# 8. 关键能力2：Graph Builder

---

## 8.1 自动构建 DAG

```text id="conv_08"
Planner
  ↓
Script Agent
  ↓
Character Agent
  ↓
Storyboard Agent
  ↓
Image Agent
  ↓
Video Agent
  ↓
Reviewer Agent
```

---

## 8.2 动态插入节点（关键）

例如：

```text id="conv_09"
Storyboard → Critic → Storyboard
```

形成闭环：

> **Feedback Loop Graph**

---

# 9. 关键能力3：子对话（Sub-Conversation）

---

## 9.1 定义

一个 Conversation 可以拆成多个子会话：

```text id="conv_10"
Conversation
 ├── Story Dev Thread
 ├── Visual Thread
 ├── Audio Thread
```

---

## 9.2 每个子会话独立 A2A

但共享：

* global memory
* conversation_id
* artifact pool

---

# 10. 关键能力4：Role-based Agent

---

## 10.1 Agent角色

```text id="conv_11"
planner
executor
critic
reviewer
optimizer
```

---

## 10.2 控制策略

```python id="conv_12"
if agent.role == "critic":
    enable_judge = True
    temperature = 0.2
```

---

# 11. 执行模型（核心变化）

---

## 11.1 旧模式（Pipeline）

```text id="conv_13"
A → B → C → D
```

---

## 11.2 新模式（Conversation Graph）

```text id="conv_14"
        ┌────────────┐
        ▼            │
Planner → Executor → Reviewer
        ▲            │
        └──── Critic ┘
```

---

# 12. 与 A2A 的关系（关键）

---

## 12.1 分工

| 模块                   | 职责                |
| -------------------- | ----------------- |
| A2A Bus              | message transport |
| Conversation Manager | logic + planning  |

---

## 12.2 数据流

```text id="conv_15"
Conversation Manager
      ↓
A2A Envelope
      ↓
Control Server
      ↓
Agent Runtime
```

---

# 13. 状态机设计

---

```python id="conv_16"
class ConversationState:

    INIT
    PLANNING
    EXECUTING
    WAITING_FEEDBACK
    REVISING
    COMPLETED
```

---

# 14. Evaluation Integration（关键）

---

Conversation Manager 会触发：

```text id="conv_17"
每个 stage → Judge Agent
```

例如：

* 剧本是否合理
* 人物是否一致
* 分镜是否可执行

---

# 15. Memory 协作层

---

所有 Agent 共享：

```text id="conv_18"
Global Memory:
- story world
- characters
- constraints
```

---

# 16. 目录结构（建议）

```text id="conv_19"
conversation/
├── manager.py
├── planner.py
├── graph_builder.py
├── task_decomposer.py
├── state_machine.py
├── roles.py
├── sub_conversation.py
```

---

# 17. 关键设计亮点总结

---

## 17.1 从“链式执行”升级为“图式协作”

---

## 17.2 Conversation 是控制中心

不是 Agent，不是 A2A，而是：

> **Conversation = 智能体群体的大脑**

---

## 17.3 支持闭环优化

Critic → Executor → Critic

---

## 17.4 支持多线程协作

不同子任务并行执行

---

# 18. 系统能力跃迁

---

| 层级                   | 能力     |
| -------------------- | ------ |
| Agent Runtime        | 单智能体执行 |
| A2A Bus              | 点对点通信  |
| Conversation Manager | 群体智能   |

---

# 19. 下一步（非常关键升级）

下一份是：

# 📘 05 - Session Manager 设计（你最初 A/Sa → B/Sb 的核心落地）

会解决：

* session 映射最终实现
* A ↔ B pairing机制
* control server session state
* conversation/session/trace 三层关系
* Redis / DB 结构设计
* session恢复
* 断线重连
* 多轮对话一致性

---

如果你继续，我下一步可以把整个系统升级到：

> **真正可运行的 Multi-Agent OS（不是 demo，是 framework 级）**
