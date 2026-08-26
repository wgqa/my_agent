# G12 System C Acceptance Contract

## 1. Purpose and scope

This document freezes the acceptance contract for the future G12 System C experiment. It is an evaluator/design artifact only. It does not implement a Finalization Guard, a requirement router, or any Runtime behavior.

System C is defined as one intervention added to the frozen Baseline A environment:

```text
deterministic typed Evidence Requirement
    +
system-level Finalization Guard
```

The benchmark, provider/model, Engineering Prompt v2 and SHA, 1200 output cap, `5 / 4 / 2` budget, seven Tools, project commits, and Knowledge corpus remain unchanged. No Prompt-only tuning is part of System C.

The machine-readable source of truth is [system_c_acceptance_contract_v1.json](../../evaluation/gate12/system_c_acceptance_contract_v1.json). Its canonical payload SHA-256 is `5a9d190dcb585a29097fac206c14aa0f31c27d178d8fe0cae8d72b1b8c17bb8f`.

## 2. Frozen Baseline A

The only Baseline A run is `g12-baseline-a-formal-20260825-195305`, on dataset freeze `gate12-v1-630fc8b527c2`, with product baseline `0a1f42e8ee0320486dbd0ddc01400e1e19150501`.

The reviewed Full Task Success distribution is `PASS=2`, `PARTIAL=8`, `FAIL=6`. Strict Full Task Success is `2/16`; partial-or-better is `10/16`. Automatic Evidence Sufficiency is `2/16`, and Premature Finalization is `12/16`. Claim Grounding is `PASS=1`, `PARTIAL=8`, `FAIL=7`; Evidence Coverage is `FULL=1`, `PARTIAL=8`, `NONE=7`.

The corrected cost baseline is provider calls `54`, Tool calls `37`, and iterations `53`. The provider-call correction is an evaluator-only aggregation correction: each `decision_completed` event carries one Decision's local call count, so case-level calls are summed across those events. It does not change the original Formal artifact or any product behavior.

## 3. Requirement source integrity

The requirement must come from generic bounded product/system logic. Evaluator Gold is not a Runtime requirement source.

The request sent to the Agent remains only the frozen question. The evaluator must not send `case_id`, task family, evidence groups, cross-file requirements, Gold obligations, Gold source paths, source candidate identity, or any other evaluator metadata. Trusted system control may communicate a bounded missing-evidence state, but it may not contain case-specific instructions or Gold claims.

The future router may use only the four generic task semantics already defined by G12-01:

- Theory <-> Code
- Change Impact <-> Test
- Diagnosis / Config
- Docs <-> Code

It may not hard-code benchmark IDs, candidate IDs, question strings, commit SHAs as routing rules, Gold paths, repository filenames, or special handling for either repository. Implementation tests must primarily use synthetic non-benchmark queries. Repeatedly reading the final dataset and tuning rules until the frozen cases match is invalid design practice.

## 4. Guard invariant

The non-negotiable behavioral invariant is:

```text
completed AND evidence_sufficient == false
    -> zero cases
```

Any System C run with Premature Finalization greater than zero fails the correctness gate. This is intentionally stricter than a general quality target: a guard that sometimes allows unsupported completion has not established the behavior it was introduced to enforce.

The guard must not turn into an always-refuse policy. A refusal can be a valid Agent outcome when evidence is insufficient, but refusing every task is not task success and cannot satisfy the utility contract.

## 5. Primary acceptance thresholds

All primary gates are evaluated on the same complete 16-case run.

| Metric | Required threshold |
| --- | ---: |
| Premature Finalization | `0/16` |
| Overall Evidence Sufficiency | at least `8/16` |
| Theory <-> Code Evidence Sufficiency | at least `2/4` |
| Change Impact <-> Test Evidence Sufficiency | at least `1/4` |
| Diagnosis / Config Evidence Sufficiency | at least `1/4` |
| Docs <-> Code Evidence Sufficiency | at least `1/4` |
| Change `project_test` evidence | at least `2/4` |
| Cross-file Diagnosis shape | at least `2/3` |
| Docs bilateral `project_doc + project_code` | at least `2/4` |
| Full Task Success | at least `2/16` |
| PARTIAL-or-better | at least `9/16` |

Full Task Success cannot fall below Baseline A. The partial-or-better threshold allows at most one case of utility loss from the Baseline value `10/16`; it prevents a system from improving structural evidence by making useful answers disappear.

## 6. Grounding, outcome, cost and reliability

Claim Grounding must reach `PASS >= 3/16` and keep `FAIL <= 5/16`. Refused cases must be `<= 5/16`, guard-specific `INSUFFICIENT_EVIDENCE_TO_FINALIZE` refusals `<= 4/16`, and failed cases `<= 2/16`.

Corrected deterministic cost limits are provider calls `<=72`, Tool calls `<=52`, and iterations `<=72`. Latency must be reported separately. Average latency above twice the Baseline is a `MAJOR COST REGRESSION`, but latency alone does not make an otherwise valid run INVALID.

Reliability limits are forbidden Tool calls `0`, structured parse failure cases `<=1`, duplicate Tool stops `<=1`, and budget stops `<=2`. Runtime hard limits remain `5 / 4 / 2`; registry size remains `7`.

## 7. q004 and q006 trade-off audit

Two Baseline controls must remain visible in the System C review:

- q004 is automatic Evidence Sufficiency PASS but Manual Full Task Success PARTIAL. Shape sufficiency is not semantic correctness.
- q006 is automatic Evidence Sufficiency FAIL but Manual Full Task Success PASS. A guard cannot improve grounding by blindly refusing whenever its shape contract is not met.

These examples make the trade-off concrete. System C must improve evidence-grounded reliability without pretending that a structural gate is a semantic judge or that refusal is a substitute for useful engineering work.

## 8. Classification

Classification has explicit precedence:

1. `INVALID` takes precedence for infrastructure/provenance failure, dataset drift, project binding mismatch, Prompt/control drift, Gold leakage, or invalid Formal execution. An INVALID run produces no capability conclusion.
2. `FAIL` applies when Premature Finalization is greater than zero, Evidence Sufficiency is below `6/16`, Full Task Success is below `2/16`, refusal collapses utility, cost/reliability regresses severely, or the Guard invariant fails. A FAIL is not rerun to select a better result.
3. `PASS` requires all integrity, primary, utility, grounding, cost and reliability gates.
4. `MIXED` is the bounded middle result: integrity passes, Premature Finalization is zero, Evidence Sufficiency is at least `6/16`, and there is no major safety or utility collapse, but one or more complete PASS gates is missing.

System C failure still has experimental value: it can show whether the intervention is too weak, too refusal-heavy, too expensive, or structurally correct but semantically insufficient. That value does not justify changing the frozen thresholds after seeing the result.

## 9. Run policy

Thresholds are frozen before System C Formal. The official run is one complete benchmark run; cases cannot be cherry-picked or selectively rerun. A run that is INVALID because of infrastructure may be replaced after infrastructure repair, while the invalid artifact remains retained. A valid FAIL is not replaced by repeated attempts.

System C Formal remains `NOT RUN` until the next task explicitly authorizes its execution.
