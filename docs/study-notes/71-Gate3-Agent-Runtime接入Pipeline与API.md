# 71-Gate3-Agent-Runtime接入Pipeline与API

> G3-RUNTIME-05B：把 05A 的离线 Agent Runtime 第一次接入真实项目查询链路——PipelineRetrievalAdapter / PipelineAnswerAdapter / build_pipeline_agent_runtime / `POST /agent/query`。
> 日期：2026-08-13
> 权威来源：实现 `core/agent_runtime/adapters.py`、`core/retriever/hybrid.py`（retrieve_sparse）、`api/schemas.py`、`api/app.py`；测试 `tests/test_agent_runtime_adapters.py`、`tests/test_api.py`。
> 范围声明：本任务只打通 Planner → Runtime → BM25 → Generator → Citation → API；decomposed_retrieval 仍为 deferred；不做多 Query、不做 Prompt v2、不读 Holdout。

---

## 1. Port 与 Adapter 的区别

- **Port（端口）**是 Runtime 声明的**抽象接口**：`RetrievalPort.search(...)`、`AnswerPort.answer(...)`。它只写"要什么能力"，不写"谁来实现"。
- **Adapter（适配器）**是**某个具体实现的包装**：`PipelineRetrievalAdapter` 包住现有 Retriever，`PipelineAnswerAdapter` 包住现有 Generator / OpenAI client，让"现有的东西"长成"Runtime 认识的样子"。

一句话：**Port 是插座，Adapter 是插头。** Runtime 面向 Port 编程，生产环境插入 Adapter，测试环境插入 Fake——两者接口一致，Runtime 完全不知道换过实现。

## 2. 为什么 Runtime 不直接依赖 Pipeline

Pipeline 是"文件入库 + 检索 + 重排 + 组装 + 生成"的**一体化流程**，牵一发动全身。如果 Runtime 直接 import Pipeline 并调用它的方法，就：

1. **耦合重**：改 Pipeline 内部结构会波及 Runtime，无法独立演进；
2. **难测试**：Pipeline 依赖 embedding / vector store / 模型，Runtime 测试就非得真跑整套；
3. **违反依赖倒置**：高层（Runtime）依赖低层（Pipeline），而不是两者都依赖抽象。

所以 05B 用 Adapter 把 Pipeline 的 Retriever / Generator **隔离到接口之后**：Runtime 仍只认 Port，新增一个 Adapter 就完成接入，Pipeline 本身零改动。

## 3. Hybrid 中怎样只运行 BM25

HybridRetriever 平时跑 Dense + Sparse + RRF。05B 给它加了一个公开方法 `retrieve_sparse(query, top_k)`：

- 只调 `self._bm25.search(...)`；
- **不调用** `embedding.embed_query`、**不调用** `vector_store.search`、**不运行 RRF 融合**；
- 复用同一个 BM25Index，按 BM25 分数降序返回 Document，并写入真实 `sparse_score`。

测试用"一调用就抛 AssertionError"的 Fake Embedding / Fake VectorStore 证明：跑 `retrieve_sparse` 时它们从未被碰到。这保证了"只跑 BM25"不是口头承诺，而是可验证的行为。

## 4. Evidence 如何转 ContextBlock

Runtime 里的证据是 `EvidenceBundle.items`（每个 `EvidenceItem` 带 citation_id / chunk_id / source_name / content / score）。而现有 Generator 认识的是 `ContextBlock`（引用编号 + 来源 + 正文）。`PipelineAnswerAdapter` 做一次**无损映射**：

| EvidenceItem | ContextBlock |
|---|---|
| citation_id | citation_id（保持 [C1] 不变） |
| chunk_id | chunk_id |
| source_name | source_name |
| content | content |
| score | retrieval_scores["sparse_score"] |

保持 citation_id 是关键：Generator 输出的 `[C1]` 必须和 ContextBlock 的编号对上，CitationValidator 才能验证引用是否真实存在。

## 5. direct 与 grounded 生成的区别

两种模式回答完全不同的问题：

- **direct**：Planner 认为不需要检索（no_retrieval）时用。问题自身带足信息，只需**确定性运算/排序/字符串转换**（如"1+1=?"）。它**不用知识库、不看 Evidence**，用一个独立的 OpenAI-compatible client 单次生成，temperature=0、max_retries=0、timeout 有界、max_tokens=300，Prompt 明确"只用问题自身信息、不引入外部知识、不输出思维链"。
- **grounded**：Planner 认为要检索（single_retrieval）时用。把 EvidenceBundle 转成 ContextBlock 喂给**现有 Generator**，产出必须带真实引用 `[C1]`，再由 CitationValidator 校验。

两条路径各自**只调用一次生成能力**（direct 一次 client 调用 / grounded 一次 generator.generate），不允许重试或二次调用。

## 6. Citation 校验

Grounded 答案必须满足：

1. **至少有一个有效引用**（答案里出现 `[Cx]` 且该 ID 存在于本次 ContextBlock）；
2. **没有无效引用**（答案里不能出现 ContextBlock 里不存在的编号）。

`CitationValidator.validate(answer, blocks)` 会把 `[Cx]` 与 blocks 比对。Adapter 若发现 `valid` 为空或 `invalid` 非空，就抛 `GenerationAdapterError`——Runtime 把任何 Adapter 异常映射为 `GENERATION_FAILED`。这样"没引用的答案"和"引用了不存在编号的答案"都不可能以 `completed` 出现。

## 7. 为什么错误字符串不能算成功

现有 DeepSeek / OpenAI Generator 在调用失败时会返回占位字符串，例如 `[生成失败: RuntimeError] boom`、`[GENERATOR_TIMEOUT] 请求超时`、`[GENERATOR_UNAVAILABLE] HTTP 503`。它们**看起来像个答案，其实是错误**。

如果 Adapter 不拦截，这些字符串会直接当成功答案返回给用户——等于把"生成器炸了"伪装成"正常回答了"。所以 `PipelineAnswerAdapter` 检测这些前缀（`[GENERATOR_`、`[生成失败`）并抛 `GenerationAdapterError` → `GENERATION_FAILED`。**错误必须被如实上报，不能披着答案的外衣。**

## 8. API 如何暴露结构化 Trace

`POST /agent/query` 返回一个结构化 JSON：

```
schema_version / run_id / status / answer / sources /
planner / route / verification / trace / error_code / warnings
```

- `sources` 是逐条证据：citation_id / chunk_id / document_id / source / content（截断到 200 字）/ score / rank；
- `planner`、`route`、`verification` 是各阶段的强类型快照；
- `trace` 是脱敏执行轨迹（事件序列，不含正文/Key/Prompt）；
- `status` 四种都可能出现，`deferred` 会带 `error_code=DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED`，**绝不伪装成成功回答**。

API 层还保证：不返回 API Key、System Prompt、raw output、traceback、内部绝对路径。`AgentQueryRequest` 用 `extra="forbid"`，客户端若传 `history` 会收到 422——**本版本不接 history，也绝不静默忽略它**。

## 9. 05A 离线 Runtime 与 05B 生产集成的关系

- 05A 建立了**独立可测的 Runtime 核心**：契约模型、路由、预算、异常边界、脱敏 Trace，全用 Fake 验证，与真实检索/生成完全解耦。
- 05B 在这个核心上**长出了生产接线**：`retrieve_sparse`（只跑 BM25）、两个 Adapter（Retriever/Generator）、工厂（组装 Planner+Adapter+Runtime）、API 入口。

关系是"核心不变，外围接入"。05A 的所有 38 个测试在 05B 之后原样通过；05B 的 37 个新测试证明了接线的正确性。**先有可验证的核心，再接入真实世界，每一层都可单独审计。**

## 10. 当前 decomposed 路径为什么仍 deferred

Planner 判定一个问题需要分解（decomposed_retrieval）时，意味着"多个子问题分别检索再综合"。05B **仍不做多 Query 检索**，Runtime 返回 `deferred` + `DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED`。

原因是可评测性与诚实：静默降级成单问题检索会产出"看似正常、实际忽略子问题"的答案，污染 Gate 3 对照实验。deferred 是给下一阶段的占位契约——`/agent/query` 也如实返回它，不伪装。

## 11. 面试可能追问与参考回答

**Q：Port 和 Adapter 分别指什么？**
A：Port 是 Runtime 声明的抽象接口（检索/生成能力），Adapter 是具体实现（现有 Retriever/Generator）到该接口的包装。Runtime 面向 Port 编程，测试插 Fake、生产插 Adapter，两者接口一致。

**Q：为什么 Runtime 不直接依赖 Pipeline？**
A：避免高层耦合低层、难测试、违反依赖倒置。用 Adapter 隔离后，Pipeline 零改动，Runtime 只认 Port。

**Q：Hybrid 怎么做到"只跑 BM25"？**
A：加 `retrieve_sparse()` 方法，内部只调 BM25Index.search，不碰 embedding / vector_store / RRF。测试用"一调用就抛错"的 Fake 证明它们从未被调用。

**Q：grounded 答案怎么才算可信？**
A：至少一个有效引用且无无效引用，由 CitationValidator 校验；错误占位字符串（`[GENERATOR_*]`、`[生成失败`）一律算生成失败。

**Q：为什么错误字符串不能当成功答案返回？**
A：它们是生成器异常时的占位输出，不是真实回答。放行等于把系统故障伪装成正常答案，必须如实映射为 GENERATION_FAILED。

**Q：/agent/query 为什么能返回四种 status？**
A：completed（正常）、refused（无证据拒答）、deferred（未实现多 Query）、failed（异常/超预算）都是结构化结果，status+error_code 让客户端能区分处理。

**Q：direct 和 grounded 的生成谁更"自由"？**
A：都不自由。direct 只用问题自身信息做确定性运算，禁用外部知识与思维链；grounded 必须带真实引用。两者都是单次调用、可验证。

## 12. 当前技术债

- **多 Query 检索未实现**：decomposed_retrieval 仍为 deferred（下一任务 G3-RUNTIME-05C）。
- **direct 未做完整预算**：direct 生成无 Token 精确计费（Runtime 只数调用次数）。
- **/agent/query 不接 history**：显式拒绝，未实现多轮。
- **无 Reranker / Hybrid-Dense 自动选择**：Adapter 只支持 bm25。
- **无指标评测**：/agent/query 不计算检索/答案指标（属于后续评测任务）。
- **生产未做真机验证**：本任务全部 Fake 测试，未对真实 DeepSeek 端到端跑过 /agent/query。

---

## 边界声明

- 未读取/搜索 Gate 3 Holdout / sealed；示例全部为 synthetic。
- 未运行真实 Planner/Retriever/Generator；未计算任何指标。
- decomposed_retrieval 仍只路由为 deferred，未执行多 Query 检索。
- `/agent/query` 为可演示入口，不视为完整 Agent 或 Faithfulness 验证。
