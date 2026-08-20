# Gate 6 Spring Petclinic REST Generalization Check

## Scope

This is a no-code-change generalization check of `tool_agent_decision_prompt_v3` on a second, independent Java/Spring repository. It does not modify the Agent, Prompt, Tool descriptions, budget, Runtime, RAG, or search algorithm.

- Repository: `https://github.com/spring-petclinic/spring-petclinic-rest`
- Fixed commit and actual `git rev-parse HEAD`: `698bd832eac0da48e72deb63ce7ab275d98a88fb`
- Agent commit: `68d9bc19b0e999bb645bfea3f2ed7266d1d549f8`
- Engineering project identity: `spring-petclinic-rest` (`configured`)
- Policy version: `tool_agent_decision_prompt_v3`
- Candidate cases and run records: `evaluation/gate6/spring_petclinic_rest_cases_v0.jsonl`

The external checkout is under `benchmark_work` and is not part of this repository or this commit.

## Candidate Cases

| Case | Type |
| --- | --- |
| SPCR-01 | REST endpoint to implementation flow |
| SPCR-02 | DTO/domain/mapper flow |
| SPCR-03 | Configuration effect |
| SPCR-04 | Persistence/repository |
| SPCR-05 | Test to implementation |
| SPCR-06 | Cross-file nested-resource flow |

Each question and candidate Gold were constructed from the fixed external commit before the formal run. Candidate Gold remains non-frozen and non-sealed.

## Formal Run And Blocker

Each case was submitted exactly once to `/tool-agent/query` with the original question text. All six requests received HTTP 200 but ended on decision iteration 1 with `status=failed` and `failure_code=ACTION_PROVIDER_ERROR`. The first request took 483.9 ms and the five following failures took 17.2-62.6 ms. None selected or executed a Tool.

The local API started successfully, and `GET /project` returned `{"project_name":"spring-petclinic-rest","source":"configured"}`. The local server log recorded six successful HTTP request lifecycles, but did not expose an upstream provider detail beyond the runtime's safe `ACTION_PROVIDER_ERROR` code. No case was retried and no Prompt, Tool, model configuration, or source code was changed to work around the failure.

## Observed Metrics

| Metric | Result |
| --- | ---: |
| PASS / PARTIAL / FAIL | 0 / 0 / 6 |
| `read_project_context` coverage | 0/6 |
| Engineering Evidence coverage | 0/6 |
| Evidence items | 0 |
| Wrong `knowledge_search` route | 0/6 (no Tool routing occurred) |
| Duplicate stop | 0 |
| Budget stop | 0 |
| Average Tool calls | 0.0 |
| Average latency | 107.3 ms (half-up, one decimal) |

## Diagnosis

Only one actual failure pattern is available to report: the decision provider failed before any Tool decision on every case. This prevents a valid ranking of three repository-level failure patterns.

1. **Provider availability:** all six cases stopped with `ACTION_PROVIDER_ERROR` at decision iteration 1.
2. **Tool-policy behavior unobserved:** no case selected `code_search`, `read_project_context`, or `knowledge_search`, so routing and grounded search behavior cannot be assessed.
3. **No search, multi-file, budget, or synthesis signal:** zero Tool calls and zero Evidence mean literal-search coverage, multi-file coverage, budget behavior, and answer synthesis are all unmeasured rather than negative findings.

This differs from the first Spring Petclinic policy v1 run, which completed all eight cases and observed `read_project_context` in 8/8 cases, Evidence in 8/8 cases, and no incorrect `knowledge_search` routing. The current failure is upstream of Tool policy and does not establish either success or failure of cross-repository generalization.

## Validation

The JSONL contains six unique, nonblank case IDs and questions. All candidate Gold paths and ranges are repository-relative and exist in the fixed external checkout. The report metrics are derived from the six JSONL records.
