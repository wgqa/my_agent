# 交接文件（Handoff）

> 更新：2026-08-06（HANDOFF-R1）
> 用途：快速摘要，**不是**完整上下文来源。执行边界以当前审计任务文本为准，事实以代码、测试与 `docs/status.md` 为准。

## 信息优先级

1. 用户当前决定
2. 当前审计任务/返工单
3. 代码与测试
4. `docs/status.md`
5. `docs/HANDOFF.md`
6. study-notes / archive
7. Agent 本地记忆（可选补充，不属于项目事实来源；新 Agent 不得依赖它才能继续工作）

## 1. 当前状态

- **Gate 1（基础 RAG 可信状态）已正式归档**（08-06）
- **当前进入 Gate 2（可复现评测）**
- **当前活动任务：`G2-ER-05`**——目标为 ExperimentCorpus → 独立 Pipeline 入库 → 一致性校验 → 原子 Index Manifest；暂不执行查询、评测和报告
- 本文件只提供背景；**G2-ER-05 的修改范围与验收标准以审计任务原文为准，新 Agent 必须取得完整任务文本后才能编码**

## 2. 工作流约定

项目由外部审计方驱动：审计给任务 → Agent 实现 → 全量测试 → 提交推送 → 复审 → 通过给下一项 / 不通过给返工单（R1/R2...）。

**硬性约定**：
- **TDD**：代码行为与 Bug 修复先写失败回归测试（验证 RED）再实现（GREEN）；纯文档任务不要求 RED/GREEN；不得删除或弱化测试来换取通过
- **范围严格**：任务说"不要修改 X / 不要顺手处理其他问题"就绝对不碰
- **提交信息**：不带 `Co-Authored-By: Claude` 行（用户要求）
- **测试命令**：`python -m pytest -q --basetemp=.tmp_pytest`（Windows 中文用户名环境必须加 `--basetemp=.tmp_pytest`）
- **平台兼容**：Windows 无 symlink 特权 → 测试用 `mklink /J` junction 兜底（`Path.resolve()` 会跟随）

**文档更新纪律**：
- `docs/status.md` 是实时状态来源，公开状态/契约变化时更新
- `docs/study-notes/` 仅在**当前任务明确要求**或公开状态/契约发生变化时更新；不得为了形成学习笔记而扩大提交范围

## 3. 已完成模块（Gate 1 归档）

| 模块 | 状态 |
|------|------|
| M0 工程基线 / M1 数据正确性 / M2 检索验证 / M3 上下文生成引用 | ✅ |
| REWORK-P0-01/02/03（Hybrid 链路 / BM25 膨胀 / 丢字乱码） | ✅ |
| E-01~04（hit_at_k 命名 / 虚假实验保护 / BM25 重建 / strict 模式） | ✅ |
| ER-01 ExperimentConfig（强类型 + 类型契约 + rrf_k 规范化） | ✅ |
| ER-02 ExperimentWorkspace（独立工作区 + 路径逃逸修复） | ✅ |
| ER-03 ExperimentRunner 最小版（workspace→factory→一致性校验） | ✅ |
| ER-04 ExperimentCorpus（语料清单 + corpus_id JSON 无歧义序列化） | ✅ |
| Gate1 RRF 缺席通道贡献为 0 | ✅ |
| G1-META-02/R1 Sparse-only 完整元数据（BM25 存 meta 副本） | ✅ |
| G1-CTX-03A/R1 统一渲染契约 + 最终渲染字符串真实 count 预算 | ✅ |
| G1-CTX-03B 端到端 Prompt Budget（4096/800/16） | ✅ |
| G1-RANK-04 保持上游顺序 + display_score 统一展示分 | ✅ |
| G1-CHUNK-05A/R1 普通路径真实 overlap + 纯分隔符崩溃修复 | ✅ |
| G1-CHUNK-05B Semantic 实验性隔离（ExperimentConfig 拒绝 semantic） | ✅ |
| G1-CLOSE-06 文档收尾 | ✅ |

## 4. 后续路线（Gate 2 起）

- **Gate 2**：可复现评测（当前：G2-ER-05 入库 → 原子 Index Manifest）
- **Gate 3**：Query Decomposition + Adaptive Retrieval
- **GraphRAG**：仅在关系型语料证明有必要时考虑
- **Gate 4**：结构化 Tool Calling
- **Gate 5**：Docker、CI、安全、Trace、SSE、README、报告和 Demo
- 暂不发展复杂多 Agent
- M4 评测语料：等待用户提供（Spring Boot/Java/JVM/Redis/MySQL/MQ 文档 + QA 测试集）

## 5. 关键文件地图（以 Git 仓库根目录为基准）

```
core/
  pipeline.py          # query(): 检索→Rerank→预算→ContextAssembler→Generator
  config.py            # YAML 校验（含 generator 预算字段）
  chunker/             # fixed_size / recursive / semantic（experimental）
    recursive.py       # 硬切+普通路径真实 overlap（_next_block_start）
    token_counter.py   # max_substring / substring_start（BPE 不可跨边界相加！）
  retriever/hybrid.py  # BM25Index（存 _meta 副本）+ RRF（缺席通道贡献 0）
  context/assembler.py # render_context_block / display_score / 渲染预算
  generator/base.py    # build_messages / available_context_tokens / validate_budget
evaluation/
  experiment_config.py    # ExperimentConfig（拒绝 semantic）
  experiment_workspace.py # ExperimentWorkspace（路径逃逸校验）
  experiment_runner.py    # prepare() 一致性校验
  experiment_corpus.py    # 语料清单 + corpus_id
tests/                 # 全量测试，每个模块对应 test_*.py
docs/status.md         # 唯一实时状态来源（真相来源）
docs/study-notes/      # 学习笔记 00-44（历史记录，备查）
docs/HANDOFF.md        # 本文件（快速摘要）
```

## 6. 关键陷阱清单（审计踩过的坑，避免重犯）

1. **BPE token 不可跨字符串边界相加**：`count(A) + count(B) ≠ count(A+B)`——所有预算判断必须基于完整候选字符串重新 count
2. **测试假阳性**：断言要验证"真实发生"（如 overlap 必须 `0 < ov <= 配置`，不能只断言 `<=`）
3. **默认值陷阱**：`.get(key, default)` 的 default 参与计算 = 伪造数据（RRF 虚拟排名教训）
4. **序列化歧义**：哈希输入用 JSON `sort_keys=True` 结构化序列化，不用未转义分隔符拼接
5. **路径归属**：`resolve()` 后 `is_relative_to()` 校验（符号链接/junction 逃逸），不用字符串前缀
6. **平台兼容**：Windows symlink 需要特权 → junction 兜底
7. **真实 tiktoken 数值**：测试用 Char3TokenCounter 时注意 ASCII 字符也是 3 token；"缓"真实 = 2 token
8. **过时文档**：文档声称与实现不符会进返工单（G1-CLOSE-06 教训）
9. **测试数字**：status.md 测试历史只写真实全量结果，不写预测值
