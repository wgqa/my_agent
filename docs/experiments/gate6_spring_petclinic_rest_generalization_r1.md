# Gate 6 Spring Petclinic REST Generalization R1

## Scope

R1 is a provider diagnosis and gated rerun attempt for the same six cross-repository candidate cases. No Agent, Prompt, Tool description, budget, Runtime, RAG, API, UI, or search implementation changed.

- Repository: `https://github.com/spring-petclinic/spring-petclinic-rest`
- Fixed commit and actual `git rev-parse HEAD`: `698bd832eac0da48e72deb63ce7ab275d98a88fb`
- Agent commit at diagnosis: `2fe2e490d6cc684d2087621297fb256b6df26b5d`
- Engineering project identity used by R0: `spring-petclinic-rest` (`configured`)
- Policy version: `tool_agent_decision_prompt_v3`
- Candidate source: `evaluation/gate6/spring_petclinic_rest_cases_v0.jsonl`
- R1 audit records: `evaluation/gate6/spring_petclinic_rest_policy_v1_r1_results.jsonl`

## R0 Classification

R0 remains preserved in `evaluation/gate6/spring_petclinic_rest_cases_v0.jsonl` and `docs/experiments/gate6_spring_petclinic_rest_generalization.md`. Its six HTTP 200 requests all failed at Decision iteration 1 with `ACTION_PROVIDER_ERROR`, before any Tool call. R0 is therefore **BLOCKED / INVALID CAPABILITY RUN**, not a valid cross-repository policy result.

## Provider Probe

One minimal direct OpenAI-compatible JSON-mode probe used the same provider, base URL configuration, model, timeout, retry setting, and credential environment as the Tool Decision Provider:

| Field | Result |
| --- | --- |
| Provider / model | `deepseek` / `deepseek-chat` |
| Credential present | yes |
| Request phase | SDK request dispatch was initiated; no HTTP response was received |
| Exception class | `APIConnectionError` |
| HTTP status | none |
| Provider error type / code | none safely supplied by the SDK |
| Classification | `APIConnectionError` |

The probe does not print or store the API key, authorization data, request/response headers, response body, or provider exception message.

## Canary Gate

The calculator Tool Decision canary was **not run**. The R1 gate requires a successful provider probe first; its failure means a canary would only add another failed provider request and cannot validate a structured action.

## R1 Result

**BLOCKED / INVALID RUN.** The six formal R1 cases were not started. Their questions and candidate-Gold references are copied unchanged into the R1 audit JSONL and marked `formal_run_status=NOT_STARTED`; this records exactly which fixed cases were gated without presenting them as Tool-Agent results.

| Metric | R1 result |
| --- | --- |
| Formal case requests | 0/6 |
| PASS / PARTIAL / FAIL | not applicable |
| `read_project_context` coverage | not measured |
| Engineering Evidence coverage | not measured |
| Wrong `knowledge_search` route | not measured |
| Duplicate stop / budget stop | not measured |
| Average Tool calls / latency | not measured |

No capability failure patterns can be inferred: there was no Tool Decision, literal search, context read, Evidence, budget use, or answer synthesis. The sole observed blocker is upstream provider connectivity before Decision completion.

## Validation

The R1 audit JSONL has six unique case IDs. Every question and candidate-Gold case reference equals the preserved R0 candidate source. The fixed external checkout remains at the stated commit and is clean. No production file was modified.
