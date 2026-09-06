"""Provider-free contracts for ARCH-INTEGRATION-12C Activity observability."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from core.tool_agent.activity import build_tool_activity_event
from evaluation.integration_v7.kind_aware_candidate_runner import (
    CANDIDATE_RUNTIME_COMMIT,
    CANDIDATE_SYSTEM_LABEL,
    _candidate_raw_record,
)
from evaluation.integration_v7.runner import RunnerPreflightError
from evaluation.integration_v7.runner_worker import _run, _safe_activity


def _observation(result=None, error_code=None):
    return SimpleNamespace(result=result or {}, error_code=error_code)


def test_code_search_artifact_kind_is_preserved_only_for_the_public_enum():
    for artifact_kind in ("any", "project_code", "project_doc"):
        event = build_tool_activity_event(
            activity_id="A1",
            iteration=1,
            tool_name="code_search",
            state="started",
            arguments={"query": "runtime", "artifact_kind": artifact_kind},
        )
        assert event.to_dict()["target"] == {
            "query": "runtime",
            "artifact_kind": artifact_kind,
        }

    for artifact_kind in ("unknown", None, 1, [], {}, "secret=not-a-kind", "sk-secret"):
        event = build_tool_activity_event(
            activity_id="A1",
            iteration=1,
            tool_name="code_search",
            state="started",
            arguments={"query": "runtime", "artifact_kind": artifact_kind},
        )
        assert event.to_dict()["target"] == {"query": "runtime"}


def test_code_search_query_and_result_paths_keep_existing_safe_boundaries():
    event = build_tool_activity_event(
        activity_id="A1",
        iteration=1,
        tool_name="code_search",
        state="completed",
        arguments={"query": "runtime", "artifact_kind": "project_code"},
        observation=_observation(
            {
                "matches": [
                    {"path": "src/runtime.py"},
                    {"path": "docs/runtime.md"},
                    {"path": r"C:\private\secret.py"},
                    {"path": "api_key=secret"},
                ]
            }
        ),
    )
    payload = event.to_dict()
    assert payload["target"] == {"query": "runtime", "artifact_kind": "project_code"}
    assert payload["result_summary"] == {
        "match_count": 4,
        "top_paths": ["src/runtime.py", "docs/runtime.md"],
    }
    assert r"C:\private" not in repr(payload)
    assert "secret" not in repr(payload).lower()

    for query in (r"C:\private\runtime.py", "/private/runtime.py", "api_key=secret"):
        blocked = build_tool_activity_event(
            activity_id="A1",
            iteration=1,
            tool_name="code_search",
            state="started",
            arguments={"query": query, "artifact_kind": "project_code"},
        )
        assert blocked.to_dict()["target"] == {
            "artifact_kind": "project_code"
        }


def test_read_project_context_activity_keeps_repo_path_and_evidence_ids_only():
    event = build_tool_activity_event(
        activity_id="A2",
        iteration=2,
        tool_name="read_project_context",
        state="completed",
        arguments={
            "path": "src/runtime.py",
            "line": 10,
            "context_lines": 3,
            "prompt": "DO_NOT_LEAK",
        },
        observation=_observation(
            {
                "path": "src/runtime.py",
                "start_line": 8,
                "end_line": 12,
                "lines": ["DO_NOT_LEAK"],
            }
        ),
        evidence_ids_added=("E1", "invalid", "E2", "E1"),
    )
    assert event.to_dict() == {
        "type": "activity",
        "activity_id": "A2",
        "iteration": 2,
        "tool_name": "read_project_context",
        "state": "completed",
        "purpose": "读取项目上下文，确认实际实现",
        "target": {"path": "src/runtime.py", "line": 10, "context_lines": 3},
        "result_summary": {
            "path": "src/runtime.py",
            "start_line": 8,
            "end_line": 12,
        },
        "evidence_ids_added": ["E1", "E2"],
    }


def test_worker_safe_activity_projection_is_bounded_and_has_no_raw_fields():
    events = [
        build_tool_activity_event(
            activity_id="A1",
            iteration=1,
            tool_name="code_search",
            state="started",
            arguments={
                "query": "runtime",
                "artifact_kind": "project_doc",
                "prompt": "DO_NOT_LEAK",
                "raw_observation": "DO_NOT_LEAK",
                "secret": "sk-123456789012345",
            },
        ),
        build_tool_activity_event(
            activity_id="A1",
            iteration=1,
            tool_name="code_search",
            state="completed",
            arguments={"query": "runtime", "artifact_kind": "project_doc"},
            observation=_observation(
                {"matches": [{"path": "docs/runtime.md"}, {"path": r"C:\private\x.py"}]}
            ),
        ),
        build_tool_activity_event(
            activity_id="A2",
            iteration=2,
            tool_name="read_project_context",
            state="completed",
            arguments={"path": "src/runtime.py", "line": 1, "context_lines": 2},
            observation=_observation(
                {"path": "src/runtime.py", "start_line": 1, "end_line": 2}
            ),
            evidence_ids_added=("E1",),
        ),
    ]
    payload = _safe_activity(events + events * 30)
    assert len(payload) == 64
    assert payload[0]["target"] == {"query": "runtime", "artifact_kind": "project_doc"}
    assert payload[1]["result_summary"] == {
        "match_count": 2,
        "top_paths": ["docs/runtime.md"],
    }
    assert payload[2]["evidence_ids_added"] == ["E1"]
    serialized = repr(payload)
    for forbidden in ("prompt", "raw_observation", "DO_NOT_LEAK", "sk-123456789012345", "C:\\private"):
        assert forbidden not in serialized
    assert all("arguments" not in event and "observation" not in event for event in payload)


def test_worker_activity_sink_and_safe_payload_wiring_is_observational():
    source = inspect.getsource(_run)
    assert source.count("activity_sink=activities.append") == 2
    assert '"activity": _safe_activity(activities)' in source
    activity_source = inspect.getsource(_safe_activity)
    assert "to_dict" in activity_source
    assert "safe_artifact" in activity_source
    assert "prompt" not in activity_source.lower()


def test_candidate_raw_record_persists_only_the_bounded_activity_projection():
    activity = _safe_activity(
        [
            build_tool_activity_event(
                activity_id="A1",
                iteration=1,
                tool_name="code_search",
                state="started",
                arguments={"query": "runtime", "artifact_kind": "project_code"},
            )
        ]
    )
    raw = _candidate_raw_record(
        {"case_id": "v7d001", "task_family": "repo_only"},
        {"system": CANDIDATE_SYSTEM_LABEL, "run_order": 1, "case_order": 1},
        {"run_validity": "VALID", "activity": activity},
        {"tool": "code_search", "version": "code_search_v5"},
    )
    assert raw["candidate_runtime_commit"] == CANDIDATE_RUNTIME_COMMIT
    assert raw["activity"] == activity
    assert raw["activity"][0]["target"]["artifact_kind"] == "project_code"
    assert "arguments" not in raw
    assert "observation" not in raw


def test_activity_projection_does_not_change_runtime_control_contracts():
    assert "5/4/2" not in inspect.getsource(_safe_activity)
    assert "finalization" not in inspect.getsource(_safe_activity).lower()
    with pytest.raises(RunnerPreflightError):
        # The existing safe serializer remains the boundary for forbidden raw fields.
        from evaluation.integration_v7.runner import safe_artifact

        safe_artifact({"raw_provider_response": "DO_NOT_LEAK"})
