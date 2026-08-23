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
    FindTestsHandler,
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
    assert all(case["head_ref"] == case["target_commit"] for case in runner.CASES)
    assert all(case["base_ref"] == f"{case['target_commit']}^" for case in runner.CASES)
    assert [case["focus_path"] for case in runner.CASES] == [
        "api/app.py",
        "core/engineering_knowledge.py",
        "core/tool_agent/decision_prompt.py",
        "core/tool_agent/tools/git_change.py",
    ]
    assert runner.validate_case_identities() == runner.CASES


def test_fixed_case_accepted_tests_are_discoverable_by_real_find_tests():
    """Fixed case accepted tests must be reachable through the real Tool contract."""
    handler = FindTestsHandler(REPO_ROOT)

    for case in runner.CASES:
        result = handler.execute({"path": case["focus_path"]})
        candidate_paths = {candidate["path"] for candidate in result["candidates"]}
        accepted_paths = set(case["accepted_test_paths"])
        assert accepted_paths & candidate_paths, (
            f"{case['case_id']} accepted tests are not discoverable for "
            f"{case['focus_path']}: candidates={sorted(candidate_paths)}"
        )


def test_target_commits_exist_in_the_current_checkout():
    assert runner.validate_case_identities(git_root=REPO_ROOT) == runner.CASES


def test_required_and_forbidden_tool_contract_is_frozen():
    assert runner.REQUIRED_TOOLS == (
        "changed_files",
        "git_diff",
        "find_tests",
        "read_project_context",
    )
    assert {"knowledge_search", "calculator"} <= set(runner.FORBIDDEN_TOOLS)


def _metric_case(sequence: list[str], evidence_kinds: list[str]) -> dict:
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
    }


def test_metrics_count_change_test_pairs_and_exact_sequence():
    cases = [
        _metric_case(list(runner.REQUIRED_TOOLS), ["project_change", "project_test"]),
        _metric_case(["changed_files", "git_diff"], ["project_change"]),
        _metric_case(["find_tests", "read_project_context"], ["project_test"]),
        _metric_case(
            [
                "changed_files",
                "git_diff",
                "code_search",
                "find_tests",
                "read_project_context",
            ],
            ["project_change", "project_test"],
        ),
    ]

    metrics = runner._metrics(cases)

    assert metrics["change_evidence_cases"] == 3
    assert metrics["test_evidence_cases"] == 3
    assert metrics["change_test_pair_cases"] == 2
    assert metrics["change_test_pair_rate"] == 0.5
    assert metrics["exact_target_sequence_cases"] == 1
    assert metrics["non_target_tool_calls"] == 1


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
    assert runner.MAX_OUTPUT_TOKENS == 600
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
