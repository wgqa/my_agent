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

## 边界声明

- 未读取/搜索 gate3/sealed；09B 只用 tmp_path / synthetic fixture / 公开 freeze JSON。
- 0 real Planner/Generator/Judge/Retriever/Embedding/Index/Holdout/sealed。
- 未运行 --execute；未创建正式 attempt ledger entry。
- Holdout execution 仍 BLOCKED；待 Reviewer 审计 09B 后决定 09C。
