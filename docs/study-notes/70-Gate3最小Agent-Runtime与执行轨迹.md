# 70-Gate3最小Agent-Runtime与执行轨迹

> G3-RUNTIME-05A：从 QueryPlan → RouteDecision → Retrieval / No Retrieval → EvidenceBundle → VerificationResult → Answer → RunTrace 的最小 Agent Runtime 离线垂直切片。
> 日期：2026-08-13
> 权威来源：实现 `core/agent_runtime/models.py`、`core/agent_runtime/runtime.py`；测试 `tests/test_agent_runtime.py`（38 测试）。
> 范围声明：本任务只建立可独立运行的 Runtime 核心；不接 API/Pipeline、不执行真实模型/检索/生成、不读 Holdout；decomposed_retrieval 仅路由为 deferred，尚未执行。

---

## 1. 为什么 Planner 不等于 Agent

Planner（`BaseQueryPlanner` / 04B 系列）只做一件事：**把一个原问题变成一份 QueryPlan**——要不要检索、要不要分解、分解成什么。它是一个"决策器"，输出一份静态快照就结束，没有后续动作。

Agent 则是一台**执行机器**：拿到 QueryPlan 之后，还要决定怎么走（路由）、真的去检索、把结果拼成证据、判断证据够不够、决定生成还是拒答、记录整个过程，最后给出一份完整结果。Planner 只管"想"，Agent 负责"做"，并且把"想和做"的每一步都留下可检查的记录。

一句话：**Planner 是 Agent 的头脑的一部分，Agent 是 Planner 之上的执行主体。** 没有 Agent，Planner 只能孤零零地产生计划；没有 Planner，Agent 就不知道要做什么。

## 2. Agent Runtime 的职责

本任务的 AgentRuntime 明确只做六件事：

1. **编排**：按固定顺序推进——规划 → 路由 → （按需）检索 → 验证 → （按需）生成 → 收尾。
2. **预算控制**：每次调用外部 Port 之前检查 AgentRunBudget，超预算立刻失败，不无限循环、不隐式重试。
3. **异常边界**：Planner / RetrievalPort / AnswerPort 的异常不吞掉，转成结构化 failed result，Trace 里只记异常类型名。
4. **证据规范化**：把检索返回的 Documents 去重、截断、分配连续 citation_id，做成 EvidenceBundle。
5. **生成准入**：最小 Verifier 判断"能不能生成"，不能就返回固定拒答文本。
6. **结果与轨迹**：产出结构化 AgentRunResult，包含一条脱敏的 RunTrace。

**不该做的**：Runtime 不做 API、不做 UI、不做指标评测、不做多 Query 检索、不自动选 Hybrid/Dense、不调用真实模型。它是一块"可以被任何 Adapter 插上去"的核心，而不是一个完整产品。

## 3. QueryPlan 与 RouteDecision 的边界

- **QueryPlan**（`core/query_planning/models.py`）回答"**这题应该怎么规划**"：query_type、要不要检索、action、reason_code、子问题。它是**语义决策层**，由 Planner 产出。
- **RouteDecision**（`core/agent_runtime/models.py`）回答"**这次运行实际怎么走**"：route（direct_answer / single_retrieval / decomposed_retrieval）、retrieval_strategy、要执行的 queries。它是**执行决策层**，由 DeterministicRouter 从 QueryPlan 映射而来。

区别的关键：QueryPlan 是"规划语义"，RouteDecision 是"本次执行的具体指令"。同一种 QueryPlan 语义在不同运行环境可能有不同执行方式（例如未来 decomposed 接上多 Query 检索后，执行路径会变化），但规划语义不变。把两者分开，是为了让"规划"和"执行"可以独立演进、独立测试。

## 4. 为什么 Router v1 是确定性的

Router v1 不调用 LLM，只是**一张查表**：

| action | route | strategy | queries |
|---|---|---|---|
| no_retrieval | direct_answer | none | () |
| single_retrieval | single_retrieval | bm25 | (original_query,) |
| decomposed_retrieval | decomposed_retrieval | bm25 | (sq1, sq2, sq3) |

这样做的三个理由：

1. **可复现**：同样的 QueryPlan 永远得到同样的 RouteDecision，没有随机性。
2. **可审计**：路由逻辑一眼能看懂，出错能立刻定位，不用猜模型在想什么。
3. **边界清晰**：模型只负责"规划"，系统负责"怎么执行"。让模型去选检索策略（Hybrid/Dense）会把不可信输出扩大到执行层，风险更大。

Router v1 的"笨"是刻意的：先把执行骨架打通，将来即使引入更聪明的路由（例如按查询类型选策略），也有一个确定的基线可对照。

## 5. Port/Adapter 模式

Runtime 需要检索和生成，但它**不关心具体实现**。它只依赖两个抽象接口（Port）：

```python
class RetrievalPort(Protocol):
    def search(self, query, strategy, top_k): ...

class AnswerPort(Protocol):
    def answer(self, question, evidence_bundle, mode): ...
```

谁来实现？**Adapter**——比如一个包着现有 BM25 Retriever 的 RetrievalPort Adapter、一个包着 DeepSeek Generator 的 AnswerPort Adapter。Runtime 依赖"接口"而不是"具体类"，于是：

- 测试时可以注入 Fake Adapter（本任务全部测试就是这么做的）；
- 将来接真实 Retriever / Generator 时，只写新的 Adapter，不动 Runtime 核心；
- 换模型、换检索库都不改编排逻辑。

这就是依赖倒置：高层模块（Runtime）不依赖低层模块（具体检索/生成实现），两者都依赖抽象（Port）。Port 上的 `mode` 只允许 `direct` / `grounded`，由 `validate_answer_mode` 强制。

## 6. EvidenceBundle 的意义

EvidenceBundle 是"这次运行要用到的证据集合"的统一快照，承担四件事：

1. **去重**：chunk_id 非空时按 chunk_id 去重；chunk_id 为空时按 (source_name, content) 去重；保留首次出现顺序。
2. **截断**：不允许多于 `AgentRunBudget.max_evidence_items`（默认 5），防止证据无限膨胀撑爆生成端。
3. **连续编号**：citation_id 从 [C1]、[C2]… 连续递增，且唯一——这是生成端引用（[C1]）与结果 `sources` 能对上的前提。
4. **如实透传**：缺失的 chunk_id / document_id / score 保留为 None，**不虚构**。宁缺毋假，避免"编造出处"。

它把"检索结果（Documents）"和"生成输入"之间加了一层规范化，让 AnswerPort 拿到的是稳定、干净、可引用的证据，而不是五花八门的原始返回。

## 7. 最小 Verifier 能证明什么、不能证明什么

本任务的三条规则：

| 情况 | 结论 | can_generate |
|---|---|---|
| no_retrieval | not_required | true |
| retrieval_required 且证据非空 | supported | true |
| retrieval_required 且证据为空 | insufficient_evidence | false |

它能证明的：**"该不该生成"这个准入判断**——没有检索需求的直接生成；有检索需求的，有证据才能生成，没有证据就拒答。这是回答"可信不可信"的最粗一层闸门。

它**不能**证明的：

- 证据内容是否真的支持答案里的每个断言（claim-level Faithfulness / 事实蕴含验证）；
- 证据是否相关、是否有足够信息量；
- 模型是否在答案里编造了证据里没有的内容。

换句话说，最小 Verifier 只回答"有没有证据可用"，不回答"证据能不能支撑答案"。把它说成"完整 Faithfulness Verifier"是误导，本任务明确不这么做。

## 8. Budget 为什么必须由系统控制

Agentic 系统让模型"自主决策"，但**预算必须握在系统手里**，理由：

1. **成本有界**：每 Case 调用 Planner 最多一次、Retrieval 最多一次、Generation 最多一次、证据最多 5 条，成本可预期。
2. **延迟有界**：不会因为模型"想多检索几轮"而无限拖长。
3. **防失控**：模型可能被诱导进入循环或隐式重试；系统在每次外部 Port 调用前检查预算，超了立刻 `failed + BUDGET_EXCEEDED`，不继续。
4. **可复现**：有界预算让同一输入在配置不变时行为可预测，实验才能对照。

本任务的预算只数"调用次数"（steps 与各 Port 计数），**不做 Token 精确计费、不做 wall-clock 超时**——那些留作技术债，等真接生成模型时再加。

## 9. RunTrace 与思维链的区别

RunTrace 是本任务最容易被误读的地方。它是**脱敏的执行记录**，不是思维链：

| 维度 | RunTrace | 思维链（CoT） |
|---|---|---|
| 内容 | 结构化事件：started / planning_completed / retrieval_completed … | 模型的内心推理步骤 |
| 目的 | 可审计、可复现、可诊断 | 让模型"想清楚" |
| 保密性 | 脱敏，只记事实与计数 | 常含敏感/半成品内容 |
| 可回放 | 是（可 JSON 序列化） | 否 |

TraceEvent.data **禁止**保存：思维链、System Prompt、raw model output、API Key、Authorization、traceback、完整文档正文。每条事件只记"发生了什么"（route、count、status、error_code、exception 类型名），不记"内容是什么"。

这一条是安全边界：日志、Artifact、结果对象若含 Key / Prompt / 正文，等于把机密泄漏出去。测试里专门验证了"正文和假 Key 都不会出现在 Trace 里"。

## 10. completed / refused / deferred / failed 的区别

四种状态是**互相独立**的结果，含义不同：

| status | 含义 | 何时发生 | 有没有答案 |
|---|---|---|---|
| completed | 正常走完全程，给了答案 | direct 生成成功，或检索有证据且生成成功 | 有 |
| refused | 该检索却没有任何证据，拒绝回答 | 检索返回空 → insufficient_evidence | 固定拒答文本 |
| deferred | 需要多 Query 检索，但本阶段未实现，先挂起 | decomposed_retrieval 只路由不执行 | 无 |
| failed | 系统层失败（异常或预算超限） | 异常 / BUDGET_EXCEEDED | 无 |

关键点：

- **refused 不是失败**，是"诚实地说不知道"，它的 error_code 是 None。
- **deferred 不是失败**，是"明确告知还没实现"，error_code 固定为 `DECOMPOSED_RETRIEVAL_NOT_IMPLEMENTED`。
- **failed 才带真正的 error_code**（PLANNING_FAILED / RETRIEVAL_FAILED / GENERATION_FAILED / BUDGET_EXCEEDED），并且必须区分——方便上游知道该重试哪个环节。

## 11. 为什么本阶段不静默降级复杂问题

decomposed_retrieval 意味着"这个问题被规划成需要多个子问题分别检索再综合"。本阶段 Runtime 直接返回 `deferred`，**绝不明知该拆却不拆**、不悄悄退回单问题检索。

原因：

1. **诚实优于"看起来能用"**：静默降级会给出一个看似正常、实际忽略了一半子问题的答案，最危险。
2. **可评测性**：Gate 3 的实验要对比"分解检索 vs 单次检索"的收益，静默降级会污染对照。
3. **渐进式开发**：先把骨架立住，明确"这里还没实现"，下一阶段再接真正的多 Query 检索（G3-RUNTIME-05B 及之后）。deferred 状态 + 明确 error_code 是给后续实现的"占位契约"。

## 12. 下一步如何接入 Pipeline、API 和多 Query Retrieval

- **Pipeline Adapter（G3-RUNTIME-05B）**：写一个 RetrievalPort Adapter 包住现有 BM25 Retriever，AnswerPort Adapter 包住现有 Generator，再把 AgentRuntime 作为新的问答入口接入。
- **API（G3-RUNTIME-05B）**：`/agent/query` 接受问题，构造一次 AgentRuntime 跑 `run()`，把 AgentRunResult 序列化返回；把 refused / deferred / failed 映射成 HTTP 语义。
- **多 Query Retrieval**：把 decomposed_retrieval 从"deferred"升级为"对 route.queries 逐条检索，合并 EvidenceBundle，再生成"——这个升级发生在 Runtime 内部，Router 的 RouteDecision 契约已经预留了 queries 字段，API/Pipeline 层不用大改。

## 13. 面试可能追问与参考回答

**Q：Planner 和 Agent 的区别？**
A：Planner 把问题变成 QueryPlan（要不要检索/分解），是静态决策；Agent 是执行主体，负责路由、检索、证据、验证、生成与记录。Planner 是 Agent 的一部分能力，不是 Agent 本身。

**Q：Router 为什么用确定性映射而不是让模型选？**
A：确定性能保证可复现、可审计，且把不可信输出限制在"规划层"而不是扩大到"执行层"。先有确定基线，将来要加更聪明的路由也有对照。

**Q：Port/Adapter 的好处？**
A：Runtime 依赖抽象接口，不依赖具体实现；测试注入 Fake，生产注入真实 Adapter，换模型/换检索库不动编排逻辑（依赖倒置）。

**Q：refused 和 failed 有什么区别？**
A：refused 是"该检索但没有证据，诚实拒答"，是正常结束（error_code=None），返回固定拒答文本；failed 是系统层失败（异常/预算超限），必须带 error_code 区分环节。

**Q：Trace 和思维链的区别？**
A：Trace 是脱敏的结构化执行记录（事件/计数/状态），可回放、可审计；思维链是模型推理过程，含半成品内容。Trace 禁止存 Prompt/raw output/Key/traceback/正文。

**Q：最小 Verifier 能保证什么？**
A：只保证"能不能生成"的准入：无检索需求直接生成；有检索需求必须有证据。它不证明 claim-level 事实蕴含，不能把证据够不够当作答案对不对。

**Q：Budget 由谁控制？为什么？**
A：由系统（AgentRuntime）在每次外部调用前检查，因为成本/延迟/可复现性都要求有界，且不能让模型自行决定何时停。本阶段只数调用次数，不精确计费。

**Q：decomposed_retrieval 为什么返回 deferred？**
A：多 Query 检索尚未实现。静默降级成单问题检索会给出忽略子问题的"伪正常"答案，污染可评测性，也不诚实。用 deferred + 明确 error_code 占位，下一阶段实现真多 Query 检索。

## 14. 当前技术债

- **多 Query 检索未实现**：decomposed_retrieval 只路由为 deferred；真实执行在后续任务。
- **Token 精确计费 / wall-clock 超时未做**：AgentRunBudget 只数调用次数。
- **Verifier 是最小规则版**：无 claim-level Faithfulness、无相关性与信息量判断。
- **无真实 Adapter**：RetrievalPort / AnswerPort 只有测试 Fake，未包住真实 Retriever/Generator。
- **无 API / Pipeline / UI**：AgentRuntime 是离线核心，尚未对外暴露。
- **无 Reranker / Hybrid/Dense 自动选择 / Tool Registry / Checkpoint / SSE / 多 Agent / MCP / GraphRAG**：全部明确不在本任务范围。

---

## 边界声明

- 本任务只建立最小离线 Runtime 垂直切片，未运行真实 Planner/Retriever/Generator，未计算任何指标。
- 未访问 Gate 3 Holdout / sealed；示例全部为 synthetic。
- decomposed_retrieval 仅路由，未执行多 Query 检索，未静默降级。
- 最小 Verifier 不宣称完整 Faithfulness 验证。
