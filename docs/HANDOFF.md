# 交接文件（Handoff）

> 用途：快速摘要，**不是**完整上下文来源。
> - 执行边界以用户当前决定和当前任务卡为准；
> - 实现事实以最新代码和测试为准；
> - Gate 2 冻结数字与结论以 `docs/experiments/gate2_freeze.json` 为准；
> - 实时状态以 `docs/status.md` 为准；
> - 长期路线以 `docs/roadmap.md` 为准。

## 信息优先级

1. 用户当前决定
2. 当前审计任务/返工单
3. 代码与测试
4. `docs/experiments/gate2_freeze.json`（冻结数字与结论）
5. `docs/status.md`（当前实时任务）
6. `docs/roadmap.md`（长期路线）
7. `docs/HANDOFF.md`（快速交接）
8. study-notes / archive（设计演进与学习历史）

## 1. 当前状态（Gate 4 接管点）

- **Gate 1 = CLOSED**、**Gate 2 = CLOSED / FROZEN**、**Gate 3 = CLOSED / FROZEN**
  （Gate 3 Holdout 保持冻结，不得重跑）
- **Gate 4 = CLOSE CANDIDATE / pending Reviewer**（最终 CLOSED 待 Reviewer 审核
  `docs/experiments/gate4_freeze.json` 后签发）

**Gate 4 已有一个有界 Structured Tool Agent：**

- strict structured decisions（强类型 Decision，禁止未定义字段/重复 key）
- 3 个真实只读 Tool：calculator / code_search / knowledge_search
- 固定预算 5 / 4 / 2（iterations / tool_calls / tool_errors），系统控制、不可 API 覆盖
- duplicate / error 保护（重复 ToolCall 拒绝、Tool error 2 次封顶）
- untrusted observations（Tool 结果作为不可信数据回喂，不拼 system role）
- safe trace（Trace ≠ CoT；API 只透出安全字段白名单）
- public Dev benchmark（24-case，evaluation_set_id=5639ca57b09a）
- real HTTP endpoint（`POST /tool-agent/query`）
- real DeepSeek E2E smoke（6 条固定请求全 HTTP 200 结构化）

**关键冻结证据：**

- 正式 baseline：`docs/experiments/gate4_tool_use_dev_baseline.json`（run_id=fa4ab9aa5f13）
- offline seal：`docs/experiments/gate4_tool_use_dev_seal.json`（verdict=valid_public_dev_baseline）
- 系统 freeze：`docs/experiments/gate4_freeze.json`（gate4_system_freeze_id=96c159b1ca2c）

**Do NOT：**

- **不要重跑 Gate 4 正式 Dev baseline `fa4ab9aa5f13`**；
- **不要针对冻结的 24-case 结果调参**（未经单独授权的实验）；
- **Gate 3 Holdout 保持冻结，不得重跑**。

实时状态以 `docs/status.md` 为准，长期路线以 `docs/roadmap.md` 为准。

## 2. 工作流约定

- 审计驱动：审计给任务 → Agent 实现 → 全量测试 → 提交推送 → 复审 →
  通过给下一项 / 不通过返工单（R1/R2...）
- **TDD**：代码行为与 Bug 修复先写失败回归测试（RED）再实现
  （GREEN）；纯文档任务不要求 RED/GREEN；不得删除或弱化测试换取通过
- **范围严格**：任务说"不要修改 X"就绝对不碰
- **提交信息**：不带 `Co-Authored-By: Claude` 行
- **测试命令**：`python -m pytest -q --basetemp=.tmp_pytest`
  （Windows 中文用户名环境必须加 `--basetemp=.tmp_pytest`）
- **平台兼容**：Windows 无 symlink 特权 → 测试用 `mklink /J`
  junction 兜底（`Path.resolve()` 会跟随）

**文档更新纪律**：
- `docs/status.md` 是实时状态来源，公开状态/契约变化时更新
- `docs/study-notes/` 仅在当前任务明确要求或公开状态契约变化时更新

## 3. 已完成模块

### Gate 1（CLOSED）

M0-M3 + REWORK-P0-01/02/03 + E-01~04 + ER-01~04 + G1-META-02/R1 +
G1-CTX-03A/R1/03B + G1-RANK-04 + G1-CHUNK-05A/R1/05B + G1-CLOSE-06

### Gate 2（CLOSED / FROZEN）

G2-ER-05、G2-EVAL-06/07/08/09、G2-EXP-10、G2-REAL-11、
G2-ANALYSIS-12、G2-DIAG-13/R1、G2-ANALYSIS-14、G2-ABL-15/R1、
G2-ABL-16/R1、G2-ABL-17/R1、G2-DIAG-18/R1/R2/R3、G2-DESIGN-19/R1/R2、
G2-IMPL-20/R1、G2-ABL-21/R1、G2-CLOSE-22/R1/R2/R3/R4

## 4. 关键文件地图（以 Git 仓库根目录为基准）

```
core/
  pipeline.py              # 索引/查询链路（embedding -> chunker -> retriever）
  config.py                # YAML 校验（含 chunk_budget_policy 字段）
  chunker/                 # fixed_size / recursive / semantic(experimental)
    embedding_runtime_counter.py  # BGE-aligned content/model-input counter
    token_counter.py       # cl100k 预算（二分 + BPE 单调假设技术债）
  embeddings/
    bge_emb.py             # BGEEmbedding（get_runtime_model/tokenizer/contract）
    runtime_contract.py    # probe v1 + contract/corpus-scoped fingerprint 唯一事实源
  retriever/               # simple / hybrid / bm25_only / mmr
evaluation/
  experiment_config.py     # ExperimentConfig（含 chunk_budget_policy 等身份字段）
  experiment_spec.py       # unresolved 用户声明（无 experiment_id）
  experiment_resolver.py   # 唯一 resolver（spec -> Final Config）
  experiment_runner.py     # prepare/index/retrieval/metrics/finalize + runtime binding
  experiment_workspace.py  # 独立 Workspace + 派生 config.yaml
  experiment_corpus.py     # corpus_id + SHA-256
  index_manifest.py        # Manifest v2 + observed facts
docs/
  status.md                # 唯一实时状态来源（真相来源）
  HANDOFF.md               # 本文件（快速摘要）
  experiments/gate2_final_review.md   # Gate 2 证据冻结总结
  experiments/gate2_freeze.json       # Gate 2 冻结结构化数据
  study-notes/             # 学习笔记 00-60
  design/                  # 设计文档（tokenizer-aligned chunk intervention 等）
tests/                     # 全量测试（当前基线 673 passed）
```

## 5. 关键陷阱清单（审计踩过的坑）

1. **BPE token 不可跨字符串边界相加**：`count(A)+count(B) ≠
   count(A+B)`；预算判断必须基于完整候选字符串重新 count
2. **测试假阳性**：断言要验证"真实发生"（如 overlap 必须
   `0 < ov <= 配置`，不能只断言 `<=`）
3. **默认值陷阱**：`.get(key, default)` 的 default 参与计算 = 伪造
   数据（RRF 缺席通道必须贡献 0）
4. **序列化歧义**：哈希输入用 JSON `sort_keys=True` 结构化序列化
5. **路径归属**：`resolve()` 后 `is_relative_to()` 校验（符号链接/
   junction 逃逸）
6. **声明 ≠ 运行**：strategy/tokenizer/contract 必须做 runtime
   binding 验证（isinstance / object identity / fingerprint）
7. **真实验证**：`status.md` 测试历史只写真实验证数字，不写预估值
