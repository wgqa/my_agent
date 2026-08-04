# 项目状态

> 唯一的实时状态表。每次里程碑/修复后更新本文件。
> 历史大规划已归档至 `docs/archive/`，以本文件为真相来源。

**更新日期：** 2026-08-04

## 当前结论

- **定位**：面向技术文档与代码的可评测 RAG Agent
- **阶段**：M0-M3 完成 → P0 修复完成（08-04）→ **下一步 M4（评测与消融，等真实语料）**
- **测试**：全量 suite 通过（--basetemp=.tmp_pytest）

## 任务状态

| 里程碑 | 状态 | 说明 | 验收要点 |
|--------|------|------|---------|
| M0 工程基线 | ✅ | T1-T4 | git 初始化 / baseline.md / 测试隔离 / config Fail-Fast / README |
| M1 数据正确性 | ✅ | T1-T6 | 领域模型 / ChromaStore 契约 / 统一 Token 计数 / chunker 修复 / Loader 元数据 / 幂等入库 |
| M2 检索验证 | ✅ | 08-03 收尾 | Dense fixture / Sparse 补召回 / Reranker 降级 |
| M3 上下文/生成/引用 | ✅ | T1-T6（08-03） | ContextAssembler / Prompt 重写 / 引用验证 / 拒答 / Generator 可靠性 / 多轮对话 |
| P0 修复 | ✅ | 08-04（外部评审驱动） | 见下表 |
| M4 评测与消融 | ⬜ | 需要真实语料 + QA 测试集 | — |
| M5/M6 | ⏭ | 计划跳过大部分，仅做 Docker | — |
| Agent（结构化 Tool） | ⬜ | M4 之后 | — |

## P0 修复清单（2026-08-04）

| # | 问题 | 修复 | 验证 |
|---|------|------|------|
| P0-1 | rerank 分数未写回，assembler 按稠密分重排覆盖 rerank 顺序 | bge_reranker 写回 `rerank_score`/`final_rank`；assembler 优先按 rerank_score 排序 | tests/test_reranker.py、test_context_citation.py |
| P0-2 | 更新先删旧数据，中途失败丢数据 | 先写后删，仅删未被新版本覆盖的旧 chunk | test_index_file_update_keeps_old_data_when_embedding_fails |
| P0-3 | reranker.enabled/candidate_k/final_k 是死配置 | pipeline.query 接线 | test_query_wires_reranker_candidate_and_final_k、test_query_disabled_reranker_skips_rerank |
| P0-4 | TokenCounter 解码乱码（tiktoken 与 fallback 两条路径） | decode 去除边界 U+FFFD；fallback 丢弃不完整字节 | tests/test_token_counter.py |
| P0-5 | compare_retrievers.py 引用已删除的旧 API（BM25/alpha/top_k_initial） | 改用现行 API（BM25Index / Hybrid 新签名） | 脚本可完整运行 |
| P0-6 | README 过期声明（不存在的 streamlit UI、不支持多轮、错误测试命令） | 已更新 | — |

## 测试

- 命令：`python -m pytest --basetemp=.tmp_pytest`（Windows 中文用户名环境规避）
- 历史：130 passed（08-03）→ **139 passed**（08-04 P0 修复后，新增 9 用例）

## Git

- 远端：GitHub `wgqa/my_agent`，分支 main
- 最近提交：`3fd2620`（08-04 docs 重组）；P0 修复提交 639b944/198bf92/b277473/7f226be/3fd2620

## 文档地图

| 文件 | 用途 |
|------|------|
| README.md | 快速上手（安装/配置/API） |
| docs/baseline.md | M0 工程基线 |
| docs/known-issues.md | 已知问题（仅剩增强级 Bug 15） |
| docs/study-notes/ | 学习笔记 00-33 |
| docs/archive/ | 历史大规划（改进路线图 / RAG 与 Agent 融合），备查不跟进 |
| ../docs/superpowers/ | 原始设计与实施计划 |
