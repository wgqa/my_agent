"""Offline audit of the retained slice; never calls a provider or edits inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import types
from pathlib import Path


ARCHIVE = Path(__file__).resolve().parents[1]
REPO = ARCHIVE.parents[1]
sys.path.insert(0, str(REPO))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_module(path: Path, name: str):
    module = types.ModuleType(name)
    sys.modules[name] = module  # dataclasses resolves its defining module
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def requirement_identity(module, question: str) -> dict:
    result = module.route_engineering_evidence_requirement(question)
    return {
        "profile": result.requirement_profile.value,
        "required_evidence_groups": result.required_evidence_groups,
        "min_distinct_project_code_paths": result.min_distinct_project_code_paths,
        "router_version": result.router_version,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "Use a fresh output; never overwrite an audit"

    from core import engineering_requirements as retained

    document_archive = ARCHIVE / "document_source_slice"
    paid = snapshot_module(document_archive / "snapshots/requirements_candidate.snapshot", "_paid_doc_router")
    baseline = snapshot_module(document_archive / "snapshots/requirements_baseline.snapshot", "_baseline_doc_router")
    catalog = json.loads((document_archive / "catalog.json").read_text(encoding="utf-8"))
    routing = []
    for case in catalog["cases"]:
        paid_identity = requirement_identity(paid, case["question"])
        retained_identity = requirement_identity(retained, case["question"])
        assert paid_identity == retained_identity, case["id"]
        routing.append({"id": case["id"], "paid": paid_identity, "retained": retained_identity, "identical": True})

    legacy_specs = {profile.value: spec for profile, spec in baseline.FROZEN_PROFILE_SPECS.items()}
    current_specs = {profile.value: spec for profile, spec in retained.FROZEN_PROFILE_SPECS.items()}
    assert all(current_specs[name] == spec for name, spec in legacy_specs.items())
    assert set(current_specs) - set(legacy_specs) == {"PROJECT_DOC_V1"}

    initial = json.loads((document_archive / "initial_manifest.json").read_text(encoding="utf-8"))
    protected = {}
    for name, expected in initial["protected_files_sha256"].items():
        actual = sha(REPO / name)
        assert actual == expected, name
        protected[name] = {"sha256": actual, "unchanged": True}
    assert (REPO / "core/tool_agent/decision_prompt.py").read_bytes() == (ARCHIVE / "baseline_decision_prompt.snapshot").read_bytes()
    assert (REPO / "core/engineering_requirements.py").read_bytes() == (document_archive / "snapshots/requirements_retained.snapshot").read_bytes()

    frozen_inputs = {}
    for phase in (ARCHIVE, document_archive):
        manifest = json.loads((phase / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in manifest["artifacts_sha256"].items():
            actual = sha(phase / name)
            assert actual == expected, f"{phase.name}/{name}"
        for name, expected in manifest["reused_harness_files_sha256"].items():
            assert sha(REPO / name) == expected, name
        run = json.loads((phase / "raw/paired/run_manifest.json").read_text(encoding="utf-8"))
        assert run["input_manifest_sha256"] == sha(phase / "manifest.json")
        rows = [json.loads(line) for line in (phase / "raw/paired/live_results.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(rows) == manifest["planned_requests"] == 24
        assert {(row["id"], row["arm"]) for row in rows} == {(case["id"], arm) for case in catalog["cases"] for arm in ("baseline", "candidate")}
        frozen_inputs[phase.relative_to(REPO).as_posix()] = {"manifest_sha256": sha(phase / "manifest.json"), "manifest_and_helpers_unchanged": True, "recorded_requests": len(rows)}
    prompt_manifest = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
    assert sha(ARCHIVE / "candidate_decision_prompt.snapshot") == prompt_manifest["runtime_file_sha256"]["core/tool_agent/decision_prompt.py"]

    ci = re.findall(r"tests/test_[A-Za-z0-9_]+\.py", (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    runbook = (REPO / "docs/release2_local_runbook.md").read_text(encoding="utf-8")
    # The first test list is the CI command; later commands describe separate maintenance runs.
    blocks = re.findall(r"```bash\n(.*?)```", runbook, re.DOTALL)
    documented = next(re.findall(r"tests/test_[A-Za-z0-9_]+\.py", block) for block in blocks if "tests/test_tool_agent_core.py" in block)
    assert ci == documented
    assert len(ci) == len(set(ci)) == 35
    assert "tests/test_project_document_requirements.py" in ci

    report = {
        "provider_calls": 0,
        "frozen_inputs": frozen_inputs,
        "paid_candidate_sha256": sha(document_archive / "snapshots/requirements_candidate.snapshot"),
        "retained_candidate_sha256": sha(document_archive / "snapshots/requirements_retained.snapshot"),
        "post_live_change": "Mask literal filenames before interpreting request signals; additional filename/path boundaries verified offline only.",
        "live_catalog_routing_identical": routing,
        "legacy_profile_shapes_unchanged": legacy_specs,
        "protected_files": protected,
        "ci_and_runbook_test_lists_identical": True,
        "ci_selected_test_files": len(ci),
        "limit": "Identical routing is not a second live run of the retained file and does not establish model answer reproducibility.",
    }
    args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({"routing_cases": len(routing), "protected_files": len(protected), "ci_files": len(ci), "provider_calls": 0}))


if __name__ == "__main__":
    main()
