# Planner 不检索字段组合对齐（2026-10-03）

## 保留结论

保留 Engineering 主链的 `engineering_planner_contract_prompt_v2`。它明确现有 QueryPlan 的跨字段约束，消除“不需要知识检索却因非法字段组合回退、注入知识并最终缺引用拒答”的已复现链路。没有增加计算关键词放行、答案后处理或新的任务分类器。

八题旧/新各一次，**16 个真实用户请求 / 53 次实际 provider 调用**。两道计算、通用 README/API 用途对比及新增排序题：旧 **0/4 完成 → 新 4/4 完成**，旧四题均 `PLAN_INVALID_SCHEMA → single_retrieval fallback → ANSWER_EVIDENCE_REFERENCE_MISSING`，新四题均合法 `no_retrieval`、零知识检索、最终绑定 `NOT_REQUIRED`。两道计算实际调用原 calculator，返回精确数值 `1073` / `294`；排序保留重复值，返回 `2, 2, 5, 8`。

相关 15 模块局部 **377 passed / 3 warnings**，其中包含新增 22 项。首次三模块验证 **205 passed / 2 warnings** 已包含在 377 中，不累加。未运行全量 pytest、完整 CI、Holdout、部署或推送。代码结构重构与长期 Task / Evidence / Execution v2 契约继续暂缓。

## 根因和修复边界

旧 Planner 提示词让模型分别填写 `query_type` 和 `action`，同时建议确定性计算不检索，却未说明 `no_retrieval` 必须配 `query_type=unanswerable_or_no_retrieval`。已复现模型输出 `fact` 或 `comparison` + `retrieval_required=false` + `action=no_retrieval` + `NO_RETRIEVAL_NEEDED`；严格解析正确拒绝了这些组合，系统按保守策略检索知识，随后答案没有引用这些无关材料而被 Guard 拦截。

修复只使模型输出规则与既有契约一致：

1. `no_retrieval` 使用完整字段组合，`subqueries=[]`；它表示无需知识检索，可以回答，也可以调用 calculator 等其他工具。
2. 单次与分解检索分别写明布尔值、子问题数量/ID/required 和 reason_code 约束；模型仍不能主动输出系统 fallback。
3. 用户明确要求知识库/特定材料或查证时仍需检索；仓库文档/源码证据由独立 requirement 管理，Planner 不能取消它。

生产改动为 [`prompt.py`](../../core/query_planning/prompt.py)、[`openai_compatible.py`](../../core/query_planning/openai_compatible.py)、[`api/app.py`](../../api/app.py)。Provider 接受系统选择的两个固定提示词版本，发送消息和调用元数据使用同一身份；Engineering 启动显式选择新版本。旧 Gate 3 默认仍为 v1，原全文与身份保持可用：

- v1：`gate3_planner_prompt_v1`，SHA `5b209054f5274fa8f1f88975625c80b78d7e9e2a84569179288fed0c3a3b5c95`。
- Engineering：`engineering_planner_contract_prompt_v2`，SHA `3278c2450d6a59aa44c1a0aa5b4af311c66a42d4103a5ba50c67649f0a39a56c`。

QueryPlan/schema、严格 parser、保守 fallback、Router v3、Verifier、Runtime 控制循环、Reader v2、默认搜索 v5、主 Decision Prompt 和 toolset 都保持原样。没有恢复动态 knowledge_search、追加循环或扩容；仍是 **5 次逻辑决策 / 4 次工具调用 / 2 次工具错误**。Planner 的单次模型调用仍单独统计。

## 配对诊断

输入使用当前工作树，包括此前保留的文档域与公共正文修复；HEAD 单独不足以恢复该基线。运行前冻结案例、旧/新生产快照、18 个保护文件和历史归档 SHA。两臂使用同一当前实现，只切换 Engineering Planner 提示词；交替请求顺序、无付费重试。源码绑定干净的 Requests `b25c87d7cb8d6a18a37fa12442b5f883f9e41741`；知识为原 corpus `870e5864df67`，37 文件 / 215 chunk。

| 案例 | 旧 → 新 | 内容审查 |
|---|---|---|
| C02 中文计算 | 拒答 → 完成 | 实际 calculator，精确数值 1073，不注入知识 |
| C03 英文计算 | 拒答 → 完成 | 实际 calculator，精确数值 294，不注入知识 |
| K01 通用文档用途对比 | 拒答 → 完成 | 说明通用用途，不主张当前仓库事实；无仓库或知识检索 |
| N01 新增排序 | 拒答 → 完成 | 保留重复 2，输出 2,2,5,8；同类字段冲突被消除 |
| D01 仓库安装文档 | 完成 → 完成 | 两臂均真实读 README 并引用，Python 3.9+ / pip 命令正确；搜索参数和读取窗口不同 |
| R02 环境设置方法 | 完成 → 完成 | 同一两步工具链、定义 750–779；新版新增错误优先级概括和窗口外调用说明，按内容 **PASS → PARTIAL** |
| D03 限定缺失文档 | 拒答 → 拒答 | 指定标记搜索无命中，无替代文件；未直接探测存在性，不能把搜索无命中称为文件不存在的证明 |
| C01 引用知识对比 | 失败 → 完成 | 两臂均进行知识分解检索；新版真实引用仍缺少核心机制支持，内容 **FAIL → PARTIAL** |

| 描述性指标 | baseline | candidate |
|---|---:|---:|
| completed / refused / failed | 2 / 5 / 1 | 7 / 1 / 0 |
| Planner schema fallback | 4 | 0 |
| 实际 provider 调用（含 Planner、Decision、repair） | 27 | 26 |
| input / output tokens | 111135 / 2743 | 95590 / 2439 |
| Tool calls / tool errors | 9 / 0 | 9 / 0 |
| SSE v2 请求 | 4 | 4 |
| 所问行为及整份答案：PASS / PARTIAL / FAIL | 3 / 0 / 5 | 6 / 2 / 0 |

16 次 HTTP/响应 schema 与预算检查通过，含 8 次 SSE v2；SSE v1 仅在局部离线回归中覆盖。一次配对不能用于宣称长期成功率、成本或延迟改善。

## 保留的负结果与限制

R02 新答案末尾把优先级概括为“调用方 > Session > 环境”，与环境先写入请求参数、再合并 Session 的实际顺序不符；并把未读取的 579 行调用归入 send 流程，实际调用在 request。两臂 Planner shape、检索身份、工具参数与范围相同，只有一对样本，不能建立该语义回归与新提示词的因果关系，也不能宣称零质量回归。

C01 baseline 在 Decision 输出上出现 `ACTION_SCHEMA_INVALID`，一次 repair 后仍 `ACTION_PARSE_FAILED`；`initial_finish_reason=stop`，没有捕获原始输出，无法证明具体格式错误或将其归为截断。candidate 进行真实知识检索并通过引用结构绑定，但引用片段是选型问题、面试自检或落地清单，没有支持全部稀疏/倒排/稠密/语义匹配机制。对冻结计划和同一 corpus 的离线 seed 重建确认了此缺口，**零额外 provider 调用**。不把 C01 的解析失败消失计作本修复的确定效果。

评审由同一实施助手完成，案例包含已知开发失败；不是独立验收或 Holdout。本轮关闭的是已复现的四类合法不检索计划的错误回退，TD-PLAN-01 的 Planner mandatory 策略、TD-VERIFY-02 的更广任务适用性、语义支持与源码调查完整性仍开放。

## 验证和复跑

新增 `tests/test_engineering_planner_alignment.py` 的 22 项覆盖实际消息/元数据身份、旧默认身份、非法 profile 拒绝、真实 calculator → Unified Runtime、通用直接问答，以及非法计划/超时保守 fallback、仓库/理论缺证据与伪造引用不能放行、生产 lifespan 选择。新测试夹具初次用错动作构造并缺少 call_metadata，修正夹具后通过；失败日志原样保留，没有放宽生产规则。

CI 和运行手册逐项一致，共 37 模块；本轮只跑相关 15 模块。18 个保护文件、上两次实验归档的 56 个文件 SHA 全部不变。详细原始记录、逐题审查、快照和检查脚本见 [实验归档](../../evaluation/no_retrieval_alignment_20261003/README.md)。

```bash
python -m evaluation.no_retrieval_alignment_20261003.analyze
```

此命令不调用模型，不改旧结果；原配对命令另见归档 README，显式 `--live` 会付费，输出目录必须新建。之后继续开发导致保护文件变动时，历史检查应报告版本不匹配，不能改写冻结 manifest 掩盖差异。
