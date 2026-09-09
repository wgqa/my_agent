# PRODUCT-ACCEPT-25 — Fresh Set B

## Identity

- Product commit / actual runtime `HEAD`: `542418395b8d337401e1b745f25c82dbe1213018`
- Fresh repository: `langchain-ai/chat-langchain` at pinned source commit `2656b028b44e6a39096aed782f0ed3ae7cd72478`
- Provider/model: DeepSeek `deepseek-chat`
- Decision profile: `engineering_agent_decision_prompt_unified_kind_aware_grounded_v1`
- Corpus: `179f18e812ad63c36c5569de8e86c5ff9a931cb5` / `870e5864df67`
- Budget: 5 iterations / 4 tool calls / 2 tool errors; deadline 60 seconds
- Questions were frozen before the first formal run. System A and Holdout were not run; retry count was zero.

## Execution

Seven scenarios produced ten formal turns: **10 observed, 10 valid, 0 infrastructure-invalid**. At scenario level: **2 PASS, 1 PARTIAL, 4 FAIL, 0 INFRA**. The separate invalid-provider smoke returned a typed safe failure (`ACTION_PROVIDER_ERROR`) and did not use the formal scenario store.

Bounded execution totals across the ten turns were 15 decision LLM calls, 1,470 output tokens, 74,041 input tokens, 40,279 ms elapsed, and 4 tool calls. Token fields are execution measurements, not price claims.

The frozen Integration-v7 automatic metric contract was **not applied** to Fresh Set B: these scenarios have a new acceptance contract and no frozen Integration-v7 Gold mapping. Therefore no `task_completion`, `required_evidence_coverage`, `tool_coverage`, `premature_finalization`, `refusal_correctness`, `latency`, or `knowledge_source_hit_at_5` score was inferred or reported as a benchmark score. The raw bounded execution fields remain in `runs/safe_results.jsonl`.

The only formal repository acquisition success was S05 (change + test): `changed_files → git_diff → find_tests → read_project_context`, yielding `project_change` and `project_test` evidence. S01, S02, S03, S04, and the S07 multi-turn investigation did not acquire project evidence. S06 was a justified safe refusal.

## Product-path checks

| Path | Result | Evidence |
|---|---|---|
| UI → Conversation → SSE → Runtime → answer | PASS as a product path | Answers, status, evidence summary and runtime trace were visible in Streamlit |
| Conversation create/reload | PASS | Seven conversations persisted in the isolated acceptance store |
| API restart persistence | PASS | Seven conversations remained after restart |
| Multi-turn history | PASS mechanically / FAIL semantically | S07 retained four turns but did not acquire repo evidence |
| Evidence card | PASS for S05 | `CHANGE 1`, `TEST 1`, E6/E7 visible |
| Execution metrics | PASS for S05 | 5 iterations, 4 tools, 0 tool errors visible |
| Citation | PARTIAL | S05 citations were supported; knowledge-only repo claims were unsupported/incomplete |
| Evidence acquisition | FAIL | Repeated evidence-free repository behavior across independent scenario families |
| Refusal | PASS for secret request; over-refusal elsewhere | S06 `UNSAFE_REQUEST`; answerable repo questions stopped early |
| Provider-failure safety | PASS | Separate invalid configuration produced safe typed failure, without secret/raw response/stack |

## Automatic and manual interpretation

The product mechanics are operational, but this acceptance is not a release acceptance: repository implementation, theory↔code, cross-file, and multi-turn investigation scenarios repeatedly produced no project evidence. This is a general evidence-free repository-answer blocker, not an infrastructure failure. The S05 result shows the change/test path can acquire repository evidence, so the finding is specifically not a blanket repository checkout failure.

No Product code, Router, Prompt, Runtime, Tool schema, frozen Integration-v7 data, or historical result directory was modified. The full bounded records are in `runs/safe_results.jsonl`, `manual_review.json`, and `ui_observations/ui_observations.json`.

## Final verdict

**RELEASE BLOCKED**

Reason: a general repository-evidence acquisition blocker reproduced across at least two independent scenario families (repository implementation, theory↔code, cross-file, and multi-turn). This result is valid for governance; it does not automatically open a repair task.

**NEXT: STOP FOR GOVERNANCE**
