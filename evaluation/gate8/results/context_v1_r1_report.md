# G8 Context v1 R1 Clean-Corpus Capability Check

- schema: `gate8_context_report_r1`
- endpoint: `http://127.0.0.1:8004/agent/query`
- formal request design: 6 Turn1 + 6 A no-history + 6 B with-history = 18 requests
- sealed holdout: untouched / not read

## Corpus Identity

- repository: `wgqa/agent_data`
- commit: `179f18e812ad63c36c5569de8e86c5ff9a931cb5`
- path: `agent_ai_v1/02_corpus_candidate`
- corpus_id: `870e5864df67`
- file_count: `37`
- commit verification: `git_head_and_locked_bytes`

## Clean-Index Proof

- isolated: `True`
- index_id: `gate8-clean-870e5864df67`
- vector_store_count: `215`
- document_count: `37`
- source_count: `37`
- contamination preflight: `passed`

## Cases and Turn1 Validity

| Case | Type | Turn1 | A | B | Comparison | Resolver used/fallback |
|---|---|---|---|---|---|---|
| `g8ctxr101` | `pronoun_reference` | `VALID` | `PASS` | `PASS` | `equal` | `True/False` |
| `g8ctxr102` | `plural_reference` | `VALID` | `FAIL` | `PASS` | `improved` | `True/False` |
| `g8ctxr103` | `previous_concept_reference` | `VALID` | `PASS` | `PASS` | `equal` | `True/False` |
| `g8ctxr104` | `previous_answer_reference` | `VALID` | `FAIL` | `FAIL` | `equal` | `True/False` |
| `g8ctxr105` | `short_elliptical_followup` | `VALID` | `FAIL` | `PASS` | `improved` | `True/False` |
| `g8ctxr106` | `topic_switch_control` | `VALID` | `PASS` | `PASS` | `equal` | `True/False` |

## A/B Metrics

- no-history: PASS `3` / PARTIAL `0` / FAIL `3`
- with-history: PASS `5` / PARTIAL `0` / FAIL `1`
- improved/equal/regressed: `2/4/0`
- resolver used: `6/6`
- resolver fallback: `0/6`
- average A/B latency: `5333.35 ms`
- average tool calls: `not exposed by Agent Runtime response; request count is 18`

## Topic Switch

`g8ctxr106`: A `PASS`, B `PASS`, safety `True`.

## Source Safety

- `ABSOLUTE_SOURCE_PATH_EXPOSED_BY_API = false`
- result serialization keeps corpus-relative source identities only; raw local paths are not retained

## Decision

`mixed`: clean-corpus R1 completed with six valid cases; this is the observed result of this fixed check.
