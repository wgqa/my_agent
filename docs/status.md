# 项目状态

> 唯一的实时状态表。每次里程碑/修复后更新本文件。
> 历史大规划已归档至 `docs/archive/`，以本文件为真相来源。

**更新日期：** 2026-08-06

## 当前结论

- **定位**：面向技术文档与代码的可评测 RAG Agent
- **阶段**：M0-M3 + REWORK-P0 + 评测阻塞修复（E-01~04）+ ER-01~04 完成 → **Gate 1（基础 RAG 可信状态）已通过** → 下一步 ExperimentRunner 入库功能 → M4 评测（等真实语料）
- **测试**：全量 suite 通过（--basetemp=.tmp_pytest）

## 任务状态

| 里程碑 | 状态 | 说明 | 验收要点 |
|--------|------|------|---------|
| M0 工程基线 | ✅ | T1-T4 | git 初始化 / baseline.md / 测试隔离 / config Fail-Fast / README |
| M1 数据正确性 | ✅ | T1-T6 | 领域模型 / ChromaStore 契约 / 统一 Token 计数 / chunker 修复 / Loader 元数据 / 幂等入库 |
| M2 检索验证 | ✅ | 08-03 收尾 | Dense fixture / Sparse 补召回 / Reranker 降级 |
| M3 上下文/生成/引用 | ✅ | T1-T6（08-03） | ContextAssembler / Prompt 重写 / 引用验证 / 拒答 / Generator 可靠性 / 多轮对话 |
| REWORK-P0-01 | ✅ | 08-05 复审通过 | Hybrid 候选链路 |
| REWORK-P0-02 | ✅ | 08-05 复审通过 | BM25 统计膨胀 + ID 错位 |
| REWORK-P0-03 | ✅ | 08-05 R2 复审通过 | TokenCounter/Chunker 静默丢字 + 严格预算 + 真实 overlap |
| M4 评测与消融 | ⬜ | 需要真实语料 + QA 测试集 | — |
| M5/M6 | ⏭ | 计划跳过大部分，仅做 Docker | — |
| Agent（结构化 Tool） | ⬜ | M4 之后 | — |

## 修复清单

| # | 问题 | 修复 | 状态 |
|---|------|------|------|
| P0-1 | rerank 分数未写回，assembler 按稠密分重排 | 写回 rerank_score/final_rank；按 rerank 排序 | ✅ 08-05 复审通过 |
| P0-2 | 更新先删旧数据 | 先写后删 | ✅ |
| P0-3 | reranker 死配置 | pipeline 接线 | ✅ |
| P0-4 | TokenCounter 乱码 | 见 REWORK-P0-03（推翻重做） | ✅ |
| P0-5 | 实验脚本旧 API | 改用现行 API | ✅ |
| REWORK-P0-01 | candidate_k 被 internal final_k 截断 | 池取 max(final_k, top_k)；top_k 语义明确 | ✅ 复审通过 |
| REWORK-P0-02 | BM25 重复入库统计膨胀 + zip 错位 | add_document 真 upsert；全量 idf；_batch 写回 id | ✅ 复审通过 |
| REWORK-P0-03 | 分块静默丢字/乱码 | 文本为事实源 + token 只做预算（见 study-notes 35/36） | ✅ 08-05 R2 复审通过 |
| E-01 | 报告排序/展示查 hit_rate，生成端是 hit_at_k | 统一 hit_at_k（见 study-notes 37） | ✅ 复审通过 |
| E-02 | 跨 chunk_strategy 实验不重建索引，产出虚假对比 | run() 入口拒绝多值（见 study-notes 37） | ✅ 复审通过 |
| E-03 | Evaluator 重建 Retriever 后 Hybrid BM25 为空，退化为 Dense-only | _apply_config 后调 _rebuild_sparse_index（见 study-notes 37） | ✅ 复审通过 |
| E-04 | _rebuild_sparse_index 吞异常，"调用过"≠"重建成功" | strict 模式 fail-fast + 数量校验（见 study-notes 38） | ✅ 复审通过 |
| ER-01 | Evaluator 用无约束 dict 配置 | ExperimentConfig 强类型模型：构造即校验 + 稳定 experiment_id（见 study-notes 39） | ✅ 复审通过 |
| ER-02 | 实验共享同一 ChromaDB 索引 | ExperimentWorkspace 独立工作区 + 派生配置（见 study-notes 40） | ✅ 复审通过 |
| ER-03 | Pipeline 从 YAML 构建，未接通工作区 | ExperimentRunner 最小版：workspace → 派生配置 → 独立 Pipeline + 一致性校验（见 study-notes 41） | ✅ 复审通过 |
| ER-04 | 实验语料不固定，指标无法复现 | ExperimentCorpus：文件清单 + 字节 SHA-256 + 稳定 corpus_id（见 study-notes 42） | ✅ 复审通过 |
| Gate1 | RRF 给缺席通道虚拟排名，单通道文档获得另一通道正分 | 未命中通道贡献严格为 0（见 study-notes 43） | ✅ 复审通过 |
| G1-META-02 | Sparse-only 结果丢失原始元数据 | BM25 存元数据副本，sparse-only 命中恢复（实时入库同步） | ✅ 复审通过 |
| G1-CTX-03A/R1 | 双模块各自截断、预算可加性假设 | 统一渲染契约 + 按最终渲染字符串真实 count 预算 | ✅ 复审通过 |
| G1-CTX-03B | Context 预算未含固定成本与输出预留 | 端到端 Prompt Budget（4096/800/16） | ✅ 复审通过 |
| G1-RANK-04 | assembler 重排覆盖 RRF/MMR 顺序 | 保持上游顺序 + display_score 统一展示分 | ✅ 复审通过 |
| G1-CHUNK-05A/R1 | 普通语义段换块无 overlap；纯分隔符文本崩溃 | 换块回退真实 overlap + _split_text flush pending | ✅ 复审通过 |
| G1-CHUNK-05B | SemanticChunker 会产出不可信结果 | 标记实验性，ExperimentConfig 拒绝，保留手动入口 | ✅ 复审通过 |
| G1-CLOSE-06 | — | Gate 1 文档状态收尾 | ✅ 完成 |

## Chunker 策略状态（G1-CHUNK-05B）

| 策略 | 状态 | 说明 |
|------|------|------|
| fixed | ✅ stable baseline | 可进入正式实验（ExperimentConfig） |
| recursive | ✅ stable baseline | 可进入正式实验（ExperimentConfig） |
| semantic | ⚠️ experimental | 保留手动学习/调试入口；未满足原文 Span/严格预算/Embedding 对齐契约；不得用于正式 Gate 2 基线报告；ExperimentConfig 已拒绝 |

## 测试

- 命令：`python -m pytest --basetemp=.tmp_pytest`（Windows 中文用户名环境规避）
- 历史：130（08-03）→ 139（P0）→ 141（REWORK-01）→ 147（REWORK-02）→ 157（REWORK-03）→ 163（REWORK-03-R1）→ 169（REWORK-03-R2）→ 170（E-01）→ 172（E-02）→ 173（E-03）→ 180（E-04）→ 199（ER-01）→ 213（ER-01 类型契约）→ 227（ER-02）→ 228（ER-02 路径逃逸）→ 242（ER-03）→ 254（ER-04）→ 256（ER-04 序列化）→ 260（Gate1 RRF）→ 266（G1-META-02）→ 269（G1-META-02-R1）→ 277（G1-CTX-03A）→ 280（G1-CTX-03A-R1）→ 292（G1-CTX-03B）→ 301（G1-RANK-04）→ 306（G1-CHUNK-05A）→ 312（G1-CHUNK-05A-R1）→ 314（G1-CHUNK-05B）→ **314**（G1-CLOSE-06 文档收尾，08-06）

## Git

- 远端：GitHub `wgqa/my_agent`，分支 main
- 最近验收基线：REWORK-P0-01/02/03 + E-01~E-04 + ER-01~ER-04 复审通过；**Gate 1（基础 RAG 可信状态）全部任务复审通过，正式通过**（含 G1-META-02、G1-CTX-03A/R1/03B、G1-RANK-04、G1-CHUNK-05A/R1/05B；具体 hash 以 git log 为准，本文件不维护提交哈希）

## 文档地图

| 文件 | 用途 |
|------|------|
| README.md | 快速上手（安装/配置/API） |
| docs/baseline.md | M0 工程基线 |
| docs/known-issues.md | 已知问题（仅剩增强级 Bug 15） |
| docs/study-notes/ | 学习笔记 00-44 |
| docs/archive/ | 历史大规划（改进路线图 / RAG 与 Agent 融合），备查不跟进 |
| ../docs/superpowers/ | 原始设计与实施计划 |
