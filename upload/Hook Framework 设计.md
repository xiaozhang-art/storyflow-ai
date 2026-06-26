很好，现在进入你这个系统里**非常关键的一层：Hook Framework（Agent 的“神经系统 + 眼睛”）**。

这一层决定了你后面能不能做到：

* 每一步可观测
* 每一步可回放
* 每一步可定位“为什么跑偏”
* Langfuse / OTEL / 日志统一
* Agent debug 从“猜”变成“看”

---

# 📘 06 - Hook Framework 设计（V1 / 可观测性核心）

---

# 1. 设计目标

Hook Framework 的目标不是“打日志”，而是：

> **把 Agent Runtime 变成一个可观测的执行机器（Observable Runtime OS）**

---

## 解决的问题

### ❌ 没有 Hook 时

* 不知道 LLM 为什么答错
* 不知道 tool 参数怎么来的
* 不知道 skill 是否选错
* 不知道 prompt 哪一步变坏
* 不知道 memory 是否污染
* 不知道 A2A 哪一步断了

---

### ✅ 有 Hook 后

你可以看到：

* 每一次 LLM 输入输出
* 每一次 tool 调用参数
* 每一次 session routing
* 每一次 skill selection
* 每一次 prompt 构建过程
* 每一次 memory 注入
* 每一次 retry / judge

---

# 2. 核心设计思想

---

## Hook = Runtime Event System

```text id="hook_01"
Agent Runtime
    ↓ emits events
Hook Dispatcher
    ↓ triggers handlers
Observability Layer (Langfuse / Log / OTEL)
```

---

## 核心原则

### 1️⃣ 所有行为必须可观测

### 2️⃣ Hook 不影响业务逻辑

### 3️⃣ Hook 可插拔

### 4️⃣ Hook 可分层（global / workspace）

### 5️⃣ Hook 必须支持 trace 绑定

---

# 3. Hook 生命周期标准（核心）

---

## 3.1 标准 5 + 2 + N 模型

```python id="hook_02"
BEFORE_SESSION
BEFORE_AGENT
BEFORE_SKILL
BEFORE_LLM
BEFORE_TOOL

AFTER_TOOL
AFTER_LLM
AFTER_AGENT
AFTER_SESSION

ON_ERROR
ON_RETRY
```

---

# 4. Hook 架构

---

```text id="hook_03"
                ┌────────────────────┐
                │   Agent Runtime     │
                └─────────┬──────────┘
                          │ emit(event)
                          ▼
            ┌──────────────────────────┐
            │   Hook Dispatcher        │
            │                          │
            │ - registry               │
            │ - filter                 │
            │ - async executor        │
            └─────────┬──────────────┘
                      ▼
     ┌──────────────────────────────────┐
     │  Hook Handlers                  │
     │  - Langfuse Hook               │
     │  - Structured Logger           │
     │  - OTEL Exporter               │
     │  - Debug Recorder              │
     └──────────────────────────────────┘
```

---

# 5. Hook 数据结构

---

## 5.1 Event Object

```python id="hook_04"
class HookEvent:
    name: str

    trace_id: str
    session_id: str
    conversation_id: str

    agent_id: str

    payload: dict
    timestamp: int
```

---

## 5.2 Handler Interface

```python id="hook_05"
class HookHandler:

    async def handle(self, event: HookEvent):
        pass
```

---

# 6. Hook Dispatcher（核心实现）

---

```python id="hook_06"
class HookDispatcher:

    def __init__(self):
        self.registry = defaultdict(list)

    def register(self, event_name, handler):
        self.registry[event_name].append(handler)

    async def emit(self, event: HookEvent):

        handlers = self.registry.get(event.name, [])

        for h in handlers:
            await h.handle(event)
```

---

# 7. Hook Registry（分层设计）

---

## 7.1 Global Hook

```text id="hook_07"
- structured_logger
- langfuse_trace
- otel_exporter
```

---

## 7.2 Workspace Hook

```text id="hook_08"
- task_audit
- business_metrics
- cost_tracker
```

---

## 7.3 合并执行

```python id="hook_09"
final_hooks = global_hooks + workspace_hooks
```

---

# 8. Langfuse Hook（核心观测）

---

## 8.1 BEFORE_LLM

```python id="hook_10"
async def handle(event):

    langfuse.create_span(
        name="llm-call",
        input=event.payload["prompt"],
        metadata={
            "agent": event.agent_id,
            "session": event.session_id
        }
    )
```

---

## 8.2 AFTER_LLM

```python id="hook_11"
async def handle(event):

    span.update(
        output=event.payload["response"]
    )
```

---

# 9. Structured Log Hook（调试核心）

---

```python id="hook_12"
{
  "event": "BEFORE_TOOL",
  "agent": "storyboard",
  "session": "Sa",
  "input": {...},
  "trace_id": "xxx"
}
```

---

# 10. Tool Hook（关键 debug 点）

---

## 10.1 BEFORE_TOOL

```python id="hook_13"
tool_input = {
    "name": "comfyui_generate",
    "params": {...}
}
```

---

## 10.2 AFTER_TOOL

```python id="hook_14"
tool_output = {
    "image_url": "...",
    "latency": 3.2
}
```

---

# 11. Hook 如何解决“跑偏问题”

---

## 11.1 跑偏来源

* prompt污染
* memory错误
* skill选错
* tool参数错误
* session错配

---

## 11.2 Hook定位方式

### 示例：

```text id="hook_15"
llm-call-2 → prompt异常
tool-call-3 → 参数错误
memory-load → 引入错误角色
```

---

## 11.3 直接定位方式

👉 在 Langfuse trace：

* 找最后正确 LLM
* 看下一 step tool input
* 看 session injection

---

# 12. Hook + Replay System（高级能力）

---

## 12.1 记录所有事件

```text id="hook_16"
event stream:
BEFORE_LLM
AFTER_LLM
BEFORE_TOOL
AFTER_TOOL
```

---

## 12.2 replay

```python id="hook_17"
replay(trace_id)
```

---

# 13. Hook 与 A2A / Session 的关系

---

| 模块      | 作用 |
| ------- | -- |
| Session | 状态 |
| A2A     | 通信 |
| Hook    | 观测 |

---

Hook 会自动注入：

```python id="hook_18"
event.session_id
event.conversation_id
event.trace_id
```

---

# 14. Hook 性能设计

---

## 14.1 异步执行

```python id="hook_19"
asyncio.create_task(handler.handle(event))
```

---

## 14.2 不阻塞 Runtime

Hook 必须：

> ❗ 不能影响 Agent 主流程

---

# 15. Hook 插件机制

---

```python id="hook_20"
class HookPlugin:
    name: str
    events: list[str]
```

---

# 16. 目录结构

```text id="hook_21"
hook/
├── dispatcher.py
├── event.py
├── registry.py
├── handlers/
│   ├── langfuse.py
│   ├── logger.py
│   ├── otel.py
│   ├── tool_logger.py
│   ├── memory_logger.py
```

---

# 17. 系统能力提升总结

---

加入 Hook 后，你系统变成：

## ❌ 之前

* 黑盒 Agent
* debug靠猜
* 跑偏无法定位

---

## ✅ 现在

* 全链路可观测
* 每一步 trace
* 每一步可 replay
* 每一步可 debug

---

# 18. 本质升级

Hook 带来的不是日志，而是：

> **Agent Runtime → 可调试操作系统**

---

# 19. 下一步（关键升级）

下一份是：

# 📘 07 - Skill Engine 设计（你前面提到“Skill + Agent 防跑偏核心”）

会解决：

* Skill = 防跑偏核心机制
* Skill DSL
* Skill Prompt 模板系统
* Skill routing（比 tool 更高层）
* Skill + Judge 联动
* Skill versioning
* Skill marketplace（未来扩展）

---

如果你继续，我下一步会把系统升级到：

> **“Agent 不再靠 prompt，而是靠 Skill 驱动的系统”**
