好，我们继续进入**可直接开发级别设计文档**。

---

# 📘 01 - Agent Runtime 设计（V1 / 可落地实现版）

---

# 1. 设计目标

Agent Runtime 是 StoryFlow 的“执行内核”，目标是：

> 让 Agent 变成一个**无状态执行器（Stateless Executor）**，所有能力由 Runtime 注入。

---

## 核心职责

Agent Runtime 负责：

* Envelope 解析
* Memory 注入
* Skill 加载与选择
* Prompt 构建
* LLM 调用
* Tool 调度
* Hook 生命周期触发
* Judge / Retry
* Trace 上报（Langfuse）
* 返回 Envelope

---

# 2. 核心抽象

---

## 2.1 Envelope（输入输出统一协议）

所有 Agent 输入输出必须统一：

```python id="env_01"
class Envelope:
    trace_id: str
    conversation_id: str
    message_id: str
    parent_id: str

    sender: str
    receiver: str

    action: str
    payload: dict

    memory_refs: list[str]
    artifact_refs: list[str]

    metadata: dict
```

---

## 2.2 Agent Runtime 核心接口

```python id="rt_01"
class AgentRuntime:

    async def run(self, envelope: Envelope) -> Envelope:
        pass
```

---

# 3. Runtime 执行流程（核心）

---

## 3.1 完整执行链路

```text id="flow_01"
Envelope Input
    ↓
1. Parse Context
    ↓
2. Load Memory
    ↓
3. Load Skills
    ↓
4. Hook: BEFORE_AGENT
    ↓
5. Select Skill
    ↓
6. Build Prompt
    ↓
7. Hook: BEFORE_LLM
    ↓
8. LLM Call
    ↓
9. Hook: AFTER_LLM
    ↓
10. Tool Execution (optional)
    ↓
11. Judge/Evaluation (optional)
    ↓
12. Retry Loop (optional)
    ↓
13. Hook: AFTER_AGENT
    ↓
Return Envelope
```

---

# 4. Runtime 代码结构

---

## 4.1 主 Runtime

```python id="rt_02"
class AgentRuntime:

    def __init__(
        self,
        hook_manager,
        memory_manager,
        skill_engine,
        tool_registry,
        llm_client,
        tracer,
    ):
        self.hooks = hook_manager
        self.memory = memory_manager
        self.skills = skill_engine
        self.tools = tool_registry
        self.llm = llm_client
        self.tracer = tracer
```

---

## 4.2 run() 主流程（关键）

```python id="rt_03"
async def run(self, env: Envelope) -> Envelope:

    ctx = RuntimeContext.from_envelope(env)

    # 1. Memory
    memories = await self.memory.load(ctx)

    # 2. Skills
    skills = await self.skills.load(ctx.agent_id)

    # 3. Hook
    await self.hooks.emit("BEFORE_AGENT", ctx)

    # 4. Skill Selection
    skill = await self.skills.select(skills, ctx)

    # 5. Prompt Build
    prompt = self._build_prompt(ctx, skill, memories)

    # 6. LLM Call
    await self.hooks.emit("BEFORE_LLM", ctx)

    llm_resp = await self.llm.call(
        model=ctx.model,
        messages=prompt,
    )

    await self.hooks.emit("AFTER_LLM", {
        "response": llm_resp
    })

    # 7. Tool Execution (optional)
    tool_result = None
    if self._need_tool(llm_resp):
        tool_result = await self._execute_tools(llm_resp, ctx)

    # 8. Judge (optional)
    if ctx.enable_judge:
        score = await self._judge(llm_resp, tool_result)
        if score < ctx.threshold:
            return await self._retry(env, ctx)

    # 9. Build Output
    output_env = self._build_output(env, llm_resp, tool_result)

    # 10. Hook
    await self.hooks.emit("AFTER_AGENT", ctx)

    return output_env
```

---

# 5. Prompt 构建机制（关键）

---

## 5.1 Prompt Builder

```python id="pb_01"
def _build_prompt(self, ctx, skill, memories):

    system_prompt = f"""
You are {ctx.agent_id}

Skill:
{skill.description}

Memory:
{memories}

Task:
{ctx.payload}
"""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": ctx.payload}
    ]
```

---

## 5.2 Prompt 结构规范

```text id="pb_02"
[System]
- Agent Identity
- Skill Definition
- Memory Context
- Constraints

[User]
- Task Input

[Tool Schema]
- Optional tools
```

---

# 6. Skill Engine（与 Runtime 的关系）

---

## 6.1 Skill 数据结构

```python id="sk_01"
class Skill:
    name: str
    description: str
    prompt_template: str
    input_schema: dict
    output_schema: dict
```

---

## 6.2 Skill 选择逻辑

```python id="sk_02"
async def select(self, skills, ctx):

    # 简单版本：LLM routing
    if len(skills) == 1:
        return skills[0]

    return await self.llm_router.pick(skills, ctx)
```

---

# 7. Memory 注入机制

---

## 7.1 Memory 类型

```text id="mem_01"
Character Memory
Story Memory
Workflow Memory
Agent Memory
```

---

## 7.2 Memory Loader

```python id="mem_02"
async def load(self, ctx):

    character = await self.qdrant.search("character", ctx)
    story = await self.qdrant.search("story", ctx)

    return {
        "character": character,
        "story": story
    }
```

---

## 7.3 注入 Prompt

```text id="mem_03"
Memory:
- David: fat, 180cm, black shirt
- Lina: student, long hair
```

---

# 8. Tool 调用机制

---

## 8.1 Tool Schema

```python id="tool_01"
class ToolCall:
    name: str
    input: dict
```

---

## 8.2 执行

```python id="tool_02"
async def _execute_tools(self, llm_resp, ctx):

    tool_calls = parse_tool_calls(llm_resp)

    results = []

    for call in tool_calls:
        tool = self.tools.get(call.name)
        result = await tool.run(call.input)
        results.append(result)

    return results
```

---

# 9. Hook 生命周期（必须）

---

## 9.1 Hook Events

```python id="hook_01"
BEFORE_AGENT
BEFORE_LLM
AFTER_LLM
BEFORE_TOOL
AFTER_TOOL
AFTER_AGENT
ON_ERROR
ON_RETRY
```

---

## 9.2 Hook 调用

```python id="hook_02"
await self.hooks.emit(
    "BEFORE_LLM",
    context=ctx
)
```

---

## 9.3 Hook 结构

```python id="hook_03"
class HookManager:

    async def emit(self, event, context):
        handlers = self.registry.get(event)

        for h in handlers:
            await h.handle(context)
```

---

# 10. Judge / Evaluation（Agent “眼睛”）

---

## 10.1 Judge 接口

```python id="jd_01"
class Judge:

    async def evaluate(self, output, context) -> float:
        pass
```

---

## 10.2 示例规则

```text id="jd_02"
Script Agent:

- 是否JSON合法
- 是否有角色
- 是否有冲突

Image Agent:

- 是否符合prompt
- 是否人物一致
- 是否风格统一
```

---

## 10.3 Retry机制

```python id="jd_03"
if score < threshold:
    return self.run_again(env)
```

---

# 11. Trace（Langfuse绑定）

---

## 11.1 Trace结构

```text id="tr_01"
trace_id
 ├── llm_call
 ├── tool_call
 ├── memory_load
 ├── skill_select
 ├── judge
```

---

## 11.2 Hook中上报

```python id="tr_02"
langfuse.create_span(
    name="llm-call",
    input=prompt,
    output=response
)
```

---

# 12. Agent Runtime vs Agent（关键区别）

---

## Agent（轻）

```python id="ag_01"
class ScriptAgent:

    async def run(self, runtime, envelope):
        return await runtime.run(envelope)
```

---

## Runtime（重）

* 全流程控制
* 所有能力注入
* 不依赖 Agent 实现

---

# 13. 关键设计总结

---

## 13.1 Runtime = OS

Agent = Process
Skill = Function
Tool = System Call
Memory = Disk
Hook = Kernel Event
Message Bus = IPC

---

## 13.2 所有复杂性从 Agent 移到 Runtime

Agent 越来越简单：

```text id="sum_01"
Input → Runtime → Output
```

---

# 14. 下一步（重要）

下一份文档我会写：

# 📘 03 - A2A Message Bus 设计（重点升级）

会包含：

* Envelope Router
* Conversation Graph
* Session Mapping（你刚才那个设计）
* Inbox/Outbox
* Control Server 设计
* 多 Agent 通信协议
* 分布式扩展
* Redis Stream / Kafka 方案
* 断线恢复
* 消息顺序一致性

---

如果你确认，我们下一步直接进入：

👉 **03 - A2A Message Bus（核心升级版，会是整个系统最关键的一层）**
