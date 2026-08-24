"""Deterministic contracts for the G11-03 transfer-validation runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import scripts.run_g11_03_change_impact as runner
from core.tool_agent import (
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_SHA256,
    ToolAgentBudget,
    build_readonly_tool_registry,
    max_parse_repairs_for_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _new_git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, head


def test_fixed_case_identity_and_commit_refs_are_frozen():
    assert [case["case_id"] for case in runner.CASES] == [
        "CI01",
        "CI02",
        "CI03",
        "CI04",
    ]
    assert all(len(case["target_commit"]) == 40 for case in runner.CASES)
    assert [case["target_commit"] for case in runner.CASES] == list(
        runner.FIXED_TARGET_COMMITS
    )
    assert all(case["head_ref"] == case["target_commit"] for case in runner.CASES)
    assert all(case["base_ref"] == f"{case['target_commit']}^" for case in runner.CASES)
    assert [case["focus_path"] for case in runner.CASES] == [
        "api/app.py",
        "core/engineering_knowledge.py",
        "core/tool_agent/decision_prompt.py",
        "core/tool_agent/tools/git_change.py",
    ]
    assert runner.validate_case_identities() == runner.CASES


def test_fixed_case_accepted_tests_are_in_real_target_change_sets():
    """The v2 benchmark proves changed-files candidate visibility with real Git."""
    proof = runner.validate_accepted_tests_in_change_set(git_root=REPO_ROOT)
    assert proof == {case["case_id"]: True for case in runner.CASES}
    for case in runner.CASES:
        changed_paths = set(runner.changed_paths_for_case(case, git_root=REPO_ROOT))
        assert set(case["accepted_test_paths"]) & changed_paths


def test_target_commits_exist_in_the_current_checkout():
    assert runner.validate_case_identities(git_root=REPO_ROOT) == runner.CASES


def test_required_and_forbidden_tool_contract_is_frozen():
    assert runner.REQUIRED_TOOLS == (
        "changed_files",
        "git_diff",
        "read_project_context",
    )
    assert runner.OPTIONAL_CANDIDATE_TOOLS == ("find_tests",)
    assert {"knowledge_search", "calculator"} <= set(runner.FORBIDDEN_TOOLS)


def _metric_case(
    sequence: list[str],
    evidence_kinds: list[str],
    *,
    candidate_source: str | None = None,
    accepted_test_in_change_set: bool | None = None,
    assertion_visible: bool = False,
) -> dict:
    return {
        "status": "completed",
        "tool_sequence": sequence,
        "evidence_kinds": evidence_kinds,
        "iterations": len(sequence) + 1,
        "tool_calls": len(sequence),
        "tool_errors": 0,
        "evidence": [{} for _ in evidence_kinds],
        "provider_calls_total": 1,
        "repair_attempted": False,
        "repair_succeeded": False,
        "failure_code": None,
        "initial_parse_categories": [],
        "test_candidate_source": candidate_source,
        "accepted_test_in_change_set": accepted_test_in_change_set,
        "test_evidence_assertion_visible": assertion_visible,
    }


def test_metrics_count_pairs_and_keep_sequence_diagnostic_only():
    cases = [
        _metric_case(
            list(runner.DIAGNOSTIC_TARGET_SEQUENCE),
            ["project_change", "project_test"],
            candidate_source="find_tests",
            accepted_test_in_change_set=False,
            assertion_visible=True,
        ),
        _metric_case(
            ["changed_files", "git_diff"],
            ["project_change"],
            candidate_source="changed_files",
            accepted_test_in_change_set=True,
        ),
        _metric_case(
            ["find_tests", "read_project_context"],
            ["project_test"],
            candidate_source="find_tests",
            accepted_test_in_change_set=False,
            assertion_visible=True,
        ),
        _metric_case(
            [
                "changed_files",
                "git_diff",
                "code_search",
                "read_project_context",
            ],
            ["project_change", "project_test"],
            candidate_source="changed_files",
            accepted_test_in_change_set=True,
        ),
    ]

    metrics = runner._metrics(cases)

    assert metrics["change_evidence_cases"] == 3
    assert metrics["test_evidence_cases"] == 3
    assert metrics["change_test_pair_cases"] == 2
    assert metrics["change_test_pair_rate"] == 0.5
    assert metrics["exact_target_sequence_cases"] == 1
    assert metrics["exact_target_sequence_diagnostic_only"] is True
    assert metrics["non_target_tool_calls"] == 1
    assert metrics["test_candidate_from_changed_files_cases"] == 2
    assert metrics["test_candidate_from_find_tests_cases"] == 2
    assert metrics["accepted_test_in_change_set_cases"] == 2
    assert metrics["test_evidence_assertion_visible_cases"] == 2


def test_candidate_source_requires_find_tests_for_unseen_test():
    case = {"case_id": "SYNTH", "accepted_test_paths": ["tests/test_unseen.py"]}

    with pytest.raises(ValueError, match="find_tests was not used"):
        runner.resolve_test_candidate_source(
            case, ["src/changed.py", "tests/test_other.py"], []
        )
    assert runner.resolve_test_candidate_source(
        case,
        ["src/changed.py", "tests/test_other.py"],
        ["find_tests", "read_project_context"],
    ) == "find_tests"
    assert runner.resolve_test_candidate_source(
        case, ["src/changed.py", "tests/test_unseen.py"], []
    ) == "changed_files"


def test_production_prompt_repair_budget_and_registry_identities_are_frozen(tmp_path: Path):
    assert runner.validate_prompt_identity(
        runner.PRODUCTION_PROMPT_VERSION, runner.PRODUCTION_PROMPT_SHA256
    ) == (runner.PRODUCTION_PROMPT_VERSION, runner.PRODUCTION_PROMPT_SHA256)
    assert ENGINEERING_DECISION_PROMPT_V2_PROFILE.version == (
        runner.PRODUCTION_PROMPT_VERSION
    )
    assert ENGINEERING_DECISION_PROMPT_V2_SHA256 == runner.PRODUCTION_PROMPT_SHA256
    assert runner.validate_repair_prompt_identity(
        runner.REPAIR_PROMPT_VERSION, runner.REPAIR_PROMPT_SHA256
    ) == (runner.REPAIR_PROMPT_VERSION, runner.REPAIR_PROMPT_SHA256)
    assert max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE) == 1
    assert runner.BUDGET == {
        "max_agent_iterations": 5,
        "max_tool_calls": 4,
        "max_tool_errors": 2,
    }
    assert runner.REGISTRY_SIZE == 7
    assert runner.MAX_OUTPUT_TOKENS == 1200
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)

    class RetrievalPort:
        supported_strategies = ("bm25",)

        def search(self, query, strategy, top_k):
            return ()

    assert len(build_readonly_tool_registry(tmp_path, RetrievalPort()).list_specs()) == 7


def test_prompt_v3_is_not_a_g11_03_production_identity():
    with pytest.raises(ValueError, match="production Engineering v2"):
        runner.validate_prompt_identity(
            "engineering_agent_decision_prompt_v3",
            "0e9554cffcd7240ad394afb24cc60239d583f1f0a7218b2fad0aab09507ff917",
        )


def test_source_commit_mismatch_and_tracked_dirty_checkout_are_rejected(tmp_path: Path):
    repo, head = _new_git_repo(tmp_path)
    assert runner.validate_source_commit(head, git_root=repo) == head

    with pytest.raises(ValueError, match="does not match"):
        runner.validate_source_commit("0" * 40, git_root=repo)

    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tracked modifications"):
        runner.validate_source_commit(head, git_root=repo)


def test_normalized_artifact_omits_raw_provider_output_paths_and_keys(tmp_path: Path):
    repo, _ = _new_git_repo(tmp_path)
    output = tmp_path / "artifact"
    output.mkdir()
    response = {
        "status": "completed",
        "answer": f"repo={repo} key=sk-test-secret-12345",
        "trace": [],
        "evidence": [
            {
                "kind": "project_test",
                "path": str(repo / "tests" / "test_service.py"),
                "snippet": "sk-test-secret-12345",
            }
        ],
        "provider_raw_output": "must not be copied",
    }
    normalized = runner._normalize_case(runner.CASES[0], response, 1.0, repo)
    encoded = json.dumps(normalized, ensure_ascii=False)
    (output / "case.json").write_text(encoded, encoding="utf-8")

    assert "provider_raw_output" not in encoded
    assert "sk-test-secret-12345" not in encoded
    assert str(repo) not in encoded
    runner.validate_artifact_safety(output, repo)


def test_artifact_safety_checks_decoded_json_values_not_json_escapes(tmp_path: Path):
    output = tmp_path / "artifact"
    output.mkdir()
    safe_value = r"ordinary\literal\backslash"
    (output / "manifest.json").write_text(
        json.dumps({"safe_value": safe_value}, ensure_ascii=False), encoding="utf-8"
    )

    runner.validate_artifact_safety(output, REPO_ROOT)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:8765/engineering/query",
        "https://example.com/api/v1",
        "http://localhost:8765/engineering/query",
    ],
)
def test_artifact_safety_accepts_http_https_and_port_urls(
    tmp_path: Path, endpoint: str
):
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "manifest.json").write_text(
        json.dumps({"endpoint": endpoint}, ensure_ascii=False), encoding="utf-8"
    )

    runner.validate_artifact_safety(output, REPO_ROOT)


def test_real_formal_manifest_shape_safety_preflight(tmp_path: Path):
    output = tmp_path / "artifact"
    output.mkdir()
    manifest = {
        "schema_version": "g11_03_change_impact_manifest_v2",
        "workflow": runner.WORKFLOW_ID,
        "run_id": "g11-03-r3-manifest-preflight",
        "endpoint": "http://127.0.0.1:8765/engineering/query",
        "source_commit": "a" * 40,
        "source_commit_attestation": "operator_declared_and_locally_verified_checkout",
        "project_identity": runner.PROJECT_IDENTITY,
        "knowledge_corpus_id": runner.KNOWLEDGE_CORPUS_ID,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "prompt_version": runner.PRODUCTION_PROMPT_VERSION,
        "prompt_sha256": runner.PRODUCTION_PROMPT_SHA256,
        "repair_prompt_version": runner.REPAIR_PROMPT_VERSION,
        "repair_prompt_sha256": runner.REPAIR_PROMPT_SHA256,
        "max_parse_repairs": runner.MAX_PARSE_REPAIRS,
        "toolset_sha256": runner.TOOLSET_SHA256,
        "registry_size": runner.REGISTRY_SIZE,
        "max_output_tokens": runner.MAX_OUTPUT_TOKENS,
        "provider_network_retries": runner.PROVIDER_NETWORK_RETRIES,
        "budget": runner.BUDGET,
        "required_tools": list(runner.REQUIRED_TOOLS),
        "optional_candidate_tools": list(runner.OPTIONAL_CANDIDATE_TOOLS),
        "diagnostic_target_sequence": list(runner.DIAGNOSTIC_TARGET_SEQUENCE),
        "candidate_source_contract": "changed_files_or_find_tests",
        "accepted_test_in_change_set": {
            case["case_id"]: True for case in runner.CASES
        },
        "forbidden_tools": list(runner.FORBIDDEN_TOOLS),
        "case_ids": [case["case_id"] for case in runner.CASES],
        "target_commits": [case["target_commit"] for case in runner.CASES],
        "absolute_paths_in_artifact": False,
        "provider_raw_responses_recorded": False,
        "cot_recorded": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    runner.validate_artifact_safety(output, REPO_ROOT)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        r"C:\Users\example\secret.txt",
        r"observed C:\Users\example\secret.txt",
        r"path=C:\Users\example\secret.txt",
        r"https://example.test/?path=C:\Users\example\secret.txt",
        str(REPO_ROOT.resolve()),
        r"\\server\share\file.txt",
        "sk-real-looking-test-value",
    ],
)
def test_artifact_safety_rejects_real_semantic_paths_and_secrets(
    tmp_path: Path, unsafe_value: str
):
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "case_results.jsonl").write_text(
        json.dumps({"value": unsafe_value}, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unsafe local path or secret"):
        runner.validate_artifact_safety(output, REPO_ROOT)


def test_artifact_safety_accepts_sanitized_jsonl_and_markdown(tmp_path: Path):
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "case_results.jsonl").write_text(
        json.dumps(
            {
                "path": "<absolute-path>",
                "secret": "<redacted-secret>",
                "root": "<repo>",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "run_report.md").write_text(
        "endpoint: http://127.0.0.1:8765/engineering/query\n"
        "docs: https://example.com/api/v1\n"
        "path: <absolute-path>\nsecret: <redacted-secret>\nroot: <repo>\n",
        encoding="utf-8",
    )

    runner.validate_artifact_safety(output, REPO_ROOT)


@pytest.mark.parametrize(
    "unsafe_value",
    [r"C:\Users\example\secret.txt", r"\\server\share\file.txt"],
)
def test_markdown_artifact_rejects_actual_local_paths(
    tmp_path: Path, unsafe_value: str
):
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "run_report.md").write_text(
        unsafe_value + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unsafe local path or secret"):
        runner.validate_artifact_safety(output, REPO_ROOT)
