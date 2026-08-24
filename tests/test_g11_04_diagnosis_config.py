"""Deterministic contracts for the G11-04 diagnosis/config runner."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import scripts.run_g11_04_diagnosis_config as runner
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
    return repo, _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_fixed_case_identity_and_gold_sources_are_frozen():
    assert [case["case_id"] for case in runner.CASES] == [
        "DC01",
        "DC02",
        "DC03",
        "DC04",
    ]
    assert runner.validate_case_identities() == runner.CASES
    assert [case["focus_path"] for case in runner.CASES] == [
        "api/project_workspace.py",
        "core/engineering_knowledge.py",
        "core/config.py",
        "core/config.py",
    ]
    assert [case["gold_source_paths"] for case in runner.CASES] == [
        ["api/project_workspace.py", "api/app.py"],
        ["core/engineering_knowledge.py", "api/app.py"],
        ["core/config.py", "api/app.py"],
        ["core/config.py", "core/tool_agent/decision_prompt.py"],
    ]
    assert runner.validate_case_identities(git_root=REPO_ROOT) == runner.CASES


def test_required_and_forbidden_tool_contract_is_frozen_without_exact_sequence():
    assert runner.REQUIRED_TOOLS == ("code_search", "read_project_context")
    assert set(runner.FORBIDDEN_TOOLS) == {
        "changed_files",
        "git_diff",
        "find_tests",
        "knowledge_search",
        "calculator",
    }
    assert not hasattr(runner, "DIAGNOSTIC_TARGET_SEQUENCE")
    assert runner.validate_required_and_forbidden_tools() == (
        runner.REQUIRED_TOOLS,
        runner.FORBIDDEN_TOOLS,
    )


def test_product_prompt_repair_cap_budget_registry_and_retry_are_frozen(tmp_path: Path):
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
    assert runner.MAX_OUTPUT_TOKENS == 1200
    assert runner.BUDGET == {
        "max_agent_iterations": 5,
        "max_tool_calls": 4,
        "max_tool_errors": 2,
    }
    assert runner.REGISTRY_SIZE == 7
    assert runner.PROVIDER_NETWORK_RETRIES == 0
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)

    class RetrievalPort:
        supported_strategies = ("bm25",)

        def search(self, query, strategy, top_k):
            return ()

    assert len(build_readonly_tool_registry(tmp_path, RetrievalPort()).list_specs()) == 7


def test_v3_is_not_accepted_as_production_identity():
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


def _metric_case(
    sequence: list[str],
    evidence: list[dict],
    *,
    status: str = "completed",
    iterations: int = 2,
    failure_code: str | None = None,
    parse_categories: list[str] | None = None,
    repair_attempted: bool = False,
    repair_succeeded: bool = False,
) -> dict:
    return {
        "status": status,
        "tool_sequence": sequence,
        "evidence": evidence,
        "iterations": iterations,
        "tool_calls": len(sequence),
        "tool_errors": 0,
        "provider_calls_total": 1,
        "failure_code": failure_code,
        "initial_parse_categories": parse_categories or [],
        "repair_attempted": repair_attempted,
        "repair_succeeded": repair_succeeded,
        "project_code_evidence": bool(
            any(item.get("kind") == "project_code" for item in evidence)
        ),
        "multi_file_evidence": len(
            {
                item.get("path")
                for item in evidence
                if item.get("kind", "").startswith("project_")
            }
        )
        >= 2,
        "behavior_body_visible": runner.behavior_body_visible(evidence),
    }


def test_metrics_cover_evidence_shape_and_do_not_require_one_sequence():
    body = {
        "kind": "project_code",
        "path": "core/config.py",
        "snippet": "def validate(self):\n    if value >= limit:\n        raise ConfigError('bad')",
    }
    cases = [
        _metric_case(
            ["code_search", "read_project_context"],
            [body, {"kind": "project_code", "path": "api/app.py", "snippet": "return"}],
        ),
        _metric_case(
            ["read_project_context", "code_search"],
            [body],
        ),
        _metric_case(
            ["code_search", "read_project_context", "calculator"],
            [{"kind": "project_doc", "path": "README.md", "snippet": "import only"}],
            status="refused",
            failure_code="ACTION_PARSE_FAILED",
            parse_categories=["INVALID_JSON"],
            repair_attempted=True,
        ),
        _metric_case([], [], status="failed", iterations=0),
    ]

    metrics = runner._metrics(cases)

    assert metrics["case_count"] == 4
    assert metrics["completed_cases"] == 2
    assert metrics["code_search_coverage"] == 3
    assert metrics["read_project_context_coverage"] == 3
    assert metrics["required_tool_coverage_rate"] == 0.75
    assert metrics["project_code_evidence_cases"] == 2
    assert metrics["multi_file_evidence_cases"] == 1
    assert metrics["behavior_body_visible_cases"] == 2
    assert metrics["forbidden_tool_calls"] == 1
    assert metrics["non_target_tool_calls"] == 1
    assert metrics["parse_failure_cases"] == 1
    assert metrics["initial_parse_failure_cases"] == 1
    assert metrics["repair_attempted_cases"] == 1
    assert "exact_target_sequence_cases" not in metrics


def test_behavior_body_signal_rejects_import_only_evidence():
    assert not runner.behavior_body_visible(
        [
            {
                "kind": "project_code",
                "path": "core/config.py",
                "snippet": "from core.config import ConfigError",
            }
        ]
    )
    assert runner.behavior_body_visible(
        [
            {
                "kind": "project_code",
                "path": "core/config.py",
                "snippet": "def validate(self):\n    if overlap >= size:\n        raise ConfigError('invalid')",
            }
        ]
    )


def test_normalized_artifact_omits_raw_output_paths_and_secrets(tmp_path: Path):
    repo, _ = _new_git_repo(tmp_path)
    output = tmp_path / "artifact"
    output.mkdir()
    response = {
        "status": "completed",
        "answer": f"repo={repo} key=sk-test-secret-12345",
        "trace": [
            {
                "event_type": "tool_observation",
                "tool_name": "code_search",
                "provider_raw_output": "must not be copied",
            }
        ],
        "evidence": [
            {
                "kind": "project_code",
                "path": str(repo / "core" / "config.py"),
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


def test_artifact_safety_uses_decoded_semantic_json_and_jsonl_values(tmp_path: Path):
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "safe.json").write_text(
        json.dumps({"value": r"ordinary\literal\backslash"}), encoding="utf-8"
    )
    (output / "safe.jsonl").write_text(
        json.dumps(
            {
                "path": "<absolute-path>",
                "secret": "<redacted-secret>",
                "root": "<repo>",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "report.md").write_text(
        "endpoint: http://127.0.0.1:8765/engineering/query\n"
        "path: <absolute-path>\nsecret: <redacted-secret>\n",
        encoding="utf-8",
    )
    runner.validate_artifact_safety(output, REPO_ROOT)


@pytest.mark.parametrize(
    "unsafe_value",
    [
        r"C:\Users\example\secret.txt",
        r"\\server\share\file.txt",
        "sk-real-looking-test-value",
    ],
)
def test_artifact_safety_rejects_absolute_paths_and_secrets(
    tmp_path: Path, unsafe_value: str
):
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "case_results.jsonl").write_text(
        json.dumps({"value": unsafe_value}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsafe local path or secret"):
        runner.validate_artifact_safety(output, REPO_ROOT)
