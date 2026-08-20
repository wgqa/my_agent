# Gate 6 Spring Petclinic Baseline

## Scope

This is a first real-repository baseline for the existing Engineering Tool Agent. It is not a benchmark freeze, Holdout, prompt change, Tool change, or production-code change.

- Repository: `https://github.com/spring-projects/spring-petclinic`
- Requested commit: `88e37c15cf6fc8490b01bc3e8e2c800cec1ac272`
- Actual `git rev-parse HEAD`: `88e37c15cf6fc8490b01bc3e8e2c800cec1ac272`
- External checkout: `benchmark_work/gate6/spring-petclinic` under the designated benchmark root, outside this repository and not committed here
- Engineering project identity: `spring-petclinic` (`configured`)
- Agent version: current `main` at the time of the run, with the existing code_search, read_project_context, knowledge_search, calculator, and Engineering Evidence capabilities

The candidate cases and candidate Gold are in `evaluation/gate6/spring_petclinic_cases_v0.jsonl`. Candidate Gold is reviewable input for a later audit; it is not frozen or sealed.

## Method

Each final question was sent once to the existing `/tool-agent/query` API with `ENGINEERING_PROJECT_ROOT` bound to the fixed external checkout. The actual configured DeepSeek provider was used. No question was rewritten after a result, no result was selected from repeated runs, and no prompt, Tool, Runtime, retrieval algorithm, or production source changed for this baseline.

`status=completed` only means the runtime reached a final answer. PASS, PARTIAL, and FAIL below are the manual comparison against candidate Gold. Evidence coverage is based only on the API's structured Engineering Evidence output.

## Results

| Case | Type | Runtime status | Tool sequence | Calls | Latency ms | Verdict | Evidence |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| SPC-01 | code location | completed | code_search | 1 | 2696.2 | FAIL | none |
| SPC-02 | call and data flow | refused: INSUFFICIENT_INFORMATION | code_search | 1 | 1589.0 | FAIL | none |
| SPC-03 | configuration effect | completed | knowledge_search | 1 | 2134.9 | FAIL | none |
| SPC-04 | documentation to code | completed | code_search -> code_search | 2 | 3679.0 | PARTIAL | none |
| SPC-05 | database and persistence | refused: INSUFFICIENT_INFORMATION | knowledge_search | 1 | 1462.0 | FAIL | none |
| SPC-06 | test to implementation | refused: AGENT_DUPLICATE_TOOL_CALL | code_search | 1 | 1801.7 | FAIL | none |
| SPC-07 | cross file | refused: INSUFFICIENT_INFORMATION | code_search | 1 | 1560.4 | FAIL | none |
| SPC-08 | hard multi-file flow | refused: AGENT_BUDGET_EXCEEDED | code_search -> code_search -> code_search -> code_search | 4 | 4597.9 | FAIL | none |

Totals: PASS 0, PARTIAL 1, FAIL 7. All eight formal runs returned HTTP 200. No run reported a Tool execution error. No run called `read_project_context`, so all eight API responses had `evidence: []`.

## Manual Assessment

- SPC-01 failed because it reported that the root MVC handler could not be found, despite the candidate Gold root mapping and view return.
- SPC-02 failed because it refused after one code search and did not explain surname normalization or repository flow.
- SPC-03 failed because it used `knowledge_search` and reported no matching knowledge instead of reading the configured project's README and properties.
- SPC-04 is partial: it correctly named `CacheConfiguration`, `@EnableCaching`, the `vets` cache, and `VetRepository`, but incorrectly named `findById` instead of the paged `findAll(Pageable)` overload and did not join the README evidence.
- SPC-05 failed because it routed to `knowledge_search` and did not compare the H2 and PostgreSQL constraints or describe the form error mapping.
- SPC-06 failed because its second Tool action was an exact duplicate; the runtime stopped before it read the test or the handler.
- SPC-07 failed because it refused after one code search and did not connect the HTML and response-body endpoints to their repository calls.
- SPC-08 failed because it exhausted all four Tool calls on code searches and never read project context or returned an answer.

## Top Failure Patterns

1. No project-context reads: `read_project_context` was called zero times across eight runs. Consequently there was no structured Engineering Evidence, even where `code_search` found enough surface information to support a follow-up read.
2. Knowledge search was not project-grounded for this external repository: SPC-03 and SPC-05 selected `knowledge_search` and returned no usable Spring Petclinic context instead of inspecting the configured checkout.
3. Repeated literal searching consumed the bounded budget: SPC-06 hit `AGENT_DUPLICATE_TOOL_CALL`, and SPC-08 used all four calls on `code_search` before `AGENT_BUDGET_EXCEEDED`.

## Observed Capability Gap

The clearest current gap is reliable conversion of natural engineering questions into inspected, project-grounded code or document context. This baseline records the gap only; it does not select or implement a remedy.

The closest result was SPC-04, which correctly found several cache facts but remained partial and unsupported by structured evidence. SPC-08 is the representative failure: it required a multi-file explanation, spent its full budget on literal searches, and produced neither context nor answer.

## Validation

The JSONL must parse as eight records with unique case IDs. Each candidate Gold path is repo-relative and was checked against the fixed external checkout at the recorded commit. The report table, manual assessment, and JSONL use the same run status, tool sequence, counts, latency, and verdicts.
