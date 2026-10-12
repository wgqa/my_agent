# B2 离线证据适配验收报告

**范围：** B0/B2 固定 Observation 组件对照与错误放行边界检查。
**真实模型调用：** 无。
**正式评测：** 未运行。
**提交/合并：** 未执行。

## 1. 验收结论

三类完整、受限的工具结果现在可以作为对应粒度的最终回答来源：

| Observation | 可支撑的窄回答 | 不可支撑的回答 |
|---|---|---|
| 完整 `code_search` `locator` | 精确的 `路径:行号` 定位行 | 函数实现、符号含义、该行逻辑正确等解释 |
| 完整 `changed_files` `status_list` | 与 Observation 完全一致的路径/状态清单；重命名行包含旧路径和新路径 | 单文件 diff、源码内容或其他未列出的变更 |
| 完整 `find_tests` `candidate` | 标明“工具返回的候选测试位置”的精确 `路径:行号` | 测试正文、测试已运行/通过、测试实际影响关系 |

为维持边界，低粒度回答必须采用逐行、可精确比对的格式。例如：`位置：docs/late.md:161 [E6]`、`工具返回的候选测试位置：tests/test_search.py:1 [E6]`、`src/app.py — modified [E6]`。完整变更清单必须逐项列完；重命名使用 `旧路径 -> 新路径 — renamed`。不符合格式、证据不完整、缺少引用或包含额外解释的低粒度引用，Verifier 返回 `INCOMPLETE`，最终拒答原因为 `ANSWER_EVIDENCE_REFERENCE_INCOMPLETE`。

这只验证 E-ID、来源粒度、完整性和路径/状态范围，不判断任意自然语言主张是否被来源语义蕴含。完整 `git_diff` 配合同一路径仍可能结构性绑定不准确的自由文本；B2 不能防止所有语义幻觉。

## 2. 实验身份与输入记录

- B0 基线：`evidence-rule-v5-baseline-20261010` / `f3c9e28aec8b29ccfcad9476ea88871aacbefa06`。
- B2 工作区：`experiment/evidence-ablation-b2`；HEAD 仍为上述 B0 Commit，B2 改动保持未提交。
- 固定记录来自任务卡 005 的真实模型运行：
  - Dev：`b0_flash_full_20261011_dev_r02`，Evaluator Commit `6bd2178934470840d39b8c7cdd334a6edf996740`。
  - Validation：`b0_flash_full_20261011_validation_r01`，同一 Evaluator Commit。
- 只读输入的 SHA-256：
  - Dev `calls.jsonl`: `833fbf39d5cc0a6b5e17d6334545a7e30cfce0c500096d5d880d3f4666195332`
  - Dev `manifest.json`: `247b1493e5076bfc09a02aeeb217a1c7654dade70acce31a4df2c6660fa91e73
  - Validation `calls.jsonl`: `fa220257e808b966e626bd89be5a5822499a306f719a50a2dcd5d43056d074ed`
  - Validation `manifest.json`: `16994020c83b9baddec21497a07330c8e93321c30d26f079deb24d9ec82b7665`

源记录位于 `../rag-knowledge-base-b0-eval-calibration-20261011/evaluation/tool_calls_v2/results/`。本次只读取 `calls.jsonl`、`manifest.json` 和任务卡 006 的既有审计报告，没有改写 Gold、历史分数或原始产物。

### 12 道固定 Observation 对照

任务卡 006 已记录的 12 题 B0 最终阻塞均为 `ANSWER_EVIDENCE_REFERENCE_MISSING`。每题第一次/唯一一次真实工具调用均为 `seq=7`。离线重放按该题 B0 最终记录中的 5 个已有 Evidence 项，从 `E6` 分配 B2 适配器 E-ID；`dev-022` 和 `dev-024` 各产生两个候选 E-ID。这里的 E-ID 是确定性组件重放，不是一次新的 Agent 执行记录。

| Case | B0 已知拒答点 | B2 Observation → Evidence | 合成有限答案 Gate | 需要额外读取正文？ |
|---|---|---|---|---|
| dev-006 | `code_search` 命中 `docs/late.md:161`，无可引用 E-ID | `E6 locator / complete` | `VALID`，只列路径和行号 | 否 |
| dev-008 | `code_search` 命中 `tests/test_cache.py:4`，无可引用 E-ID | `E6 locator / complete` | `VALID`，只列路径和行号 | 否 |
| dev-013 | `changed_files` 返回完整 5/5 清单，缺 E-ID | `E6 status_list / complete`；含 deleted、renamed、modified、untracked 五项 | `VALID`，逐项列全路径/状态，rename 含旧、新路径 | 否 |
| dev-014 | 完整清单含 `agent_demo/ranking.py -> agent_demo/scoring.py` | `E6 status_list / complete` | `VALID`，同一完整清单中精确列出重命名 | 否 |
| dev-016 | commit range 返回 `docs/guide.md / modified`，缺 E-ID | `E6 status_list / complete` | `VALID` | 否 |
| dev-021 | `find_tests` 返回 `tests/test_search.py:1`，缺 E-ID | `E6 candidate / complete` | `VALID`，标成工具返回的候选位置 | 否 |
| dev-022 | `find_tests` 返回两个候选，缺 E-ID | `E6 tests/test_cache.py:1`、`E7 tests/test_search.py:1`，均为 candidate/complete | `VALID`，两个候选均逐行引用 | 否 |
| dev-023 | 源文件已删除；工具仍返回 `tests/test_retired.py:1`，缺 E-ID | `E6 candidate / complete` | `VALID`，只陈述候选位置 | 否 |
| dev-024 | `find_tests` 返回两个候选，缺 E-ID | `E6 tests/test_adapters.py:1`、`E7 tests/test_requests.py:20`，均为 candidate/complete | `VALID`，两个候选均逐行引用 | 否 |
| val-007 | working tree 返回两项完整状态清单，缺 E-ID | `E6 status_list / complete`；untracked 与 modified 两项 | `VALID` | 否 |
| val-008 | commit range 返回 `src/urllib3/util/retry.py / modified`，缺 E-ID | `E6 status_list / complete` | `VALID` | 否 |
| val-012 | `find_tests` 返回 `test/test_filepost.py:6`，缺 E-ID | `E6 candidate / complete` | `VALID`，只陈述候选位置 | 否 |

有限答案由离线测试输入构造，只检查适配器和 Verifier 的结构行为。12/12 `VALID` **不等于** 12 道 Agent PASS，也不计作新增模型成功题。

## 3. 错误放行和安全反例

| 反例 | 验收结果 |
|---|---|
| `dev-015`：Router 为删除源码文件列表建立 `PROJECT_CODE_V1` | `changed_files` 只生成 `project_change/status_list`，`requirement_eligible=false`；即使完整状态清单可引用，也不能满足 `project_code/source_body`。保持 Router 分类问题，不将 status 冒充源码。 |
| `val-011`：10 条候选且 `truncated=true` | 候选 Evidence 标为 `partial`；Verifier 不放行。不能声称完整候选清单。第一版不支持以部分候选自动完成回答。 |
| `dev-029`：单文件 `git_diff` 引用整个工作区清单 | 引文出现其他文件路径时超出该 diff 的 `scope_paths`，返回 `INCOMPLETE`。要回答清单，必须引用完整 `changed_files status_list` 并列出其各项。 |
| `code_search` 定位行冒充函数实现 | 仅 `位置：path:line [E-ID]` 这种精确行可由 locator 独立绑定；加上“正确处理所有错误”等自由文本即拒绝。 |
| `find_tests` 候选冒充测试结果/影响关系 | 仅“工具返回的候选测试位置”精确行可由 candidate 独立绑定；添加“已通过”“覆盖此改动”等断言即拒绝。 |
| 损坏 `changed_files` Schema、未知状态、错误工具/调用身份 | 适配器不生成 Evidence；`ToolResultEvidence` 和 API Schema 也校验工具、粒度、路径和状态字段。 |
| 越界/绝对路径及 `src//x.py`、`src/./x.py` | 适配器拒绝，不生成 Evidence。Evidence 本身只接受安全 repo-relative POSIX 路径。 |
| 错误 E-ID 或重复 E-ID | 不存在的引用返回 `INVALID`；同一 Evidence 序列中的重复 E-ID 被拒绝。运行时 E-ID 按当前 Evidence 列表顺序分配。 |
| 敏感项被省略、列表截断或计数不一致 | completeness 不能是 `complete`，低粒度回答不能通过。完整空的 changed_files 清单也只有在计数为 0、无截断、无敏感遗漏时才能用受限的“当前没有可见变更”答案绑定。 |
| 过期/跨项目 Evidence | `ToolResultEvidence` 不接受为下一次运行的 `initial_evidence`；适配器只接受当前执行器回传、且 `call_id` 与实际 ToolCall 相同的 Observation。API 不接收客户端提交 Evidence。路径以当前绑定项目根目录为基准。Evidence 没有独立 `project_id` 字段，因此内部手工构造的跨项目对象无法仅凭对象自身再辨认；当前产品调用链不提供这种注入入口。 |

仍有语义边界：Verifier 不判断 `diff/source_body` 的自然语言是否被内容蕴含。同一路径 diff 配上“实现正确处理所有缓存故障”这类过宽文字仍可能通过结构绑定。测试保留了这一已知限制，不宣称 B2 消除了语义幻觉。

## 4. 改动范围与行为核对

### `git_diff` 的既有 B0 Evidence

B0 的 `core/tool_agent/runtime.py::_evidence_from_git_diff` 已经把成功的 `git_diff` Observation 转为 `EngineeringEvidence(project_change)`，并带有 bounded diff snippet。B2 删除这个旧适配函数，由 `_evidence_from_tool_result` 生成 `ToolResultEvidence(diff)`，因此同一次 git_diff 不会同时产生两条新旧 Evidence，也不会因为两个适配器给同一调用重复分配 E-ID。

B2 的 Evidence identity 加入 tool/version/call ID/参数哈希/结果哈希/范围；不同执行调用因此可拥有不同 E-ID，但运行时编号仍顺序唯一，Requirement 的源码路径计数仍按不同路径计算。一个 `code_search` 与后续 `read_project_context` 可分别表示 locator 与正文，这是不同粒度，不是重复表示同一来源事实。

差异：B0 `EngineeringEvidence` 的 `git_diff.snippet` 字段不再保留在 B2 `ToolResultEvidence` 公共结构中；新 Evidence 保存摘要、范围、行号、粒度和完整性。原始 `ToolObservation` 仍在本次运行的 Tool Context 中。需要人工查看 diff 正文时，应查看原始 Calls/Observation 记录；不能把哈希本身当成内容。

### API 兼容扩展

- `api/app.py::_serialize_project_evidence` 和两个响应构造器现在传递运行时 Evidence 的原始 E-ID。若不改装配序列化，旧代码只序列化 `EngineeringEvidence`，新 `ToolResultEvidence` 会被丢弃或重新编号。
- `api/schemas.py::ToolAgentEvidence` 将 path/line/snippet 设为可选，以表达没有单文件 path 的 `status_list`，并增加粒度、完整性、调用/哈希身份和结构化 `status_entries`。旧 Reader `EngineeringEvidence` 仍按原字段校验。
- `read_project_context` 在当前 B2 runtime 中仍产生旧 `EngineeringEvidence`；没有额外增加第二套 Reader Evidence。`ToolResultEvidence` 的运行时适配只处理 `code_search`、`changed_files`、`find_tests` 和 `git_diff`。

### B0 核心业务不变

- `core/engineering_requirements.py` 的差异只在 `evaluate_evidence_requirement` 加入来源粒度/完整性检查；Rule Router 的规则、profile 形状和分类逻辑未改。
- Planner、Decision Prompt、Tool Registry/Schema、工具执行器、预算常量没有修改。实际执行循环只在拿到成功 Observation 后调用 Evidence 适配器并登记 E-ID；没有增加模型调用、Tool Call 或恢复回路。
- 生产源码没有 Case ID、Gold 或固定题目特判。
- 没有移植 Candidate 的 Requirement Contract、Material Ledger、Verifier 或 Reviewer。

## 5. Diff 与实现位置

相对 B2 工作区 HEAD（B0 Commit）的累计 tracked Diff：**16 个文件，1,318 insertions / 144 deletions**。`git diff --stat` 不包含未跟踪文件 `tests/test_b2_tool_result_evidence.py`；该测试文件也保留在工作区供审阅。当前没有提交。

关键实现位置：

- Evidence 身份及 schema 不变量：`core/tool_agent/runtime_models.py::ToolResultEvidence`。
- 四类 Observation 适配与状态/完整性校验：`core/tool_agent/runtime.py::_evidence_from_code_search`、`_evidence_from_changed_files`、`_evidence_from_find_tests`、`_evidence_from_tool_result`。
- 运行时登记新 E-ID：`core/tool_agent/runtime.py` 的 Observation 完成分支。
- granularity 约束：`core/engineering_requirements.py::evaluate_evidence_requirement`。
- 受限 locator/candidate/status-list 引用格式与路径范围：`core/engineering_verification.py::_tool_result_citations_have_complete_matching_scope`。
- 结构化变更状态输出：`api/schemas.py::ToolAgentChangeStatus`、`ToolAgentEvidence`。

可审阅完整工作树差异：在 B2 工作区运行 `git diff`；摘要为 `git diff --stat`。关键路径没有任何 Case ID 特判。

## 6. 离线验证

在新建的 B2 工作区临时目录执行了 20 个相关离线测试模块，包含 B2 新测试、Requirement/Verifier、Runtime/API、真实本地 Git 工具、测试发现工具、Stream、Evaluation Observer/Scorer。

```powershell
pytest -q tests/test_b2_tool_result_evidence.py tests/test_engineering_requirements.py tests/test_engineering_verification.py tests/test_product_grounding_21.py tests/test_tool_agent_runtime.py tests/test_tool_agent_core.py tests/test_tool_agent_evidence.py tests/test_tool_agent_finalization_guard.py tests/test_tool_agent_api.py tests/test_project_evidence_excerpt.py tests/test_project_test_acquisition.py tests/test_tool_agent_activity.py tests/test_tool_agent_real_tools.py tests/test_git_change_tools.py tests/test_test_discovery_tools.py tests/test_tool_call_evaluation_v2_observer.py tests/test_tool_call_evaluation_v2.py tests/test_engineering_stream.py tests/test_engineering_stream_v2.py tests/test_engineering_conversation_stream_v2.py --basetemp=.pytest-task008-suite-final2-20261012
```

结果：**502 passed / 0 failed / 4 skipped**，3 条第三方依赖弃用/兼容性 warning。最初默认 pytest 临时目录触发 Windows `PermissionError`；改用 B2 工作区内新建的 `--basetemp` 后复跑通过。测试中没有真实模型调用。

## 7. 是否可以进入正式消融

**组件层：通过。** 固定 12 条 Observation 全部可生成带真实工具身份、参数哈希、结果哈希、粒度与完整性状态的 Evidence；相应合成有限答案全部通过 Gate；反例保持拒答。B2 可以作为后续经批准的正式模型对照候选。

**真实 Agent 成功率：未验证。** B0 Planner/Decision Prompt 未改；模型是否会输出 Gate 所需的精确逐行格式尚未测试。格式不匹配会继续拒答，即使 Observation 内容充分。正式 Agent PASS 增量必须用后续真实模型运行测量，不能把本报告的 12 条组件 Gate 结果记为新增成功题。

**B0 与 Candidate 状态：** B0 工作区仍在 `f3c9e28...` 且干净；Candidate 工作区仍在原分支/HEAD 且干净。本轮没有修改二者。


## 8. Gate 与适配器源码定位

- B0 在这 12 条记录上没有可引用的对应 Tool Evidence：`core/engineering_verification.py:103` 的 `_evaluate_answer_evidence_binding` 在无引用时返回 `ANSWER_BINDING_STATUS_MISSING`；运行期将其归因为 `ANSWER_EVIDENCE_REFERENCE_MISSING` 的位置是 `core/engineering_verification.py:810`。这解释历史拒答，不代表 B0 的材料本身为空。
- B2 locator/candidate 仅接受精确位置行：`core/engineering_verification.py:217` 的 `_is_bounded_location_line`；status list 仅接受结构化路径状态行：`:243` 的 `_is_bounded_status_line`。批次完整性、逐项清单、作用域与自由文本限制集中在 `:282` 的 `_tool_result_citations_have_complete_matching_scope`。不满足时 `_evaluate_answer_evidence_binding` 在 `:164` 返回 `INCOMPLETE`，对外拒答原因在 `:812` 映射为 `ANSWER_EVIDENCE_REFERENCE_INCOMPLETE`。
- `NO_ADDITIONAL_REQUIREMENT` 下，精确位置行/完整状态行可以作为范围内的有限答案通过引用绑定；locator/candidate/status_list 不能满足 `PROJECT_CODE_V1`、`PROJECT_TEST_V1` 或要求变更材料的 Requirement。来源粒度和完整性过滤由 `core/engineering_requirements.py:219` 的 `evaluate_evidence_requirement` 执行，且不依赖 `requirement_eligible` 单字段。
- Evidence schema 与 adapter 位置：`core/tool_agent/runtime_models.py:347` `ToolResultEvidence`；`core/tool_agent/runtime.py:298` code_search，`:348` changed_files，`:414` find_tests，`:468` 通用结果分发；API 结构化状态与序列化位于 `api/schemas.py:238`、`:270` 及 `api/app.py:545`、`:613`。
- 新增边界测试在 `tests/test_b2_tool_result_evidence.py`，覆盖低粒度精确引用、任意结论拒绝、完整批次、缺项/错误状态/截断、`PROJECT_CODE_V1` 与 `PROJECT_TEST_V1` 不被低粒度材料满足，以及完整空变更清单的窄回答。

完整工作区改动仍是未提交状态。`git diff --stat` 的 16 个已跟踪文件统计不包含新增测试文件；新测试文件保留在工作区。没有生成或覆盖历史评测产物。

### Diff stat（本轮最终工作树）

下列为 `git diff --stat` 的完整已跟踪文件输出；Git 默认不会把尚未跟踪的文件计入该命令。另有 `tests/test_b2_tool_result_evidence.py`（657 行）和本报告两个新文件，均未暂存、未提交。

```text
 api/app.py                                     |  48 +--
 api/schemas.py                                 | 190 +++++++++++-
 core/engineering_requirements.py               |  28 +-
 core/engineering_verification.py               | 252 +++++++++++++++-
 core/tool_agent/runtime.py                     | 387 ++++++++++++++++++++++---
 core/tool_agent/runtime_models.py              | 359 ++++++++++++++++++++++---
 tests/test_engineering_stream.py               |   7 +-
 tests/test_engineering_stream_v2.py            |   7 +-
 tests/test_git_change_tools.py                 |  14 +-
 tests/test_product_grounding_21.py              |   4 +
 tests/test_project_evidence_excerpt.py          |  11 +-
 tests/test_project_test_acquisition.py          |   2 +-
 tests/test_test_discovery_tools.py              |  21 +-
 tests/test_tool_agent_api.py                    | 122 ++++++--
 tests/test_tool_agent_runtime.py                |   5 +-
 tests/test_tool_call_evaluation_v2_observer.py  |   5 +-
 16 files changed, 1318 insertions(+), 144 deletions(-)
```

### 多结果 Observation 的精确边界

locator/candidate 不是无条件一条就能支撑任意位置问答：如果同一调用返回多个命中/候选，Gate 以相同 `call_id` 和 `result_sha256` 组成批次，要求答案引用该批次全部位置（见 `core/engineering_verification.py:339-351`）。因此完整单结果的文件/行号问答可以通过；多结果时逐项列出可以通过，只回答子集会因批次不完整返回 `ANSWER_EVIDENCE_REFERENCE_INCOMPLETE`。这属于当前的保守完整性规则，未来若需支持用户指定子集，要先让 Gate 能验证原始问题的筛选范围，不能简单移除批次检查。

### 本轮测试临时产物

B2 工作区仍有 10 个未跟踪 `.pytest-task008-*` 隔离 pytest 临时目录；它们只含本轮测试临时产物，不属于业务或评测源码。递归删除命令被执行策略拒绝，因此未尝试换用其他删除方式。它们及本报告、新增测试文件会出现在 `git status --short` 中；B0 与 Candidate 工作区不受影响。

## 9. 关键源码 Diff 摘录

以下为工作树 Diff 的关键新增逻辑摘录，省略的其余改动可在 B2 工作区用 `git diff` 完整审阅。

### 9.1 Binding Gate 接入结构化来源范围

```diff
     cited_evidence = tuple(
         item for item in evidence if item.evidence_id in references
     )
+    if not _tool_result_citations_have_complete_matching_scope(
+        proposed_answer, cited_evidence, evidence
+    ):
+        return (
+            ANSWER_BINDING_STATUS_INCOMPLETE,
+            True,
+            references,
+            (),
+        )
     if evaluate_evidence_requirement(requirement, cited_evidence).satisfied:
```

Gate 在既有 Requirement 判定前检查受信任 Tool Evidence 的粒度、完整性、E-ID、路径和窄格式；低粒度 Evidence 本身仍不会增加工程源码/测试正文 Requirement 的计数。

### 9.2 Requirement 使用来源粒度，而非信任布尔开关

```diff
+        eligible = _public_value(item, "requirement_eligible")
+        granularity = _public_value(item, "granularity")
+        completeness = _public_value(item, "completeness")
+        if eligible is not None:
+            if type(eligible) is not bool or not eligible:
+                continue
+            if (
+                granularity not in _REQUIREMENT_SOURCE_GRANULARITIES.get(kind, ())
+                or completeness != "complete"
+            ):
+                continue
```

完整匹配规则见 `core/engineering_requirements.py:25-30`、`:219-263`；`project_code/project_doc/project_test` 只接受 `source_body`，`project_change` 只接受 `diff`。

### 9.3 API 为 status_list 保留结构化状态

```diff
+class ToolAgentChangeStatus(BaseModel):
+    path: str = Field(min_length=1)
+    status: Literal["modified", "added", "deleted", "renamed", "untracked"]
+    old_path: Optional[str] = Field(default=None, min_length=1)
+
 class ToolAgentEvidence(BaseModel):
-    path: str = Field(min_length=1)
-    start_line: int = Field(ge=1)
-    end_line: int = Field(ge=1)
-    snippet: str = Field(min_length=1, max_length=MAX_PROJECT_CONTEXT_CHARACTERS)
+    path: Optional[str] = None
+    start_line: Optional[int] = Field(default=None, ge=1)
+    end_line: Optional[int] = Field(default=None, ge=1)
+    snippet: Optional[str] = Field(default=None, min_length=1, max_length=MAX_PROJECT_CONTEXT_CHARACTERS)
+    granularity: Optional[Literal["locator", "candidate", "status_list", "source_body", "diff"]] = None
+    completeness: Optional[Literal["complete", "partial", "unknown"]] = None
+    status_entries: List[ToolAgentChangeStatus] = Field(default_factory=list)
```

这里省略 schema 中对旧 `EngineeringEvidence` 完整字段、Tool 调用身份、哈希、路径、安全状态和跨字段组合的校验。状态条目使 Verifier 能核对真实变化类型和 rename 两端；不把 `changed_files` 的结果转写为 diff 或正文。

### 9.4 ToolObservation 适配的来源身份

`core/tool_agent/runtime.py:468-505` 根据实际 Observation 的工具名和 `call_id` 分派到 `code_search/changed_files/find_tests/git_diff` 适配器；`:126-150` 对当前受信任 Evidence 序列去重并编号。任一失败 Observation、工具名不匹配、call_id 不匹配或内容不满足 schema 均不会产生可引用 Tool Evidence。
