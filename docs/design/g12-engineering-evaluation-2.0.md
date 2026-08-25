# G12 Engineering Evaluation 2.0 Protocol and Evidence Sufficiency Contract

## Status and Scope

Status: design frozen by G12-01. This document defines the protocol to be implemented and evaluated in later G12 work; it does not change production behavior.

G12-01 is pure design and documentation work. It does not implement an evidence verifier or Finalization Guard, modify the Runtime or Prompt, add a Tool, create a benchmark dataset, select/download an external repository, rerun a G11 Formal, or call a real provider.

The current production baseline remains `0a1f42e8ee0320486dbd0ddc01400e1e19150501`. The production Engineering prompt remains v2, the public registry remains 7 Tools, the Engineering transport cap remains 1200, and the system budget remains 5 iterations / 4 Tool calls / 2 Tool errors. These are controls for future experiments, not G12-01 changes.

## 1. Motivation From Frozen G11 Evidence

G11 established that obtaining a locator, making a Tool call, or returning a structured completion is not enough to establish a grounded engineering answer.

| G11 family | Frozen result | Evidence debt carried into G12 |
|---|---|---|
| G11-02 Theory <-> Code | CLOSED / MIXED | Knowledge and repository evidence can both exist while claim-level grounding is still incomplete. |
| G11-03 Change Impact <-> Test | CLOSED / MIXED | Change evidence acquisition can succeed while test evidence sufficiency and claim grounding fail. |
| G11-04 Diagnosis / Config | CLOSED / NEGATIVE; Manual Gold 0/4 | Low `read_project_context` coverage, unsupported cross-file propagation, premature finalization, duplicate Tool calls, and structured action failures. |
| G11-05 Docs <-> Code | CLOSED / NEGATIVE; Manual Gold 0/4 | Bilateral document/code evidence pair was 0/4; the Agent made consistency conclusions from one side only, with duplicate calls and structured action failures. |

G11-04 and G11-05 separately showed `ARGUMENTS_SCHEMA_INVALID` with repair 0/1. That is a structured-action reliability problem, not an evidence-sufficiency measurement. G11-05 also established a mandatory evaluator-isolation lesson: evaluator Gold metadata must not be searchable in the evaluated project.

The frozen research questions are:

1. **RQ1:** Across real engineering task families, what proportion of answers have sufficient evidence, correct evidence, and claim-level grounding, in addition to a correct engineering conclusion?
2. **RQ2:** Is the current Prompt evidence policy enough to reliably guarantee those properties? G11 provides a negative answer: no.
3. **RQ3:** Can a minimal system-level Evidence Sufficiency / Finalization Guard improve grounded task success without materially increasing refusal, Tool calls, latency, or failure rate?

The production v2 Prompt is not an empty baseline. It already says that `code_search` is a locator, implementation claims require context, Theory <-> Code needs heterogeneous evidence, duplicate exact Tool calls are forbidden, and insufficient evidence must not be presented as verified implementation. G12 therefore does not treat adding more Prompt prose as the primary intervention.

## 2. Protocol Goals and Non-goals

Evaluation 2.0 measures a chain rather than a single response label:

```text
Task request
    -> task requirement
    -> evidence acquisition
    -> evidence sufficiency
    -> claim grounding
    -> engineering conclusion
```

The first benchmark version targets 16 cases, provisionally allocated 4 + 4 + 4 + 4 across four task families. G12-02 may audit and adjust the total to 12-20 cases before any Formal run. No formal cases are authored or frozen in G12-01.

G12-01 explicitly does not:

- implement a verifier, Finalization Guard, critic Agent, multi-agent system, GraphRAG, semantic code index, or new Tool;
- tune the Prompt, expand the 5/4/2 budget, or alter current Runtime behavior;
- create or run a real-provider G12 Formal;
- reuse G11 development cases as a claimed independent benchmark;
- decide that the Core Agent System is complete.

## 3. Task Families and Dataset Independence

The formal benchmark must cover all four families below.

| Family | Required task shape | Minimum initial allocation |
|---|---|---:|
| Theory <-> Code | Technical mechanism + current project implementation + semantic comparison | 4 |
| Change Impact <-> Test | Change evidence + affected implementation + test-side evidence | 4 |
| Diagnosis / Config | Symptom or configuration + implementation + cross-file propagation where relevant + bounded remediation | 4 |
| Docs <-> Code Consistency | Document claim + current implementation + consistency judgment | 4 |

G11 cases such as TC01, CI01, DC01, and DOC01 are development evidence. G12 may reuse their task semantics and failure taxonomy, but it must not simply copy their questions and claim that an intervention improved an independent benchmark.

The G12 benchmark must contain at least:

- one `my_agent` pinned checkout; and
- one pinned public external RAG or Agent repository.

External repository selection is deferred to G12-02. The selected repository must have a public source and license, a fixed commit SHA, a size practical for the existing bounded lexical Tools, genuine AI-engineering tasks, and no requirement for a per-repository vector database. It must remain separate from evaluator metadata.

## 4. Evaluator and Repository Provenance

Every formal Engineering evaluation must enforce:

```text
Evaluator checkout != Evaluated project checkout
```

The evaluator checkout may contain cases, Gold labels, obligations, runner code, and study notes. The evaluated project tree must not contain evaluator-owned metadata that the Agent can discover with repository Tools.

Each formal artifact must independently record and attest:

- `evaluator_commit`;
- `project_source_commit`;
- tracked-clean status for both checkouts;
- distinct resolved roots;
- project-target isolation and evaluator-Gold-file absence;
- case-contract identity;
- project-relative rather than evaluator-relative source paths.

This follows the G11-05 isolated-run contract. It is an evaluator-integrity condition, not a capability score. The contaminated G11-05 run remains invalid and must never be reinterpreted as a negative capability result.

## 5. Frozen Evidence Taxonomy

G12 uses only current production public evidence kinds:

| Evidence kind | Meaning in this protocol |
|---|---|
| `knowledge` | Verified Engineering Knowledge evidence returned by the current public Runtime/API surface. |
| `project_code` | Bounded repository source context containing implementation evidence. |
| `project_doc` | Bounded project documentation context containing a document claim. |
| `project_change` | Bounded Git change evidence. |
| `project_test` | Bounded test-source context containing test evidence. |

The protocol must not invent synthetic evidence kinds merely to make a metric look complete. A `code_search` result is a locator. It is not `project_code` implementation evidence until an appropriate source window has actually been read and exposed through the public evidence surface.

## 6. Evidence Sufficiency Contract

Evidence Sufficiency is a task-specific minimum contract. It is not `evidence_count > 0`, a Tool call, a path hit, or a correctly guessed answer.

| Family | Minimum evidence groups | Additional rule |
|---|---|---|
| Theory <-> Code | `knowledge >= 1` AND (`project_code >= 1` OR `project_doc >= 1`) | Repository evidence must be an implementation-relevant source window, not a `code_search` locator alone. |
| Change Impact <-> Test | `project_change >= 1` AND test-side support `>= 1` | Test-side support is `project_test`, or explicitly contracted changed-files-derived test candidate evidence. A filename containing `test` is not automatically test-behavior evidence. |
| Diagnosis / Config | `project_code >= 1` | A final cross-file propagation, startup, caller/callee, or runtime-consequence claim requires evidence from the corresponding multiple implementation sources. |
| Docs <-> Code | `project_doc >= 1` AND `project_code >= 1` | Without this bilateral pair, the Agent may not emit a deterministic `CONSISTENT`, `OUTDATED`, `INCOMPLETE`, or `PARTIALLY CONSISTENT` conclusion. |

The contract governs permission to finalize, not truth. It establishes a minimum evidence shape; it does not prove that a source window covers every Gold obligation or that the final answer is correct.

### 6.1 Evidence Levels Must Stay Separate

| Term | Question answered | Automatic in v1? |
|---|---|---|
| Evidence Presence | Does a public evidence kind exist? | Yes. |
| Evidence Sufficiency | Does the case meet its task-family minimum contract? | Yes, from the frozen contract. |
| Evidence Coverage | Is each Gold obligation covered by a relevant evidence item? | Partially structural signals may be automatic; final assessment is manual Gold. |
| Evidence Correctness | Is the evidence from the correct source and implementation region? | Manual Gold in v1. |
| Claim Grounding | Does each concrete final claim have supporting evidence? | Manual Gold in v1. |
| Task Success | Is the engineering conclusion correct? | Manual Gold in v1. |

No result may equate required Tool coverage, a source-path hit, evidence-kind presence, or a completed response with Task Success.

## 7. Metrics

All rates use a frozen denominator stated in the run artifact. Missing, refused, and failed cases must be reported rather than silently dropped.

| Metric | Definition | Scoring in v1 |
|---|---|---|
| Task Success Rate | Cases with a correct final engineering conclusion. | Manual Gold. |
| Evidence Sufficiency Rate | Cases satisfying the family-specific minimum contract. | Automatic. |
| Evidence Coverage | Fraction of Gold obligations with supporting evidence. | Manual Gold; structural diagnostics may assist. |
| Evidence Correctness | Evidence items from correct source and relevant behavior/claim region. | Manual Gold. |
| Claim Grounding Rate | Fraction of verifiable concrete final claims supported by evidence. | Manual Gold. |
| Required Tool Coverage | Required Tool calls observed for the case contract. | Automatic. |
| Forbidden / Wrong Tool Rate | Forbidden or non-target Tool calls divided by applicable case/run denominator. | Automatic. |
| Premature Finalization Rate | Final answers emitted while the frozen minimum evidence contract was not met. | Automatic. |
| Structured Action Failure Rate | Cases with an L1 structured parsing/action failure. | Automatic. |
| Duplicate Tool Stop Rate | Cases stopped by duplicate Tool-call handling. | Automatic. |

Operational and reliability metrics are also required: `provider_calls`, `tool_calls`, `iterations`, latency, parse failures, repair attempts, repair success, refused, failed, and budget stop. Token usage is recorded only if the provider supplies stable, trustworthy values; otherwise the artifact must say `NOT AVAILABLE`, never an estimate presented as measured usage.

## 8. Manual and Automatic Boundaries

The first version is deliberately conservative.

Automatic scoring may determine evidence kinds, evidence pairs, source-path hits, required and forbidden Tools, premature finalization under the frozen minimum contract, and provider/Tool/latency/failure metrics.

Automatic scoring must not initially decide answer semantic correctness, complete claim grounding, remediation correctness, propagation reasoning correctness, or subtle documentation semantics. These remain manual Gold until a separate deterministic scorer has been validated against audited cases.

## 9. Failure Taxonomy

Every case failure analysis must classify one or more layers without collapsing them into a single "bad answer" label.

| Layer | Name | Examples |
|---|---|---|
| L1 | Structured Transport / Parsing | `ARGUMENTS_SCHEMA_INVALID`, `ACTION_PARSE_FAILED`, repair failure. |
| L2 | Planning / Tool-loop | Duplicate call, wrong Tool, budget misuse, failure to choose a usable next Tool. |
| L3 | Evidence Acquisition | Locator only, missing second source, missing bilateral pair, insufficient test source. |
| L4 | Reasoning / Grounding | Unsupported propagation, wrong consistency conclusion, overclaim beyond acquired evidence. |

L1 must be measured separately from evidence insufficiency. A parse failure may prevent evidence acquisition, but it is not evidence insufficiency itself. Likewise, an L2 duplicate hard stop is not proof that an L4 conclusion would have been wrong.

## 10. Finalization Guard Hypothesis

The proposed intervention is a **Finalization Guard**, not an implemented component.

Current production behavior is:

```text
FinalAnswerAction -> completed
```

The candidate G12 behavior is:

```text
FinalAnswerAction
    -> immutable Evidence Requirement check
    -> sufficient?
       yes -> completed
       no  -> do not finalize yet
```

The hypothesis is that a small deterministic gate can reduce premature finalization and increase evidence sufficiency and claim grounding, while preserving Task Success and making refusal, Tool use, provider calls, latency, and budget pressure transparent.

The future Guard may use only the bounded task requirement and already acquired public evidence. It must not:

- read a Gold label or case ID;
- special-case DOC01, DC03, a question string, or a repository filename;
- generate answer content or act as a second LLM Agent;
- invent evidence or increase the Tool budget;
- replace manual Gold assessment.

### 10.1 Candidate Insufficient-Evidence Semantics

`INSUFFICIENT_EVIDENCE_TO_FINALIZE` is a candidate design name only. It is not a current production reason code or failure code.

The proposed future semantics are bounded:

1. When a `FinalAnswerAction` is blocked and a suitable registered Tool plus Tool budget remain, the Runtime returns the Agent to one next Decision iteration with immutable requirement context.
2. When no Tool budget remains, or no suitable registered Tool exists, the Runtime returns a structured refusal or incomplete result rather than silently declaring completion.
3. The Runtime cannot loop indefinitely: existing iteration, Tool-call, and Tool-error budgets remain authoritative.

The first implementation must define the public structured result shape and its interaction with safe trace before code is written. It must not swallow a potentially useful answer without exposing why finalization was blocked.

## 11. Typed Task Requirement Alternatives

The Guard needs a requirement source that cannot be weakened by the Agent at finalization time.

| Option | Source | Benefit | Main risk | Decision |
|---|---|---|---|---|
| A | LLM self-reports the requirement | Flexible wording | The model can wrongly lower its own evidence bar. | Reject as authoritative source. |
| B | Deterministic query classifier | Auditable and simple | Fragile rules and taxonomy drift. | Retain as a possible bounded input. |
| C | Hybrid typed requirement | A system/router creates a bounded typed requirement; Runtime consumes it immutably. | Requires a narrow, auditable classification contract. | Recommended design direction. |

The recommended direction is C, not because it is more autonomous, but because it separates requirement production from Runtime enforcement. The future Runtime must consume an immutable typed value and must not trust an LLM action to downgrade it.

Illustrative architecture contract only; this is not a production class:

```text
EngineeringEvidenceRequirement
    task_family
    required_evidence_groups
    requires_cross_file
    allows_knowledge_only
    allows_repo_only
```

For Theory <-> Code, `required_evidence_groups` would be `[[knowledge], [project_code, project_doc]]`. For Docs <-> Code, it would be `[[project_doc], [project_code]]`. The final field semantics, classifier/router boundary, and serialization schema remain implementation design work after benchmark baseline data exists.

## 12. Duplicate Tool Call and Structured Action Reliability

Current Runtime duplicate-call handling is a safety hard stop. G11 showed that it may also terminate an otherwise recoverable planning mistake. G12 will evaluate, not change, two future alternatives:

| Variant | Candidate behavior | Invariant |
|---|---|---|
| A | Keep the existing duplicate hard stop. | No repeated Tool execution. |
| B | Allow one bounded duplicate recovery Decision. | No duplicate Tool execution, no larger budgets, and recovery is observable. |

This is distinct from the Finalization Guard. Duplicate recovery concerns an L2 planning/Tool-loop error. Structured Action Reliability concerns whether actions parse and validate at all. `ARGUMENTS_SCHEMA_INVALID`, action parser failure, repair attempt, and repair outcome therefore remain independent measurements from L3 evidence acquisition and L4 reasoning.

## 13. Future A/B Protocol

Future Formal comparison must use the same frozen benchmark contract, project commits, evaluator isolation, provider/model identity, cap, budget, registry, and artifact-safety policy unless a factor is explicitly the tested intervention.

| Arm | Configuration | Purpose |
|---|---|---|
| Baseline A | Current Engineering v2 + current Runtime | Establish post-G11 independent baseline. |
| Control B | Prompt-only improvement, if authorized | Isolate any effect of Prompt wording; it is not the default solution. |
| System C | Same Prompt as A + deterministic Evidence Finalization Guard | Test the system-level hypothesis. |

The core comparison reports Task Success, Evidence Sufficiency, Claim Grounding, Premature Finalization, refusal, Tool calls, provider calls, latency, parse/repair outcomes, duplicate stops, failed cases, and budget stops. It must present all cases and failure layers, not only successful completions.

The primary success direction for System C versus Baseline A is:

- Evidence Sufficiency increases;
- Premature Finalization decreases;
- Claim Grounding increases;
- Task Success does not materially decrease.

Guard-induced refusal and average Tool calls are mandatory trade-off metrics. Concrete thresholds are intentionally not frozen in G12-01; they must be set after an independent Baseline A measurement, before inspecting System C results. This prevents choosing attractive targets after the fact.

## 14. Core Completion Interpretation

G12 is not complete merely because G11 covered four task families. Core Agent System completion remains undecided until Engineering Evaluation 2.0 has a unified independent benchmark, isolated provenance, baseline and intervention results, and a system-level conclusion about the evidence problem.

Current state: **Core Agent System is NOT COMPLETE.**

## 15. Next Design Boundary

G12-02, not started by this task, owns external repository selection, pinned checkout verification, independent dataset construction, case-contract freezing, and audit of the 12-20 case target. It must preserve all requirements in this document before any provider Formal or Runtime implementation is authorized.
