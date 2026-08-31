# ARCH-EVAL-08A — V7 Architecture Integration Evaluation Protocol

This directory freezes the evaluation contract for the v7 architecture
integration. It is an evaluation-design package, not a benchmark result. The
package performs only deterministic input, identity, provenance, and
execution-precondition checks. It does not create an Agent, call a provider,
run A/B generation, open Holdout, or produce a product score.

## Frozen purpose and systems

The question is whether the cutover changes the integration behavior of one
Engineering Agent, not whether a new prompt or a new corpus is better.

| Item | System A | System B |
|---|---|---|
| Role | ToolAgent-only pre-architecture baseline | Unified Runtime v7 cutover baseline |
| Source commit | `0eef8ef9d6decdaa10efebe04087b06611654670` | `385b7795eafde7c114efc382e95c0d18ec273f54` |
| Reason | Last business-code baseline after `P1-OBS-03A-R1-MICRO` before ARCH-RUNTIME-02 | Cutover candidate after ARCH-CUTOVER-07 |
| Provider/model | `deepseek` / `deepseek-chat` | `deepseek` / `deepseek-chat` |
| Engineering prompt | `engineering_agent_decision_prompt_v2`, SHA recorded in manifest | Same frozen identity |
| Repair prompt | `engineering_action_repair_prompt_v1`, SHA recorded in manifest | Same frozen identity |
| Budget | 5 iterations / 4 tool calls / 2 tool errors | Same frozen 5/4/2 hard enforcement |

System A is never G12 `0a1f42e8ee0320486dbd0ddc01400e1e19150501`, System C,
or another historical Gate commit. G12 remains historical evidence only. A
does not acquire Planner, Adaptive Retrieval, or Unified Verifier behavior by
being evaluated against B; A is intentionally the last ToolAgent-only
business-code baseline.

System B records its actual component identities: G3 planner prompt and
payload, Adaptive Retrieval policy, top-k and planned-call limits, merge policy
and RRF k, Context Resolver, Requirement Router, and the
`EngineeringVerificationResult` contract identity. These values are checked
against the current source constants where available; the manifest must not
invent a version string for a class that has no such source constant.

## Target project and corpus identity

Both systems use the same read-only target project snapshot:

- project: `wgqa/my_agent` (`project_id = my_agent`);
- target project source commit:
  `385b7795eafde7c114efc382e95c0d18ec273f54`;
- checkout: independent, full-history, pinned to that SHA, `dirty = false`;
- binding: `ENGINEERING_PROJECT_ROOT`;
- public artifact: records project id, SHA, clean state, and binding source;
  never records the local checkout path.

Missing repository, dirty checkout, wrong SHA, failed Git inspection, or a
binding mismatch is a protocol/infrastructure violation. It invalidates the
run and cannot become a product negative. The offline validator exposes
`validate_target_project_checkout()` for this fail-closed precondition.

Both systems use the exact verified corpus identity from the public lock and
verified manifest:

```text
repository             = wgqa/agent_data
source_commit          = 179f18e812ad63c36c5569de8e86c5ff9a931cb5
path                   = agent_ai_v1/02_corpus_candidate
corpus_id              = 870e5864df67
file_count             = 37
chunk_count            = 215
retrieval_strategy     = bm25
manifest_experiment_id = dbc497c796d5
```

The A/B comparison cannot change project snapshot, corpus, corpus strategy,
question, Gold, environment, or output cap where the system contract permits
the cap. Retrieval backend calls are counted as retrieval calls, not LLM
calls.

## Dataset freeze

The dataset contains only new cases. No G12 final case id, question, normalized
question, or exact source-proof identity is permitted. Cases cannot simply
paraphrase G12. A deterministic validator checks duplicate IDs, exact and
normalized questions, exact proof identity collisions, Dev/Holdout overlap,
forbidden same change target commits, and duplicate context dependencies.

There are nine task families. Every family has two Dev cases and one
independent Holdout case:

| Family | Dev | Holdout | What it probes |
|---|---:|---:|---|
| `knowledge_only` | 2 | 1 | corpus-bound knowledge evidence |
| `repo_only` | 2 | 1 | current repository evidence |
| `theory_code` | 2 | 1 | knowledge plus implementation mapping |
| `context_followup` | 2 | 1 | bounded history and standalone intent |
| `change_test` | 2 | 1 | Git change evidence plus tests |
| `docs_code` | 2 | 1 | documentation and code consistency |
| `diagnosis` | 2 | 1 | cross-file failure/config diagnosis |
| `decomposed_knowledge` | 2 | 1 | non-trivial query decomposition and multi-query coverage |
| `insufficient_refusal` | 2 | 1 | correct refusal of unsupported claims |
| **Total** | **18** | **9** | **27** |

Dev and Holdout have distinct IDs and questions, no normalized duplicate, no
fully shared proof identity, and independent source proofs. Holdout cases
also carry an `independence_note` explaining why they are independent of Dev,
G11, and G12. Change/test Holdout uses a distinct historical target range;
context Holdout uses a distinct history/current-intent dependency;
decomposed Holdout has distinct facets rather than a trivial rename.

Each JSONL case follows `integration_v7_case_v1` and includes:

```text
schema_version, case_id, split, task_family, difficulty, question,
conversation_context, project_id, project_source_commit, gold_obligations,
source_proofs (including source_excerpt), knowledge_gold_sources, knowledge_probe_query,
required_evidence_groups, required_tools, forbidden_tools,
required_tools_by_system,
min_distinct_project_code_paths, expected_outcome, independence_note
```

Context cases additionally contain `current_question` and
`expected_standalone_intent`. They store bounded G8 history as strict
`user`/`assistant` role-content messages, at most six messages and at most the
G8 1200-token context budget. A receives only the current question and has no
G8 resolver. B is invoked through
`EngineeringAgentFacade.run(current_question, conversation_context=...)`.
The automatic context metric is `context_resolution_correct`.

Change/test cases additionally contain `base_ref`, `head_ref`, and
`accepted_test_paths`. All paths are safe repository-relative POSIX paths;
the public cases contain no absolute path, credential, raw provider response,
private reasoning, or full prompt.

## A/B run protocol

The run order is deterministic and recorded in the manifest:

```text
odd case:  A then B
even case: B then A
```

The same provider/model, target snapshot, corpus, environment, question, Gold
and applicable output cap are used for both systems. System B is not changed
after observing System A. Provider/infrastructure failures are classified
before any product comparison.

Infrastructure failures include provider outage or `APIConnectionError`,
port/process failure, wrong or dirty repository, corpus mismatch, missing
environment, and artifact write failure. They produce `INVALID` and no
product result. Product failures include planner error, retrieval error,
insufficient evidence, premature finalization, wrong refusal, and unsupported
claim. They remain normal negative results for the system under test.

## Automatic metric schema

Metric schema identity is `integration_v7_metrics_v1`. Numerators and
denominators are case-level unless a component metric explicitly says call,
obligation, or source. The frozen metrics are:

- `task_completion`;
- `required_evidence_coverage`;
- `tool_coverage`;
- `premature_finalization`;
- `refusal_correctness`;
- `context_resolution_correct`;
- knowledge source hit@5;
- retrieval call count;
- subquery coverage;
- hybrid rescue attempted and hybrid rescue used;
- merged evidence count;
- tool calls;
- LLM calls split into context resolver, planner, ToolAgent decision,
  repair, and total;
- end-to-end latency plus context, planner, retrieval, ToolAgent, verifier,
  and finalization component timings;
- token cost with source identity; `UNAVAILABLE` when provider usage is not
  available.

Retrieval backend calls do not inflate LLM-call metrics. Component timing and
cost are diagnostic facts and do not change task outcome. Observability is not
a second control state.

The operational definitions are frozen as follows: `task_completion` is a
case-level comparison of `expected_outcome` with the runtime/business
terminal state (`completed`, `refused`, or `failed`); Gold semantic obligations
do not enter this automatic metric. `required_evidence_coverage` is
`satisfied required groups / total required groups` per case, with groups
evaluated as AND-of-OR; the schema has no obligation-to-group mapping.
`tool_coverage` is system-contract-local: `required_tools_by_system` counts
only that system's dynamic ToolAgent obligations, so B's planned knowledge
retrieval is not penalized for not calling `knowledge_search`.
`premature_finalization` is true when finalization occurs while required
evidence or typed requirement state is unmet. `refusal_correctness` compares
`expected_outcome` with the terminal answer/refusal state; refusal-reason
quality remains in the manual rubric. `context_resolution_correct` compares
the resolved standalone intent with the case oracle; System A is recorded as
having no context resolver because it receives the current question only.
`knowledge_source_hit_at_5` checks whether a Gold knowledge
source is present in the top five returned sources. `retrieval_call_count`,
`subquery_coverage`, `hybrid_rescue_attempted`, `hybrid_rescue_used`, and
`merged_evidence_count` are taken from the retrieval component trace, before
they are confused with ToolAgent or LLM counts. `tool_calls` counts executed
allowlisted Tool calls; the five LLM counters count provider calls by stage;
`latency_*` is elapsed component time; and `token_cost` is computed only from
provider usage with its provider/model identity, otherwise it is
`UNAVAILABLE`.

## Manual rubric

Manual scoring is per case and frozen separately from automatic metrics:

| Dimension | Allowed values |
|---|---|
| Task Success | `PASS` / `FAIL` |
| Evidence Correctness | `PASS` / `PARTIAL` / `FAIL` |
| Grounding | `PASS` / `PARTIAL` / `FAIL` |
| Answer Obligation | `O1`, `O2` boolean plus aggregate |
| Unsupported Claim | `NONE` / `PRESENT` |
| Citation Validity | `VALID` / `INVALID` / `NOT_PRESENT` / `NOT_APPLICABLE` |

Citation validity means that a citation identifier resolves to an allowed
evidence item. It is not semantic entailment: a valid `[C1]` does not imply
`Grounding = PASS`. The protocol does not claim complete factual verification
or semantic correctness.

## Contamination and Holdout safety

Dev may be used to diagnose bugs and validate metric implementation. The
Holdout candidate SHA must be frozen before the first Holdout open or run.
After that freeze, no result-driven production, Prompt, Router, Guard, budget,
Gold, or easy-case modification is allowed. The R1 locator repair and R2
semantic-provenance closure happened before any Holdout execution, so their
Holdout Gold/source-proof changes are protocol repairs, not result-driven
contamination. If a result-driven modification
occurs after the candidate freeze, the Holdout is no longer independent and
must not be reported as a clean comparison.

The files may live in the repository, but the runner default is Dev. Holdout
is deny-by-default. It requires both `--split holdout` and an exact
`--confirm-frozen-candidate <SHA>` matching the manifest's Holdout dataset
SHA. `ARCH-EVAL-08A` only freezes this contract; it performs no Holdout run,
no real Provider call, no manual scoring, and no result artifact.

## Protocol and artifact integrity

`protocol_manifest_v1.json` records the protocol SHA, both dataset SHA-256
values, exact counts and family matrix, System A/B identities, target project
commit, corpus identity, prompt/planner/policy/toolset/budget identities,
metric schema identity, manual rubric identity, failure classification,
contamination policy, Gold proof audit identity, and Holdout protection. R1
explicitly distinguishes
System A's base/effective dynamic registry from System B's base registry,
effective Engineering dynamic registry, and planned knowledge backend. B's
dynamic registry excludes `knowledge_search`; planned retrieval supplies
knowledge evidence instead.

Dataset SHA-256 is over canonical JSON objects in JSONL order, with stable
UTF-8 JSON serialization. The protocol SHA is over the canonical manifest
after removing only its `protocol_sha256` field. Validators fail closed on
dataset mutation or SHA mismatch. A future result artifact must include
protocol and system identity, target binding, corpus identity, case result,
automatic metrics, manual rubric result, and failure classification; it must
exclude absolute paths, API keys, raw provider/model output, private
reasoning, and full prompts.

R2 supersedes the R1 protocol SHA
`534c0a69c817125c23cf2b1d75d60df1c3cd65dacf13844ee4b654206e313d31`, while R1
superseded the R0 protocol SHA
`e440ed8c32b366e99980b3b3fbd01f4325978547b929fbd6e94adec48b791f42`. R0 and
R1 were never used for a product run or result. Each proof now carries a
short exact `source_excerpt`; project code/doc uses target
`385b7795eafde7c114efc382e95c0d18ec273f54`, project changes must be members of
the declared historical diff and use head-side changed text, project tests
must be readable at `head_ref` and listed in `accepted_test_paths`, and
knowledge uses the verified corpus commit
`179f18e812ad63c36c5569de8e86c5ff9a931cb5`. The offline validators enforce
these locator contracts and the `gold_proof_audit_v1.jsonl` identity; semantic
entailment is recorded by review, not auto-inferred from a class/type name.

The Gold audit has one record per case/obligation/proof and is prepared with
`review_decision = ACCEPT`, but this is not an Agent self-acceptance. The
architecture/evaluation status remains `ARCH-EVAL-08A-R2-MICRO = CURRENT /
REVIEW PENDING` until an independent audit makes the final ACCEPT decision.

The automatic metric boundary is explicit: `task_completion` reads only the
runtime/business terminal state; Task Success and Answer Obligation remain
manual semantic dimensions. `required_evidence_coverage` is
`satisfied_required_groups / total_required_groups` per case and does not
invent an obligation-to-group mapping. `premature_finalization` reads typed
requirement/evidence state at finalization, while `refusal_correctness`
compares `expected_outcome` with the terminal answer/refusal state; refusal
reason quality remains manual.

## Current versus target architecture

The evaluation is intended to make the integration drift observable. At the
architecture-freeze starting point, the capability islands were real but the
Engineering main-chain control was ToolAgent-only:

```text
CURRENT / pre-integration boundary

Engineering request
        |
        v
ToolAgentRuntime  ---> Decision -> Tool -> Observation -> Finalize
        |
        +--> Knowledge / Repo / Git / Test tools (evidence islands)

G3 Planner / QueryPlan / decomposition / adaptive retrieval / multi-query /
MinimalEvidenceVerifier       [implemented historically, not in this chain]
G8 Context / Standalone Resolver[implemented historically, not in this chain]
G11 Unified Evidence + G12 Requirement/Guard                 [ACTIVE inputs]
```

The final v7 control plane has one Engineering Agent and one trusted control
state. Knowledge RAG, Repository, Git, and Test are Evidence Backends, not
independent Agents:

```text
TARGET / Unified Engineering Agent Runtime

Request
  -> Context Resolver
  -> Evidence Planner
  -> Execution Policy (single logical Budget Owner)
  -> Tool Execution Engine
       -> Evidence Backends: Knowledge RAG / Repo / Git / Test
  -> Evidence Aggregator
  -> Evidence Verifier
  -> Finalization Policy (one completion decision)
  -> Activity / Observability (projection only)
```

`ToolAgentRuntime` may continue to enforce 5/4/2 during migration, but it is
only the Tool Execution Engine component. It is not a second Agent/controller.
There is no nested autonomous controller and no third product Runtime.

## Files and safe invocation boundary

- `integration_dev_v1.jsonl`: 18 frozen Dev cases;
- `integration_holdout_v1.jsonl`: 9 frozen Holdout cases;
- `protocol_manifest_v1.json`: identity, hashes, metrics, rubric, and safety;
- `gold_proof_audit_v1.jsonl`: obligation-level Gold provenance review records;
- `case_contract.py`: offline case/identity/hash/checkout validator;
- `tests/test_integration_v7_protocol.py`: deterministic contract tests.

Importing the package and running its validators is offline. No command in
ARCH-EVAL-08A is authorized to start a later evaluation stage, alter production
Runtime/Prompt/Router/Guard/budget, rerun Formal, or create Persistence or
Citation UI.
