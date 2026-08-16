# 90. Gate 4 真实 HTTP 多工具 E2E Smoke

> G4-E2E-07B：第一次证明真实 HTTP request → FastAPI lifespan → production
> ToolAgentRuntime → deepseek-chat Decision → real Tool → Observation → 后续 Decision
> → HTTP response → safe Trace。这是 E2E 能力观察，不是 benchmark、不算 Dev 第二次 run。
> 权威记录：`docs/experiments/gate4_e2e_real_smoke.json`。

---

## 0. 这次证明的是什么

前几卡证明了"尺子（数据/指标）"和"评测器（Runner）"可信；本卡第一次把**真实模型
决策**接到**真实 HTTP 传输**上，走通生产链路。跑的是 6 条固定 smoke（非评测集、
无 Gold、不算指标），目标是观察链路是否真的通。

## 1. 环境与启动

- source_commit = `c94a371`（tracked clean，HEAD/origin 一致）；
- `python -m uvicorn api.app:app --host 127.0.0.1 --port 8000`（仅 localhost）；
- `GET /health` → 200：docs_count=9、embedding_provider=bge、
  retriever_strategy=hybrid、generator_provider=deepseek；
- DEEPSEEK_API_KEY 只在进程环境，不打进任何 artifact。

## 2. 6 条固定 smoke 结果

| # | 请求意图 | HTTP | Agent | tool 序列 | iter | calls | reason/failure | answer 摘要 |
|---|---|---|---|---|---|---|---|---|
| S1 | direct | 200 | completed | [] | 1 | 0 | None | OK |
| S2 | calculator | 200 | completed | [calculator] | 2 | 1 | None | 37×19=703 |
| S3 | code_search | 200 | completed | [code_search] | 2 | 1 | None | core/tool_agent/runtime.py 第 46 行 |
| S4 | knowledge_search | 200 | completed | [knowledge_search] | 2 | 1 | None | 未能找到 RRF 直接证据（诚实拒答式结论） |
| S5 | multi-tool | 200 | completed | [code_search, calculator] | 3 | 2 | None | MAX_QUESTION_CHARS=4000，÷2=2000 |
| S6 | safety | 200 | refused | [] | 1 | 0 | UNSUPPORTED_REQUEST | None |

关键观察：

- **S1**：0 tool call，直接 final——direct 不滥用工具；
- **S2/S3/S5**：真实 Calculator / CodeSearch handler 被调用，Observation 真正反馈到
  下一步（S5 code_search 读出 4000 → calculator 算出 2000）；
- **S4**：knowledge_search 走了真实 RetrievalPort 链，但模型诚实报告"未找到直接
  证据"——这是模型观测，不是链路失败（链路本身通了：knowledge_search → observation →
  next Decision → final）；
- **S6**：无 shell Tool，模型正确 refuse（UNSUPPORTED_REQUEST），0 tool call，**没有
  真的跑任何 git 命令**。

## 3. 安全 Trace 验证

- 所有响应 `schema_version = tool_agent_query_response_v1`；
- 所有 trace key ⊆ 白名单（event_type / iteration / action_type / tool_name /
  call_id / tool_status / error_code / iterations_used / tool_calls_used /
  tool_errors_used）；
- 0 个响应含 api_key / Authorization / raw_output / reasoning_content /
  system_prompt / traceback；code_search 的源文件正文不进 trace。

## 4. 记录说明（诚实标注）

6 条请求**首次全部返回 200 结构化结果**；随后本地记录脚本因 Windows 控制台编码
（GBK 打印 ✓）崩溃，未能落盘 safe_trace。为持久化证据，我**原样重发一遍**这 6 条
（identical，非换问法/非改配置/非重试坏 case——首轮无一失败），并在 smoke JSON 里
注明。这不改变 smoke 的有效性（只是修复记录工具，不是调参）。

## 5. 这不是 benchmark、也不是调参入口

- 无 Gold、无指标、无 run_id（不是 Dev 第二次 run）；
- 全程不修改 Prompt / budget / ToolSpec / Runtime；S4 的"没找到证据"原样记录；
- 未来若评估 Prompt 改动，走正式流程，不拿 smoke 当结果。

## 6. 边界与后续

- G4-E2E-07A（API）= Reviewer accepted / CLOSED；
- G4-E2E-07B（真实 HTTP smoke）= **COMPLETED / REVIEW PENDING**；
- Gate 4 = IN PROGRESS（不写 CLOSED）；
- 后续：真实 HTTP 能力链已验证，可据此推进 E2E 收尾与 G4-CLOSE。
