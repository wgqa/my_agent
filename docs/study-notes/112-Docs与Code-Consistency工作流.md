# Docs 与 Code Consistency 工作流

## 1. 什么是 documentation drift

Documentation drift 是文档对产品行为、入口、配置或安全边界的描述，逐渐与当前 HEAD 的真实实现不一致。它不只表现为明显错误，也可能是文档只覆盖旧入口、遗漏新入口，或只描述了一个仍然正确但范围不完整的局部事实。

G11-05 验证的不是 README 摘要能力，而是一个 Docs ↔ Code 比较工作流：

```text
Document claim
    ↓
code_search
    ↓
read_project_context(document)
    ↓
locate current implementation
    ↓
read_project_context(code)
    ↓
compare semantics
    ↓
CONSISTENT / OUTDATED / INCOMPLETE / PARTIALLY CONSISTENT
    ↓
bounded correction or no-change recommendation
```

## 2. 为什么 README 不是 implementation authority

README 是产品说明和使用入口，不是 Runtime、API 或 Tool Registry 的权威来源。DOC01 的 README 仍只列 `knowledge_search`、`code_search`、`calculator`，但当前 `build_readonly_tool_registry` 已注册七个 bounded read-only Tool；DOC02 仍只列 Basic RAG、Agentic RAG 和 Structured Tool Agent，却遗漏当前 Engineering 公开入口。文档可以故意落后，也可以只选择产品层面的部分内容，因此必须把它作为待核对的 claim source。

这不意味着所有文档 claim 都是错误的。DOC03 的 5/4/2 system-controlled budget 与当前 `ToolAgentBudget`、builder 和 hard cap 一致；DOC04 的 Safe Trace 核心安全声明也与 allowlist projection 和 RuntimeTraceEvent contract 一致。benchmark 必须同时包含 stale/incomplete 和 still-correct docs，否则 Agent 可能只学会把所有文档判为过时。

## 3. 为什么也不能只看代码

只有代码证据时，Agent 只能说明当前实现有什么，不能证明 README 到底声称了什么，也不能判断某段实现是否正是用户要求核对的文档 claim。只有文档证据时，Agent 又无法判断当前 HEAD 是否已经更新了行为。可靠判断需要两侧证据：文档实际文字 + 当前实现的 bounded source context。

`code_search` 是 locator，负责在当前项目中定位 README、代码文件和可能的 anchor；`read_project_context` 才能提供真正被读取的行窗口。对 DOC01，必须先读 README 的“三个 Tool” claim，再读 registry registration 和 runtime builder；对 DOC02，必须把 README 的三种模式与 `api.app` 的 `/project`、`/engineering/query`、`/engineering/knowledge` 对照。

## 4. 三类一致性判断

- `CONSISTENT`：文档 claim 的语义与当前实现一致，当前无需修正。例如 DOC03 的 5 iterations、4 tool calls、2 tool errors 是 system-owned budget；模型看到 `remaining_*` 不代表能扩大 hard budget。
- `OUTDATED / INCOMPLETE`：文档仍描述旧的或不完整的产品 surface。例如 DOC02 的旧入口仍存在，但 Engineering Agent 的入口没有列出。
- `OUTDATED / INCONSISTENT`：文档对当前实现作出直接不再成立的断言。例如 DOC01 把当前 Tool registry 说成只有三个 Tool。
- `PARTIALLY CONSISTENT`：一部分 claim 仍成立，另一部分范围、例外或传播关系已经过时。它不应被强行压缩成完全正确或完全错误。

这些 label 是人工 Gold 结论。Runner 只保存 Gold label 身份和 evidence shape，不自动判 Agent 的 consistency correctness、修复建议或 claim-level grounding。

## 5. path hit 不等于 claim visible

`document_source_paths = ["README.md"]` 只能说明预期文档文件；Agent 读到 README 的任意一行，并不表示它读到了 DOC01 的 Tool list、DOC02 的三种模式、DOC03 的 5/4/2 或 DOC04 的 Safe Trace claim。`doc_claim_visible` 因此只检查真实 `project_doc` snippet 是否包含固定 anchor，例如 `Safe Trace` 或 `Chain-of-Thought`，而且只是 diagnostic signal。

同理，`code_source_paths` 命中 `api/app.py` 或 `runtime_models.py`，不等于上下文窗口显示了 route decorator、allowlist、dataclass default、registration call 或 trace serialization。`code_behavior_visible` 只接受保守的 implementation-defining structure，例如 function body、route decorator、allowlist constant、registration call、dataclass/default assignment 或 branch/raise。它不能证明所有回答 claim 都被覆盖。

## 6. Docs ↔ Code 是 claim-evidence coverage

一致性判断本质上是 claim-evidence coverage 的双侧版本：

```text
document claim evidence
        +
current implementation evidence
        ↓
semantic comparison
```

`project_doc + project_code` 是最低限度的 evidence pair。只有 `project_doc`，可能把旧说明当成当前事实；只有 `project_code`，可能忽略文档的实际措辞和范围。即使 pair 存在，也还要确认它们分别覆盖了 question 的子 claim；`doc_code_pair = true` 不能自动推出 label 正确。

## 7. 四个固定 case 的工程边界

DOC01 核对 Tool Registry：当前七个 Tool 仍全部是 bounded read-only，不存在 arbitrary shell，因此 README 过时不等于安全边界失效。维护动作是更新产品 surface，同时保留 Gate 4 历史 evidence 的历史口径。

DOC02 核对 Product/API surface：`/query`、`/agent/query`、`/tool-agent/query` 仍然存在，不能因为 README 漏写 Engineering 就删除 legacy endpoint；应补充 `/project`、`/engineering/query` 和 `/engineering/knowledge` 的公开语义。

DOC03 核对预算：`ToolAgentBudget` 默认 5/4/2，并拒绝超过冻结 cap 的值；builder 不接受调用方扩大预算。`DecisionControlState` 的 `remaining_iterations`、`remaining_tool_calls`、`tool_call_allowed` 和 `must_terminate` 是 Runtime-owned trusted metadata，不是模型可修改的配置。

DOC04 核对 Safe Trace：Engineering public trace 在 legacy allowlist 上增加 `provider_call_count`、`repair_attempted`、`repair_succeeded`、`parse_failure_category` 四个结构化 diagnostics，但仍由 `_safe_trace` 投影 allowlisted keys；这些字段不是 private reasoning。结论只覆盖 public/runtime trace contract，不扩大为整个进程永远不持有任何模型数据。

## 8. 评测和环境边界

本任务复用 G11-04 已验收的 Knowledge/Project preflight。case 禁止 `knowledge_search`，是因为 Gold 来自当前 README 与当前代码；这不表示 verified Knowledge backend 可以从 Formal runtime 缺席。HTTP error、503、connection failure、invalid JSON 或错误 runtime identity 都是 infrastructure failure；HTTP 200 的 structured `completed`、`failed` 或 `refused` 才是有效 Agent case result。

Artifact 复用 shared `validate_artifact_safety`，包括 JSON semantic、JSONL semantic 和 Markdown JSON-fence semantic validation。runner 不记录 raw provider output、Prompt、CoT、API key 或绝对路径；所有自动指标都服务于后续人工 Gold review。

G11-05-01 只建立 benchmark、runner、deterministic tests、Study Note 和 status。Formal 尚未运行，不提前修 README，不开始 G12，也不因为固定 case 的 drift 直接修改被测产品文档。只有在 Formal 和人工 review 完成后，才另行决定文档修复或 workflow closure。

## 9. Benchmark Prompt Leakage

Benchmark 的 Gold source 属于 evaluator metadata，不属于用户 query。Evaluator 知道正确 label、实现位置和应满足的 obligation，并不意味着 Agent 应在题干中直接看到这些答案。题干只能描述用户希望核对的文档 claim 和自然的比较任务。

例如，题干直接写“当前七个 Tool”会泄漏 comparison result；直接写 `default_tools.py`、`integration.py`、`api/app.py` 或 `runtime_models.py` 会把 code_search 的 locate implementation 任务变成按提示读取文件。题干如果写“缺少的 Engineering 公开入口”，还会预设 README 的结论是 incomplete。这样的 case 即使 Agent 回答正确，也不能证明它完成了 Docs ↔ Code transfer。

因此 DOC01-DOC04 保留 Gold label、source paths、anchors 和 obligations，但 query 改为不带结论、不带实际数量、不带 exact Gold implementation path 的自然用户问题。Agent 必须从 README 的真实文字和当前代码证据自行形成 consistency judgment；Gold label 只用于人工评审，不自动评分。

完整 case contract 必须把 `question` 与 `obligations` 和 label、source paths、anchors、required/forbidden tools 一起 canonicalize 并冻结 SHA-256。只冻结 case id 或 source path 不足以防止 benchmark 漂移：任何题干、Gold obligation、结论、证据边界或 Tool contract 的改变都必须导致 deterministic validation 失败。这个 identity freeze 保护的是评测有效性，不是产品运行时行为。

## 10. Evaluator Must Not Live Inside the Evaluated Search Space

Prompt leakage 和 repository leakage 是两个不同层次的问题。Prompt leakage 是题干直接告诉 Agent Gold 结论、实际数量或 exact implementation path；repository leakage 则是 evaluator 的 case、obligation、Gold label 和 runner 文件被放进 Agent 可以搜索的 project checkout。前者污染输入，后者污染 evidence plane；只在 Prompt 中要求“不要搜索 evaluator 文件”不能修复后者，因为 `code_search` 仍会把这些文件作为真实项目证据返回。

本次 G11-05 Formal attempt `g11-05-docs-code-consistency-formal-20260824-221006` 已经提供了实证 contamination：4/4 requests completed，但 DOC03 final answer 明确引用 `docs/study-notes/112` 作为 5/4/2 consistency 依据。该文件包含 Gold/evaluator 语义，因此这次 run 是 `INVALID / EVALUATION CONTAMINATION`，不能用于 Agent capability、manual Gold score 或 G11-05 PASS/MIXED/NEGATIVE 结论。

正确的边界是 `Evaluator Checkout != Project Target Checkout`。Evaluator checkout 保存 runner、tests、Study Note 和 case contract；Project Target Checkout 固定为不含 G11-05 evaluator 文件的 `3e0d5cd54ff916ae1df650ca9a55ad21b363234a`。Formal 前必须分别校验 evaluator/project 的 HEAD、tracked-clean 状态和不同的 resolved directory，并对 project checkout 拒绝 evaluator-owned 文件。不要粗暴禁止正常 project code 中偶然出现 `DOC01` 等字符串；guard 应针对明确的 evaluator-owned paths 和身份。

Runner manifest 必须同时记录 `evaluator_commit` 与 `project_source_commit`，并标记 `project_target_isolated=true`、`project_evaluator_same_root=false`。所有 document/code source paths 都相对于 project checkout 验证；API 服务也必须从 frozen project worktree 启动，让 `api.app` 的 repository binding 指向被评测项目，而不是 evaluator checkout。Artifact safety 同时检查 evaluator 和 project 两个 local root，继续保留 JSON、JSONL 和 Markdown JSON-fence 的 semantic validation。
