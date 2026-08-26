# G12 System C Typed Requirement and Finalization Guard Design

## 1. Status and scope

This is the G12-04B design freeze. It defines the implementation contract for
System C; it does not implement the requirement router, an
`EngineeringEvidenceRequirement` production class, or a Finalization Guard.
System C Formal remains `NOT RUN`.

The product baseline is
`0a1f42e8ee0320486dbd0ddc01400e1e19150501`. The current Engineering Prompt,
Runtime, Tool implementations, API, Knowledge backend, provider, benchmark,
and evaluator artifacts remain frozen. This design does not modify
`engineering_agent_decision_prompt_v2`, its SHA
`14a1cbbe3dec951b7723bf5a7578e5f1aabc96639ac62b984976cecb5f53a107`,
`engineering_action_repair_prompt_v1`, provider/model `deepseek` /
`deepseek-chat`, the Engineering output cap `1200`, the `5 / 4 / 2` budgets,
or the seven-Tool registry.

The only future System C intervention is a generic typed Evidence Requirement
plus a system-level Finalization Guard. There is no Prompt-only tuning in
System C. The frozen dataset is `gate12-v1-630fc8b527c2`, and its evaluator
Gold remains outside the product requirement path.

## 2. Ownership and execution boundary

The proposed production flow is:

```text
user question
    -> Engineering Requirement Router
    -> immutable Evidence Requirement
    -> ToolAgentRuntime
    -> Decision / Tool loop
    -> FinalAnswerAction
    -> Finalization Guard
    -> completed or bounded recovery/refusal
```

The `EngineeringAgentFacade` owns generic requirement routing. The
`ToolAgentRuntime` owns requirement enforcement and is the sole owner of the
finalization gate. The model does not choose, weaken, or replace the
requirement. The Guard does not generate an answer, run a Tool, or act as a
second Agent.

There must be no second Agent loop, Critic Agent, Verifier LLM, multi-agent
layer, or evaluator-side post-processing that changes the Runtime result.
Legacy `/query`, `/agent/query`, and `/tool-agent/query` behavior remains
unchanged. A request with `evidence_requirement=None` follows the existing
termination behavior, preserving legacy and Baseline A compatibility.

## 3. Immutable typed requirement

The future system-side value is an immutable, typed requirement. Its minimum
contract contains `requirement_profile`, `required_evidence_groups`,
`min_distinct_project_code_paths`, and `router_version`.

`requires_cross_file` may be retained as an internal requirement attribute or
derived from the selected profile. `task_family` may be retained only as an
internal diagnostic label; it is never model-visible and is not an
authoritative evaluator input.

The requirement is created once before the Tool loop and passed to the Runtime
read-only. Finalization code must not accept a model-provided replacement, a
weaker copy, or a late evaluator annotation.

### 3.1 Frozen profile shapes

The following generic profiles are frozen for the future implementation:

| Profile | Required evidence groups | Minimum distinct code paths |
|---|---|---:|
| `THEORY_CODE_V1` | `[["knowledge"], ["project_code", "project_doc"]]` | 1 |
| `CHANGE_TEST_V1` | `[["project_change"], ["project_test"]]` | 0 |
| `DIAGNOSIS_SINGLE_V1` | `[["project_code"]]` | 1 |
| `DIAGNOSIS_CROSS_FILE_V1` | `[["project_code"]]` | 2 |
| `DOCS_CODE_V1` | `[["project_doc"], ["project_code"]]` | 1 |
| `NO_ADDITIONAL_REQUIREMENT` | `[]` | 0 |

These are minimum structural requirements, not task success labels. A profile
does not assert that a snippet is relevant, that a source path is the correct
implementation region, or that the answer is correct.

`required_evidence_groups` uses AND-of-OR semantics: every outer group must be
satisfied, and any evidence kind in an inner group can satisfy that group.
Thus Theory <-> Code requires `knowledge` and either repository code or
documentation evidence; Change Impact <-> Test requires both
`project_change` and `project_test`.

For cross-file Diagnosis, `min_distinct_project_code_paths` must be at least
2. Two paths are only a structural shape and do not prove a caller/callee or
propagation relationship. Tool-call count cannot substitute for distinct
relative source paths.

## 4. Router contract

The Router reads only the raw user question. It must not read or import
`evaluation.gate12`, benchmark files, Gold obligations, source proofs, case
IDs, candidate IDs, commit SHAs, repository files, Tool observations, or the
Agent answer. It invokes no Tool, Knowledge search, LLM, embedding service, or
external NLP service.

Normalization is deterministic and bounded: Unicode normalization, case
folding, whitespace normalization, and bounded punctuation handling are
allowed. It must not use embedding similarity, unbounded keyword expansion,
or repository-specific lookup.

The generic semantic signatures are:

| Profile | Bounded signal families |
|---|---|
| Change/Test | change, commit, diff, 变更 plus test, regression, 测试, 回归 |
| Docs/Code | documentation, README, doc, 文档 plus current implementation, code, 实现 plus consistency, correspondence, still accurate, 一致性, 是否对应 |
| Theory/Code | principle, mechanism, theory, 原理, 机制 plus implementation, source, code, 当前实现 plus compare, relate, 对照, 结合 |
| Diagnosis/Config | failure, error, fallback, validation, config, runtime behavior, 异常, 失败, 回退, 校验, 配置 plus reason, path, behavior, propagation, diagnosis semantics |

The precedence order is `CHANGE_TEST`, `DOCS_CODE`, `THEORY_CODE`, then
`DIAGNOSIS_CONFIG`. A query that does not meet a generic signature returns
`NO_ADDITIONAL_REQUIREMENT`; the Router must not force ordinary questions into
a G12 profile.

`DIAGNOSIS_CROSS_FILE_V1` is selected only when the diagnosis signature also
contains generic relational language such as cross-file propagation,
calling-chain, caller/callee, between components or layers, cross-module,
调用链, 跨模块, or equivalent bounded wording. It must never be inferred
from a filename, Gold path, case identity, or the mere existence of two Tool
calls.

The implementation test suite must primarily use synthetic, non-benchmark
questions. Production source must not contain `g12q`/`g12c` routing rules,
frozen question strings, benchmark SHA rules, Gold source paths, or
my_agent/pydantic-specific branches. Reading the final benchmark repeatedly
and adjusting rules until the 16 cases match is prohibited overfitting.

## 5. Evidence evaluation

The future deterministic evaluator has the conceptual contract
`evaluate_evidence_requirement(requirement, public_evidence)`, returning an
`EvidenceRequirementState` with `satisfied`, `missing_evidence_groups`,
`evidence_kind_counts`, `distinct_project_code_paths`, and
`required_min_distinct_project_code_paths`.

It consumes only the immutable requirement and already acquired public
evidence. Current public evidence kinds remain exactly `knowledge`,
`project_code`, `project_doc`, `project_change`, and `project_test`.

`changed_files` is candidate discovery and candidate provenance. It may remain
a Tool metric or change-set membership diagnostic, but it is not public
EngineeringEvidence and cannot satisfy `project_test` or any Guard group.
Candidate provenance is not test behavior evidence. A future product change
would first need a controlled, public, typed evidence representation; an
evaluator must not promote a Tool observation silently.

Evaluation is shape-only. It checks evidence kinds, minimum counts, the
AND-of-OR group structure, and distinct relative source paths where required.
It does not inspect snippet relevance, implementation-region correctness,
Gold-obligation coverage, answer text, claim support, remediation, or
semantic task success. Those remain Evidence Coverage, Evidence Correctness,
Claim Grounding, and Task Success judgments for Manual Gold v1.

## 6. Finalization Guard contract

The sole enforcement point is the Runtime immediately after a
`FinalAnswerAction` is parsed and before a `completed` result is created:

```text
FinalAnswerAction
    -> evaluate immutable requirement against public evidence
       -> sufficient: create completed
       -> insufficient: block completion
```

When no requirement is present, the existing completion path is preserved. If
the requirement is present and sufficient, the answer completes normally. The
Guard never runs a Tool automatically and never changes the evidence.

When evidence is insufficient, the Guard checks whether a suitable registered
Tool and normal Tool budget remain and whether another bounded Decision could
theoretically acquire one of the missing evidence groups:

1. If recovery is possible, completion is blocked and the Runtime permits one
   next Decision iteration under the unchanged `5 / 4 / 2` limits.
2. The next Decision consumes normal provider/iteration budget. The Guard block
   itself does not consume a Tool call.
3. If no recovery budget or suitable Tool remains, the Runtime returns a
   system-owned refusal with reason `INSUFFICIENT_EVIDENCE_TO_FINALIZE`.
4. This reason is not a model-controlled `RefuseAction` reason and cannot be
   forged by the Agent.

The Guard cannot guarantee that a later Decision will acquire evidence. It only
prevents unsupported completion and reports the bounded outcome.

### 6.1 No-progress termination

Every blocked attempt records an evidence fingerprint built only from public
evidence kind and safe relative source identity/path/bounded location. The
fingerprint excludes answer text, Gold, absolute paths, private Tool payloads,
and private reasoning.

If the next finalization attempt remains insufficient and the fingerprint is
unchanged, the Guard stops recovery and returns the system-owned refusal. If
public evidence progressed and the requirement is still insufficient, another
bounded recovery attempt is permitted while budget remains. This makes the
recovery rule finite and prevents an unchanged Tool loop from becoming an
unbounded retry.

The Guard must preserve the hard limits: `iterations <= 5`, `Tool calls <= 4`,
and `Tool errors <= 2`. It does not reinterpret a refused or failed result as
a premature completion. The automatic invariant is specifically:
`status == completed AND evidence_sufficient == false` is impossible.

## 7. Trusted recovery control

The Prompt template and its SHA remain unchanged. Only after a Guard block,
the existing system-managed control channel may expose a bounded recovery
state to the model, for example `finalization_blocked`,
`missing_evidence_groups`, `current_distinct_project_code_paths`, and
`required_min_distinct_project_code_paths`.

This is trusted Runtime metadata, not user input or Tool Observation. It must
not expose profile/task-family names, the rejected answer, Gold, the full
question, snippets, absolute paths, the Prompt, or private chain of thought.
The state tells the model what structural requirement is still missing; it
does not tell it which answer to write or inject benchmark instructions.

The safe trace may add a `finalization_guard_blocked` event with only bounded
fields: iteration, guard status, missing evidence kinds/groups, current code
path count, and required path minimum.

## 8. Metrics and outcome semantics

Future System C artifacts should add `guard_block_count`,
`guard_recovery_attempted`, `guard_recovery_succeeded`, and
`guard_final_refusal`. Recovery succeeds only when the Guard blocked a
finalization, the Agent acquired new public evidence, and the requirement
subsequently became satisfied. A later completion without new evidence is not
recovery success.

The runner continues to distinguish valid HTTP Agent outcomes (`completed`,
`refused`, `failed`) from infrastructure invalidity. `refused` and `failed`
may be valid bounded Agent outcomes; they are not automatically premature
finalization. System C is evaluated under the frozen G12-04A acceptance
contract, including its utility, grounding, cost, reliability, and
no-always-refuse thresholds.

## 9. Trade-off controls

The design must preserve the lessons from the frozen Baseline A:

- `q004`: Evidence Sufficiency is a structural PASS while Manual Task Success
  is PARTIAL. The Guard is not a semantic verifier.
- `q006`: Evidence Sufficiency is a structural FAIL while Manual Task Success
  is PASS. The Guard must not blindly convert useful work into refusal; it
  should expose the missing `project_test` and allow bounded recovery when
  possible.

These cases are controls for the evidence/utility trade-off, not special cases
in production logic.

## 10. Future implementation boundary

After reviewer approval, the smallest plausible implementation surface is:

```text
core/engineering_agent.py          requirement routing boundary
core/engineering_requirements.py   immutable requirement/evaluator contract
core/tool_agent/runtime.py         finalization gate and recovery state
core/tool_agent/runtime_models.py  typed state/trace additions if required
```

An API or Safe Trace adapter may change only if the public result contract
requires it. `decision_prompt.py`, Tool specifications, registry, Tool
implementations, Knowledge backend, and the frozen evaluator remain outside
the intervention. If the design cannot be implemented without changing the
Prompt template or its identity, implementation must stop for review rather
than silently turning System C into Prompt tuning.

Future tests should assert the generic contract with synthetic queries and
public evidence, including unmatched queries, precedence, cross-file minimum,
AND-of-OR satisfaction, unchanged-fingerprint termination, legacy behavior,
and the zero-premature-completion invariant. They must also assert that
production logic cannot import evaluator metadata.

## 11. Decision and next step

G12-04B freezes the typed requirement and Guard design only. It does not claim
that the Guard exists or that System C improves Baseline A. The next authorized
task is G12-04C System C Guard Implementation, after reviewer audit.

```text
System C Formal       NOT RUN
Finalization Guard    DESIGNED / NOT IMPLEMENTED
G12-04C               next, not started
```
