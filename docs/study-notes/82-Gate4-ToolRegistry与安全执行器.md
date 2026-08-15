# 82-Gate4-ToolRegistry与安全执行器

> G4-TOOL-02：Structured Tool Agent 纯确定性底座（ToolSpec / ToolCall / ToolObservation / ToolHandler / RegisteredTool / ToolRegistry / ToolExecutor）。
> 日期：2026-08-15
> 状态：Gate 4 = IN PROGRESS；G4-DESIGN-01 / R1 / R1-R1 = Reviewer accepted / CLOSED；**G4-TOOL-02 = REVIEW PENDING**（Structured Tool core infrastructure implemented candidate）。
> 契约权威：`docs/design/g4_structured_tool_agent.md`；本实现只做"注册一个 Tool → 接收结构化 ToolCall → 校验 → 执行系统绑定 Handler → 校验返回 → 得到 ToolObservation"，0 LLM / 0 Agent Loop / 0 真实工具。

这篇笔记面向第一次理解"工具执行底座"的读者。上一张卡（笔记 81）讲"为什么要有 Tool"，这张卡讲"底座到底怎么落地"。

---

## 0. 一句话

Gate 4 先不碰模型。先证明一件事：**系统能安全地"注册一个 Tool → 接收结构化 ToolCall → 校验 → 执行系统绑定 Handler → 校验返回 → 得到 ToolObservation"**。模型完全不参与。这一步做好了，后面接 LLM 选工具才安全。

---

## 1. ToolSpec 是什么

ToolSpec = 系统允许调用一个工具的**完整声明**，也是**模型唯一能看到的工具面**：

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str          # 唯一工具名
    description: str   # 告诉模型"什么时候用、怎么用"
    input_schema: dict # 输入参数强 Schema
    output_schema: dict# 返回值强 Schema
    version: str       # 契约版本
```

关键：**ToolSpec 里没有实现**。它只有"这个工具长什么样、输入输出是什么"，没有"这个工具怎么执行"。

## 2. 为什么 schema 是 Tool 的边界

Schema 就是"工具能力的边界线"。

- **input_schema** 规定模型能传什么参数、不能传什么参数；
- **output_schema** 规定工具返回什么结构、什么类型；
- 模型和工具之间**只靠 schema 通信**——模型传参数，工具吐结果，两边都不接触对方的"内部实现"。

如果不要 schema，模型可以传任意东西，工具可以返回任意东西，那"校验、授权、记账、复现"全都无从谈起。schema 让每一步都可被程序验证。

## 3. input_schema / output_schema 的差异

- **input_schema**：本实现强制要求根类型是 `object`，且 `additionalProperties` 必须显式为 `false`。为什么？因为 input 来自模型（未来）或调用方，**默认拒绝 unknown argument**——多传一个字段就失败，而不是默默接受或忽略；
- **output_schema**：本实现只要求是合法 JSON Schema，不强制 object 根。因为输出是系统 handler 控制的，信任级别更高；但仍要校验，防止 handler 悄悄返回结构之外的东西。

## 4. 为什么 additionalProperties = false

这是"严格模式"的关键开关。

JSON Schema 默认允许对象带上未声明的属性。如果 input 允许额外属性，那"模型多传了个字段"会被静默接受——这是脏数据进入工具的第一道口子。设置 `additionalProperties: false` 后，**只要参数里出现 schema 没声明的键，校验直接失败**（`INVALID_TOOL_ARGUMENTS`，handler 不执行）。

一句话：宁可拒绝，不可宽容。宽容会掩盖工具契约 bug。

## 5. ToolSpec 与 ToolHandler 为什么分开

- **ToolSpec**：给模型看的声明（name / description / schemas / version）；
- **ToolHandler**：系统内部的执行实现（`execute(arguments) -> object`）。

两者绝不能混。如果把 callable 塞进 ToolSpec，模型就能看到甚至"引用"一个可执行对象——那就等于给了模型选择任意代码执行的入口。分开后：模型只面对声明，系统只执行已注册的 handler，中间隔着 Registry。

## 6. RegisteredTool 为什么系统私有

```
RegisteredTool
├── spec: ToolSpec        ← 模型唯一可见面
└── handler: ToolHandler  ← 系统私有，不序列化，不进入 ToolSpec / ToolCall
```

Registry 内部保存的是 `name → RegisteredTool`。**handler 只存在于 Registry 内部**，`get_spec / list_specs` 永远只返回 ToolSpec，绝不把 handler 交出去。这就是"handler 不暴露给模型"的落地方式。

## 7. Registry 做什么

Registry 是工具的**真相来源**（source of truth）：

- `register(spec, handler)`：注册。**重复 name 直接 fail-fast，不允许覆盖**；
- `resolve(name)`：按名字找 RegisteredTool，找不到返回 None（由 Executor 转成 `UNKNOWN_TOOL`）；
- `get_spec(name)`：模型可访问的只读面，只返回 ToolSpec；
- `list_specs()`：确定性、按 name 排序、只返回 ToolSpec。

Registry **不执行任何工具**。它只负责"有哪些工具、长什么样、怎么找到执行实现"。

## 8. Executor 做什么

Executor 是**唯一执行入口**，固定流水线：

```
ToolCall
→ resolve RegisteredTool（查 Registry）
→ validate input_schema
→ allowlist / permission
→ per-call budget guard
→ handler.execute(...)
→ validate output_schema
→ JSON 安全 + 独立深拷贝
→ ToolObservation
```

任何一个环节失败，都返回结构化 `ToolObservation(status=error, error_code=...)`，**绝不抛 traceback 给上层**。

## 9. 为什么模型不能指定 callable

如果允许模型指定"我要调用 `core.xxx.func`"，就等于给了模型任意代码执行能力。正确做法：**模型只能输出 `tool_name + arguments`**，剩下的事（resolve、校验、授权、预算、执行、记账）全部由系统完成。模型永远不接触 handler，也永远不提供"实现路径"。

## 10. JSON Schema Validation（本任务新增依赖）

本任务引入 `jsonschema>=4.0`（requirements.txt）。用成熟库：

- `Draft202012Validator.check_schema(schema)`：验证 schema 自身合法；
- `jsonschema.validate(instance, schema)`：验证实际数据。

**不要自己手写残缺的 JSON Schema 解析器**。规则集是公开标准，成熟库已经处理了所有边界。

## 11. fail-fast 和 fail-closed

- **fail-fast**：构造阶段发现问题立刻抛错。ToolSpec 的 name/description/version 为空、schema 非法、input 缺 `additionalProperties:false`，都在构造时拒绝；
- **fail-closed**：执行阶段无法证明合法就当作失败。参数校验不过、权限不允许、预算耗尽、输出校验不过、结果不是 JSON-safe，全部返回 error Observation，而不是"放行试试"。

两者合起来：**宁可拒绝，不可放行**。

### frozen dataclass ≠ 深层不可变（R1 关键补丁）

`@dataclass(frozen=True)` 只做一件事：**阻止给字段重新赋值**。

```python
@dataclass(frozen=True)
class A:
    data: dict

a = A(data={"x": 1})
a.data = {"y": 2}      # ❌ FrozenInstanceError：被阻止
a.data["x"] = 999      # ⚠️ 不报错！字段本身是 dict，可变引用被直接改掉
```

所以 frozen 只能挡住 `spec.input_schema = ...`，**挡不住 `spec.input_schema["x"] = ...`**。这正是 R1-1 修补的洞：光靠 frozen 不够，还要把 schema 存进私有 backing，用 property 只返回深拷贝，让外部任何直接或嵌套修改都落在拷贝上，Registry 真正执行用的契约毫发无损。

为什么 Tool schema、ToolCall arguments 这类"审计事实"必须防 aliasing / mutation？

- **它们是契约的真相来源**：执行器用它校验参数、校验输出；如果被外部偷偷放宽，等于 bypass 了安全边界；
- **它们是审计事实**：`call_id / tool_name / arguments` 是"这次执行到底发生了什么"的证据，必须不可变，否则事后无法复现、无法归责；
- **aliasing 是隐式共享**：一个 dict 被多处引用，任何一处修改都会污染其它处，很难排查。

结论：**frozen 管"字段级不变"，深拷贝管"值级不变"，两者缺一不可。** 这个知识点本身很适合面试：问"frozen dataclass 是不是就是不可变？"——答案是否定的，还要处理可变内部对象。

## 12. Tool error 为什么不等于 Agent crash

工具执行失败（比如 handler 抛异常 → `TOOL_EXECUTION_FAILED`）返回的是**结构化 Observation**，不是程序崩溃。未来的 Agent 看到这个 Observation 可以决定：换工具、改参数、直接回答、或拒答。只有**系统级基础设施故障**才是真正的 crash。

本卡用固定错误码区分失败原因：

| error_code | 含义 | handler 是否执行 |
|---|---|---|
| UNKNOWN_TOOL | 工具未注册 | 否 |
| INVALID_TOOL_ARGUMENTS | 参数不符合 input_schema | 否 |
| TOOL_PERMISSION_DENIED | 不在 allowlist | 否 |
| TOOL_BUDGET_EXCEEDED | 预算耗尽 | 否 |
| TOOL_EXECUTION_FAILED | handler 执行异常 | 是（异常） |
| TOOL_RESULT_INVALID | 输出不合 schema / 非 JSON-safe | 是 |

## 13. Fake Handler 怎么测试基础设施

真实工具（knowledge_search / code_search / calculator）是下一张卡。本卡测试只用 **Fake Handler**：

- `EchoHandler`：返回合法结果；
- `FailingHandler`：执行即抛异常（验证 → TOOL_EXECUTION_FAILED，且异常细节不进 Observation）；
- `InvalidOutputHandler`：返回不合 output_schema 的结果（验证 → TOOL_RESULT_INVALID）；
- `CountingHandler`：记录调用次数（验证"参数/权限/预算失败时 handler calls = 0"）；
- `BytesOutput / SetOutput / CustomObject / NaN / Inf`：返回非 JSON-safe 结果（验证 → TOOL_RESULT_INVALID）。

用 Fake Handler 测的是**基础设施本身**：校验顺序对不对、错误码对不对、handler 是不是真的没被调用、返回结果是不是独立拷贝。

## 14. 为什么现在还不能称为 Tool Agent

本卡完成的是 **Structured Tool core infrastructure**，不是 Tool Agent。因为：

- **0 real tools**（只有 Fake Handler）；
- **0 LLM selection**（模型不参与选工具）；
- **0 tool loop**（没有"决策 → 执行 → 观测 → 再决策"的循环）。

Agent 的前提是"模型在预注册工具集合里选择并决定是否继续"。这些留给 G4-AGENT-04 / G4-RUNTIME-05。现在只能诚实写："Structured Tool core infrastructure implemented candidate"。

## 15. 下一步真实三个 Tool 怎么接进来

G4-TOOLS-03 会用本底座接入三个 read-only 工具，每个工具 = 一个 ToolSpec + 一个 ToolHandler：

- **knowledge_search**：handler 内部复用 Gate 3 检索能力（通过 ToolAdapter，不碰冻结 runtime），input 只有 `query`；
- **code_search**：handler 在 repo-root 内只读搜索，无路径逃逸；
- **calculator**：handler 用受控 parser / allowlisted arithmetic evaluator，绝不 `eval(user_input)`。

到时候只需要：写 Handler → 注册到 Registry → 用 Executor 执行。底座不用改。

## 16. 面试问答

**Q1：ToolSpec 里为什么没有 handler？**
> 因为 ToolSpec 是给模型看的声明，handler 是系统私有实现。混在一起会让模型接触可执行对象，等于给了任意代码执行入口。

**Q2：注册工具时重复名字怎么办？**
> fail-fast，直接拒绝覆盖。工具名是唯一键，Registry 是真相来源，不允许静默替换。

**Q3：参数多了个没声明的字段会怎样？**
> `additionalProperties: false` 触发校验失败 → `INVALID_TOOL_ARGUMENTS`，handler 0 次调用。

**Q4：handler 抛异常会崩掉整个系统吗？**
> 不会。Executor 捕获并返回 `ToolObservation(status=error, error_code=TOOL_EXECUTION_FAILED)`，异常细节（traceback / repr）绝不进入 Observation。

**Q5：为什么 call_id 不由模型生成？**
> call_id 是系统记账凭证。`ToolCall.create()` 由系统用 UUID 生成，构造时不接受外部 call_id，模型永远无法伪造调用记录。

**Q6：output 是 NaN 会怎样？**
> jsonschema 通常放过 NaN，但 JSON 标准不允许。Executor 在安全归一化阶段用 `json_deep_copy` 拒绝非有限浮点数 → `TOOL_RESULT_INVALID`。

**Q7：Registry 和 Executor 为什么分开？**
> Registry 管"有哪些工具、长什么样、怎么找 handler"；Executor 管"怎么安全地执行一次调用"。职责不同、变化原因不同，分开才能独立测试和加固。

**Q8：怎么证明"handler 没被调用"？**
> 用 CountingHandler 记录调用次数，断言参数/权限/预算失败场景下 calls == 0。

**Q9：为什么不允许手写 JSON Schema 解析器？**
> JSON Schema 是公开标准，边界情况多，成熟库（jsonschema）已经处理。手写残缺解析器会漏掉 `additionalProperties`、`$ref`、类型嵌套等大量规则，留下安全洞。

**Q10：为什么现在还不能说"实现了 Tool Agent"？**
> 0 real tools / 0 LLM selection / 0 tool loop。Agent 的核心是"模型在观测后做选择"，本卡只完成了可安全执行工具的底座。
