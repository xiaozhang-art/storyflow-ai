好，进入你这个系统里**最关键的一层：A2A（Agent-to-Agent）通信系统**。

这一层写完，你的 StoryFlow 就从“流水线生成器”升级为：

> **多智能体可对话、可协作、可演化的 Runtime OS**

---

# 📘 03 - A2A Message Bus 设计（V1 / 工程可落地版）

---

# 1. 设计目标

A2A（Agent-to-Agent）Message Bus 解决三个核心问题：

### ❌ 旧系统问题

* Agent 之间强耦合（Script → Character → Storyboard）
* 无法动态插入 Agent
* 没有真正“对话”
* session / state 分散在 workflow

---

### ✅ 新系统目标

A2A Bus 必须支持：

* Agent 间**像发消息一样通信**
* Session 隐藏在 Control Server
* 支持 **双向对话（A ↔ B）**
* 支持 **多轮状态恢复**
* 支持 **自动 session 绑定/切换**
* 支持 **trace 全链路追踪**
* 支持 **未来分布式扩展（Kafka / Redis Stream）**

---

# 2. 核心思想（非常重要）

> Agent 不知道 session，也不知道对方是谁
> **所有通信由 Control Server 调度 + 重写 Envelope**

---

# 3. 系统架构

```text id="a2a_01"
              ┌──────────────────────┐
              │   Agent A (Sa)       │
              └─────────┬────────────┘
                        │ send_message
                        ▼
              ┌──────────────────────┐
              │   Control Server      │
              │  (A2A Router Core)    │
              └─────────┬────────────┘
                        │ rewrite envelope
                        ▼
              ┌──────────────────────┐
              │   Agent B (Sb)       │
              └──────────────────────┘
```

---

# 4. 核心设计：Session 隐藏机制

---

## 4.1 Session 不给 Agent

Agent 永远看不到：

* session_id Sa / Sb
* routing key
* control logic

Agent 只看到：

```text
message.content
message.from_agent
message.context
```

---

## 4.2 Control Server 才维护映射

```python id="a2a_02"
SessionMapping:

A(Sa) → B(Sb)
B(Sb) → A(Sa)
```

---

# 5. Envelope 升级设计（核心协议）

---

## 5.1 基础 Envelope

```python id="env_01"
class Envelope:
    message_id: str
    trace_id: str

    source_agent: str
    target_agent: str

    source_session_id: str   # Control Server 填
    target_session_id: str   # Control Server 填

    conversation_id: str

    action: str
    content: dict

    reply_to: str | None
```

---

# 6. A2A 通信协议（核心）

---

## 6.1 第一条消息（A → B）

```text id="a2a_03"
A(Sa) → Control Server

content:
"帮我生成角色设定"
```

Control Server 处理后：

```json id="a2a_04"
{
  "source_session_id": "Sa",
  "target_session_id": "Sb",
  "source_agent": "A",
  "target_agent": "B"
}
```

---

## 6.2 B 收到消息

B 看到的是：

```text id="a2a_05"
content:
"帮我生成角色设定"
context:
- 来自 A 的请求
```

---

## 6.3 B 回复（B → A）

```text id="a2a_06"
content:
"已生成角色设定"
target_session_id: Sa
```

---

Control Server 自动切换：

```text id="a2a_07"
B(Sb) → A(Sa)
```

---

# 7. Control Server（核心组件）

---

# 7.1 职责

Control Server 是整个 A2A 的“大脑”：

### 负责：

* session 映射
* routing
* prompt 拼接
* context 注入
* trace 管理
* message queue
* retry / dead letter

---

# 7.2 核心结构

```python id="cs_01"
class ControlServer:

    session_map: dict
    conversation_map: dict
    inbox: Queue
    outbox: Queue
```

---

# 8. Routing 逻辑（核心）

---

## 8.1 Send Message

```python id="cs_02"
async def send_message(self, envelope):

    source = envelope.source_session_id
    target = self.session_map.get(source)

    if not target:
        target = self.create_session(envelope.target_agent)

        self.session_map[source] = target
        self.session_map[target] = source

    envelope.target_session_id = target

    enriched = self._inject_context(envelope)

    await self.route(enriched)
```

---

# 9. Session 自动创建机制

---

## 9.1 首次通信

```text id="sc_01"
A(Sa) → B(?)
```

Control Server：

```python id="sc_02"
if no session exists:
    Sb = create_session(B)
```

---

## 9.2 双向绑定

```text id="sc_03"
Sa ↔ Sb
```

形成：

> **Pair Session Model（双会话绑定）**

---

# 10. Prompt 拼接机制（关键）

---

Control Server 会做：

```python id="pp_01"
prompt = f"""
[System Context]
You are Agent B

[Conversation Context]
- From Agent A (session Sa)
- Previous messages: ...

[Message]
{content}
"""
```

---

# 11. Inbox / Outbox 模型

---

## 11.1 每个 Agent 有：

```text id="io_01"
Inbox  → 收消息
Outbox → 发消息
```

---

## 11.2 Redis Stream 实现

```text id="io_02"
stream: agent:A:inbox
stream: agent:B:inbox
```

---

# 12. Conversation Graph（升级点）

---

不是线性，而是：

```text id="cg_01"
A → B → A → B → C → A
```

形成：

> **Message Graph，而不是 Workflow DAG**

---

# 13. 状态机设计

---

## 13.1 Message State

```text id="sm_01"
PENDING
ROUTED
PROCESSING
COMPLETED
FAILED
RETRYING
```

---

# 14. Trace 绑定（Langfuse）

---

## 14.1 一个 message = 一个 trace span

```text id="tr_01"
trace_id
 ├── A_send
 ├── control_server_route
 ├── B_receive
 ├── B_llm_call
 ├── B_reply
 ├── route_back_to_A
```

---

## 14.2 关键点

Control Server 必须写：

* session mapping
* routing decision
* prompt injection

---

# 15. A2A vs Workflow（核心差异）

---

| 维度      | Workflow | A2A            |
| ------- | -------- | -------------- |
| 控制方式    | 静态 DAG   | 动态消息流          |
| 扩展性     | 低        | 高              |
| Agent关系 | 固定链路     | 任意通信           |
| 状态管理    | 本地       | Control Server |
| 可演化性    | ❌        | ✅              |

---

# 16. 关键设计亮点

---

## 16.1 Agent 不知道 session

完全隔离复杂度

---

## 16.2 Control Server 是唯一真相源

SSOT（Single Source Of Truth）

---

## 16.3 Message = Primitive

系统最小单元不是 Task，而是 Message

---

## 16.4 自动 pairing session

A ↔ B 自动建立关系

---

# 17. 目录结构（建议）

```text id="dir_01"
a2a/
├── control_server/
│   ├── router.py
│   ├── session_manager.py
│   ├── prompt_injector.py
│   ├── conversation_manager.py
│
├── message/
│   ├── envelope.py
│   ├── state.py
│
├── transport/
│   ├── redis_stream.py
│   ├── kafka_adapter.py
│
├── trace/
```

---

# 18. 这一层完成后的能力

系统会从：

### ❌ 旧 StoryFlow

* 固定 pipeline
* 单向执行

---

### ✅ 新 StoryFlow

* Agent 可以互相“聊天”
* 可动态生成协作结构
* 可插入 reviewer / judge / critic agent
* 可形成 multi-agent swarm

---

# 19. 下一步（关键升级）

下一份我会写：

# 📘 04 - Conversation Manager 设计（非常关键）

会解决：

* 多 Agent 群聊
* DAG → Graph
* 任务拆解
* 子对话线程
* A/B/C 多角色协作
* reviewer / critic / planner 模式
* 以及如何和 A2A 结合

---

如果你继续，我下一步可以直接把系统升级到：

> **Multi-Agent Swarm Runtime（真正可进化的版本）**
