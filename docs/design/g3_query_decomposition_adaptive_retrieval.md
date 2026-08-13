# Gate 3：Query Decomposition 与 Adaptive Retrieval 设计

> 任务：G3-DESIGN-01（设计契约，零业务实现）
> 日期：2026-08-09
> 基线提交：`13cb26d` fix: restrict local API exposure and query boundaries
> 状态：Gate 3 = IN PROGRESS / DESIGN ONLY；Query Decomposition 与 Adaptive Retrieval 业务实现仍为 NOT STARTED
> 权威来源分层：本设计文档记录 Gate 3 评测协议与架构契约；冻结数字以 `docs/experiments/gate2_freeze.json` 为准；实时状态以 `docs/status.md` 为准。

本设计只回答 **评测协议与架构契约**，不描述任何已实现功能。文中所有“必须/禁止/上限”都是契约要求，不是现状描述。

---

## 1. 研究问题

Gate 3 只回答一个问题：

> 在冻结语料（`corpus_id = 870e5864df67`）和新增复杂问题上，有界 Query Decomposition 与 Adaptive Retrieval 是否比单次 BM25 primary 和 Hybrid control 带来可复现收益；收益是否值得额外检索调用、Planner Token、延迟和失败风险？

约束：

- 不得把“实现了高级 RAG”作为验收标准；
- 验收标准是“完成受控对照并得到可信结论”；
- **负结果同样有效**：如果 Decomposition 没有稳定收益，它就是 Gate 3 的正式结论；
- 任何结论必须限定范围：仅该语料、该 evaluation set、该 holdout，不推广为通用规律。

---

## 2. 冻结 Baseline

Gate 3 必须同时保留两个 Baseline，Gate 2 冻结 Artifact 不得重写。

### A：BM25 primary（主基线）

| 字段 | 值 |
|---|---|
| chunk_strategy | recursive |
| chunk_budget_policy | `cl100k_content_v1` |
| retriever_strategy | `bm25` |
| top_k | 5 |
| Gate 2 experiment_id | `dbc497c796d5` |
| Gate 2 result_id | `acd92171966d` |

### B：Hybrid control（对照基线）

| 字段 | 值 |
|---|---|
| chunk_strategy | recursive |
| chunk_budget_policy | `cl100k_content_v1` |
| retriever_strategy | `hybrid` |
| top_k | 5 |
| Gate 2 experiment_id | `3c613202e1ed` |
| Gate 2 result_id | `e27141a2b63e` |

规则：

- 只与 Hybrid 比较可能掩盖“简单 BM25 已经更强”的事实；只与 BM25 比较又无法观察融合策略行为变化，因此两个都要保留；
- Gate 3 可以在新 evaluation set 上重新运行相同配置，但必须生成 **新的 Gate 3 Run Artifact**，不得覆盖 Gate 2 Artifact；
- Gate 2 的冻结 JSON、experiments/ 目录和 50 条 Case 一律不改。

---

## 3. 数据与 sealed holdout

### 3.1 语料

Gate 3 使用当前冻结的 37 文件语料，`corpus_id = 870e5864df67`。

原因：控制语料、分块、索引变量，只测量**查询规划与检索策略**的变化。

这一选择只能证明：

> 在该冻结语料上的 query-level 泛化。

**不能**声称跨语料泛化。

### 3.2 新增 36 条问题（G3-DATA-02 建立）

| 类型 | 数量 |
|---|--:|
| comparison | 8 |
| multi_entity / multi-hop | 6 |
| causal / evidence synthesis | 6 |
| troubleshooting | 4 |
| simple fact / code_symbol control | 6 |
| unanswerable | 3 |
| no_retrieval | 3 |
| 合计 | 36 |

要求：

- 至少 **20 条**具有两个或以上 required evidence obligations；
- **24 条进入 dev**，**12 条进入 sealed holdout**；
- split 必须分层，不能把复杂问题全部放入 dev；
- holdout 中至少 **7 条**具有多个 evidence obligations。

### 3.3 Gate 2 原有 50 条 Case

- 字节保持不变；
- 继续作为 **regression suite**；
- 允许用于开发期失败分析；
- **不得计入新的 holdout**，不得继续当作 Gate 3 泛化证明。

### 3.4 Holdout 隔离纪律

实际 holdout 的 Query、Gold 和逐 Case 结果**不得提前提交到主项目仓库**。

建议存放于用户控制目录：

```
D:\学习\rag实战项目\rag数据集\benchmark_work\gate3\sealed\
```

主仓库在正式评测前只允许登记：

- schema version；
- corpus_id；
- case_count；
- 类型分布；
- holdout 文件 SHA-256；
- evaluation_set_id；
- sealed 状态。

纪律：

- 实现 Agent 在编码、路由调参和 Prompt 调整阶段**不得读取 holdout 内容**；
- 正式 holdout 运行前必须冻结：代码 commit、Planner Prompt、Planner provider/model、temperature、QueryPlan Schema、Router policy、Router threshold、merge policy、fallback、全部成本上限；
- holdout 原则上**只正式运行一次**；
- 如果看到 holdout 逐 Case 结果后继续调规则，该 holdout 立即失效，必须建立新的 evaluation_set_id，不能继续用原结果证明泛化。

**上下文隔离（session isolation）**：

- 数据构建 / Gold 审核阶段**可以**读取待封存 Case（这是数据建设者的正当职责）；
- sealed 之后，数据构建 Agent 必须**停止**；
- 后续 G3-PLAN / G3-DECOMP / G3-ADAPT 必须使用**新的执行会话**；
- 新会话不得接收 holdout 的 Query、Gold、文件内容或逐 Case 结果；
- 用户与审计负责 Gold 技术判断和最终 split 拍板；
- 若同一实现会话读取过 holdout，该 holdout 立即失效；
- 这是**流程隔离**，不声称操作系统级访问控制。

---

## 4. 架构边界

Gate 3 分成四层，禁止把 Planner、Router 或 Evidence 业务逻辑直接堆入现有 `ExperimentRunner`。

### 4.1 Query Planning

未来目录：`core/query_planning/`

负责：

- 问题分类；
- 是否需要检索；
- 是否需要分解；
- 生成最多 3 个子问题；
- Schema 校验与规范化；
- 失败时回退。

#### 4.1.1 04B-01 实现事实（OpenAI-compatible Planner Provider）

以下为 04B-01 + R1 已实现的固定执行事实（非实验效果，不登记任何指标）：

- **Prompt v1（R1 收口身份）**：`PLANNER_PROMPT_VERSION = gate3_planner_prompt_v1`；user payload 是真正 canonical JSON（`ensure_ascii=False / sort_keys=True / separators=(",", ":")`），字段结构 `{original_query, payload_version}`；`PLANNER_PROMPT_SHA256` 绑定 prompt version、system prompt 全文、user payload 模板结构（`original_query` 占位符 + `payload_version` 固定值）与 canonicalization 标识 `python_json_sort_keys_compact_v1`；R1 前旧 SHA `043860f8...`，R1 收紧后新 SHA `5b209054...`（此前版本未 push/正式运行，version 保持不变）；原始 query 运行时值不进入模板哈希。
- **OpenAI-compatible Provider**：`OpenAICompatibleQueryPlanner`（`core/query_planning/openai_compatible.py`）实现 `BaseQueryPlanner`，生产默认构造 openai SDK client（`api_key`/`timeout=20`/`max_retries=0`/可选 `base_url`），测试用 Fake Client 注入。
- **固定参数**：`temperature=0`、`max_tokens=800`、`timeout=20s`、`max_retries=0`；每个问题最多一次模型调用，无重试循环、无 sleep。
- **失败代码**：`PLANNER_PROVIDER_ERROR` 与 `PLANNER_TIMEOUT` 由 04B-01 Provider 主动产生；非法/空模型文本仍交 `parse_planner_output` 分类（PLAN_EMPTY/INVALID_SCHEMA/OVER_DECOMPOSE/UNDER_DECOMPOSE/DUPLICATE_SUBQUERY）。
- **响应结构缺损完整映射**：`_extract_content` 逐层检查（choices 存在 / 是 list / 非空 / choices[0].message 存在且非 None / message.content 存在 / content 是 str）；任何缺损统一映射 `PLANNER_PROVIDER_ERROR`；`usage` 畸形同样映射；不宽泛捕获 AttributeError/TypeError，content 属性内部抛的未知编程错误向上传播。
- **PlannerCallMetadata**：记录 provider/model/prompt_version/prompt_sha256/call_count/tokens/latency_ms，作为观测事实，**不进入 plan_id**。
- **当前未实现**：运行时语义新实体检测、比较对象语义保持检测、语义近义子问题检测（属 04B-02）；**当前未运行** Dev/Holdout 指标；04B-01/R1 仍为 REVIEW PENDING。

### 4.2 Adaptive Routing

未来目录：`core/adaptive_retrieval/`

负责：

- 为原问题或每个子问题选择 Retriever；
- 输出结构化 RouteDecision；
- **不生成子问题**；
- **不判断 Gold**；
- **不承担实验编排**。

### 4.3 Evidence

未来目录：`core/evidence/`

负责：

- 保留 subquery → chunk → document 映射；
- 去重；
- 确定性合并；
- 生成 EvidenceBundle；
- **不能让一个高分 Chunk 假装覆盖全部子问题**。

### 4.4 Gate 3 Evaluation

未来目录：`evaluation/gate3/`

负责：

- Gate3Case；
- Gate3ExperimentConfig；
- Gate3Run Artifact；
- Gate 3 指标；
- dev/holdout Manifest；
- 实验编排。

现有 `ExperimentRunner` 只继续承担 Gate 2 检索实验（prepare → index_corpus → run_retrieval → compute_retrieval_metrics → finalize_result）。

---

## 5. QueryPlan Schema v1

QueryPlan 与 RouteDecision **必须分离**。

### 5.1 QueryPlan 不允许包含

以下字段不属于 QueryPlan，属于 Router、Executor、实验配置或评测层：

- effective selected strategy；
- candidate_k；
- final_k；
- reranker 开关；
- max retrieval rounds；
- Gold obligation ID；
- 隐藏思维链。

### 5.2 QueryPlan 字段

| 字段 | 契约 |
|---|---|
| schema_version | 固定 `query_plan_v1` |
| plan_id | 规范化 QueryPlan 的稳定哈希（见 §5.2.1） |
| original_query | 保留原问题，1～4000 字符 |
| query_type | 固定枚举 |
| retrieval_required | bool |
| action | 固定枚举 |
| reason_code | 固定枚举，不使用自由推理文本 |
| subqueries | 0～3 条 |
| fallback_policy | 固定 `single_bm25_original_query` |

### 5.2.1 plan_id 哈希算法

plan_id 的哈希 payload 是**规范化 QueryPlan，但排除 plan_id 字段本身**。任何对象都不能参与自身的身份哈希。

算法：

- payload 包含 `schema_version` 和其余规范化 QueryPlan 字段（`original_query`、`query_type`、`retrieval_required`、`action`、`reason_code`、`subqueries`、`fallback_policy`）；
- dict key 按字典序（`sort_keys=True`）；
- `subqueries` list 顺序具有语义，保持 `sq1 → sq3` 顺序，**不排序**；
- canonical JSON：UTF-8、`ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")`；
- SHA-256 取前 12 位小写十六进制；
- `plan_id` 不参与自身哈希；
- 时间、路径、对象地址、原始模型输出、latency 一律不参与 plan_id。

### 5.3 query_type 枚举

- `fact`
- `comparison`
- `causal`
- `multi_entity`
- `code_symbol`
- `troubleshooting`
- `unanswerable_or_no_retrieval`

### 5.4 action 枚举

- `no_retrieval`
- `single_retrieval`
- `decomposed_retrieval`

### 5.5 reason_code（至少包含）

- `NO_RETRIEVAL_NEEDED`
- `SIMPLE_FACT`
- `CODE_SYMBOL`
- `COMPARISON_EVIDENCE`
- `MULTI_ENTITY_EVIDENCE`
- `CAUSAL_SYNTHESIS`
- `TROUBLESHOOTING_EVIDENCE`
- `UNANSWERABLE_CHECK`
- `PLANNER_FALLBACK`

### 5.6 Subquery 字段

| 字段 | 契约 |
|---|---|
| id | `sq1`～`sq3`，唯一且连续 |
| query | 1～1000 字符 |
| evidence_target | 1～500 字符，只描述需要寻找的证据 |
| required | bool |

### 5.7 子问题约束

子问题必须：

- 去重；
- 不引入原问题中不存在的新实体；
- 保持比较问题的两侧对象；
- 不携带 Gold 文件名或 Gold obligation ID；
- Schema 失败、空结果、重复结果或越界时，回退为原问题单次 BM25。

### 5.8 执行上限不属于模型输出

最大子问题数、最大轮数等限制属于**不可变执行配置**，不能由 LLM 输出并控制。任何模型输出都不能突破这些上限（见第 11 节硬预算）。

### 5.9 QueryPlan 跨字段不变量（fail-fast）

QueryPlan 是强类型对象，字段之间存在**跨字段不变量**，Schema 校验必须 fail-fast。违反任一不变量即视为 Schema 无效，回退为 `PLANNER_FALLBACK`（见下）。

#### no_retrieval

- `retrieval_required = false`
- `action = no_retrieval`
- `subqueries` 必须为空
- 不生成任何 RouteDecision
- `reason_code` 必须为 `NO_RETRIEVAL_NEEDED`

#### single_retrieval

- `retrieval_required = true`
- `action = single_retrieval`
- `subqueries` 必须为空
- 只生成一条 `subquery_id=ROOT` 的 RouteDecision

#### decomposed_retrieval

- `retrieval_required = true`
- `action = decomposed_retrieval`
- `subqueries` 数量必须为 **2～3**
- 子问题 ID 必须连续且唯一：`sq1`、`sq2`、`sq3`
- v1 中所有生成的 `Subquery.required` 固定为 `true`
- 每个子问题生成一条 RouteDecision
- 不额外生成 ROOT 检索

#### fallback 规范化

Planner Schema 无效、越界、空结果或重复结果时，必须规范化为一个**合法的 single_retrieval QueryPlan**：

- `query_type = unknown`（系统 fallback 哨兵，见下）
- `retrieval_required = true`
- `action = single_retrieval`
- `reason_code = PLANNER_FALLBACK`
- `subqueries = []`
- `fallback_policy = single_bm25_original_query`

随后再计算该 fallback QueryPlan 的 `plan_id`。

#### system fallback sentinel：unknown

Planner 失败时**不存在可信分类结果**，因此 fallback 使用系统专属 `query_type = unknown`：

- 正常 Planner 的 `query_type` 仍然恰好是原 7 种（`fact / comparison / causal / multi_entity / code_symbol / troubleshooting / unanswerable_or_no_retrieval`）。
- `unknown` 是 **system-only sentinel**：它不是模型输出类型、不属于 Gate3Case 标签、不参与正常分类准确率。
- `query_type = unknown` ⇔ `reason_code = PLANNER_FALLBACK` 双向强约束：模型无权输出 `unknown`，系统也无权用分类类型填充 fallback。
- **禁止**用 Gold 标签、Dev 标签、部分非法模型输出或任意语义类型填充 fallback `query_type`。
- fallback rate 与 `failure_code` 单独统计，不混入正常分类指标。
- Router 看见 `reason_code = PLANNER_FALLBACK` 时固定走原问题单次 BM25，不根据 `unknown` 做普通路由。

#### unanswerable 与 no_retrieval 的区分

`query_type = unanswerable_or_no_retrieval` 由 `retrieval_required` 区分：

- `retrieval_required = false` → `no_retrieval`（不生成 RouteDecision）
- `retrieval_required = true` → `unanswerable check`（允许检索一次以核实不可回答，Gate 3 只记录 Planner/Router 行为，拒答正确性属于 Gate 5）

---

## 6. RouteDecision Schema v1

字段至少包括：

| 字段 | 契约 |
|---|---|
| schema_version | 固定 `route_decision_v1` |
| plan_id | 绑定规范化 QueryPlan |
| subquery_id | `ROOT` 或 `sq1`～`sq3` |
| selected_strategy | `bm25`、`simple`、`hybrid` |
| reason_code | 封闭枚举（见 §6.4），未知值必须拒绝 |
| retrieval_top_k | 固定为 5 |
| dense_candidate_k | 正整数或 null（见 §6.4 映射） |
| sparse_candidate_k | 正整数或 null（见 §6.4 映射） |
| reranker_enabled | Gate 3 retrieval 第一版固定 `false` |
| fallback_used | bool |
| latency_ms | 观测事实，不进入配置身份 |

说明：

- `simple` 是当前代码中 Dense Retriever 的正式策略名（`ExperimentConfig.retriever_strategy` 合法值为 `simple/hybrid/mmr/bm25`；`core/retriever/simple.py` 的 `SimpleRetriever` 即 Dense 检索器）。文档与配置必须沿用 `simple`，不能另造一个无法映射代码的 `dense` 配置值。
- **删除模糊的单一 `candidate_k`**：不同策略的候选池语义不同（Hybrid 有双通道候选池，BM25/simple 没有），单一字段无法表达，改为 `dense_candidate_k` / `sparse_candidate_k` 显式分离。

### 6.1 Router v1 允许使用的信号

Router v1 只允许使用：

- QueryPlan query_type；
- retrieval_required；
- action；
- 确定性 lexical / code-symbol 特征（如类名、方法名、错误码、精确 term）；
- 在 dev 上预先定义并冻结的规则。

### 6.2 Router v1 禁止使用

- holdout 逐 Case 结果；
- Gold 文件；
- 无法比较的跨 Retriever 原始分数阈值；
- 自由文本隐藏推理。

### 6.3 默认与候选

- 默认 fallback 永远是 BM25；
- Router 候选可以包含 BM25、simple（Dense）、Hybrid；
- 但 Dense 或 Hybrid 是否真正进入最终规则，**必须由 dev 证据决定**；
- 不因”Hybrid 更高级”默认选择 Hybrid。

### 6.4 Retriever 精确映射与 reason_code 封闭

每个 `selected_strategy` 精确映射到现有 Retriever 的确定性调用：

#### bm25

- `retrieval_top_k = 5`
- `dense_candidate_k = null`
- `sparse_candidate_k = null`
- 直接映射 `BM25OnlyRetriever.retrieve(query, top_k=5)`

#### simple

- `retrieval_top_k = 5`
- `dense_candidate_k = null`
- `sparse_candidate_k = null`
- 直接映射 `SimpleRetriever.retrieve(query, top_k=5)`

#### hybrid

- `retrieval_top_k = 5`
- `dense_candidate_k = 30`
- `sparse_candidate_k = 30`
- 映射冻结 Hybrid control 的内部候选池（Gate 2 Hybrid control `3c613202e1ed` / `e27141a2b63e` 的检索参数）
- 最终仍返回每个子问题 Top-5

Route `reason_code` 封闭为以下枚举，未知 `reason_code` 必须拒绝：

- `NO_RETRIEVAL`
- `DEFAULT_BM25`
- `EXACT_LEXICAL_BM25`
- `DEV_RULE_SIMPLE`
- `DEV_RULE_HYBRID`
- `ROUTER_FALLBACK`

---

## 7. EvidenceBundle Schema

### 7.1 EvidenceHit

schema_version 固定 `evidence_hit_v1`。至少保留：

- subquery_id；
- chunk_id；
- document_id；
- relative_path；
- selected_strategy；
- rank；
- 实际存在的 score/rank 字段（沿用 Gate 2 分数白名单思路：只保存真实存在的字段，不虚构 0）；
- route reason_code。

### 7.2 EvidenceBundle

schema_version 固定 `evidence_bundle_v1`；`merge_policy_version` 固定 `subquery_round_robin_v1`。

EvidenceBundle 必须绑定：

- `query_plan_snapshot_id` 或 `plan_id`；
- 对应的 RouteDecision；
- 每个子问题的原始命中；
- subquery → chunks → documents 映射；
- 去重后的最终唯一文档顺序；
- `retrieval_top_k`；
- `final_unique_document_k = 5`。

至少保留：

- plan_id；
- 每个 subquery 的原始命中；
- subquery → chunks → documents 映射；
- 去重后的最终文档顺序；
- merge policy version；
- fallback_used；
- retrieval_call_count；
- total_latency_ms。

### 7.3 Merge Policy v1：`subquery_round_robin_v1`

规则（按序执行）：

1. 有效分解时不额外检索原问题；
2. 每个子问题独立检索；
3. 按 `sq1 → sq2 → sq3` 顺序，每轮各取一个尚未出现的文档；
4. 重复文档跳过；
5. 重复轮转直到得到 5 个唯一文档或候选耗尽；
6. 单个 Retriever 内沿用其既有稳定排序；
7. 不直接比较 BM25、Dense、RRF 的原始分数；
8. 输出必须确定性。

---

## 8. Gate 3 独立实验身份

禁止扩展或改变 Gate 2 `ExperimentConfig` 的现有身份语义（`evaluation/experiment_config.py`：frozen dataclass，experiment_id = 字段序序列化后 SHA-256 前 12 位）。Gate 2 ExperimentConfig 只服务 Gate 2 检索实验。

后续在 `evaluation/gate3/` 建立**独立** `Gate3ExperimentConfig`。

### 8.1 配置身份至少绑定

- Gate 3 config schema version；
- QueryPlan schema version；
- RouteDecision schema version；
- EvidenceBundle schema version；
- frozen base retrieval config/reference；
- planner mode；
- planner provider；
- planner model；
- prompt version 或 prompt hash；
- temperature；
- max planner output tokens；
- max subqueries；
- max subquery chars；
- router policy version；
- fallback strategy；
- merge policy version；
- per-query final_k；
- max retrieval rounds；
- max retrieval calls；
- timeout；
- corrective retrieval 是否启用。

### 8.2 配置 ID 不包含

- 时间；
- 路径；
- API Key；
- 对象地址；
- latency；
- 实际输出内容。

### 8.3 正式 Run ID 再绑定

- Gate3ExperimentConfig ID；
- corpus_id；
- evaluation_set_id；
- split；
- QueryPlan snapshot ID；
- 代码冻结 commit。

### 8.4 C/D 共享 QueryPlan snapshot

C（Decomposition + BM25）与 D（Decomposition + Adaptive Retrieval）的正式对照必须复用**同一份规范化 QueryPlan snapshot**，避免 LLM 两次输出不同而污染 Router 对照。只有 Router 这一变量允许不同。

### 8.5 身份哈希：query_plan_snapshot_id、gate3_config_id、gate3_run_id

全部身份使用同一 canonical JSON + SHA-256 前 12 位小写十六进制（UTF-8、`ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")`）。

#### QueryPlan snapshot ID

- schema_version 固定 `query_plan_snapshot_v1`；
- payload 至少包含：`schema_version`、`evaluation_set_id`、按 `case_id` 排序的 plans；
- 每项 plan 包含 `case_id`、`plan_id` 和排除 `plan_id` 后的规范化 plan；
- 不含时间、路径、latency 与实际输出。

#### gate3_config_id

- `gate3_config_id = Gate3ExperimentConfig 规范化 JSON 的 SHA-256[:12]`；
- 规范化 JSON 覆盖第 8.1 节全部身份绑定字段。

#### gate3_run_id

- schema_version 固定（沿用 Run 身份 schema）；
- `gate3_run_id` 绑定：`schema_version`、`gate3_config_id`、`corpus_id`、`evaluation_set_id`、`split`、`query_plan_snapshot_id`、`frozen_code_commit`；
- 使用 canonical JSON + SHA-256[:12]；
- **不包含**：时间、绝对路径、API Key、latency、实际得分。

---

## 9. 实验矩阵

| 组 | 策略 | Planner | Router |
|---|---|---|---|
| A | 原问题单次 BM25 | 无 | 固定 BM25 |
| B | 原问题单次 Hybrid | 无 | 固定 Hybrid |
| C | Decomposition + BM25 | 同一 Planner snapshot | 所有子问题固定 BM25 |
| D | Decomposition + Adaptive Retrieval | 与 C 完全相同的 Planner snapshot | adaptive_rules_v1 |
| E | D + 一次 Corrective Retrieval | 条件性 | 条件性 |

控制要求：

- A/B 不调用 Planner；
- C/D 使用完全相同的 QueryPlan；
- C 与 D 只能改变 Router；
- 所有组最终文档预算固定 Top-5；
- 同一语料、分块、索引和 evaluation set；
- 不启用新 Reranker；
- E 默认不实现（见第 13 节立项条件）。

---

## 10. Gate3Case 与指标

### 10.1 Gate3Case 数据不变量

schema_version 固定 `gate3_case_v1`。至少包含：

- case_id；
- query；
- query_type；
- answerability：answerable / unanswerable / no_retrieval；
- retrieval_required；
- decomposition_expected：required / optional / forbidden；
- evidence_obligations；
- relevant_files；
- tags；
- split 由独立 Manifest 管理（不进 Case 本体）。

每个 evidence obligation 包含：

- obligation_id；
- description；
- relevant_files；
- required。

#### 10.1.1 answerable 不变量

- `retrieval_required = true`
- `evidence_obligations` 非空
- 每个 `required` obligation 的 `relevant_files` 非空
- 顶层 `relevant_files` 必须等于所有 obligation `relevant_files` 的**排序去重并集**
- 文件必须属于冻结 ExperimentCorpus

#### 10.1.2 unanswerable 不变量

- `retrieval_required = true`
- `query_type = unanswerable_or_no_retrieval`
- `evidence_obligations = []`
- `relevant_files = []`
- `decomposition_expected = forbidden`
- 不参与 Hit/Recall/MRR/nDCG

#### 10.1.3 no_retrieval 不变量

- `retrieval_required = false`
- `query_type = unanswerable_or_no_retrieval`
- `evidence_obligations = []`
- `relevant_files = []`
- `decomposition_expected = forbidden`
- 主要评估是否产生**零** Planner 后续检索调用

#### 10.1.4 其他约束

- `obligation_id` 在 Case 内唯一
- `relevant_files` 排序、去重
- `tags` 排序、去重
- split 不进入 Case 本体，由 split Manifest 管理
- dev 与 holdout 分别生成**独立 evaluation_set_id**
- `evaluation_set_id` 必须绑定 `schema_version`、`corpus_id` 和按 `case_id` 排序的完整规范化 Case
- 使用 canonical JSON + SHA-256[:12]
- split Manifest 另有独立 `manifest_id`

### 10.2 Obligation 覆盖定义

> 最终检索文档中至少有一个文件属于该 obligation 的 relevant_files。

### 10.3 Headline 指标

- final Gold obligation coverage；
- full obligation coverage rate；
- answerable Case 的 Hit@5、Recall@5、MRR、nDCG@5；
- multi-document complete recall；
- candidate obligation coverage；
- merge 后 obligation coverage；
- merge-drop rate。

### 10.4 Planning 指标

- schema validity；
- decomposition decision accuracy；
- unnecessary decomposition rate；
- missed decomposition rate；
- duplicate subquery rate；
- new entity introduction rate；
- fallback rate。

`new entity introduction` 自动规则只能作为候选告警，最终指标需要人工确认，不能把简单字符串不匹配直接当成事实。

### 10.5 no_retrieval 与 unanswerable

- `no_retrieval`：主要评估是否正确产生零检索调用；
- `unanswerable`：不参与 Hit/Recall/MRR/nDCG；
- unanswerable 的最终拒答正确性属于 Gate 5；
- Gate 3 只记录 Planner/Router 行为及是否发生无界检索；
- 不得伪造“无答案检索准确率”。

### 10.6 成本指标

- planner_call_count；
- retrieval_call_count；
- planner input/output tokens；
- 总 token；
- P50/P95 latency；
- timeout rate；
- fallback rate；
- 错误率；
- 按正式运行时价格快照估算的成本。

### 10.7 分层报告

所有结果必须按以下维度分层：

- simple；
- comparison；
- multi_entity；
- causal；
- troubleshooting；
- code_symbol；
- unanswerable；
- no_retrieval；
- dev；
- sealed holdout。

不得只报告总体均值。

---

## 11. 硬预算（第一版固定）

| 项 | 值 |
|---|---|
| 每请求 Planner 调用 | 最多 1 次 |
| 最大子问题数 | 3 |
| 每个子问题最长 | 1000 字符 |
| evidence_target 最长 | 500 字符 |
| 最大 retrieval rounds | 1 |
| 最大 Retriever 调用次数 | 3 |
| 最终唯一文档数 | 5 |
| Planner temperature | 0 |
| Planner 最大输出 | 800 tokens |
| Planner timeout | 20 秒 |
| Planner 自动重试 | 0 |
| Reranker | false（第一版） |
| Corrective Retrieval | false（第一版） |
| 任何失败默认回退 | 原问题单次 BM25 |

**任何模型输出都不能突破这些上限。** 上限属于不可变执行配置，不由 LLM 控制。

---

## 12. 失败分类

至少定义以下失败类型：

- `PLAN_INVALID_SCHEMA`
- `PLAN_OVER_DECOMPOSE`
- `PLAN_UNDER_DECOMPOSE`
- `PLAN_DUPLICATE_SUBQUERY`
- `PLAN_NEW_ENTITY`
- `PLAN_EMPTY`
- `ROUTE_WRONG_STRATEGY`
- `ROUTE_FALLBACK`
- `RETRIEVAL_EMPTY`
- `OBLIGATION_MISS`
- `MERGE_DROPPED_EVIDENCE`
- `BASELINE_REGRESSION`
- `PLANNER_TIMEOUT`
- `RETRIEVER_ERROR`
- `DATA_LABEL_DEFECT`

失败报告必须区分：

- Planner 失败；
- Router 失败；
- Retriever 失败；
- merge 失败；
- 数据标注问题；
- 系统异常。

---

## 13. Dev 晋级与停止条件

以下是项目工程 Gate，**不得包装成统计学普遍结论**。

### C：Decomposition + BM25 晋级 holdout

Dev 复杂问题子集同时满足：

- Schema validity ≥ 98%；
- 所有请求经过 fallback 后完成率 = 100%；
- 不必要分解率 ≤ 10%；
- 新增实体人工确认率 ≤ 5%；
- 相对 A 的 obligation coverage 至少提高 0.05；
- 至少修复 3 个 full-obligation Case；
- 相对 A 的 full-obligation loss 不超过 1 个。

否则停止扩大 Decomposition，先分析 Planner 或数据问题。

### D：Adaptive Router 晋级 holdout

相对 C：

- obligation coverage 至少提高 0.03，或者净修复至少 2 个 Case；
- full-obligation loss 不超过 1 个；
- 不突破调用预算；
- 规则可以用 reason_code 解释；
- 规则和阈值在 holdout 前冻结。

若不满足，删除或降级 Router，Gate 3 可以只保留 Decomposition + BM25。

### E：Corrective Retrieval 立项条件

只有 Dev 至少出现 3 条“一次检索证据不足”的可复现 Case，并且一次补检索能修复至少 2 条、损失不超过 1 条时，才允许立项。

否则 `G3-CORRECT-07` 直接标记为 SKIPPED。

### Holdout 保留条件

C 相对 A 在复杂 holdout 子集：

- obligation coverage 至少提高 0.08；
- 至少修复 2 个 full-obligation Case；
- 损失不超过 1 个；
- 简单 control 的 Hit@5 损失不超过 1 个 Case；
- 无上限突破；
- 无未处理异常。

D 相对 C 必须出现正向净修复，且损失不超过 1 个；否则不保留 Adaptive Router。

样本规模较小，因此结论必须限定为该语料和该 holdout，不能写成通用规律。

---

## 14. 后续任务边界

设计文档最后列出 Gate 3 顺序任务：

1. G3-DATA-02：建立 36 条新问题及 sealed holdout；
2. G3-PLAN-03：实现强类型 QueryPlan；
3. G3-DECOMP-04：实现有界 Planner 与 fallback；
4. G3-MRETR-05：实现 EvidenceBundle 与 Multi-query Retrieval；
5. G3-ADAPT-06：实现可解释 Router；
6. G3-CORRECT-07：条件性任务（满足第 13 节 E 才立项）；
7. G3-EVAL-08：Dev、冻结配置、正式 holdout；
8. G3-CLOSE-09：失败分析和 Gate 3 freeze。

GraphRAG **不进入**当前实现范围（决策 Gate 见 `docs/roadmap.md` 第 8 节）。

---

## 附：与现有代码的核对结论

- Gate 2 冻结身份：corpus_id=`870e5864df67`、evaluation_set_id=`18c1c0470652`、file_count=37、case_count=50、gold_obligation_count=58、top_k=5；primary BM25=`dbc497c796d5`/`acd92171966d`、Hybrid control=`3c613202e1ed`/`e27141a2b63e` —— 与 `gate2_freeze.json` 逐项一致。
- Retriever 策略名：`simple`（SimpleRetriever/Dense）、`bm25`（BM25OnlyRetriever）、`hybrid`（HybridRetriever）—— 与 `ExperimentConfig.VALID_RETRIEVER_STRATEGIES` 及 `core/retriever/*` 一致。
- Gate 3 必须使用独立 `Gate3ExperimentConfig`，不扩展 `ExperimentConfig`（frozen dataclass，experiment_id 已冻结语义）。
- `ExperimentRunner` 保持 Gate 2 编排职责（prepare→index_corpus→run_retrieval→compute_retrieval_metrics→finalize_result），不承载 Planner/Router 业务逻辑。
- RRF 排序契约（rrf_score DESC → chunk_id ASC）与分数白名单思路（只保存真实存在字段）延续到 Gate 3 的 EvidenceHit。
