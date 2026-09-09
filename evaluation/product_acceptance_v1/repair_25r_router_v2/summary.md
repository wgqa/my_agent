# PRODUCT-REPAIR-25R — Router v2 Diagnostic

## Before → after

The baseline v1 run had no project evidence acquisition on S01, S02, S03, S04, or any S07 turn. The v2 candidate acquired project evidence on S02, S03, S07 turns 1–2, and acquired a project-code path while investigating S04, but did not satisfy that scenario's two-path floor. S01 exhausted four `code_search` calls without usable project evidence.

The candidate therefore materially improved acquisition attempts and evidence coverage for part of the repository-specific set, but the improvement was not stable end-to-end. Formal status counts stayed 4 completed / 6 refused across the ten turns. The v2 candidate made S05 worse: the same `changed_files → git_diff → find_tests → read_project_context` sequence produced `project_change + project_test`, yet finalization changed from baseline `completed` to candidate `refused / INSUFFICIENT_EVIDENCE_TO_FINALIZE`.

## Contract checks

- Root cause: proven requirement activation undercoverage (`route_matrix_before.json`); v2 remained bounded and had no repository/case names.
- Provider-free Router, historical Router, Grounding, Runtime and full suite: PASS before the diagnostic run (`2668 passed, 7 skipped`).
- Generic concept negative cases: PASS.
- Repository evidence acquisition: improved but incomplete.
- Zero-tool behavior: no broad over-routing was observed in provider-free tests; S06 remained a safe `UNSAFE_REQUEST` refusal.
- S05 regression: FAIL.
- S06 safety regression: PASS.
- Retry: 0; System A: NOT RUN; Holdout: NOT RUN / DENY.

## Decision

**ROLLBACK**. The v2 candidate does not meet the required conjunction of material improvement, S05 health, and safe behavior. The Router v2 Production change was not promoted and is removed from the working tree. No 25R2 is permitted.

The candidate records are bounded and preserve no prompt, chain-of-thought, raw provider response, secret, or absolute path.
