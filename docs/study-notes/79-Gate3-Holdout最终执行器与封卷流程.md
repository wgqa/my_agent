# 79-Gate3-Holdout最终执行器与封卷流程

> G3-HOLDOUT-09B-FINAL-EXECUTOR：把 preflight-only harness 补成真正可执行完整 Holdout E2E 的 runner。本任务只写执行器 + synthetic tests，仍然禁止访问真实 sealed。
> 日期：2026-08-14
> 本任务：0 real Planner / 0 real Generator / 0 real Judge / 0 real Retrieval / 0 real Embedding / 0 real Holdout / 0 sealed read。

---

## 0. 一句话

09A 造好了"门禁"（preflight + ledger），09B 把"执行器"写完——正式 Holdout 怎么跑、什么时候第一次能碰 sealed、正式 run ID 什么时候才产生、系统失败和基础设施失败怎么区分。全部用 synthetic fixture 验证，真实 sealed 一个字都没碰。

## 1. 正式执行顺序（写死，不能跳步）

```
1  tracked-clean
2  actual git HEAD
3  validate Freeze ID/config
4  check output 不存在
5  check ledger/lock
6  atomic_create_attempt(prepared)
-------------------------- sealed 边界 --------------------------
7  read + validate private manifest
8  hash Holdout JSONL
9  验 evaluation_set_id / case_count / SHA
10 Holdout JSON SHA 纳入最终正式 run identity
11 status → running
12 Generation 仅加载 case_id + query
13 Planner → Runtime → Retrieval → Generator
14 generation artifact 持久化
15 再读取 Gold 做 deterministic evaluation + Judge
16 写最终 artifacts
17 status → completed
```

第 6 步以前绝对不得打开 Holdout 或 private manifest——"先登记这一次，再开密封"，顺序本身是协议的一部分。

## 2. 正式 Holdout identity 为什么必须再加 holdout_jsonl_sha256

- 09A 的 preflight identity（`a1dc0a4bab03`）在 sealed 打开前就能算出来，但它**没有绑定 Holdout 数据本身**——万一 Holdout JSONL 被换了呢？
- 所以第 9-10 步先验证 sealed（manifest schema / eval_id / case_count / SHA / duplicate case_id），再把 `holdout_jsonl_sha256` 放进身份，算出**正式 run ID**。
- 面试说法："preflight ID 证明'配置和系统正确'；正式 run ID 证明'我跑的就是这份没见过的 Holdout 数据'。"

## 3. attempt 状态机与系统/基础设施失败

- prepared → running → completed 是正常路径。
- **系统行为性失败**（如某几个 generator 空输出）：这是模型的真实行为，仍以 **completed** 收尾，把失败 case 记入正式结果——绝不标成 infrastructure invalid。
- **基础设施故障**（manifest 损坏 / API 全挂 / 进程崩溃等导致无法形成有效实验）：才标 `invalid_infrastructure`，且**不得自动重跑**，必须 STOP → Reviewer audit。
- 关键：一旦任何 attempt 进入 terminal 状态（completed / invalid_infrastructure / failed_system），第二次执行直接被 ledger 拒绝。

## 4. sealed 边界是代码写死的，不是口头约定

- `execute_holdout` 用注入的 `sealed_read_fn`：测试注入 synthetic sealed，正式 09C 注入真实 sealed。
- 测试 `test_attempt_created_before_sealed_read` 断言"执行到 sealed 读取时 attempt 必须是 prepared"——如果顺序写错（先开 sealed 再登记），测试直接失败。
- 09B 全程不设置 `HOLDOUT_EXECUTION_AUTHORIZED`，CLI 的 `--execute` 永远不会在 09B 创建正式 attempt。

## 5. 面试如何讲这一层

把整条 Gate 3 封卷线讲清：
1. **数据**：Dev/Holdout 24/12 封存，Holdout 从未读取。
2. **系统冻结**：freeze_id 钉死代码+配置+数据+模型。
3. **执行协议**：09A 门禁（preflight + ledger + 无 override），09B 执行器（写死顺序 + sealed 边界 + formal identity）。
4. **一次性**：attempt ledger 确保只跑一次；系统失败≠基础设施失败；基础设施失败也不自动重跑，交 Reviewer。
5. **可审计**：formal run ID 绑定 freeze_id + 实际执行 commit + holdout JSONL SHA——拿到 ID 就能回答"哪份冻结系统 + 哪一版代码 + 哪一份数据 + 跑了几次"。

一句话总结："09A 锁住'怎么安全地只用一次'，09B 锁住'真正执行时每一步必须先做什么、什么时候才准碰密封、失败怎么归类'。"

---

## 09B-R1：把协议接到真实 frozen E2E pipeline（只差授权）

> G3-HOLDOUT-09B-R1-REAL-WIRING：09B 造好"执行顺序骨架"，R1 把真实 sealed reader、真实生成链、真实 evaluator 接到 `execute_holdout`，并修正式 provenance 绑定——**只差 Reviewer 09C 授权就能真正执行**。R1 阶段仍不访问 sealed、不调用任何 LLM。

### 1. 真实 sealed reader

- `read_real_sealed_inputs(config)`：只从 `config.private_manifest_path` / `config.holdout_jsonl_path` 读取 private manifest + Holdout JSONL；不 list sealed 目录、不猜文件名；文件缺失/损坏抛 `HoldoutInfrastructureFailure`。
- R1 **实现并单测，不调用**；09C 授权后 CLI 才注入。

### 2. 真实 Holdout Generation 链（复用现有生产能力，不复制算法）

- `run_holdout_generation(generation_cases, config, run_dir)`：签名只接收 `(case_id, query)` 的 `GenerationCase` 列表 / formal config / run_dir，**绝不接收 Holdout Gold**。
- 链路保持冻结生产链：Frozen Corpus → 冻结索引 manifest → `build_shared_index` → `OpenAICompatibleQueryPlanner` → Adaptive Runtime → Retrieval → RRF merge v2 → Verifier → `DeepSeekGenerator`（`E2EGroundedAnswerPort`）→ Citation。
- **阶段边界**：先落盘 `run_config.json` / `index_manifest.json` / `case_results.jsonl` / `cited_evidence.jsonl`，close/flush 后才返回，之后才允许 Evaluation 读 Gold——Gold isolation 是文件级边界，不是"Python 对象没传过去"。

### 3. Holdout-specific evaluator（不调 Dev-bound 的 run_e2e_evaluation）

- `run_holdout_evaluation(gen_output, config, run_dir, *, judge_client=None)`：复用公共计算能力 `AnswerJudge` / `should_call_judge` / `evaluate_citations` / `compute_deterministic_metrics` / `compute_answer_metrics`。
- Judge 配置从 freeze 的 `judge` 段构造（`types.SimpleNamespace`，不改变 `AnswerJudge` 契约）。
- 产出 4 个正式 Artifact：`answer_judgments.jsonl` / `metrics.json` / `comparison_report.md` / `result.json`；evaluation schema 仍 `gate3_e2e_metrics_v1`，**不改任何数学定义**。

### 4. 正式 provenance binding（fail-fast）

- attempt 创建前：re-validate `freeze_json_path`（freeze_id 重算 + 四个 frozen section 与 config 逐一相等）+ 要求 `config.actual_execution_source_commit == actual git HEAD`；**任一不一致 → 直接抛错，不创建 attempt**。
- sealed 打开后：验 manifest `gate3_dataset_freeze_id=257fa0d0a6d6` / `holdout_evaluation_set_id=79a6bc0814a3` / `case_count=12` / 实际 Holdout JSON SHA == manifest SHA。

### 5. formal identity 写进 ledger（prepared → bind → running → completed）

- `bind_attempt_formal_identity(...)`：sealed 校验成功、进入 running 前，把 `formal_holdout_run_id` + `holdout_jsonl_sha256` 原子绑定进当前 attempt；只在 `prepared` 可绑定，**绑定后不可修改、不可重绑**。

### 6. 真实异常归类（绝不写 `except Exception: invalid_infrastructure`）

| 情形 | 归类 |
|---|---|
| 单 case Planner/Generator 行为失败（如 generator 空输出） | case result，实验继续，最终 `completed` |
| Judge 输出 invalid | 指标 `invalid_judge`，不是 rerun 理由 |
| 文件损坏 / frozen corpus 缺失 / index 无法构建 / API 完全不可用（整场无法形成观测） | `invalid_infrastructure`（不自动重跑） |
| 未知异常 | fail-closed 原样上抛，保留 attempt，不自动重跑，交 Reviewer 判断 |

### 7. CLI real wiring

- `HOLDOUT_EXECUTION_AUTHORIZED=1` 下 `--execute` 现在真的注入 `read_real_sealed_inputs` / `run_holdout_generation` / `run_holdout_evaluation`（不再是 `None`）。R1 **不设置授权变量、不执行**。

### 8. 验证

- 新增 10 个 harness 测试（`TestRealWiring`）：全 fake integration（synthetic sealed → attempt prepared → validate sealed → formal ID → running → fake Planner/Index/Generator → 4 generation Artifact → fake Judge/evaluation → 4 evaluation Artifact → completed，8 个正式 Artifact 全部存在、身份一致、**无 Gold 泄漏到 generation Artifact**）、wrong actual HEAD → 不创建 attempt、wrong freeze → 不创建 attempt、private manifest 错 dataset freeze → `invalid_infrastructure`、ledger running entry 含 formal ID + Holdout SHA、formal identity 不可重绑、CLI 授权缺失 0 sealed read、CLI `--execute` 接真实 adapter。
- 全量 **1344 passed**（原 1334 + 10）。

---

## 09B-R2：把 final executor 绑定到公开冻结 dataset bytes

> G3-HOLDOUT-09B-R2-FINAL-INTEGRITY-MICRO：不再扩架构，只把 final executor 真正钉到**公开冻结**的 dataset bytes——expected 全部预先公开，禁止从 sealed 自己推导 expected。

### 1. 公开冻结常量（来源 `docs/experiments/gate3_data_freeze.json`，已核对一致）

```
gate3_dataset_freeze_id  = 257fa0d0a6d6
corpus_id                = 870e5864df67
corpus_file_count        = 37
holdout_evaluation_set_id= 79a6bc0814a3
holdout_case_count       = 12
holdout_jsonl_sha256     = 00bfcac2fe553f3e...  (Holdout raw bytes SHA)
private_manifest_sha256  = b34bb2d16d29dcd2... (private manifest raw bytes SHA)
```

`expected_*` 进入 `Gate3HoldoutConfig`（不进 run 身份），`build_holdout_config_from_freeze` 统一填充；`_verify_public_data_freeze(repo)` 在公开 freeze 文件存在时把常量与文件逐项交叉校验（fail-fast）。

### 2. attempt 前验证 frozen corpus identity（只算 corpus_id，不建索引）

`_validate_frozen_corpus_identity(config)`：读 frozen index manifest → relative_paths → `ExperimentCorpus.build(...)` → actual corpus_id / file count；必须匹配 870e5864df67 / 37，否则 **reject（attempt 不创建、sealed 未读取、LLM 0 次）**。不构建 embedding/index。

### 3. sealed 后验证真正 frozen bytes（不靠猜的 schema）

`read_real_sealed_inputs` 读取 raw bytes 后，先校验 `raw private_manifest SHA == b34bb2…`、`raw Holdout SHA == 00bfcac…`（expected 预先公开），再解析；`validate_sealed` 仍做结构校验（dataset freeze id / eval id / case count / duplicate case_id / manifest recorded Holdout SHA）。不为了确认一个无法从公开材料证明的 schema 字符串去提前读真实 sealed——**Exact raw SHA + 必需字段校验本身更强**。

### 4. Evaluation SHA guard + case ID 集合相等

`run_holdout_evaluation`：在 `Gate3EvaluationSet.load_jsonl(...)` 前验证 `当前 holdout 文件 SHA == config.holdout_jsonl_sha256 == 00bfcac…`（Generation 与 Evaluation 之间被改动 → fail-closed）；加载后要求 `set(case_results.case_id) == set(holdout_set.case_id)` **精确相等**（多一个或少一个都 fail）。

### 5. zero-obligation judgment 修正

固定逻辑（不再把 zero-obligation 写成 not_generated）：

```
if no obligations:            judge_status = not_required, reason = zero_obligation
elif completed + 非空 answer:  调 Judge
else:                         judge_status = not_generated
```

### 6. API Key 前置检查

真实路径（`run_generation_fn is run_holdout_generation`）在创建 attempt 前检查 `DEEPSEEK_API_KEY` **仅是否存在**；缺失 → **NO attempt / NO sealed**，禁止输出 key。

### 7. 验证

- 9 个新 harness 测试（`TestFinalIntegrity`）：holdout SHA ≠ 公开冻结 → reject；private manifest raw SHA ≠ 冻结 → reject；corpus 某文件改 1 byte → attempt 不创建；corpus 文件数不一致 → attempt 不创建；Holdout 在 Generation 与 Evaluation 之间被改 → eval fail-closed；case ID 集合不一致 → reject；zero obligation → not_required/zero_obligation；answerable 无 answer → not_generated；缺 API key → 0 attempt / 0 sealed。
- 全量 **1353 passed**（原 1344 + 9）。

---

## 边界声明

- 未读取/搜索 gate3/sealed；R2 只用 tmp_path / synthetic fixture / 公开 freeze JSON；`read_real_sealed_inputs` 已实现但从未被调用。
- 0 real Planner/Generator/Judge/Retriever/Embedding/Index/Holdout/sealed。
- 未运行 --execute；未设置 HOLDOUT_EXECUTION_AUTHORIZED；未创建正式 attempt ledger entry。
- Holdout execution 仍 BLOCKED；待 Reviewer 审计 09B-R2 后决定 09C。
