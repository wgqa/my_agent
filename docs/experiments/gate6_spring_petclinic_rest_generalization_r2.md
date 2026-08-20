# Gate 6 Spring Petclinic REST Generalization R2

## Scope

R2 is the completed gated rerun for the frozen six Spring Petclinic REST candidate cases. No code, Prompt, Tool, budget, provider configuration, Runtime, RAG, API, UI, or search implementation changed.

- Repository: `https://github.com/spring-petclinic/spring-petclinic-rest`
- Fixed commit and actual `git rev-parse HEAD`: `698bd832eac0da48e72deb63ce7ab275d98a88fb`
- Agent commit used for the run: `bdf0bfd2f7a59da9a0072ed60734d182a9d745ad`
- Engineering project identity: `spring-petclinic-rest` (`configured`)
- Policy version: `tool_agent_decision_prompt_v3`
- Frozen candidate source: `evaluation/gate6/spring_petclinic_rest_cases_v0.jsonl`
- R2 results: `evaluation/gate6/spring_petclinic_rest_policy_v1_r2_results.jsonl`

R0 and R1 are preserved and not modified. The provider probe succeeded, the calculator canary returned `84`, and each frozen case was invoked exactly once on isolated API port `8011`.

## Results

| Metric | R2 result |
| --- | ---: |
| Formal case requests | 6/6 |
| PASS / PARTIAL / FAIL | 2 / 2 / 2 |
| `read_project_context` coverage | 6/6 |
| Engineering Evidence coverage | 6/6 |
| Evidence type distribution | 5 project_code, 1 project_doc |
| `knowledge_search` used | 0/6 |
| Tool execution errors | 0 |
| Duplicate stop | 0 |
| Budget stop | 2 |
| Total Tool calls | 19 |
| Average Tool calls | 3.17 |
| Average latency (ms) | 4531.7 |

## Per-Case Results

| Case | Result | Tool sequence | Evidence | Calls | Latency ms |
| --- | --- | --- | --- | ---: | ---: |
| SPCR-01 | FAIL | code_search -> code_search -> code_search -> read_project_context -> budget stop | 1 code | 4 | 5304.1 |
| SPCR-02 | FAIL | code_search -> code_search -> code_search -> read_project_context -> budget stop | 1 code | 4 | 4526.1 |
| SPCR-03 | PARTIAL | code_search -> read_project_context | 1 doc | 2 | 4353.4 |
| SPCR-04 | PASS | code_search -> read_project_context | 1 code | 2 | 3824.5 |
| SPCR-05 | PARTIAL | code_search -> code_search -> read_project_context | 1 code | 3 | 4213.9 |
| SPCR-06 | PASS | code_search -> code_search -> code_search -> read_project_context | 1 code | 4 | 4968.2 |

## Observed Patterns

1. The fixed budget stopped SPCR-01 and SPCR-02 after four Tool calls, before a final answer could be produced. Both runs did read project context, but search routing did not reach the required controller and mapper/service evidence in time.
2. Context grounding was consistent across all six cases, but one context read was still insufficient for questions that explicitly join documentation, configuration, security code, or tests. SPCR-03 answered from README evidence without inspecting the filter chain and JDBC queries; SPCR-05 read the validator but missed the unit test.
3. The strongest results were the repository query and nested visit-flow cases. SPCR-04 and SPCR-06 matched the candidate Gold from project-code evidence despite using only one context read.

These are observed R2 results only. This report does not prescribe a next implementation or change any frozen artifact.

## Validation

The R2 JSONL has six unique case IDs. Each question and candidate-Gold reference equals the frozen source. All six responses returned HTTP 200, with zero Tool execution errors. The external checkout remained clean at the fixed commit. No production file was modified.
