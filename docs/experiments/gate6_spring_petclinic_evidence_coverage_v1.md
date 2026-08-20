# Gate 6 Evidence Coverage Policy v1

## Scope

This comparison adds the general Evidence Coverage / Completion Policy to the model-visible Tool Decision Prompt. It does not change production code, the ToolAgentBudget, runtime loop, duplicate guard, search algorithm, project-context reader, knowledge backend, RAG, API, UI, frozen questions, or candidate Gold.

- Prompt version: `tool_agent_decision_prompt_v4`
- Fixed Tool budget: `max_agent_iterations=5`, `max_tool_calls=4`, `max_tool_errors=2`
- First repository: `evaluation/gate6/spring_petclinic_policy_v2_results.jsonl`
- Second repository: `evaluation/gate6/spring_petclinic_rest_policy_v2_results.jsonl`
- Frozen sources: `spring_petclinic_cases_v0.jsonl` and `spring_petclinic_rest_cases_v0.jsonl`

The second-repository artifact contains the raw results of the provider run recorded on 2026-08-21. Provider runs can vary in tool trajectory even with temperature zero; this report uses the persisted raw run rather than an earlier unpersisted summary.

## Policy

The prompt now requires the model to identify explicit information obligations, maintain an internal coverage checklist, and support each Engineering Project obligation with a relevant `read_project_context` Observation. Search matches are locator hints only. Before `final_answer`, uncovered obligations must trigger a targeted search/read when budget remains; otherwise the model must refuse rather than invent evidence.

Search and read are directed to alternate: a plausible search hit is followed by context reading, and subsequent searches target the current uncovered obligation. A single context may still justify a final answer when it covers all obligations; the policy does not require mechanically reading every Gold file. The model-visible Tool descriptions make the same contract explicit, and `knowledge_search` is explicitly excluded from current-project evidence.

## Results

### First Repository

| Metric | v3 baseline | v4 policy |
| --- | ---: | ---: |
| PASS / PARTIAL / FAIL | 5 / 3 / 0 | 4 / 4 / 0 |
| `read_project_context` coverage | 8/8 | 8/8 |
| Engineering Evidence coverage | 8/8 | 8/8 |
| Average Tool calls | 3.00 | 3.25 |
| Average latency (ms) | 5352.5 | 5811.4 |
| Budget stop | 0 | 0 |
| Wrong `knowledge_search` route | 0 | 0 |

This is a regression in result distribution: the policy did not improve the already-grounded first-repository run and one previous partial remained partial while another partial became partial. No budget or routing regression occurred.

### Second Repository

| Metric | v3 R2 baseline | v4 policy |
| --- | ---: | ---: |
| PASS / PARTIAL / FAIL | 2 / 2 / 2 | 2 / 1 / 3 |
| `read_project_context` coverage | 6/6 | 4/6 |
| Engineering Evidence coverage | 6/6 | 4/6 |
| Average Tool calls | 3.17 | 3.17 |
| Average latency (ms) | 4531.7 | 4348.1 |
| Budget stop | 2 | 2 |
| Duplicate stop | 0 | 1 |
| Wrong `knowledge_search` route | 0 | 0 |

The v4 run did not improve the fixed-budget stop count. SPCR-02 moved from FAIL to PARTIAL because it reached the controller context, while SPCR-01 and SPCR-06 still stopped at budget and SPCR-05 stopped on a duplicate search before any context read.

## Per-Case Coverage

| Case | Result | Tool sequence | Calls | Context | Evidence assessment | Main gap |
| --- | --- | --- | ---: | --- | --- | --- |
| SPCR-01 | FAIL | `code_search -> code_search -> code_search -> code_search` | 4 | no | none | route, empty response, and DTO mapping |
| SPCR-02 | PARTIAL | `code_search -> code_search -> code_search -> read_project_context` | 4 | yes | partial | mapper contract and service PetType resolution |
| SPCR-03 | PASS | `code_search -> read_project_context -> code_search -> read_project_context` | 4 | yes | partial | default property and disable-security context were not read |
| SPCR-04 | PASS | `code_search -> read_project_context` | 2 | yes | full | none |
| SPCR-05 | FAIL | `code_search` | 1 | no | none | test dates and validator branches |
| SPCR-06 | FAIL | `code_search -> code_search -> code_search -> read_project_context` | 4 | yes | none for asked flow | nested handler, persistence, and Location |

The `PASS` label for SPCR-03 is answer-level: the response stated the expected behavior. Its policy evidence assessment remains partial because the default-property and disable-configuration obligations were not grounded by a project-context read. SPCR-04 demonstrates the intended one-context completion case.

## Tests

- Related Tool Agent tests: `357 passed, 3 skipped, 4 warnings`
- Full suite: `1798 passed, 5 skipped, 5 warnings`
- Budget contract remains unchanged at `(5, 4, 2)`.
- Prompt contract tests verify explicit-obligation coverage, search/read alternation, targeted gap search, one-context completion, fixed budget, and absence of repository-specific names in the model-visible policy.

## Retention And Assessment

All prior Gate 6 artifacts remain preserved. No v4 success claim is made.

- Most visible improvement: SPCR-02 reached a grounded partial answer instead of the v3 budget-stop failure, but it still omitted mapper/service evidence.
- Worst remaining case: SPCR-01 used all four calls for search and never read project context.
- Evidence-sufficient-but-wrong cases: 0 identified in this comparison.
- Actual blocker: the fixed four-call budget is still consumed by search-first or duplicate-search behavior on multi-obligation questions; the policy text alone did not reliably force economical coverage.

## Retention Decision

- v4 双仓库结果发生回归。
- v4 rejected as default。
- Production Tool policy restored to v3。
- Experiment retained as negative evidence。
