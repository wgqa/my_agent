# Diagnosis 与 Config Analysis 工作流

## 1. 这类工作流解决什么问题

Diagnosis & Config Analysis 不是修改配置系统，也不是让 Agent 凭经验猜一个“可能原因”。它处理的是一个已经出现的 symptom、error 或 configuration clue：

```text
Symptom / Config clue
        ↓
    code_search
        ↓
read_project_context
        ↓
必要时读取第二个实现点
        ↓
    Diagnosis
        ↓
Remediation / verification suggestion
```

这里至少要区分四件事：

- symptom：用户看到的现象，例如 startup failed 或 `/engineering/query` 不可用；
- root cause：真正触发异常、拒绝启动或阻止 runtime 构造的代码条件；
- consequence：根因发生后哪些对象被置为 `None`、哪些 endpoint 因此不可用；
- remediation：如何修复输入或配置，以及如何验证修复，不是绕过系统校验。

一个文件名只能提示可能的定位方向。它不能证明函数如何校验、异常在哪里传播，也不能证明两个同名配置属于同一个层次。因此，Diagnosis 工作流要求先找到实现，再读取实现上下文。

## 2. 为什么不能只看文件名

`core/config.py` 可能同时包含 chunk、generator、retriever 等多组配置；`api/app.py` 可能同时包含 Pipeline、legacy Tool Agent 和 Engineering Agent 的初始化。仅凭文件名回答“配置错了，所以 provider 失败”，会把不同阶段的故障混在一起。

真正需要确认的是：

1. 哪个函数或构造器接收这个值；
2. 哪个条件会触发 `ConfigError` 或其他明确异常；
3. 异常发生在 startup 的哪一个 `try` 边界；
4. 哪些 runtime 已经创建，哪些 runtime 因此没有创建；
5. 修复输入之后应该检查哪个状态或行为。

所以 `code_search` 是 locator，不是 evidence。它返回 path、line 和有限匹配行，适合回答“去哪里读”。`read_project_context` 才能提供函数体、分支、`raise`、返回值和相邻初始化逻辑等实现证据。

## 3. 四个配置边界

G11-04 的四个 Dev case 刻意覆盖不同的配置边界：

| Case | 边界 | 关键区别 |
|---|---|---|
| DC01 | system-owned project workspace | explicit invalid root 不等于 env 未设置 |
| DC02 | Engineering Knowledge backend | verified corpus 不等于 legacy vector store |
| DC03 | Pipeline chunk validation | `overlap < size` 是构造时不变量 |
| DC04 | generator budget 与 decision cap | 同名 `max_output_tokens` 属于不同层 |

### DC01：Invalid Engineering Project Root

`resolve_engineering_project` 负责把系统绑定到一个 Engineering Project。配置值为空时，系统可以使用默认 repo；但显式给出的不存在路径或非目录必须报错：

- `ENGINEERING_PROJECT_ROOT does not exist`；
- `ENGINEERING_PROJECT_ROOT must be a directory`。

这不是一个可以静默 fallback 的普通用户查询参数。Project root 是 system-owned binding；模型不能在回答中自己挑选另一个目录。`api.app` 的 lifespan 在 Pipeline 初始化的 `try` 之前解析这个 binding，因此它与“Pipeline init 失败后打印 warning 并将 pipeline 置空”属于不同传播边界。

正确修复是配置真实目录，或者取消显式 override 以使用默认 repo。把非法值忽略掉会把 Agent 绑定到用户没有要求的代码库，反而隐藏更严重的问题。

### DC02：Engineering Knowledge Root Missing

`ENGINEERING_KNOWLEDGE_CORPUS_ROOT` 是独立 verified backend 的入口。`VerifiedEngineeringKnowledge.from_repo(None)` 或 blank 值直接抛出 `EngineeringKnowledgeError`。该 backend 是独立、read-only、BM25 的 Engineering Knowledge backend，不是 legacy `./data/vector_store` 的别名或 fallback。

Engineering Knowledge 初始化位于 legacy Tool Agent 初始化成功之后的独立 `try` block。失败时 Engineering runtime 和 facade 会被置为 `None`，但不能据此笼统断言整个 FastAPI 必然启动失败。`/engineering/knowledge` 的 `ready` 反映 facade 是否可用，`verified` 反映 backend identity 是否已验证。

正确修复是提供通过 manifest、文件和 corpus identity 校验的 corpus root；不能为了让状态变成 ready 而关闭 verification。

### DC03：Invalid Chunk Overlap

给定：

```yaml
chunker:
  size_tokens: 512
  overlap_tokens: 512
```

合法关系是：

```text
chunk_size > 0
chunk_overlap >= 0
chunk_overlap < chunk_size
```

因此 `512 == 512` 违反严格小于关系，应该在 Config construction / Pipeline init 阶段触发 `ConfigError`。`api.app` 对 Pipeline 初始化异常打印 warning 并将 `pipeline = None`；依赖 Pipeline 的后续 runtime 不能正常构建。这不是 embedding 或 provider failure。

修复应当把 overlap 改成严格小于 size 的值，并保留 validation。绕过验证只会把无效分块参数推迟到更难定位的阶段。

### DC04：Generator Budget 与 Engineering Decision Cap

给定：

```yaml
generator:
  max_total_tokens: 4096
  max_output_tokens: 4096
```

两个 generator 值都必须是正整数，并且 `max_output_tokens < max_total_tokens`。相等会触发 `ConfigError`。这组值属于 Pipeline / answer generator 的配置预算。

Engineering Agent 的 1200 是 profile-scoped structured decision transport cap。它服务于 Engineering Decision Provider 的结构化决策响应，和 Pipeline generator 的 total/output 关系不是同一个配置边界。把 `config.yaml` 的 generator output 改大，不会自动修改 Engineering v2 的 1200 policy；讨论后者时必须去看 profile policy 的代码实现。

这个 case 专门检查 config analysis 能否避免因为字段同名就合并两个系统层次。正确修复先满足 Pipeline 的 total/output 关系；若确实需要变更 decision cap，那是另一个明确的代码级 policy 变更，不能伪装成 YAML 调整。

## 4. Evidence contract

G11-03 已经说明：correct file 不等于 sufficient evidence。G11-04 因此只对 evidence shape 做自动统计，不自动宣称诊断正确：

- `project_code_evidence_cases`：是否获得 `project_code` evidence；
- `multi_file_evidence_cases`：project evidence 是否来自至少两个不同 path；
- `behavior_body_visible_cases`：源码片段是否出现保守的函数体、分支或 `raise` 结构信号。

`behavior_body_visible` 只是结构诊断。它不能证明读取的是 Gold 函数，也不能证明回答中的每一个 claim 都被覆盖。一个 import snippet 可以有正确文件名，却没有足够的行为证据；一个有函数体的 snippet 也可能仍然缺少启动调用方。因此 diagnosis correctness、root-cause correctness、remediation correctness 和 claim-level grounding 仍由人工 Gold review 判断。

## 5. 工具边界

Required tools 是：

- `code_search`：在系统绑定的 project 内做 bounded literal search，定位可能的 path 和 line；
- `read_project_context`：读取 bounded、line-numbered 的源码上下文，确认真正实现。

Forbidden tools 是：

- `changed_files`、`git_diff`、`find_tests`：本 task 不是历史变更或测试推荐任务；
- `knowledge_search`：四个 case 是当前仓库的配置与启动诊断，不是通用理论问答；
- `calculator`：没有需要独立计算的 Gold obligation。

这里不冻结唯一 sequence。通常是 `code_search` 后读取一个实现点，必要时再读取第二个实现点；有些 case 可能先通过一个命中定位，再读取跨文件调用方。固定的是语义责任和 required coverage，不是模型必须复现某个 token-level 调用顺序。

5/4/2 budget 下，两个 required tools 为一条紧凑证据链：搜索负责缩小范围，context 负责把 locator 转成实现证据，剩余能力用于读取第二个实现点或给出有界结论。预算仍由 Runtime hard enforcement 控制，Prompt guidance 不能扩大预算。

## 6. Artifact 与评测边界

Runner 绑定 operator 声明的 `source_commit` 到本地 checkout HEAD，并要求 tracked-clean。每个 case artifact 至少记录 case identity、Gold source、status、reason/failure、iterations、tool calls、safe trace、tool sequence、evidence、answer、provider calls、repair 和 initial parse category。

Artifact 只保存公开结构化 response 和白名单 trace 字段：

- 不保存 raw provider response；
- 不保存 API key、完整 prompt、CoT 或 traceback；
- 不保存本机绝对路径；
- JSON/JSONL 按解析后的 semantic values 检查路径和 secret，Markdown 也执行同样的安全规则。

Runner 可以统计 completion、required coverage、forbidden/non-target calls、evidence shape、parse failure 和 repair；不能自动判断“根因分析正确”或“修复建议正确”。这样可以把 Agent failure、证据不足和人工 Gold 结论分开。

## 7. 面试时如何解释

可以这样概括：

> Diagnosis Agent 不是看到 `Pipeline initialization failed` 就凭经验猜 provider，也不是看到 `config.py` 就声称已经读懂实现。它先用 bounded `code_search` 定位，再用 `read_project_context` 读取真实校验和 startup 分支，区分 root cause、consequence 与 remediation。对于同名但不同层的配置，它把 Pipeline generator budget 和 Engineering Decision cap 分开；对于 system-owned project root 和 verified corpus，它不会建议静默 fallback。最终建议基于 Git-like repository evidence 和 bounded source evidence，但正确性仍需要人工 Gold review。

G11-04-01 只冻结 evaluation contract、runner、deterministic tests、Study Note 和 status。此阶段不运行 real-provider Formal；审计通过后再由用户在同一 provider 环境执行正式验证。G12 尚未开始。
