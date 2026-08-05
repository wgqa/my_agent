# 项目状态

> 唯一的实时状态表。每次里程碑/修复后更新本文件。
> 历史大规划已归档至 `docs/archive/`，以本文件为真相来源。

**更新日期：** 2026-08-05

## 当前结论

- **定位**：面向技术文档与代码的可评测 RAG Agent
- **阶段**：M0-M3 完成 → REWORK-P0-01/02/03 完成 → **下一步 M4（评测与消融，等真实语料）**
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
| E-04 | _rebuild_sparse_index 吞异常，"调用过"≠"重建成功" | strict 模式 fail-fast + 数量校验（见 study-notes 38） | 🔄 待复审 |

## 测试

- 命令：`python -m pytest --basetemp=.tmp_pytest`（Windows 中文用户名环境规避）
- 历史：130（08-03）→ 139（P0）→ 141（REWORK-01）→ 147（REWORK-02）→ 157（REWORK-03）→ 163（REWORK-03-R1）→ 169（REWORK-03-R2）→ 170（E-01）→ 172（E-02）→ 173（E-03）→ **180**（E-04，08-05）

## Git

- 远端：GitHub `wgqa/my_agent`，分支 main
- 最近验收基线：REWORK-P0-01/02/03 与评测项 E-01/E-02/E-03 复审通过；E-04 待复审（具体 hash 以 git log 为准，本文件不维护提交哈希）

## 文档地图

| 文件 | 用途 |
|------|------|
| README.md | 快速上手（安装/配置/API） |
| docs/baseline.md | M0 工程基线 |
| docs/known-issues.md | 已知问题（仅剩增强级 Bug 15） |
| docs/study-notes/ | 学习笔记 00-38 |
| docs/archive/ | 历史大规划（改进路线图 / RAG 与 Agent 融合），备查不跟进 |
| ../docs/superpowers/ | 原始设计与实施计划 |
