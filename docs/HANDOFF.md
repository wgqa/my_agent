# 交接文件（Handoff）

> 生成日期：2026-08-06
> 目的：原会话上下文过大，换新 agent 继续执行。本文件 + `docs/status.md` + 用户记忆（`C:\Users\tu me manques\.claude\projects\D-----rag----\memory\`）是完整上下文。

## 1. 项目概览

- **定位**：面向技术文档与代码仓库的可评测 RAG Agent（Python）
- **目录**：`D:\学习\rag实战项目\rag-knowledge-base`（Windows 11，bash shell）
- **阶段**：M0-M3 + P0 修复 + 评测修复 + ExperimentRunner 前三步（ER-01~04）+ **Gate 1（基础 RAG 可信状态）已全部通过**（08-06）
- **测试**：全量 314 passed（`python -m pytest -q --basetemp=.tmp_pytest`；Windows 中文用户名环境必须加 `--basetemp=.tmp_pytest`）
- **git 状态**：本地 HEAD `e641a0a`，工作区干净；**e641a0a 推送可能未成功**（网络间歇性失败，需 `git push` 确认）

## 2. 工作流约定（重要）

项目由**外部审计方**驱动，循环为：

```
审计给任务（Gate/REWORK/ER 编号 + 明确要求 + 验收测试清单）
→ agent 按 TDD 实现（先写失败测试验证 RED，再实现验证 GREEN）
→ 跑全量测试确认无回归
→ git 提交推送（提交信息不带 Co-Authored-By 行！）
→ 用户把状态发给审计方复审
→ 复审通过给下一项 / 不通过给返工单（R1/R2...）
```

**硬性约定**：
- **TDD**：每个任务先写失败测试（验证 RED）再实现（GREEN），禁止先写实现
- **范围严格**：任务说"不要修改 X / 不要顺手处理其他问题"就绝对不碰；每项任务只做任务要求的改动
- **提交信息**：**不带 `Co-Authored-By: Claude` 行**（用户明确要求，见记忆 feedback_git_author.md）
- **学习文档**：每项任务完成后更新 `docs/study-notes/`（编号递增，现到 44）和 `docs/status.md`（实时状态表）
- **测试命令**：`python -m pytest -q --basetemp=.tmp_pytest`
- **平台兼容**：Windows 无 symlink 特权 → 测试用 `mklink /J` junction 兜底（`Path.resolve()` 会跟随）

## 3. 已完成模块（全部复审通过）

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

## 4. 下一步：Gate 2

- 审计已预告：**Gate 2 = ExperimentRunner 入库功能**（把语料真正入到独立 Pipeline 的向量库，做实验隔离的完整闭环）
- M4 评测仍等真实语料（用户提供 Spring Boot/Java/JVM/Redis/MySQL/MQ 文档 + QA 测试集）
- 路线：评测优先 → 高级 RAG 逐变量（Query Transformation → Corrective → Agentic → GraphRAG 按需）→ 单 Agent
- **不要做**：不要开始多 Agent；不要重写 SemanticChunker（实验性保留）；每次实验只变一个变量

## 5. 关键文件地图

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
tests/                 # 314 个测试，每个模块对应 test_*.py
docs/status.md         # 唯一实时状态表（真相来源）
docs/study-notes/      # 学习笔记 00-44（每任务记录）
docs/HANDOFF.md        # 本文件
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

## 7. 用户记忆位置（新 agent 务必读取）

```
C:\Users\tu me manques\.claude\projects\D-----rag----\memory\
  MEMORY.md            # 索引
  session_state.md     # 完整项目状态（含 08-05/06 全部历史）
  feedback_git_author.md  # git 提交不带 Co-Authored-By
```

## 8. 待确认事项

- [ ] `git push` 确认远程与本地同步（HEAD `e641a0a`；网络间歇性失败）
- [ ] 等待审计方复审 G1-CLOSE-06（f9937c4 + e641a0a）
- [ ] 审计给 Gate 2 第一项任务（ExperimentRunner 入库）
