# Gate 6 Spring Petclinic Policy v1

## Scope

This is the policy v1 rerun of the fixed Spring Petclinic candidate cases. It preserves the v0 candidate questions and candidate Gold without modification.

- Repository: `https://github.com/spring-projects/spring-petclinic`
- Fixed commit and actual `git rev-parse HEAD`: `88e37c15cf6fc8490b01bc3e8e2c800cec1ac272`
- Baseline commit: `2f98513ff82bd47d512eb57f0fb0ffde45de6363`
- Engineering project identity: `spring-petclinic` (`configured`)
- Policy version: `tool_agent_decision_prompt_v3`
- Candidate source: `evaluation/gate6/spring_petclinic_cases_v0.jsonl`
- Policy v1 runs: `evaluation/gate6/spring_petclinic_policy_v1_results.jsonl`

Each v1 result is one separately invoked, immediately recorded `/tool-agent/query` run using the original question string from v0 and the configured DeepSeek provider. No question, candidate Gold, Tool budget, Tool implementation, Runtime, RAG pipeline, API, or UI changed between the policy edit and these recorded runs.

## Policy Change

The decision prompt and model-visible `code_search` / `knowledge_search` descriptions now state that current Engineering Project source, README, configuration, SQL, tests, call relationships, and behavior use `code_search` plus `read_project_context` rather than `knowledge_search`. They also require short literal search terms, context reads before inferring implementation behavior, avoidance of identical calls, and multiple context reads for multi-file questions within the existing budget.

## Before And After

| Metric | v0 baseline | policy v1 |
| --- | ---: | ---: |
| PASS | 0 | 5 |
| PARTIAL | 1 | 3 |
| FAIL | 7 | 0 |
| Cases calling `read_project_context` | 0/8 | 8/8 |
| Cases with Engineering Evidence | 0/8 | 8/8 |
| Evidence items | 0 | 11 |
| Evidence type distribution | none | 10 project_code, 1 project_doc |
| Wrong `knowledge_search` route | 2/8 | 0/8 |
| Duplicate stop | 1 | 0 |
| Budget stop | 1 | 0 |
| Average Tool calls | 1.5 | 3.0 |
| Average latency (ms) | 2440.1 | 5352.5 |

All v1 cases returned HTTP 200 with zero Tool execution errors. The increased latency follows the higher observed Tool-call count; no token or cost metric was added.

## Per-Case Results

| Case | v0 -> v1 | v1 Tool sequence | Context | Evidence | Calls | Latency ms |
| --- | --- | --- | --- | --- | ---: | ---: |
| SPC-01 | FAIL -> PASS | code_search -> code_search -> read_project_context | yes | 1 code | 3 | 3953.4 |
| SPC-02 | FAIL -> PASS | code_search -> code_search -> read_project_context -> read_project_context | yes | 2 code | 4 | 5570.7 |
| SPC-03 | FAIL -> PARTIAL | code_search -> read_project_context | yes | 1 doc | 2 | 4579.6 |
| SPC-04 | PARTIAL -> PARTIAL | code_search -> read_project_context -> code_search | yes | 1 code | 3 | 5434.3 |
| SPC-05 | FAIL -> PASS | code_search -> read_project_context | yes | 1 code | 2 | 6056.5 |
| SPC-06 | FAIL -> PASS | code_search -> read_project_context | yes | 1 code | 2 | 4556.2 |
| SPC-07 | FAIL -> PASS | code_search -> code_search -> read_project_context -> read_project_context | yes | 2 code | 4 | 6095.0 |
| SPC-08 | FAIL -> PARTIAL | code_search -> code_search -> read_project_context -> read_project_context | yes | 2 code | 4 | 6574.4 |

Manual verdicts compare each answer with the unchanged candidate Gold. Evidence coverage describes actual Engineering Evidence returned by the API, not inferred source coverage from search-match lines.

## Representative Cases

SPC-07 is the representative improvement. The v0 run refused after one search. Policy v1 read two VetController contexts and correctly explained both routes, their HTML versus response-body behavior, and their paged versus collection repository calls.

SPC-08 is the weakest v1 result. It no longer exhausted the budget and it returned two contexts, but it did not read `Visit.java` and therefore incorrectly said a new `Visit` has a null default date; the constructor actually initializes tomorrow.

## Remaining Partial Patterns

1. Configuration grounding is incomplete: SPC-03 read README but did not inspect the base and postgres properties, then added unsupported or inaccurate connection details.
2. Multi-file source coverage remains incomplete: SPC-04 through SPC-07 often answer from one inspected controller/configuration file while the candidate Gold also includes README, repository, schema, or test evidence.
3. Context selection can remain too narrow or repetitive: SPC-08 read two overlapping VisitController windows instead of the separate Visit and Owner sources needed for the complete flow.

These are observed results only. This report does not prescribe a next implementation.

## Validation

The v1 JSONL has eight unique case IDs. Each `question` must equal its v0 source record, and each candidate Gold reference must resolve to the same v0 case. Every evidence path is repo-relative and exists at the fixed external commit. The report metrics are derived from the v0 and v1 JSONL records.
