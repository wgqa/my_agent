# RAG 项目进阶规划：从 RAG 到 Agent 的学习与面试路线

> 对应项目：`D:\学习\rag实战项目\rag-knowledge-base`
> 文档用途：在已有 RAG 基础上，规划 RAG + Agent 融合学习路径，作为大厂校招简历项目
> 生成日期：2026-07-18
> **不修改**原有的 `RAG项目-从学习原型到大厂面试级工程-改进路线图.md` 和 `2026-06-16-rag-knowledge-base-implementation.md`

---

## 0. 项目定位（调整后）

### 0.1 一句话定位

> **面向通用技术文档的 RAG + Agent 智能检索与问答系统**

不做"Java 知识库"，而是做一个领域无关的 RAG 基础设施。面试时你可以说："我构建了一个通用 RAG 框架，支持任意技术文档的入库、混合检索和 Agent 驱动的多步推理问答。"

### 0.2 这个项目在面试中证明什么

| 能力维度 | 具体体现 |
|---------|---------|
| **RAG 原理** | 手写分块/Embedding/BM25/RRF/MMR/Rerank/引用验证 |
| **Agent 架构** | ReAct loop、Tool use、多步推理、RAG 作为 Agent 工具 |
| **实验能力** | 测试集构建、控制变量消融、LLM-as-Judge、失败分析 |
| **工程能力** | 幂等入库、流式输出、Docker 部署、Trace、结构化错误 |
| **产品判断** | 知道什么场景用 RAG、什么场景用 Agent、何时不做 |

### 0.3 与另一份规划文档的区别

另一份 `RAG项目-从学习原型到大厂面试级工程-改进路线图.md` 的核心问题是：
- 将项目定位为"Java 技术资料知识库"，场景过于狭窄
- 没有包含 Agent 相关的学习内容
- 某些建议（如 SQLite 元数据仓库、蓝绿索引）对于学习项目过度工程化

**本文档的策略：**
- 场景保持通用，不绑定任何特定领域
- 在 RAG 正确性修复后，追加 Agent 学习模块
- 控制工程复杂度，只在面试有价值的地方深入

---

## 1. 当前状态总结

### 1.1 已有的（Day 1-8 完成）

```
Loader (PDF/TXT/MD/Code)
  → Chunker (Fixed/Recursive/Semantic)
  → Embedding (BGE/OpenAI)
  → VectorStore (Chroma)
  → Retriever (Simple/MMR/Hybrid)
  → Reranker (BGE Cross-Encoder)
  → Generator (DeepSeek/OpenAI)
  → Pipeline (串联)
  → FastAPI (4 个端点 + 14 个测试)
  → Streamlit (上传 + 聊天 UI)
  → Evaluation (metrics/evaluator/report/quality, 64 tests)
```

### 1.2 已知的关键问题

参考另一份规划文档的审计结果（已验证了 5 个典型复现），以下是影响最大的 P0 问题：

1. **中文分块**：FixedSize 用空格分词，中文可能完全不切
2. **Chroma ID 冲突**：基于 collection.count 生成，删除后复用旧 ID
3. **Hybrid 不是真正的 Hybrid**：BM25 只在 Dense 候选上打分，且缓存第一次查询语料
4. **Reranker 候选不足**：只重排最终 Top-K，无法挽救 Dense 的漏召回
5. **评测指标公式错误**：NDCG 用了非标准折损公式，hit_rate 实际是 Recall@K

这些问题**需要在加 Agent 之前修复**，否则后续的实验数据不可信。

---

## 2. 总体路线图

```
Phase 1: 修地基（RAG 正确性，~10 天）
  → Phase 2: 建评测（可复现实验，~8 天）
    → Phase 3: 加 Agent（RAG → Agent，~10 天）★ 区分度核心
      → Phase 4: 工程收口（Docker、Trace、文档，~7 天）
        → Phase 5: 面试准备（Demo、简历、题库，~5 天）
```

每阶段预计 1-2 周（每天 3-4 小时），总计约 6-8 周。

---

## 3. Phase 1：修复 RAG 正确性（~10 天）

> 目标：让已有的 RAG 管线产生可信的结果。

### Task 1.1：修复分块系统（2 天）

| 优先级 | 问题 | 修复方案 |
|-------|------|---------|
| P0 | FixedSize 用 split() 分词，中文不切 | 引入 tiktoken 或 BGE tokenizer，真正按 token 切 |
| P0 | Recursive 的 overlap 参数未使用 | 在递归合并时加入 overlap 逻辑 |
| P1 | Semantic 的 min/max 不生效 | 加入长度校验和合并/拆分后处理 |
| P1 | chunk size 语义不统一 | 统一为 `size_tokens` / `overlap_tokens` |

**验收：** 700 字无空格中文 + chunk_size=128 能切出 ~6 个块；overlap 真实存在。

### Task 1.2：修复 VectorStore（2 天）

| 优先级 | 问题 | 修复方案 |
|-------|------|---------|
| P0 | ID 基于 count 生成，删除后冲突 | 使用 `sha256(doc_id + chunk_index + content)` 生成 chunk_id |
| P0 | 查询不返回 distance | 显式取 distances，写入结果 |
| P0 | 无 document_id/version | 添加基本的文档身份字段 |
| P1 | Embedding 模型升级时维度冲突 | collection 名称包含 embedding 模型信息 |

**验收：** 增-删-增后 count 正确；查询结果有真实 distance；同一文档重复入库幂等。

### Task 1.3：修复检索系统（3 天）

| 优先级 | 问题 | 修复方案 |
|-------|------|---------|
| P0 | Hybrid 的 BM25 只在 Dense 候选上打分 | BM25 建立独立全库索引，Dense/Sparse 各自独立召回 Top-N → RRF 融合 |
| P0 | BM25 缓存第一次查询语料 | 每次查询使用最新索引，文档变更时同步更新 |
| P0 | BM25 用空格分词 | 使用 jieba 分词 |
| P0 | Reranker 只重排最终 K 条 | Retriever 返回 candidate_k (20-30)，Reranker 从中精排 final_k (5) |
| P1 | MMR 对候选重复计算 Embedding | 从 VectorStore 缓存中取 embedding |

**验收：** 关闭 Dense 时 Sparse 能独立检索；Hybrid 能补回 Dense 漏召回的文档。

### Task 1.4：修复评测指标（1 天）

| 优先级 | 问题 | 修复方案 |
|-------|------|---------|
| P0 | NDCG 折损公式非标准 | 替换为标准 DCG/IDCG 公式 |
| P0 | hit_rate 实际是 Recall@K | 重命名为 Recall@K，补上真正的 Hit@K |
| P0 | Evaluator 的 top_k 固定为 5 | 从配置读取 |

**验收：** 手算验证所有指标公式；Hit@K ≠ Recall@K 概念区分清晰。

### Task 1.5：基础工程卫生（2 天）

- Git 初始化 + .gitignore
- 测试完全隔离（使用 tmp_path，不写生产数据）
- 配置 Fail Fast（非法 provider 启动即报错）
- 最小 README（当前真实能力描述）

**验收：** 全新 clone 后一条命令跑通测试；配置文件错误时启动即失败。

---

## 4. Phase 2：建立真实评测体系（~8 天）

> 目标：用数据替代"感觉"，每个结论都有可追溯的实验 ID。

### Task 2.1：准备语料和测试集（3 天）

**语料来源（不绑定特定领域）：**
- 你手头的任何技术笔记、学习资料
- 公开的技术文档（如 Python 文档、Redis 文档等）
- 目标：15-30 份文档，覆盖 3-5 个技术主题
- 类型至少包含 Markdown、PDF、纯文本

**测试集构造：**
- 第一版目标 50-80 题
- 题型分布：直接事实 25%、对比类 20%、专有名词 15%、代码定位 10%、多文档 10%、无答案 10%、边界/冲突 10%
- 生成流程：LLM 生成候选 → 人工审核 → 冻结版本

**JSONL 格式：**
```json
{
  "id": "q_0001",
  "question": "...",
  "answerable": true,
  "relevant_chunk_ids": ["..."],
  "reference_answer": "...",
  "tags": ["topic", "type"],
  "difficulty": "medium",
  "review_status": "approved"
}
```

### Task 2.2：重写 ExperimentRunner（2 天）

核心要求：
- Chunker/Embedding 配置变化时**自动重新索引**
- 输出目录包含 config + per_query 结果 + summary + failures
- 同配置可复现
- 只改变 final_k 时复用候选结果

### Task 2.3：分阶段消融实验（2 天）

不跑 81 个组合，分 3 组控制变量：

**实验 A — Chunking：**
固定 Dense Retriever，比较 Fixed 256/384、Recursive 256/384/512
→ 观察 Recall@5、MRR、chunk 数量、索引耗时

**实验 B — Retrieval：**
固定最优 Chunk 配置，比较 Dense / Sparse / Hybrid(RRF) / +MMR
→ 按问题类型分桶（语义/专有名词/代码/多文档）

**实验 C — Reranker：**
比较 Fusion Top-10/20/30 → Rerank Top-5 vs 无 Rerank
→ 观察 MRR 变化 + 延迟代价

### Task 2.4：生成质量评测（1 天）

- LLM-as-Judge：Answer Relevance、Faithfulness、Citation Accuracy
- 规则指标：引用 ID 是否存在、输出 Schema 合法率
- 人工抽查 20-30% 的 Judge 评分

---

## 5. Phase 3：RAG + Agent 融合（~10 天）★ 区分度核心

> 纯 RAG 项目在 2026 年面试中太普遍了。加上 Agent 层，证明你理解"RAG 作为 Agent 的工具"。

### 5.1 为什么加 Agent

面试中 RAG + Agent 融合的问题越来越高频：
- "RAG 和 Agent 的关系是什么？"
- "如何让 RAG 回答需要多步推理的问题？"
- "什么时候该用 RAG，什么时候该用 Agent？"

### Task 3.1：Agent 基础框架（2 天）

实现一个最小的 ReAct Agent：

```python
class ReActAgent:
    """
    Thought → Action → Observation → Thought → ... → Final Answer
    """
    def __init__(self, llm, tools: list[Tool]):
        self.llm = llm
        self.tools = {t.name: t for t in tools}

    def run(self, query: str, max_steps: int = 5) -> AgentResult:
        ...
```

**Tool 抽象：**
```python
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    def execute(self, **kwargs) -> str: ...
```

**第一个 Tool — RAG 检索：**
```python
class RAGSearchTool(Tool):
    """把已有的 RAG Pipeline 封装成 Agent 的一个工具"""
    name = "search_knowledge_base"
    description = "在知识库中搜索相关文档"

    def execute(self, query: str, top_k: int = 5) -> str:
        results = self.pipeline.retrieve(query, top_k)
        return self._format_results(results)
```

### Task 3.2：RAG 专用的 Agent 工具集（2 天）

```python
tools = [
    RAGSearchTool(),        # 检索知识库
    DocumentLookupTool(),   # 按 ID 取完整文档
    CodeSearchTool(),       # 在代码文件中搜索
    WebSearchTool(),        # （可选）知识库不足时联网
]
```

### Task 3.3：多步推理问答（2 天）

Agent 真正产生价值的地方——单次 RAG 检索回答不了的问题：

> 用户："对比项目中三种 Chunker 在中文场景下的优劣，并给出推荐配置"

- Step 1：检索 "FixedSize Chunker" 相关信息
- Step 2：检索 "Recursive Chunker" 相关信息
- Step 3：检索 "Semantic Chunker" 相关信息
- Step 4：综合三个检索结果，生成对比表格
- Step 5：基于实验数据给出推荐

需要实现：
- **查询分解（Decomposition）**：把一个复杂问题拆成子问题
- **多轮检索**：每个子问题独立检索
- **结果合成**：汇总子问题的检索结果，统一喂给 LLM

### Task 3.4：Agent 评测（2 天）

在已有测试集基础上增加 Agent 专用评测：

- **多跳问题**：需要跨文档检索才能完整回答（10-15 题）
- **对比分析问题**：需要多轮检索+综合（5-10 题）
- **工具选择正确率**：Agent 是否选了正确的 Tool
- **步数效率**：是否在合理步数内完成
- **幻觉对比**：Agent 多步推理是否会引入更多幻觉

### Task 3.5：API + UI 集成（2 天）

- FastAPI 新增 `/query/agent` 端点
- SSE Streaming：实时展示 Agent 的 Thought → Action → Observation 循环
- UI 增加 Agent 模式开关：单轮 RAG / Agent 多步推理

```
UI 展示 Agent 思考链：
  🤔 Thought: 这个问题需要先检索 X，再对比 Y
  🔍 Action: search_knowledge_base("X")
  📖 Observation: 找到 3 条相关文档...
  🤔 Thought: 现在检索 Y
  🔍 Action: search_knowledge_base("Y")
  ✅ Final Answer: 综合对比结果...
```

这是面试 Demo 的亮点——面试官能看到 Agent 的完整思考链。

---

## 6. Phase 4：工程收口（~7 天）

> 目标：让项目从"能在本地跑"变成"能展示、能复现、能经住工程追问"。

### Task 4.1：Streaming 全链路（1 天）
- LLM 生成改为流式（SSE）
- Agent 思考过程流式展示
- UI 支持逐 token 渲染

### Task 4.2：Docker 部署（1 天）
```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    volumes: ["./data:/app/data"]
  ui:
    build: ./ui
    ports: ["8501:8501"]
```

### Task 4.3：结构化日志与 Trace（1 天）
- 每个请求生成 trace_id
- 分阶段记录耗时
- Agent 模式下记录每步 Action/Observation

### Task 4.4：错误处理与安全（1 天）
- 文件上传大小限制 + 类型白名单
- 空检索结果不强行生成
- Prompt 注入基础防护
- API 错误统一格式

### Task 4.5：文档管理与增量索引（2 天）
- 文件上传后记录 document_id + content_hash
- 相同文件重复上传 → 幂等
- 内容变化 → 创建新版本
- 删除 → 同时清理 Dense + Sparse 索引

### Task 4.6：README 与项目文档（1 天）
- 架构图（RAG 管线 + Agent 流程）
- 快速启动指南
- 实验结果摘要表

---

## 7. Phase 5：面试准备（~5 天）

### Task 5.1：实验报告汇总

| 配置 | Recall@5 | MRR | NDCG@5 | Citation Prec. | P95 Latency |
|------|---------|-----|--------|---------------|-------------|
| Dense Baseline | | | | | |
| + Sparse (Hybrid) | | | | | |
| + Reranker | | | | | |
| + Agent 多步 | | | | | |

### Task 5.2：5 分钟 Demo 脚本

```
1. 展示项目架构图（30s）
2. 上传新文档 → 展示幂等（1min）
3. 单轮 RAG 问答（带引用）（1min）
4. 复杂问题 → Agent 多步推理（1.5min）★ 亮点
5. 展示实验对比表 + 失败案例（1min）
```

### Task 5.3：面试题库

**RAG 基础：**
1. chunk_size 怎么定？overlap 的作用？
2. Dense 和 Sparse 检索各自的优势场景？
3. RRF 融合为什么比直接加权好？
4. Reranker 为什么要排比 final_k 更多的候选？
5. Lost in the Middle 怎么缓解？
6. 如何验证引用是否正确？

**Agent：**
7. ReAct Agent 的循环终止条件怎么设计？
8. RAG 作为 Agent 的 Tool vs Agent 作为 RAG 的增强，有什么区别？
9. Agent 多步推理中如何处理检索失败？
10. 如何评估 Agent 的工具选择是否正确？
11. Agent 的步数增加会导致什么风险？

**实验与工程：**
12. "Recall 提高了 15%" — 怎么证明这不是随机波动？
13. 如何构建不泄漏的测试集？
14. LLM-as-Judge 有什么偏差？如何校准？
15. 空检索场景怎么处理？
16. RAG 系统的瓶颈通常在哪里？

### Task 5.4：简历描述模板

> 从零实现面向技术文档的 RAG + Agent 知识库系统。完成 Token-aware 分块、
> Dense+BM25 RRF 混合检索、Cross-Encoder 重排序与可验证引用；
> 基于 ReAct 架构实现 Agent 多步推理，支持 RAG 检索工具的热插拔；
> 通过 X 份文档、Y 条人工审核 QA 构建评测集，分阶段消融实验证明
> Hybrid+Rerank 方案将 Recall@5 提升至 XX%，Agent 多步推理在对比类
> 问题上将答案完整度提升至 XX%。支持 SSE 流式输出、Docker 部署与全链路 Trace。

---

## 8. 推荐执行顺序

```
第 1 周：Phase 1（修复正确性）
  Day 1-2：分块系统修复
  Day 3-4：VectorStore 修复
  Day 5-7：检索系统修复 + 评测指标修复
  Day 8-10：工程卫生 + 复习闭卷自测

第 2 周：Phase 2（评测体系）
  Day 1-3：收集语料 + 构建测试集（50+ 条）
  Day 4-5：ExperimentRunner
  Day 6-8：消融实验 A/B/C + 生成质量评测

第 3 周：Phase 3（Agent 融合）★ 区分度核心
  Day 1-2：ReAct Agent 框架 + RAG Tool
  Day 3-4：工具集 + 多步推理
  Day 5-6：Agent 评测
  Day 7-8：API + UI 集成（含流式 Agent 思考链）

第 4 周：Phase 4 + 5（收口 + 面试）
  Day 1-2：Streaming + Docker
  Day 3-4：Trace + 错误处理 + 文档管理
  Day 5-6：README + Demo + 实验报告
  Day 7：面试题库 + 闭卷模拟
```

---

## 9. 项目的面试叙事

面试时不要背"我用了 X、Y、Z 技术"，而是讲一个故事：

```
"我做了一个 RAG 知识库系统。最开始实现了一个基础管线，
但在测试中发现中文分块完全不生效、混合检索其实是假的、
评测指标公式也写错了。

于是我逐层修复——引入 tokenizer 做真正的按 token 分块、
给 BM25 建了独立索引用 RRF 融合、让 Reranker 排 Top-20
而不是只排最终的 5 条。

修复后我建了 60 条人工审核的测试集，做了三组消融实验，
每个配置的差距都有数据支撑。

后来我发现单次检索回答不了复杂问题，比如'对比三种方案的优劣'，
于是基于 ReAct 架构加了 Agent 层，把 RAG 封装成一个 Tool，
让 Agent 可以多步检索、分解问题、综合答案。

整个过程让我理解了 RAG 每个环节为什么这样设计、Agent 和 RAG
是什么关系、以及评测体系为什么重要。"
```

这个故事比"我用 LangChain 搭了个 RAG"强得多。

---

## 10. 与另一份规划文档的关系

| | 另一份规划 | 本文档 |
|---|---|---|
| 场景定位 | Java 技术资料知识库 | **通用技术文档**（不绑定领域） |
| 核心目标 | RAG 正确性 + 工程能力 | RAG 正确性 + **Agent 融合** + 工程能力 |
| Agent | 明确不做（M0-M4 前） | **Phase 3 核心模块** |
| 元数据仓库 | SQLite 独立仓库 + 蓝绿版本 | **简化版**（先保证 Chunk ID 稳定，不过度工程化） |
| 执行风格 | 逐个 M 阶段严密执行 | **按面试价值排序**（Agent > 文档管理 API > CI） |

两份文档可以共存。另一份对代码缺陷的分析（30+ 条确认问题）质量很高，
Phase 1 的修复方案直接参考了它。但在**项目定位、Agent 方向和工程深度**上本文档做了不同选择。

---

## 11. 不做什么

在当前阶段明确不做：

- GraphRAG / 知识图谱
- 微调 Embedding 模型或 LLM
- Milvus / Qdrant 等重型向量数据库迁移
- 多 Agent 协作 / LangGraph
- MCP Server 封装
- Kubernetes / CI/CD 流水线
- 自研向量数据库或全文检索引擎

这些在面试中也是加分项，但前提是基础 RAG 和 Agent 已经扎实。

---

## 12. 成功标准

- [ ] 所有 P0 正确性问题有回归测试覆盖
- [ ] 50+ 人工审核 QA 测试集，有版本号
- [ ] 至少 3 组控制变量消融实验，结果可复现
- [ ] ReAct Agent 可以完成多步推理问答
- [ ] SSE 流式输出 + Docker 一键启动
- [ ] README 与代码一致，实验数字可追溯到 experiment_id
- [ ] 能闭卷回答 15/16 道面试题
- [ ] 有 5 分钟 Demo 脚本，不依赖临场操作
