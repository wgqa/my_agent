# SSE 整理后的系统验证（2026-10-02）

结论：本轮验证没有发现 SSE 共享 worker 整理引入的回归。DeepSeek 实际调用、源码取证、知识问答、两版 SSE、知识问答多轮会话及持久化均可运行；Engineering 主链的纯计算任务存在可复现的误拒答，尚未修复。

## 验证环境与范围

- Python 3.14.0；仓库基线 `538196995a2bd7e4db141be8d2f0c06d441213a6` 加本地 SSE 整理。
- 真实 provider 使用当前装配的 DeepSeek / `deepseek-chat`；未启用 Jev。
- Knowledge 身份校验通过：`870e5864df67`、37 files、215 chunks、BM25。
- 检查初始发现本地缺少 `ENGINEERING_KNOWLEDGE_CORPUS_ROOT`；已在 Git 忽略的本地 `.env` 中补齐已核验的语料路径，保留原凭据。清空进程内该变量后，正常 `.env` 自动加载仍能使 Engineering ready / verified；未为此调用模型。
- 真实 query / message 检查使用独立的会话数据库及向量库，没有改写用户已有会话或冻结评测结果。

## 离线与启动检查

| 检查 | 结果 |
|---|---|
| `tests/test_engineering_stream.py`、`tests/test_engineering_stream_v2.py`、`tests/test_product_engineering_24b.py` | 27 passed |
| `.github/workflows/ci.yml` 的 29 文件离线回归集合 | 670 passed / 5 skipped |
| `python scripts/smoke_local_app.py` | `FULL_APP_SMOKE_OK`；真实 FastAPI / Streamlit health 200，页面连接正常 |
| 本地配置自动加载 | `/health`、`/capabilities`、`/project`、`/engineering/knowledge` 均为 200；Engineering ready / verified |

专项覆盖取消转发、worker 异常、安全答案输出及 worker 真正结束后的并发槽释放。两组离线测试有重叠，不将通过数直接相加；没有重跑全量历史测试或正式 benchmark。

## 真实 DeepSeek 检查

| 场景 | 结果 |
|---|---|
| SSE v1：查看新共享文件的 `run_worker`，说明取消信号传递 | completed；3 次源码工具调用，答案引用真实源码证据 |
| SSE v2：解释 BM25 机制与适用问题 | completed；答案含合法知识库引用，活动流正常 |
| 普通 Engineering 接口：`37 * 29` | calculator 执行成功，最终 refused；诊断重现相同行为 |
| 计算会话：`128 * 64`，再将结果除以 16 | 两轮均 refused；四条消息原子保存，不能据此声称计算多轮任务成功 |
| Legacy `/tool-agent/query`：`37 * 29` 对照 | completed，返回正确的 `1073` |
| 知识会话：BM25 适用问题，再追问“它和稠密向量检索有什么不同” | 两轮 completed；追问正确解析为 BM25 与稠密检索的对比；保存四条消息，重建 API lifespan 后完整恢复 |

共 9 个真实 query / message 请求（含一次诊断复现），均返回 HTTP 200，没有 provider failure / timeout 或 SSE error。completed 的流式答案可完整拼回最终 answer；refused 流未泄露被拦截的答案。这里的请求数不是模型调用数，一个请求可包含 Planner、Context Resolver 及多轮 Decision。

## 纯计算误拒答的定位

独立诊断只包装 `BoundEngineeringEvidenceVerifier.verify` 记录判定元数据，原调用参数和返回值保持不变。`37 * 29` 的被拦截候选答案为正确数值；记录如下：

```json
{
  "numeric_candidate_is_1073": true,
  "retrieval_can_generate": true,
  "requirement_satisfied": true,
  "binding_required": true,
  "binding_status": "MISSING",
  "insufficiency_reasons": ["ANSWER_EVIDENCE_REFERENCE_MISSING"],
  "can_finalize": false
}
```

`UnifiedEngineeringRuntime` 先执行知识检索并注入知识证据；`_evaluate_answer_evidence_binding` 只要发现任何 evidence 就要求 `[E#]`。纯数值答案没有知识库引用，因而被硬停止为 `INSUFFICIENT_EVIDENCE_TO_FINALIZE`。Calculator 没有执行错误；普通同步接口也会复现，该路径不经过本次 SSE 共享 worker。

该问题登记到 TD-PLAN-01 / TD-VERIFY-02。下一步应明确纯工具任务的检索与证据需求，避免为正确计算结果强加无关知识引用，同时保留仓库和知识问答的引用校验。

本记录是有限范围的系统 smoke 和故障诊断，不替代 claim-level grounding 评审，也不修改历史 Set A / Set B 的质量结论。
