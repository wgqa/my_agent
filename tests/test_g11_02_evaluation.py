"""Contracts for reproducible G11-02 run provenance and A/B comparison."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import compare_g11_02_theory_code as comparator
from scripts import run_g11_02_theory_code as runner


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_SHA = "a" * 40
POST_SHA = "b" * 40
TOOLSET_SHA = "c" * 64
BUDGET = {"max_agent_iterations": 5, "max_tool_calls": 4, "max_tool_errors": 2}


def test_invalid_39_char_source_commit_fails_before_http(monkeypatch, tmp_path):
    called = False

    def fail_http(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("HTTP must not be called")

    monkeypatch.setattr(runner, "_post_json", fail_http)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_g11_02_theory_code.py",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "invalid",
            "--source-commit",
            "540b9bc674a76f535947179329bee572fdb4148",
            "--prompt-version",
            "tool_agent_decision_prompt_v3",
            "--prompt-sha256",
            runner.KNOWN_PROMPT_IDENTITIES["tool_agent_decision_prompt_v3"],
        ],
    )
    with pytest.raises(ValueError, match="40 hexadecimal"):
        runner.main()
    assert called is False


def test_valid_40_char_source_commit_is_verified_against_git_checkout():
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    assert len(head) == 40
    assert runner.validate_source_commit(head, git_root=REPO_ROOT) == head


@pytest.mark.parametrize(
    "bad_sha",
    ["a" * 63, "a" * 65, "g" * 64],
)
def test_prompt_sha256_validation_rejects_bad_length_or_hex(bad_sha):
    with pytest.raises(ValueError, match="64 hexadecimal"):
        runner.validate_prompt_identity("tool_agent_decision_prompt_v3", bad_sha)


def test_prompt_identity_requires_explicit_known_pair():
    with pytest.raises(ValueError, match="do not match"):
        runner.validate_prompt_identity(
            "tool_agent_decision_prompt_v3", "b" * 64
        )


def test_fixed_cases_store_full_gold_obligations():
    assert all(
        isinstance(obligation, dict)
        and isinstance(obligation.get("id"), str)
        and isinstance(obligation.get("description"), str)
        and obligation["description"]
        for case in runner.CASES
        for obligation in case["obligations"]
    )


def _manifest(run_id, prompt_version, prompt_sha, corpus="870e5864df67", source=BASELINE_SHA):
    return {
        "run_id": run_id,
        "source_commit": source,
        "project_identity": "my_agent_repository",
        "knowledge_corpus_id": corpus,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_sha,
        "toolset_sha256": TOOLSET_SHA,
        "budget": BUDGET,
        "case_ids": ["TC01", "TC02"],
    }


def _case(case_id, sequence, evidence_kinds, status="completed"):
    return {
        "case_id": case_id,
        "status": status,
        "tool_sequence": sequence,
        "evidence_kinds": evidence_kinds,
        "tool_calls_used": len(sequence),
        "iterations_used": len(sequence) + 1,
        "evidence": [{"kind": kind} for kind in evidence_kinds],
    }


def _write_run(directory, manifest, cases):
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (directory / "case_results.jsonl").write_text(
        "\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8"
    )


def test_comparator_generates_comparable_pair_and_per_case_report(tmp_path):
    baseline = tmp_path / "baseline"
    post = tmp_path / "post"
    output = tmp_path / "comparison"
    baseline_cases = [
        _case("TC01", ["code_search"], ["project_code"]),
        _case("TC02", ["code_search", "read_project_context"], ["project_code"]),
    ]
    post_cases = [
        _case("TC01", ["knowledge_search", "code_search"], ["knowledge"]),
        _case("TC02", ["knowledge_search", "read_project_context"], ["knowledge", "project_code"]),
    ]
    _write_run(
        baseline,
        _manifest(
            "baseline",
            comparator.BASELINE_PROMPT_VERSION,
            comparator.BASELINE_PROMPT_SHA256,
        ),
        baseline_cases,
    )
    _write_run(
        post,
        _manifest(
            "post",
            comparator.POST_PROMPT_VERSION,
            comparator.POST_PROMPT_SHA256,
            source=POST_SHA,
        ),
        post_cases,
    )

    result = comparator.compare_runs(baseline, post, output)

    assert result == output
    comparison_manifest = json.loads(
        (output / "comparison_manifest.json").read_text(encoding="utf-8")
    )
    assert comparison_manifest["baseline_run_id"] == "baseline"
    assert comparison_manifest["post_run_id"] == "post"
    assert comparison_manifest["correctness_scored"] is False
    report = (output / "comparison_report.md").read_text(encoding="utf-8")
    assert "baseline tool sequence: `code_search`" in report
    assert "post tool sequence: `knowledge_search -> code_search`" in report
    assert "baseline evidence kinds: `project_code`" in report
    assert "post evidence kinds: `knowledge, project_code`" in report


def test_comparator_rejects_corpus_mismatch(tmp_path):
    baseline = tmp_path / "baseline"
    post = tmp_path / "post"
    _write_run(
        baseline,
        _manifest(
            "baseline",
            comparator.BASELINE_PROMPT_VERSION,
            comparator.BASELINE_PROMPT_SHA256,
        ),
        [_case("TC01", ["code_search"], ["project_code"]), _case("TC02", [], [])],
    )
    _write_run(
        post,
        _manifest(
            "post",
            comparator.POST_PROMPT_VERSION,
            comparator.POST_PROMPT_SHA256,
            corpus="different-corpus",
            source=POST_SHA,
        ),
        [_case("TC01", ["knowledge_search"], ["knowledge"]), _case("TC02", [], [])],
    )
    with pytest.raises(comparator.ComparisonValidationError, match="knowledge_corpus_id"):
        comparator.compare_runs(baseline, post, tmp_path / "comparison")
