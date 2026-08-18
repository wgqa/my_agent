# Gate5 Release Hygiene Audit

## Baseline

- Commit: `ac4395db0c506c9421649dcc4b4faee48a7cfe29`
- Scope: tracked release surface, repository hygiene, release summary wording, and status/documentation drift.
- Policy: no history rewrite, no `git clean`, no deletion of user-created untracked files, no Holdout access.

## Blocking Findings

None found in the tracked Release 1.0 surface.

## Release Cleanup Fixed

- `docs/status.md` now marks G5-BE-06, G5-DEMO-07, G5-APP-07B and G5-README-08 as Reviewer accepted / CLOSED, and records G5-HYGIENE-09 as IN PROGRESS.
- `pytest.ini` no longer uses the unsupported `basetemp` key; local and CI callers can pass `--basetemp` explicitly.
- `scripts/demo_release.py` reports required pass/fail/skipped counts separately from the single observational case.
- `.gitignore` now ignores the exact `.tmp_g5env02_lock` output and historical generated `experiments/*/*/config.yaml` files. No tracked experiment config was found.
- The offline pipeline fake embedding documents and uses the actual 32-byte SHA-256 dimension.
- Study Note and status maps now cover notes 00–102.

## Security Checks

- Credential scan: no real API token, bearer credential, private key, or non-empty `.env` credential was found in tracked files. Matches were fake fixtures, `sk-xxx` examples, dummy smoke values, or safe placeholders.
- `.env` history: `git log --all -- .env` returned no commits; `.env.example` remains an empty-key template.
- Absolute paths: historical design/archive documents contain local-path or `benchmark_work` examples, classified as documentation provenance rather than runtime leakage. No credential path, runtime artifact path, or private content was found; these historical documents were not rewritten in this hygiene-scoped change.
- Holdout boundary: tracked files contain only runner references, IDs, hashes, and aggregate evidence. No sealed JSONL, private manifest, or Holdout content was read or tracked.
- Large files: `git ls-tree -rl HEAD` found zero tracked files at or above 1 MiB. Frozen evidence was not removed.
- User untracked files: existing temporary and historical experiment files were preserved.

## Deferred V1.1 Debt

Basic UI history transport, upload timeout cleanup, schema literal tightening, streaming, trace IDs, authentication, container packaging, stronger multi-step behavior, generator robustness, MCP, Memory, and GraphRAG remain outside Release Hygiene scope.

## Frozen Evidence Integrity

Gate 2, Gate 3 and Gate 4 frozen artifacts were not modified, re-generated, or re-run.
