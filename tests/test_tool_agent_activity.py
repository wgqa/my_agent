"""Deterministic contracts for post-G12 rich Tool Activity events."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from core.tool_agent.activity import (
    MAX_ACTIVITY_TEXT_LENGTH,
    EvidenceAddedActivity,
    RunStartedActivity,
    ToolActivityEvent,
    VerificationBlockedActivity,
    build_tool_activity_event,
)
from core.tool_agent.runtime_models import EngineeringEvidence, KnowledgeEvidence


@pytest.mark.parametrize(
    ("tool_name", "arguments", "result", "expected_target", "expected_summary"),
    [
        (
            "knowledge_search",
            {"query": "engineering evidence"},
            {
                "matches": [
                    {"source_name": "guides/evidence.md"},
                    {"source_name": "guides/runtime.md"},
                ]
            },
            {"query": "engineering evidence"},
            {"match_count": 2, "top_sources": ["guides/evidence.md", "guides/runtime.md"]},
        ),
        (
            "code_search",
            {"query": "finalize"},
            {"matches": [{"path": "core/runtime.py"}, {"path": "api/app.py"}]},
            {"query": "finalize"},
            {"match_count": 2, "top_paths": ["core/runtime.py", "api/app.py"]},
        ),
        (
            "read_project_context",
            {"path": "core/runtime.py", "line": 42, "context_lines": 3},
            {"path": "core/runtime.py", "start_line": 39, "end_line": 45, "lines": []},
            {"path": "core/runtime.py", "line": 42, "context_lines": 3},
            {"path": "core/runtime.py", "start_line": 39, "end_line": 45},
        ),
        (
            "changed_files",
            {"mode": "working_tree"},
            {
                "changes": [{"path": "core/runtime.py"}, {"path": "tests/test_runtime.py"}],
                "returned_count": 2,
                "truncated": False,
            },
            {"mode": "working_tree"},
            {"file_count": 2, "top_paths": ["core/runtime.py", "tests/test_runtime.py"], "truncated": False},
        ),
        (
            "git_diff",
            {"path": "core/runtime.py", "mode": "commit_range", "base_ref": "hidden"},
            {
                "path": "core/runtime.py",
                "mode": "commit_range",
                "truncated": True,
                "diff": "DO_NOT_LEAK",
                "start_line": 1,
                "end_line": 99,
            },
            {"path": "core/runtime.py", "mode": "commit_range"},
            {"path": "core/runtime.py", "mode": "commit_range", "truncated": True},
        ),
        (
            "find_tests",
            {"path": "core/runtime.py"},
            {
                "candidates": [{"path": "tests/test_runtime.py"}],
                "returned_count": 1,
                "truncated": False,
            },
            {"path": "core/runtime.py"},
            {"test_file_count": 1, "top_paths": ["tests/test_runtime.py"], "truncated": False},
        ),
        (
            "calculator",
            {"expression": "6 * 7"},
            {"value": 42},
            {"expression": "6 * 7"},
            {"status": "completed", "result_preview": 42},
        ),
    ],
)
def test_every_product_tool_has_a_bounded_safe_summary(
    tool_name,
    arguments,
    result,
    expected_target,
    expected_summary,
):
    event = build_tool_activity_event(
        activity_id="A1",
        iteration=1,
        tool_name=tool_name,
        state="completed",
        arguments=arguments,
        observation=SimpleNamespace(result=result, error_code=None),
    )

    payload = event.to_dict()
    assert payload["target"] == expected_target
    assert payload["result_summary"] == expected_summary
    assert "DO_NOT_LEAK" not in repr(payload)


def test_activity_models_are_immutable_and_filter_directly_supplied_private_data():
    target = {
        "query": "runtime",
        "prompt": "DO_NOT_LEAK",
        "path": "src/app.py",
    }
    summary = {
        "top_paths": ["src/app.py", r"C:\private\source.py"],
        "raw_output": "DO_NOT_LEAK",
    }
    event = ToolActivityEvent(
        activity_id="A1",
        iteration=1,
        tool_name="code_search",
        state="completed",
        purpose="Locate public source",
        target=target,
        result_summary=summary,
    )
    target["query"] = "changed"
    summary["top_paths"].append("tests/changed.py")

    assert event.to_dict()["target"] == {"query": "runtime"}
    assert event.to_dict()["result_summary"] == {"top_paths": ["src/app.py"]}
    with pytest.raises(TypeError):
        event.target["query"] = "changed"
    with pytest.raises(FrozenInstanceError):
        event.state = "error"


def test_relative_posix_paths_are_kept_but_absolute_and_sensitive_targets_are_omitted():
    event = build_tool_activity_event(
        activity_id="A1",
        iteration=1,
        tool_name="code_search",
        state="started",
        arguments={"query": "src/app.py agent-framework/finalization.md"},
    )
    assert event.to_dict()["target"] == {
        "query": "src/app.py agent-framework/finalization.md"
    }

    for query in (r"C:\private\source.py", "/private/source.py", "api_key=secret"):
        blocked = build_tool_activity_event(
            activity_id="A1",
            iteration=1,
            tool_name="code_search",
            state="started",
            arguments={"query": query},
        )
        assert "target" not in blocked.to_dict()

    cleaned = build_tool_activity_event(
        activity_id="A1",
        iteration=1,
        tool_name="calculator",
        state="started",
        arguments={"expression": "1\x00 + 1"},
    )
    assert cleaned.to_dict()["target"]["expression"] == "1 + 1"
    assert len(cleaned.to_dict()["target"]["expression"]) <= MAX_ACTIVITY_TEXT_LENGTH


def test_error_activity_contains_only_the_allowlisted_error_code():
    event = build_tool_activity_event(
        activity_id="A3",
        iteration=2,
        tool_name="find_tests",
        state="error",
        arguments={"path": "src/service.py"},
        observation=SimpleNamespace(error_code="TOOL_EXECUTION_FAILED"),
    )

    assert event.to_dict() == {
        "type": "activity",
        "activity_id": "A3",
        "iteration": 2,
        "tool_name": "find_tests",
        "state": "error",
        "purpose": "定位与目标实现相关的测试",
        "target": {"path": "src/service.py"},
        "result_summary": {"status": "error"},
        "error_code": "TOOL_EXECUTION_FAILED",
    }


def test_activity_lifecycle_fields_cannot_be_mixed():
    with pytest.raises(ValueError, match="started activity"):
        ToolActivityEvent(
            activity_id="A1",
            iteration=1,
            tool_name="calculator",
            state="started",
            purpose="Start calculation",
            result_summary={"status": "completed"},
        )
    with pytest.raises(ValueError, match="completed activity"):
        ToolActivityEvent(
            activity_id="A1",
            iteration=1,
            tool_name="calculator",
            state="completed",
            purpose="Finish calculation",
            error_code="TOOL_EXECUTION_FAILED",
        )
    with pytest.raises(ValueError, match="error activity"):
        ToolActivityEvent(
            activity_id="A1",
            iteration=1,
            tool_name="calculator",
            state="error",
            purpose="Calculation failed",
            evidence_ids_added=("E1",),
        )


def test_evidence_added_events_expose_only_public_evidence_identity():
    knowledge = KnowledgeEvidence(
        evidence_id="E1",
        kind="knowledge",
        source_name="guides/evidence.md",
        chunk_id="chunk-1",
        score=0.9,
        rank=1,
        snippet="DO_NOT_LEAK",
    )
    project_evidence = [
        EngineeringEvidence(
            evidence_id=f"E{index}",
            kind=kind,
            path="tests/test_service.py" if kind == "project_test" else "src/service.py",
            start_line=10,
            end_line=12,
            snippet="DO_NOT_LEAK",
        )
        for index, kind in enumerate(
            ("project_code", "project_doc", "project_change", "project_test"),
            start=2,
        )
    ]

    knowledge_payload = EvidenceAddedActivity.from_public_evidence(knowledge).to_dict()
    assert knowledge_payload == {
        "type": "evidence_added",
        "evidence_id": "E1",
        "kind": "knowledge",
        "source_name": "guides/evidence.md",
    }
    assert "DO_NOT_LEAK" not in repr(knowledge_payload)
    for evidence in project_evidence:
        payload = EvidenceAddedActivity.from_public_evidence(evidence).to_dict()
        assert payload == {
            "type": "evidence_added",
            "evidence_id": evidence.evidence_id,
            "kind": evidence.kind,
            "path": evidence.path,
            "start_line": 10,
            "end_line": 12,
        }
        assert "DO_NOT_LEAK" not in repr(payload)


def test_unrepresentable_legacy_evidence_is_omitted_by_the_safe_factory():
    long_path = "src/" + "a" * 121 + ".py"
    long_source_name = "knowledge/" + "b" * 121 + ".md"
    project_evidence = EngineeringEvidence(
        evidence_id="E1",
        kind="project_code",
        path=long_path,
        start_line=1,
        end_line=1,
        snippet="public source evidence",
    )
    knowledge_evidence = KnowledgeEvidence(
        evidence_id="E2",
        kind="knowledge",
        source_name=long_source_name,
        chunk_id="chunk-1",
        score=0.9,
        rank=1,
        snippet="public knowledge evidence",
    )

    for evidence in (project_evidence, knowledge_evidence):
        with pytest.raises(ValueError):
            EvidenceAddedActivity.from_public_evidence(evidence)
        assert EvidenceAddedActivity.try_from_public_evidence(evidence) is None


def test_run_and_verification_activities_are_public_and_deterministic():
    assert RunStartedActivity(available_tool_count=7).to_dict() == {
        "type": "run_started",
        "execution_model": "single_agent",
        "available_tool_count": 7,
    }
    verification = VerificationBlockedActivity(
        iteration=3,
        missing_evidence_kinds=("project_test", "not_public", "project_test"),
    )
    assert verification.to_dict() == {
        "type": "verification",
        "state": "blocked",
        "iteration": 3,
        "missing_evidence_kinds": ["project_test"],
    }
