# G8 Context v1 Capability Check

> **INVALID EVALUATION RUN**
>
> Reasons: `CONTAMINATED_VECTOR_STORE`, `TURN1_VALIDITY_NOT_ENFORCED`.
> Original results are retained for audit only and are not valid Context capability metrics.

- schema: `gate8_context_report_v1`
- endpoint: `http://127.0.0.1:8001/agent/query`
- dataset: `conversation_context_cases_v1.jsonl` (6 public-knowledge cases)
- holdout access: none

## Primary Comparison

| Case | No History | With History | Result |
|---|---:|---:|---|
| `g8ctx001` | FAIL | FAIL | equal |
| `g8ctx002` | FAIL | FAIL | equal |
| `g8ctx003` | PASS | PASS | equal |
| `g8ctx004` | FAIL | PASS | improved |
| `g8ctx005` | FAIL | PASS | improved |
| `g8ctx006` | PASS | PASS | equal |

No-history: PASS `2` / PARTIAL `0` / FAIL `4`
With-history: PASS `4` / PARTIAL `0` / FAIL `2`

- resolver used: `6/6`
- resolver fallback: `0/6`
- context truncated: `0/6`
- with history > no history: `2`
- with history = no history: `4`
- with history < no history: `0`

## Topic Switch

`g8ctx006`: no-history `PASS`, with-history `PASS`, safety `True`.

## Failure Modes

- `g8ctx001` and `g8ctx002`: with-history planning reached decomposed retrieval but refused after incomplete required-subquery evidence.
- `g8ctx004` and `g8ctx005`: history changed an elliptical/answer-reference follow-up from direct no-retrieval failure to grounded answer.

## Decision

`negative`: context improved `2/5` dependent cases; this is not a majority, so Context v1 is not validated as a general capability by this check.
