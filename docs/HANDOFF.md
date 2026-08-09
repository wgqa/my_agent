# 交接文件（Handoff）

> 用途：快速摘要，**不是**完整上下文来源。执行边界以当前审计任务
> 文本为准，事实以代码、测试与 `docs/status.md` 为准。

## 信息优先级

1. 用户当前决定
2. 当前审计任务/返工单
3. 代码与测试
4. `docs/experiments/gate2_freeze.json`（冻结数字与结论）
5. `docs/status.md`（当前实时任务）
6. `docs/roadmap.md`（长期路线）
7. `docs/HANDOFF.md`（快速交接）
8. study-notes / archive（设计演进与学习历史）

## 1. 当前状态

- **Gate 1（基础 RAG 可信状态）= CLOSED**（08-06 正式归档）
- **Gate 2（可复现评测）= CLOSED / FROZEN**
  - G2-CLOSE-22 / R1 / R2 / R3 / R4 已独立复审通过（G2-FINAL-CLOSE）
  - 证据索引：
    - `docs/experiments/gate2_final_review.md`
    - `docs/experiments/gate2_freeze.json`
    - `docs/study-notes/60-Gate2评测体系与RAG实验方法总结.md`
- **next = Gate 3：Query Decomposition / Adaptive Retrieval（尚未实现）**
  - 冻结 retrieval reference：
    - Primary：Recursive + cl100k_content_v1 + BM25 + top5
      （experiment_id=dbc497c796d5, result_id=acd92171966d）
    - Hybrid control：3c613202e1ed / e27141a2b63e
  - Gate 2 已正式冻结；Gate 3 尚未实现，下一技术任务进入
    Query Decomposition / Adaptive Retrieval（不得虚构已实现）

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
