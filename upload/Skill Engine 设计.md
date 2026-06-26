很好，这一层开始你系统就从“能跑的 Agent”进入：

> **Skill 驱动的 Agent Runtime（可控生成系统）**

这是防跑偏的核心机制，比 Hook 更“上层”。

---

# 📘 07 - Skill Engine 设计（V1 / 防跑偏核心）

---

# 1. 设计目标

Skill Engine 解决一个非常关键的问题：

> **如何让 Agent “按能力边界做事”，而不是靠 prompt 自由发挥？**

---

## ❌ 没有 Skill 的问题

* 同一个 Agent 一会写剧本，一会写分镜，一会乱生成 prompt
* LLM 自由发挥导致风格漂移
* tool 使用不稳定
* 多轮之后输出越来越“飘”
* 没有“能力约束”

---

## ✅ 有 Skill 后

Agent 变成：

> **Skill = 可执行能力模块（带约束的 prompt + tool + policy）**

---

# 2. 核心定义

---

## 2.1 Skill = 能力单元

```python id="skill_01"
class Skill:
    skill_id: str
    name: str
    version: str

    description: str

    prompt_template: str
    tools: list[str]

    input_schema: dict
    output_schema: dict

    constraints: dict
```

---

## 2.2 Skill ≠ Tool

| 概念 | Tool       | Skill      |
| -- | ---------- | ---------- |
| 层级 | 低层执行       | 高层能力       |
| 示例 | ffmpeg     | “视频合成导演能力” |
| 控制 | 无          | 强约束        |
| 输入 | 参数         | 语义任务       |
| 输出 | raw result | 结构化结果      |

---

# 3. 系统架构

---

```text id="skill_02"
                ┌────────────────────┐
                │   Agent Runtime     │
                └─────────┬──────────┘
                          ▼
                ┌────────────────────┐
                │   Skill Engine      │
                │                    │
                │ - selector         │
                │ - executor         │
                │ - validator        │
                └─────────┬──────────┘
                          ▼
        ┌────────────────────────────────┐
        │  Tools / LLM / Memory / A2A    │
        └────────────────────────────────┘
```

---

# 4. Skill 生命周期

---

```text id="skill_03"
SELECT
  ↓
LOAD
  ↓
INJECT CONTEXT
  ↓
EXECUTE (LLM + Tools)
  ↓
VALIDATE
  ↓
RETURN
```

---

# 5. Skill Registry（核心）

---

## 5.1 Skill 存储结构

```text id="skill_04"
skills/
├── script_writer/
│   ├── skill.yaml
│   ├── prompt.md
│   ├── schema.json
│   └── policy.json
├── storyboard_designer/
├── character_builder/
```

---

## 5.2 skill.yaml

```yaml id="skill_05"
name: storyboard_designer
version: 1.0

tools:
  - comfyui_generate
  - image_refiner

input_schema:
  episodes: list
  characters: list

output_schema:
  scenes: list

constraints:
  max_scenes: 15
  style: anime
```

---

# 6. Skill Selector（防跑偏核心）

---

## 6.1 输入

```python id="skill_06"
task = "生成分镜"
context = conversation_state
```

---

## 6.2 选择逻辑

```python id="skill_07"
def select_skill(task):

    if "分镜" in task:
        return "storyboard_designer"

    if "剧本" in task:
        return "script_writer"
```

---

## 6.3 升级版（LLM Router）

```text id="skill_08"
Input → LLM → Skill ID
```

---

# 7. Skill Prompt Injection（关键）

---

## 7.1 prompt = 模板 + context + constraint

```text id="skill_09"
You are STORYBOARD DESIGNER.

Constraints:
- max scenes: 10
- style: anime cinematic
- must output JSON

Input:
{episodes}
{characters}
```

---

# 8. Skill Execution（核心流程）

---

```python id="skill_10"
async def execute(skill, input):

    prompt = render(skill.prompt_template, input)

    llm_output = await llm.call(prompt)

    tool_output = run_tools(skill.tools, llm_output)

    return tool_output
```

---

# 9. Skill Validator（防跑偏第二层）

---

## 9.1 schema check

```python id="skill_11"
def validate(output, schema):

    if not match_schema(output, schema):
        raise SkillValidationError
```

---

## 9.2 constraint check

```python id="skill_12"
if len(output.scenes) > max_scenes:
    reject()
```

---

# 10. Skill 与 Hook 的关系（非常关键）

---

| 层级    | 作用   |
| ----- | ---- |
| Skill | 控制行为 |
| Hook  | 观察行为 |

---

## Hook 看到的是：

```text id="skill_13"
BEFORE_SKILL_EXECUTE
AFTER_SKILL_EXECUTE
```

---

# 11. Skill vs Prompt Engineering（本质区别）

---

| 项目   | Prompt | Skill     |
| ---- | ------ | --------- |
| 控制力  | 弱      | 强         |
| 可复用  | 差      | 强         |
| 可验证  | 无      | 有 schema  |
| 可版本化 | 无      | 有 version |
| 可组合  | 难      | 易         |

---

# 12. Skill 防跑偏机制（核心）

---

## 12.1 三层防护

### ① Prompt constraint

* style / format / role

### ② Schema validation

* JSON structure

### ③ Policy check

* scenes ≤ 10
* no forbidden content

---

# 13. Skill + A2A 联动（重要）

---

## 13.1 Skill 可以触发 A2A

```text id="skill_14"
Storyboard Skill
    ↓
needs critique
    ↓
send message → Critic Agent
```

---

## 13.2 Skill 输出可以成为 message

```python id="skill_15"
A2A.send({
    "type": "skill_output",
    "content": scenes
})
```

---

# 14. Skill Versioning（工程化关键）

---

```text id="skill_16"
storyboard_designer@1.0
storyboard_designer@1.1
```

---

## 升级机制：

* prompt 改动 = 新版本
* schema 改动 = 新版本
* tool 改动 = 新版本

---

# 15. Skill Market（未来扩展）

---

可以扩展为：

* Script Skill Marketplace
* Image Skill Marketplace
* Video Skill Marketplace

---

# 16. 目录结构（标准）

```text id="skill_17"
skill_engine/
├── selector.py
├── executor.py
├── validator.py
├── registry.py
├── loader.py
├── runtime.py
```

skills/
├── storyboard_designer/
├── script_writer/
├── character_builder/

```

---

# 17. 系统能力跃迁

---

## ❌ 没 Skill

- Agent 自由发挥
- 输出不可控
- 风格漂移

---

## ✅ 有 Skill

- Agent = 可控能力执行器
- 输出结构稳定
- 行为可预测

---

# 18. 本质总结

---

Skill Engine 让系统变成：

> **不是“会说话的 AI”，而是“有职业分工的 AI 工厂”**

---

# 19. 下一步（系统已经接近完整 OS）

下一份是：

# 📘 08 - MCP / Tool Protocol 设计（你 A2A + tool + control server 的统一协议层）

会解决：

- tool标准协议
- MCP sendMessage 统一结构
- control server routing protocol
- A2A envelope 标准化
- skill ↔ tool ↔ agent 三层统一
- message schema设计
- 可扩展插件协议

---

如果你继续，我下一步会把系统升级到：

> **“Agent OS 协议层（真正开始像操作系统一样运行）”**
```
