# BGE-Aligned Chunk Budget Intervention Contract（G2-DESIGN-19 / R1 / R2）

> 设计文档，只定义契约，不包含实现代码。
> R1 收口：拆分两种 tokenizer fingerprint、正式化 chunk budget
> policy 身份、单一模型实例绑定、monotonicity 正式决策流程、
> corpus-scoped fingerprint 的真实重算事实源。
> R2 收口：解决 `tokenizer_contract_fingerprint` 进入
> ExperimentConfig → experiment_id 的 bootstrap 生命周期，
> 引入 Preflight Runtime Contract Resolution。

## 1. 背景事实（已确认）

```text
当前正式 Chunk 预算计数器：TokenCounter → tiktoken cl100k_base
实际 Embedding 运行时：
  SentenceTransformer.max_seq_length = 512
  runtime tokenizer = BertTokenizer
  runtime tokenizer.model_max_length = 512
  num_special_tokens_to_add(pair=False) = 2（运行态实测）

would-truncate（Runtime 口径）：
  Recursive：57 / 215 = 26.51%
  Fixed：    71 / 237 = 29.96%
```

## 2. 三种预算的定义

```text
model_input_budget
  = SentenceTransformer.max_seq_length
  = 512
  = 包含 [CLS]/[SEP] 等 special tokens 后的最终输入上限

special_token_overhead
  = runtime tokenizer 对单文本实际增加的 special token 数
  = tokenizer.num_special_tokens_to_add(pair=False)
  = 2（当前运行态实测；实现时必须重新读取，不写死）

content_budget
  = model_input_budget - special_token_overhead
  = 512 - 2
  = 510
  = 正文（不含 special tokens）允许的最大 token 数

overlap_content_budget
  = chunk_overlap（正文 token 数）
  = 64（当前冻结值）
  = 不包含 [CLS]/[SEP]
```

约束：

```text
content_tokens(chunk) <= 510
model_input_tokens(chunk) = content_tokens + overhead <= 512
```

## 3. Chunk 与 Overlap 的不同计数语义

aligned counter 必须区分：

```text
count_content(text)
  = len(tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"])
  → 用于 chunk boundary 与 overlap 回退

count_model_input(text)
  = len(tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])
  = count_content(text) + special_token_overhead
  → 用于最终 chunk correctness 验证（<= 512）
```

规则：

- `chunk_size=512` 在 aligned 模式下的正式含义是 **model input
  budget**；Chunker 实际切分预算由 policy 推导为
  `content_budget = 512 - overhead`；
- `chunk_overlap=64` 表示最多 64 个**正文 token**，special tokens
  永不进入 overlap 预算；
- 切块/回退只用 `count_content`；最终每个 chunk 以
  `count_model_input(chunk) <= 512` 后置校验。

## 4. Chunk Budget Policy 与实验身份收口

### 4.1 Policy 字段（推荐）

不要只用一个模糊的 `chunk_budget_tokenizer`，因为 aligned 模式同时
改变 tokenizer、special-token accounting 与 chunk_size 的预算语义。
正式字段设计为：

```text
chunk_budget_policy: str
  = "cl100k_content_v1"
  = "embedding_runtime_model_input_v1"
```

语义：

```text
"cl100k_content_v1"
  tokenizer = tiktoken cl100k_base
  count(text) = cl100k token 数（现有 TokenCounter 行为）
  chunk_size = content budget（512）
  overlap = content token 预算（64）

"embedding_runtime_model_input_v1"
  tokenizer = 实际 BGEEmbedding 运行时 tokenizer
  count(text) = count_content（不含 special tokens）
  chunk_size = model input budget（512）
  content_budget = 512 - special_token_overhead（当前 510）
  overlap = content token 预算（64）
```

若实现仍保留 `chunk_budget_tokenizer` 字段，则必须同时正式绑定
`chunk_budget_semantics`，不得让 `chunk_size=512` 在两个实验中语义
不同却只靠一个 tokenizer 字段解释。推荐直接使用 policy。

### 4.2 身份字段

ExperimentConfig 至少能够唯一声明：

```text
chunk_budget_policy
embedding_model（BAAI/bge-small-zh-v1.5）
effective_embedding_max_seq_length（512）
tokenizer_contract_fingerprint（见第 5 节）
```

以上全部进入 `to_dict()` 与 experiment_id：

```text
policy / max / contract fingerprint 任一改变
→ experiment_id 必须改变
```

旧 cl100k Artifact 不补字段、不重写。

## 5. 两种 Tokenizer Fingerprint（R1 拆分）

DIAG-18 已真实证明：同 BertTokenizer、同 model_max_length=512，
normalizer 不同 → 实际 tokenization 不同。aligned Chunker 的边界由
tokenizer behavior 决定，因此行为契约必须进入正式实验身份，不能只进
Manifest。

### 5.1 tokenizer_contract_fingerprint（pre-run）

```text
用途：pre-run experiment identity
时机：正式切块前可计算
基础：实际 BGEEmbedding 将要使用的 runtime tokenizer
输入：固定、版本化 canonical probe suite
  probe 至少覆盖：中文、英文、大小写、中英混合、代码、数字、
  空格/换行、标点、特殊符号
计算：对 probe 的实际 tokenization output / input_ids
      做稳定 SHA-256
约束：不含路径、对象 repr、时间
```

示例：

```text
tokenizer_contract_probe_version = "v1"
tokenizer_contract_fingerprint = sha256(probe_v1 payloads)[:16]
```

必须满足：

```text
same class / same max
但 probe tokenization behavior 不同
→ contract fingerprint 不同
→ experiment_id 不同
```

probe suite 版本必须固定并进入 contract（或与 version 一起哈希）。

### 5.2 corpus_scoped_tokenizer_behavior_fingerprint（post-index）

```text
用途：post-index observed fact
时机：正式索引完成后
输入：当前冻结 Corpus + 当前实际产出的 Chunk +
      runtime tokenizer 的实际 tokenization output
存放：IndexManifest 顶层
计算：沿用 DIAG-18 算法（稳定键排序 + 流式 SHA-256）
```

它不取代 pre-run contract fingerprint。

### 5.3 二者区别

```text
contract fingerprint：
  实验开始前声明"我用的 tokenizer 行为契约是谁"
  → 进入 ExperimentConfig / experiment_id

corpus-scoped fingerprint：
  实验实际执行后证明"这批真实 chunk 被如何 tokenization"
  → 进入 IndexManifest 顶层
```

一个回答"身份"，一个回答"执行事实"，二者都需要。

## 6. Runtime Tokenizer 必须来自同一个 BGEEmbedding 实例

硬契约：

```text
EmbeddingRuntimeTokenCounter 不得：
  - 自己调用 AutoTokenizer.from_pretrained()
  - 自己 new SentenceTransformer()
  - 从第二个模型实例读取 tokenizer
```

必须使用：

```text
Pipeline.embedding
→ BGEEmbedding
→ 同一个实际 SentenceTransformer self._model
     ├─ tokenizer 给 Counter
     └─ encode() 给正式 Embedding
```

即：

```text
chunk budget 所使用的 tokenizer
===
未来实际 encode() 所使用模型实例的 tokenizer
```

设计建议 BGEEmbedding 增加窄接口：

```text
get_runtime_tokenizer()
get_runtime_contract()
```

接口内部可以 lazy-load 同一个 `self._model`，不引入第二个
tokenizer/model loader。Pipeline 当前已先初始化 embedding 再初始化
chunker，实现时利用这一顺序。

## 7. Prepare Runtime Binding

正式 prepare 必须验证：

```text
ExperimentConfig.chunk_budget_policy
ExperimentConfig.tokenizer_contract_fingerprint
ExperimentConfig.effective_embedding_max_seq_length
```

vs Pipeline 实际：

```text
Chunker counter policy
BGEEmbedding 实际 runtime tokenizer 的 contract fingerprint
SentenceTransformer.max_seq_length
```

任一不同：

```text
prepare fail-fast，不得入库
```

只比较 tokenizer class 名不够（DIAG-18 反例）。

## 8. Counter 方案（设计，不实现）

- 现有 `TokenCounter`（cl100k）默认行为不变；
- 新增 `EmbeddingRuntimeTokenCounter`，包装 BGEEmbedding 提供的
  同一 runtime tokenizer；
- 最小接口：`count(text)`（content）、`count_model_input(text)`、
  `name` / `policy`、`model_input_budget`、`special_token_overhead`、
  `content_budget`；
- 原始文本是事实源，Chunk 永远是原文精确子串，tokenizer 只做预算
  判断；禁止 decode token IDs 重造正文。

## 9. Monotonicity 正式决策流程（不再"三选一"）

### Step 1：Property Validation（必须先做）

在 runtime counter + 冻结 Corpus 所需 substring 搜索空间上验证：

```text
substring 扩展时 token count 是否满足二分所需单调性质
```

### Step 2：验证成立

允许：

```text
binary search
+ post-condition
```

### Step 3：发现任何反例

禁止 binary search，必须切换：

```text
safe boundary search
（例如线性/缓存计数等不依赖 monotonicity 的正确算法）
```

Corpus 只有 37 个文件，正确性优先于微小切块性能。

### Step 4：post-condition 只是额外防线

明确：

```text
count(end+1) > budget
```

在非单调函数下**不能证明 `end` 是全局最大合法 boundary**，因此
post-condition 不得单独作为非单调问题的解决方案；它只能在
monotonicity 成立（Step 2）或 safe search（Step 3）之上做最后防线。

## 10. Corpus-Scoped Fingerprint 的重算事实源

IndexManifest 不保存每个 Chunk 正文，因此**不能**从 Manifest 记录的
chunks 重算。正式设计指定：

```text
Index 完成
→ 从正式 experiment vector store 读取所有已入库 chunks
→ 用稳定键排序（优先正式 chunk_id）
→ runtime tokenizer → input_ids
→ corpus-scoped behavior fingerprint
```

并验证：

```text
实际读取 chunk count
== Manifest.vector_store_count
== Manifest.total_chunks
```

BM25 / Hybrid 同时继续满足 sparse integrity：

```text
sparse_index_count == vector_store_count == total_chunks
```

fingerprint 验证的是**真正进入正式 index 的 chunk**，而不是重新切一次
得到的理论副本。禁止绝对 vector-store 路径进入 fingerprint。

## 11. Manifest 字段设计

IndexManifest 后续新增（候选）：

```text
chunk_budget_policy
tokenizer_contract_fingerprint
effective_embedding_max_seq_length
special_token_overhead
content_budget
corpus_scoped_tokenizer_behavior_fingerprint
```

注意事实源唯一性：

- 若字段属于**声明配置**（policy / contract fingerprint / max /
  overhead / content_budget），只通过 `manifest.config` 记录，不建
  第二事实源；
- Manifest 顶层只增加**真正 post-index observed facts**：

```text
corpus_scoped_tokenizer_behavior_fingerprint
actual_content_token_max
actual_model_input_token_max
actual_would_truncate_count
```

必须继续保持：

```text
manifest.config == ExperimentConfig.to_dict()
```

## 12. 正式干预实验矩阵

下一阶段只做 **Recursive** 三套：

```text
Recursive + Dense  + embedding_runtime_model_input_v1
Recursive + BM25   + embedding_runtime_model_input_v1
Recursive + Hybrid + embedding_runtime_model_input_v1
```

对照：现有 cl100k Recursive 三套正式结果（dc220d794578 /
dbc497c796d5 / 3c613202e1ed）。

冻结：corpus_id=870e5864df67、evaluation_set_id=18c1c0470652、
chunk_size=512（model input budget 语义）、chunk_overlap=64、
top_k=5、dense_candidate_k=30、sparse_candidate_k=30、rrf_k=60、
rrf_tie_breaker=chunk_id_asc。

## 13. Intervention Success Contract（硬条件）

除原有数量完整性外，aligned 三个正式实验必须满足：

```text
actual_would_truncate_count == 0

actual_model_input_token_max
  <= ExperimentConfig.effective_embedding_max_seq_length
```

若出现 1 个超长：

```text
实验 intervention 未成功
不得继续把它当 tokenizer-aligned 正式结果解释
```

## 14. BM25 Control 与因果解释等级

BM25 control 设计保留：

```text
若 aligned BM25 也明显变化
→ 效果至少部分来自 chunk boundary / 统计单位改变

若 aligned BM25 几乎不变
→ 加强"Dense 侧改善与输入截断相关"的解释
```

即使：

```text
aligned Dense ↑
aligned Hybrid ↑
```

也不能直接证明：

```text
truncation alone caused improvement
```

因为 chunk boundaries / total_chunks / overlap landing 同时变化。
BM25 control 用来区分：

```text
general chunk-boundary effect
vs
Dense-input-specific effect
```

因果等级：

```text
Level A：intervention 成功（would-truncate=0，且
         actual_model_input_token_max <= max_seq_length）
Level B：检索指标变化（支持"aligned 改善当前 Retrieval"，
         不能单独归因于"仅仅因为没有 truncation"）
Level C：严格因果归因（需 BM25 control + Case-level +
         可选仅移除截断而不改变边界的 intervention）
```

## 15. 结果解释边界

```text
能说：
  - aligned 配置下 would-truncate = 0
  - aligned 配置下 Dense/BM25/Hybrid 正式指标与 cl100k 对照的 delta
  - Case-level rescue/regression

不能说：
  - "Dense 弱全部由 truncation 导致"
  - "aligned 提升完全来自消除截断"
```

## 16. 回滚 / 兼容旧 Baseline

- 旧 cl100k 是默认路径，不改 `TokenCounter` 默认行为与 Chunker 默认
  构造；
- aligned 只通过 `chunk_budget_policy` 显式开启，产生新
  experiment_id；
- 新实验使用独立 Workspace / run_id；
- 回滚 = 不使用新 policy；旧 Baseline Artifact 全部保持字节不变。

## 17. 交付物边界

本任务只交付设计。Counter / BGEEmbedding 窄接口 / Pipeline 接线 /
ExperimentConfig / IndexManifest / 正式实验与 59 号学习笔记均属于
后续独立任务。

---

# R2：Runtime Contract Preflight 与 Final Experiment Identity Bootstrap

## 18. 需要解决的循环依赖

`tokenizer_contract_fingerprint` 必须进入 `ExperimentConfig →
experiment_id`，但现有生命周期是：

```text
ExperimentConfig
→ experiment_id
→ ExperimentWorkspace
→ derived config.yaml
→ Pipeline
→ SentenceTransformer runtime
```

如果等到 Pipeline 创建后才第一次得到 fingerprint，就会出现
"experiment_id 依赖 runtime，runtime 又依赖 Workspace/experiment_id"
的循环。R2 引入 Preflight，把 runtime contract 解析提前到
experiment_id 之前。

## 19. 正式引入 Preflight Runtime Contract Resolution

```text
ExperimentSpec / ExperimentConfigDraft
        ↓
Runtime Contract Resolver（Preflight）
        ↓
Resolved ExperimentConfig（Final / frozen）
        ↓
experiment_id
        ↓
ExperimentWorkspace
        ↓
Pipeline
```

### 19.1 Unresolved / User-declared experiment inputs

用户声明阶段，**还没有正式 experiment_id**：

```text
embedding_provider
embedding_model
chunk_strategy
chunk_size
chunk_overlap
chunk_budget_policy
retriever_strategy
top_k
candidate_k
rrf_k / rrf_tie_breaker ...
```

### 19.2 Runtime-derived identity fields

当 `chunk_budget_policy = embedding_runtime_model_input_v1` 时，
Preflight 必须本地解析：

```text
effective_embedding_max_seq_length
special_token_overhead
tokenizer_contract_probe_version
tokenizer_contract_fingerprint
```

### 19.3 Final / Resolved ExperimentConfig

只有上述 runtime identity 解析完成后，才能构造正式（冻结）
`ExperimentConfig`，随后才允许访问 `experiment_id`。

## 20. 严格生命周期（写死顺序）

```text
1. 构造 ExperimentSpec / Draft
2. Runtime Contract Preflight
3. 构造 frozen Final ExperimentConfig
4. 计算 experiment_id
5. ExperimentWorkspace.prepare()
6. 生成 derived config.yaml
7. 创建正式 Pipeline
8. prepare runtime binding validation
9. index_corpus
10. retrieval / metrics / result
```

禁止：

```text
先创建 provisional workspace
→ 再补 fingerprint
→ 再改变 experiment_id
```

禁止 provisional experiment_id。正式 Workspace 路径从一开始就是：

```text
<workspace_root>/<final experiment_id>/<run_id>
```

## 21. Preflight 如何取得 Runtime Contract

Preflight 允许创建**只用于 identity resolution** 的本地
`BGEEmbedding / SentenceTransformer runtime contract instance`：

```text
local_files_only=True
不执行 encode()
不建 Vector Store
不建 Pipeline
不写 Workspace
不访问网络
```

它只读取：

```text
SentenceTransformer.max_seq_length
runtime tokenizer
num_special_tokens_to_add(pair=False)
canonical probe input_ids
```

计算：

```text
tokenizer_contract_fingerprint
```

## 22. Preflight 实例与正式 Pipeline 实例的关系

### 22.1 不要求 Python object identity 相同

Preflight SentenceTransformer 与正式 Pipeline SentenceTransformer
可以是两个独立对象；否则 experiment_id bootstrap 会被迫依赖
Workspace 后的 Pipeline，形成循环。

### 22.2 但要求 behavior contract 完全相同

正式 Pipeline 创建后，`ExperimentRunner._validate_pipeline()` 必须
重新从：

```text
Pipeline.embedding
→ 真正将用于 encode() 的 SentenceTransformer
```

计算：

```text
effective_embedding_max_seq_length
special_token_overhead
tokenizer_contract_probe_version
tokenizer_contract_fingerprint
```

并与 Final ExperimentConfig 完全比较；任一不同：

```text
prepare fail-fast
不得 index
```

因此：

```text
Preflight          = declared runtime identity
Pipeline validation = effective runtime identity
二者必须相等
```

## 23. Counter 的"同一实例"契约仍然保留

不要误解成 Counter 可以使用 Preflight tokenizer。正式：

```text
EmbeddingRuntimeTokenCounter
必须使用：
  正式 Pipeline.embedding
  → BGEEmbedding
  → 正式 SentenceTransformer self._model
  → runtime tokenizer
```

即 Counter 与真正 `encode()` 使用**同一个模型实例**。

禁止 Counter 使用 Preflight SentenceTransformer：

```text
Preflight ST
→ contract identity only

Formal Pipeline ST
├→ Counter tokenizer
└→ encode()
```

prepare 验证二者行为契约一致（第 22.2 节）。

## 24. cl100k 旧路径不需要 Runtime Preflight

```text
chunk_budget_policy = cl100k_content_v1
→ runtime-derived chunk-budget identity fields 使用
  明确 canonical sentinel / policy-defined fixed values
→ 不需要 tokenizer Runtime Preflight
```

例如固定记录：

```text
effective_embedding_max_seq_length = null（该 policy 不消费）
special_token_overhead = 0
tokenizer_contract_probe_version = null
tokenizer_contract_fingerprint = null / policy sentinel
```

重点：

```text
只有 embedding_runtime_model_input_v1 需要 BGE runtime preflight
```

不要给旧路径引入不必要的模型加载依赖。新字段加入 ExperimentConfig
后会自然产生新的 experiment_id；旧 Artifact 不补字段、不重写。

## 25. Single Source of Truth

canonical probe suite 的定义只能有一个事实源，禁止 CLI /
ExperimentRunner / BGEEmbedding 各写一套。设计指定共享模块，例如
概念上：

```text
core/embeddings/runtime_contract.py
```

提供：

```text
TOKENIZER_CONTRACT_PROBE_VERSION
TOKENIZER_CONTRACT_PROBES

compute_tokenizer_contract(runtime_tokenizer, model)
```

Preflight 与 formal Pipeline validation 调用同一实现，不复制
fingerprint 数学。

## 26. Runner / CLI API 责任边界

不要要求每个 CLI 调用者自己算 fingerprint。设计建议唯一高层解析
入口，例如概念上：

```text
ExperimentRunner.resolve_config(spec)
或
resolve_experiment_config(spec)
```

职责：

```text
user-declared spec
→ runtime preflight
→ Final ExperimentConfig
```

随后 `run_experiment()` 只接受 Final / Resolved ExperimentConfig。
如果命名需要适配当前架构可以调整，但必须只有一个正式 resolver。

## 27. Preflight 失败语义

以下任一 Preflight 失败：

```text
本地 BGE 模型不存在
SentenceTransformer 无法加载
runtime tokenizer 不存在
max_seq_length 非法
special_token_overhead 非法
probe fingerprint 无法计算
```

必须：

```text
在 ExperimentWorkspace 创建前失败
```

不得留下：

```text
experiment workspace
derived config.yaml
vector store
Manifest
```

## 28. prepare 二次验证不是重复浪费

```text
Preflight resolution
→ 用于决定 experiment identity

Formal Pipeline validation
→ 防止声明身份与实际执行行为漂移
```

即使看起来加载了两次 Runtime Contract，职责不同。这与
"declared config vs effective runtime behavior"是同一原则。

后续如需优化双模型加载成本，可以做共享缓存；本阶段 correctness
优先。

## 29. 最终正式流程（完整架构图）

```text
ExperimentSpec
      ↓
Runtime Contract Resolver（Preflight，只读 runtime contract）
      ↓
Final ExperimentConfig（frozen，含 policy / max / contract fingerprint）
      ↓
experiment_id
      ↓
ExperimentWorkspace
      ↓
derived config
      ↓
Formal Pipeline
      ↓
runtime contract re-validation（declared == effective，否则 fail-fast）
      ↓
EmbeddingRuntimeTokenCounter（同一正式模型实例）
      ↓
Chunking
      ↓
Index
      ↓
corpus-scoped tokenizer behavior fingerprint（从 vector store 重算）
      ↓
Manifest
      ↓
Retrieval
      ↓
Metrics
      ↓
Result
```

## 30. R2 完成条件回答

1. **fingerprint 在 experiment_id 之前如何获得**
   Runtime Contract Preflight 在构造 Final ExperimentConfig 之前，
   用本地只读的 SentenceTransformer contract instance
   （local_files_only、不 encode）读取 max_seq_length / tokenizer /
   special overhead / canonical probe input_ids，算出
   tokenizer_contract_fingerprint，再构造 frozen config 并计算
   experiment_id。
2. **为什么不会形成 Workspace/Pipeline 循环**
   runtime contract 在 Workspace 与 Pipeline 之前通过独立 Preflight
   解析；experiment_id 只依赖该 resolved contract，不依赖
   Workspace/Pipeline 的创建结果。
3. **Preflight 与 Formal Pipeline 是否要求同一 Python 对象**
   不要求。允许两个独立 SentenceTransformer 对象；要求 behavior
   contract（max / overhead / probe version / fingerprint）完全一致，
   由 _validate_pipeline 重算比对，fail-fast。
4. **为什么 Formal Counter 仍必须和 encode 使用同一模型实例**
   Counter 决定 chunk boundaries，encode 决定实际输入表示；两者若用
   不同 tokenizer 行为，切出的"合规 chunk"可能与真正进入模型的序列
   不一致。因此 Counter 必须取正式 Pipeline.embedding 的同一个
   self._model tokenizer；Preflight 实例只服务身份解析。
5. **谁是唯一 resolver**
   唯一高层入口（概念上 ExperimentRunner.resolve_config(spec) /
   resolve_experiment_config(spec)），负责 user-declared spec →
   preflight → Final ExperimentConfig；probe suite 与 fingerprint
   数学只存在于共享 runtime_contract 模块，禁止分叉实现。
6. **Preflight 失败为什么不会留下 Workspace**
   失败发生在生命周期第 2 步，Workspace 创建（第 5 步）之前；
   失败路径直接抛出，不创建任何 workspace / config.yaml / vector
   store / Manifest。
7. **cl100k 旧路径为什么不需要额外加载 BGE**
   cl100k_content_v1 的 runtime-derived identity 字段使用 canonical
   sentinel / policy 固定值，不消费 runtime contract；只有
   embedding_runtime_model_input_v1 需要 Preflight，因此旧路径不
   引入模型加载依赖。
