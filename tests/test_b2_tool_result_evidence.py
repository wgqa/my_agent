"""Offline B2 component checks; these do not represent Agent/model success."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from core.engineering_requirements import (
    CHANGE_TEST_V1,
    NO_ADDITIONAL_REQUIREMENT,
    PROJECT_CODE_V1,
    PROJECT_TEST_V1,
    EngineeringEvidenceRequirement,
    evaluate_evidence_requirement,
)
from core.engineering_verification import (
    ANSWER_BINDING_STATUS_INVALID,
    ANSWER_BINDING_STATUS_INCOMPLETE,
    ANSWER_BINDING_STATUS_VALID,
    _evaluate_answer_evidence_binding,
    _strict_evidence_sequence,
)
from api.schemas import ToolAgentEvidence
from core.tool_agent.models import ToolCall, TOOL_EXECUTION_FAILED, ToolObservation
from core.tool_agent.runtime import (
    _evidence_from_changed_files,
    _evidence_from_code_search,
    _evidence_from_find_tests,
    _evidence_reference_catalog,
    _evidence_from_tool_result,
    _normalize_initial_evidence,
)
from core.tool_agent.runtime_models import EngineeringEvidence, ToolResultEvidence


_HASH_A = "a" * 64
_HASH_B = "b" * 64
_EMPTY_ARGUMENTS_JSON = "{}"
_EMPTY_ARGUMENTS_HASH = hashlib.sha256(_EMPTY_ARGUMENTS_JSON.encode("utf-8")).hexdigest()


def _requirement(profile):
    from core.engineering_requirements import FROZEN_PROFILE_SPECS

    groups, paths = FROZEN_PROFILE_SPECS[profile]
    return EngineeringEvidenceRequirement(profile, groups, paths)


def _observation(tool_name, result, *, call_id="call_test", status="ok"):
    if status == "ok":
        return ToolObservation(call_id, tool_name, status, result, None)
    return ToolObservation(call_id, tool_name, status, None, TOOL_EXECUTION_FAILED)


def _tool_evidence(
    *,
    evidence_id="E1",
    kind="project_code",
    tool_name="code_search",
    granularity="locator",
    completeness="complete",
    path="src/cache.py",
    line=9,
    scope_paths=("src/cache.py",),
    status_entries=None,
):
    if granularity == "status_list" and status_entries is None:
        status_entries = tuple((path, "modified", None) for path in scope_paths)
    return ToolResultEvidence(
        evidence_id=evidence_id,
        kind=kind,
        tool_name=tool_name,
        call_id="call_test",
        tool_version="contract_v1",
        arguments_json=_EMPTY_ARGUMENTS_JSON,
        arguments_sha256=_EMPTY_ARGUMENTS_HASH,
        result_sha256=_HASH_B,
        granularity=granularity,
        completeness=completeness,
        scope=f"{tool_name} result for {path or 'list'}",
        scope_paths=scope_paths,
        path=path,
        start_line=line if path else None,
        end_line=line if path else None,
        status_entries=() if status_entries is None else status_entries,
    )


def test_code_search_creates_locator_with_call_and_content_identity():
    call = ToolCall.create(
        "code_search",
        {"query": "TAIL_POLICY", "artifact_kind": "project_doc"},
    )
    observation = ToolObservation(
        call.call_id,
        "code_search",
        "ok",
        {"matches": [{"path": "docs/late.md", "line": 161, "text": "TAIL_POLICY = 8"}]},
        None,
    )
    evidence = _evidence_from_code_search(
        observation, call.arguments_copy(), "code_search_v7"
    )

    assert len(evidence) == 1
    item = evidence[0]
    assert item.kind == "project_doc"
    assert item.granularity == "locator"
    assert item.completeness == "complete"
    assert item.requirement_eligible is False
    assert item.call_id == call.call_id
    assert item.arguments_sha256 != _HASH_A
    assert item.result_sha256 != _HASH_B
    assert (item.path, item.start_line, item.end_line) == ("docs/late.md", 161, 161)
    reference = _evidence_reference_catalog([item])[0].to_dict()
    assert reference["tool_name"] == "code_search"
    assert reference["call_id"] == call.call_id
    assert reference["granularity"] == "locator"
    assert reference["completeness"] == "complete"
    assert reference["requirement_eligible"] is False
    assert reference["scope_paths"] == ["docs/late.md"]


def test_code_search_at_its_output_cap_is_marked_partial():
    arguments = {"query": "needle"}
    matches = [
        {"path": f"docs/doc_{index}.md", "line": index + 1, "text": "needle"}
        for index in range(10)
    ]
    items = _evidence_from_code_search(
        _observation("code_search", {"matches": matches}),
        arguments,
        "code_search_v7",
    )
    assert len(items) == 10
    assert all(item.completeness == "partial" for item in items)


def test_path_escape_from_an_observation_never_becomes_evidence():
    for unsafe_path in (
        "../outside.py",
        "/other-project/src/app.py",
        "C:/other-project/src/app.py",
        "src//app.py",
        "src/./app.py",
    ):
        items = _evidence_from_code_search(
            _observation(
                "code_search",
                {"matches": [{"path": unsafe_path, "line": 1, "text": "x"}]},
            ),
            {"query": "x"},
            "code_search_v7",
        )
        assert items == ()


def test_tool_result_adapter_rejects_failed_or_cross_call_observation():
    call = ToolCall.create("changed_files", {"mode": "working_tree"})
    failed = _observation("changed_files", None, status="error")
    assert _evidence_from_tool_result(failed, call, "changed_files_v1") == ()

    other_call = _observation(
        "changed_files",
        {
            "changes": [{"path": "src/cache.py", "status": "modified"}],
            "total_count": 1,
            "returned_count": 1,
            "truncated": False,
            "omitted_sensitive_count": 0,
        },
        call_id="call_other",
    )
    assert _evidence_from_tool_result(other_call, call, "changed_files_v1") == ()


def test_changed_files_is_status_list_and_preserves_rename_and_completeness():
    arguments = {"mode": "working_tree"}
    observation = _observation(
        "changed_files",
        {
            "changes": [
                {"path": "src/new.py", "status": "renamed", "old_path": "src/old.py"},
                {"path": "README.md", "status": "modified"},
            ],
            "total_count": 2,
            "returned_count": 2,
            "truncated": False,
            "omitted_sensitive_count": 0,
        },
    )
    item = _evidence_from_changed_files(observation, arguments, "changed_files_v1")
    assert item is not None
    assert item.kind == "project_change"
    assert item.granularity == "status_list"
    assert item.completeness == "complete"
    assert item.scope_paths == ("src/new.py", "src/old.py", "README.md")
    assert item.status_entries == (
        ("src/new.py", "renamed", "src/old.py"),
        ("README.md", "modified", None),
    )
    assert item.requirement_eligible is False

    partial = _observation(
        "changed_files",
        {
            "changes": [{"path": "src/new.py", "status": "modified"}],
            "total_count": 3,
            "returned_count": 1,
            "truncated": True,
            "omitted_sensitive_count": 1,
        },
    )
    partial_item = _evidence_from_changed_files(partial, arguments, "changed_files_v1")
    assert partial_item is not None
    assert partial_item.completeness == "partial"
    assert partial_item.requirement_eligible is False


def test_find_tests_is_candidate_only_and_truncation_stays_partial():
    arguments = {"path": "src/cache.py"}
    result = {
        "candidates": [
            {"path": "tests/test_cache.py", "line": 4, "reasons": ["filename_match"]}
        ],
        "returned_count": 1,
        "truncated": False,
        "omitted_sensitive_count": 0,
    }
    items = _evidence_from_find_tests(_observation("find_tests", result), arguments, "find_tests_v1")
    assert len(items) == 1
    item = items[0]
    assert item.kind == "project_test"
    assert item.granularity == "candidate"
    assert item.scope_paths == ("src/cache.py", "tests/test_cache.py")
    assert item.requirement_eligible is False

    result["truncated"] = True
    partial = _evidence_from_find_tests(
        _observation("find_tests", result), arguments, "find_tests_v1"
    )
    assert partial[0].completeness == "partial"
    assert partial[0].requirement_eligible is False


def test_tool_granularity_and_completeness_are_an_independent_gate():
    requirement_eligible_but_locator = {
        "kind": "project_code",
        "granularity": "locator",
        "completeness": "complete",
        "requirement_eligible": True,
        "path": "src/cache.py",
    }
    state = evaluate_evidence_requirement(
        _requirement(PROJECT_CODE_V1), [requirement_eligible_but_locator]
    )
    assert state.satisfied is False
    assert state.evidence_kind_counts["project_code"] == 0

    locator = _tool_evidence()
    code_state = evaluate_evidence_requirement(_requirement(PROJECT_CODE_V1), [locator])
    assert code_state.satisfied is False
    assert code_state.evidence_kind_counts["project_code"] == 0

    candidate = _tool_evidence(
        kind="project_test",
        tool_name="find_tests",
        granularity="candidate",
        path="tests/test_cache.py",
        line=4,
        scope_paths=("src/cache.py", "tests/test_cache.py"),
    )
    test_state = evaluate_evidence_requirement(_requirement(PROJECT_TEST_V1), [candidate])
    assert test_state.satisfied is False
    assert test_state.evidence_kind_counts["project_test"] == 0

    status_list = _tool_evidence(
        kind="project_change",
        tool_name="changed_files",
        granularity="status_list",
        path=None,
        line=None,
        scope_paths=("src/cache.py",),
    )
    change_state = evaluate_evidence_requirement(_requirement(CHANGE_TEST_V1), [status_list])
    assert change_state.satisfied is False
    assert change_state.evidence_kind_counts["project_change"] == 0


def test_complete_diff_can_fill_change_shape_but_truncated_diff_cannot():
    complete = _tool_evidence(
        kind="project_change",
        tool_name="git_diff",
        granularity="diff",
    )
    assert complete.requirement_eligible is True
    test_body = EngineeringEvidence(
        evidence_id="E2",
        kind="project_test",
        path="tests/test_cache.py",
        start_line=1,
        end_line=2,
        snippet="assert cache()",
    )
    assert evaluate_evidence_requirement(
        _requirement(CHANGE_TEST_V1), [complete, test_body]
    ).satisfied is True

    partial = _tool_evidence(
        kind="project_change",
        tool_name="git_diff",
        granularity="diff",
        completeness="partial",
    )
    assert partial.requirement_eligible is False
    assert evaluate_evidence_requirement(
        _requirement(CHANGE_TEST_V1), [partial, test_body]
    ).satisfied is False


def test_no_requirement_locator_cannot_bind_a_final_conclusion():
    locator = _tool_evidence()
    requirement = _requirement(NO_ADDITIONAL_REQUIREMENT)

    bare_overclaim = _evaluate_answer_evidence_binding(
        requirement,
        (locator,),
        "The implementation correctly handles every cache failure. [E1]",
    )
    assert bare_overclaim[0] == ANSWER_BINDING_STATUS_INCOMPLETE

    precise_location_only = _evaluate_answer_evidence_binding(
        requirement,
        (locator,),
        "位置：src/cache.py:9 [E1]",
    )
    locator_with_body_claim = _evaluate_answer_evidence_binding(
        requirement,
        (locator,),
        "src/cache.py:9 correctly handles every cache failure [E1]",
    )
    assert precise_location_only[0] == ANSWER_BINDING_STATUS_VALID
    assert locator_with_body_claim[0] == ANSWER_BINDING_STATUS_INCOMPLETE


def test_no_requirement_candidate_and_status_list_cannot_masquerade_as_body_or_diff():
    requirement = _requirement(NO_ADDITIONAL_REQUIREMENT)
    candidate = _tool_evidence(
        kind="project_test",
        tool_name="find_tests",
        granularity="candidate",
        path="tests/test_cache.py",
        line=4,
        scope_paths=("src/cache.py", "tests/test_cache.py"),
    )
    status_list = _tool_evidence(
        kind="project_change",
        tool_name="changed_files",
        granularity="status_list",
        path=None,
        line=None,
        scope_paths=("src/cache.py",),
    )
    candidate_claim = _evaluate_answer_evidence_binding(
        requirement,
        (candidate,),
        "工具返回的候选测试位置：tests/test_cache.py:4 [E1]",
    )
    candidate_overclaim = _evaluate_answer_evidence_binding(
        requirement,
        (candidate,),
        "tests/test_cache.py:4 test passes and covers cache invalidation [E1]",
    )
    test_body = EngineeringEvidence(
        evidence_id="E2",
        kind="project_test",
        path="tests/test_cache.py",
        start_line=4,
        end_line=8,
        snippet="def test_cache(): assert cache()",
    )
    candidate_with_body = _evaluate_answer_evidence_binding(
        requirement,
        (candidate, test_body),
        "工具返回的候选测试位置：tests/test_cache.py:4 [E1]\n"
        "Source body: tests/test_cache.py [E2].",
    )
    status_claim = _evaluate_answer_evidence_binding(
        requirement,
        (status_list,),
        "src/cache.py — modified [E1]",
    )
    status_overclaim = _evaluate_answer_evidence_binding(
        requirement,
        (status_list,),
        "src/cache.py — modified; the implementation fixes every cache failure [E1]",
    )
    assert candidate_claim[0] == ANSWER_BINDING_STATUS_VALID
    assert candidate_with_body[0] == ANSWER_BINDING_STATUS_VALID
    assert candidate_overclaim[0] == ANSWER_BINDING_STATUS_INCOMPLETE
    assert status_claim[0] == ANSWER_BINDING_STATUS_VALID
    assert status_overclaim[0] == ANSWER_BINDING_STATUS_INCOMPLETE


def test_complete_changed_files_status_list_binds_only_the_exact_complete_inventory():
    status_list = _tool_evidence(
        kind="project_change",
        tool_name="changed_files",
        granularity="status_list",
        completeness="complete",
        path=None,
        line=None,
        scope_paths=("src/new.py", "src/old.py", "README.md"),
        status_entries=(
            ("src/new.py", "renamed", "src/old.py"),
            ("README.md", "modified", None),
        ),
    )
    requirement = _requirement(NO_ADDITIONAL_REQUIREMENT)
    full_inventory = (
        "变更文件清单：\n"
        "src/old.py -> src/new.py — renamed [E1]\n"
        "README.md — modified [E1]"
    )
    omitted_entry = "README.md — modified [E1]"
    incorrect_status = (
        "src/old.py -> src/new.py — renamed [E1]\n"
        "README.md — deleted [E1]"
    )
    assert _evaluate_answer_evidence_binding(requirement, (status_list,), full_inventory)[0] == ANSWER_BINDING_STATUS_VALID
    assert _evaluate_answer_evidence_binding(requirement, (status_list,), omitted_entry)[0] == ANSWER_BINDING_STATUS_INCOMPLETE
    assert _evaluate_answer_evidence_binding(requirement, (status_list,), incorrect_status)[0] == ANSWER_BINDING_STATUS_INCOMPLETE


def test_complete_empty_changed_files_inventory_can_only_say_there_are_no_visible_changes():
    call = ToolCall.create("changed_files", {"mode": "working_tree"})
    observation = ToolObservation(
        call.call_id,
        "changed_files",
        "ok",
        {
            "changes": [],
            "total_count": 0,
            "returned_count": 0,
            "truncated": False,
            "omitted_sensitive_count": 0,
        },
        None,
    )
    item = _evidence_from_tool_result(observation, call, "changed_files_v1")[0]
    assert item.completeness == "complete"
    assert item.scope_paths == ()
    assert item.status_entries == ()
    reference = _evidence_reference_catalog([item])[0]
    assert reference.completeness == "complete"
    assert reference.scope_paths == ()
    answer = "当前没有可见变更 [E1]"
    assert _evaluate_answer_evidence_binding(
        _requirement(NO_ADDITIONAL_REQUIREMENT), (item,), answer
    )[0] == ANSWER_BINDING_STATUS_VALID
    assert ToolAgentEvidence(**item.to_dict()).scope_paths == []
    assert _evaluate_answer_evidence_binding(
        _requirement(NO_ADDITIONAL_REQUIREMENT),
        (item,),
        "当前没有可见变更，因此实现逻辑正确 [E1]",
    )[0] == ANSWER_BINDING_STATUS_INCOMPLETE


def test_complete_locator_and_candidate_batches_require_exact_location_rows_only():
    first = _tool_evidence(evidence_id="E1")
    second = replace(
        first,
        evidence_id="E2",
        path="src/session.py",
        scope_paths=("src/session.py",),
        scope="literal search hit at src/session.py:18",
        start_line=18,
        end_line=18,
    )
    requirement = _requirement(NO_ADDITIONAL_REQUIREMENT)
    partial_locator_answer = "位置：src/cache.py:9 [E1]"
    full_locator_answer = "位置：src/cache.py:9 [E1]\n位置：src/session.py:18 [E2]"
    assert _evaluate_answer_evidence_binding(
        requirement, (first, second), partial_locator_answer
    )[0] == ANSWER_BINDING_STATUS_INCOMPLETE
    assert _evaluate_answer_evidence_binding(
        requirement, (first, second), full_locator_answer
    )[0] == ANSWER_BINDING_STATUS_VALID

    candidate = _tool_evidence(
        kind="project_test",
        tool_name="find_tests",
        granularity="candidate",
        path="tests/test_cache.py",
        line=4,
        scope_paths=("src/cache.py", "tests/test_cache.py"),
    )
    partial_candidate = replace(
        candidate,
        evidence_id="E2",
        path="tests/test_session.py",
        scope_paths=("src/cache.py", "tests/test_session.py"),
        scope="candidate tests/test_session.py:2 for src/cache.py",
        start_line=2,
        end_line=2,
    )
    assert _evaluate_answer_evidence_binding(
        requirement,
        (candidate, partial_candidate),
        "工具返回的候选测试位置：tests/test_cache.py:4 [E1]",
    )[0] == ANSWER_BINDING_STATUS_INCOMPLETE
    assert _evaluate_answer_evidence_binding(
        requirement,
        (candidate, partial_candidate),
        "工具返回的候选测试位置：tests/test_cache.py:4 [E1]\n"
        "工具返回的候选测试位置：tests/test_session.py:2 [E2]",
    )[0] == ANSWER_BINDING_STATUS_VALID


def test_low_granularity_records_cannot_satisfy_body_requirements_or_truncated_results():
    status_list = _tool_evidence(
        kind="project_change",
        tool_name="changed_files",
        granularity="status_list",
        path=None,
        line=None,
        scope_paths=("src/cache.py",),
    )
    status_binding = _evaluate_answer_evidence_binding(
        _requirement(PROJECT_CODE_V1),
        (status_list,),
        "src/cache.py — modified [E1]",
    )
    assert status_binding[0] == ANSWER_BINDING_STATUS_INCOMPLETE

    partial_candidate = _tool_evidence(
        kind="project_test",
        tool_name="find_tests",
        granularity="candidate",
        completeness="partial",
        path="tests/test_cache.py",
        line=4,
        scope_paths=("src/cache.py", "tests/test_cache.py"),
    )
    assert _evaluate_answer_evidence_binding(
        _requirement(NO_ADDITIONAL_REQUIREMENT),
        (partial_candidate,),
        "工具返回的候选测试位置：tests/test_cache.py:4 [E1]",
    )[0] == ANSWER_BINDING_STATUS_INCOMPLETE


def test_status_list_schema_and_provenance_fail_closed_for_bad_identity_or_omissions():
    call = ToolCall.create("changed_files", {"mode": "working_tree"})
    base = {
        "changes": [{"path": "src/cache.py", "status": "modified"}],
        "total_count": 1,
        "returned_count": 1,
        "truncated": False,
        "omitted_sensitive_count": 0,
    }
    assert _evidence_from_changed_files(
        _observation("changed_files", {**base, "changes": [{"path": "src/cache.py"}]}),
        call.arguments_copy(),
        "changed_files_v1",
    ) is None
    assert _evidence_from_changed_files(
        _observation("changed_files", {**base, "changes": [{"path": "src/cache.py", "status": "unknown"}]}),
        call.arguments_copy(),
        "changed_files_v1",
    ) is None
    assert _evidence_from_changed_files(
        _observation("changed_files", {**base, "changes": [{"path": "../outside.py", "status": "modified"}]}),
        call.arguments_copy(),
        "changed_files_v1",
    ) is None

    omitted = {
        **base,
        "total_count": 2,
        "omitted_sensitive_count": 1,
    }
    partial = _evidence_from_changed_files(
        _observation("changed_files", omitted), call.arguments_copy(), "changed_files_v1"
    )
    assert partial is not None and partial.completeness == "partial"
    assert _evaluate_answer_evidence_binding(
        _requirement(NO_ADDITIONAL_REQUIREMENT),
        (partial,),
        "src/cache.py — modified [E1]",
    )[0] == ANSWER_BINDING_STATUS_INCOMPLETE

    wrong_tool = _observation("find_tests", {"candidates": []}, call_id=call.call_id)
    assert _evidence_from_tool_result(wrong_tool, call, "changed_files_v1") == ()
    invalid_reference = _evaluate_answer_evidence_binding(
        _requirement(NO_ADDITIONAL_REQUIREMENT),
        (partial,),
        "src/cache.py — modified [E99]",
    )
    assert invalid_reference[0] == ANSWER_BINDING_STATUS_INVALID


def test_tool_result_evidence_cannot_be_seeded_from_an_earlier_run_or_reuse_an_eid():
    locator = _tool_evidence()
    with pytest.raises(TypeError):
        _normalize_initial_evidence((locator,))
    with pytest.raises(ValueError, match="不得重复"):
        _strict_evidence_sequence((locator, locator))


def test_no_requirement_same_scope_overclaim_remains_a_nonsemantic_gate_limit():
    diff = _tool_evidence(
        kind="project_change",
        tool_name="git_diff",
        granularity="diff",
        path="src/cache.py",
        line=9,
        scope_paths=("src/cache.py",),
    )
    binding = _evaluate_answer_evidence_binding(
        _requirement(NO_ADDITIONAL_REQUIREMENT),
        (diff,),
        "The implementation correctly handles every cache failure in src/cache.py:9 [E1].",
    )
    # A complete diff scoped to the same path passes structural binding. The
    # legacy verifier cannot prove that every prose claim follows from it.
    assert binding[0] == ANSWER_BINDING_STATUS_VALID


def test_dev029_style_diff_cannot_bind_a_multi_file_change_list():
    diff = _tool_evidence(
        evidence_id="E1",
        kind="project_change",
        tool_name="git_diff",
        granularity="diff",
        path="agent_demo/transport.py",
        line=20,
        scope_paths=("agent_demo/transport.py",),
    )
    test_body = EngineeringEvidence(
        evidence_id="E2",
        kind="project_test",
        path="tests/test_transport.py",
        start_line=1,
        end_line=3,
        snippet="assert transport retries",
    )
    answer = (
        "工作区变更包括 agent_demo/ranking.py、agent_demo/scoring.py、"
        "agent_demo/transport.py [E1]。\n"
        "测试正文位于 tests/test_transport.py [E2]。"
    )
    binding = _evaluate_answer_evidence_binding(
        _requirement(CHANGE_TEST_V1), (diff, test_body), answer
    )
    assert binding[0] == ANSWER_BINDING_STATUS_INCOMPLETE
