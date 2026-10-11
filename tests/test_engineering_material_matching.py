"""Actual Reader observations: object identity and cross-page coverage boundaries."""
from dataclasses import replace
import json

import pytest

from core.engineering_candidate_verification import material_matches_goal
from core.engineering_material_matching import goal_material_ids
from core.engineering_materials import MaterialLedger
from core.engineering_requirement_contract import RequirementGoal, RequirementTarget, canonical_json
from core.tool_agent.actions import ToolCallAction
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import ToolCall
from core.tool_agent.tools.read_project_snapshot import READ_PROJECT_SNAPSHOT_VERSION
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from tests._engineering_runtime_support import EmptyRetrievalPort
from tests.test_engineering_candidate_runtime import Reviewer, build, answer, review
from tests.test_engineering_requirement_planning import goal as raw_goal


def make_goal(*, path="a.py", symbol="A", depth="implementation", complete=True, query=None, kind="project_code"):
    return RequirementGoal("g1", "requested object", "requested object", (kind,), depth,
                           RequirementTarget(path=path, symbol=symbol, query=query), complete)


def setup(tmp_path, text, *, path="a.py", binding="1"*64, version=READ_PROJECT_SNAPSHOT_VERSION):
    source = tmp_path/path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    registry = build_readonly_tool_registry(tmp_path, EmptyRetrievalPort(), read_project_context_version=version)
    return registry, MaterialLedger(registry.list_specs(), binding_identity=binding)


def read(registry, ledger, target, path="a.py"):
    call = ToolCall.create("read_project_context", {"path": path, "target": target})
    observation = ToolExecutor(registry).execute(call)
    assert observation.status == "ok", observation.error_code
    ledger.observe(call, observation)
    return observation.result


def test_snapshot_reader_preserves_v4_bodies_limits_and_loads_source_once(tmp_path, monkeypatch):
    text = "class Service:\n    def A(self):\n" + "        pass\n"*130
    old, old_ledger = setup(tmp_path, text, version=READ_PROJECT_TARGETS_VERSION)
    new, new_ledger = setup(tmp_path, text)
    handler = new.resolve("read_project_context").handler
    original = handler._load_source
    loads = []
    def loaded(path):
        loads.append(path)
        return original(path)
    monkeypatch.setattr(handler, "_load_source", loaded)
    target = {"kind": "file", "start_line": 1}
    before = read(old, old_ledger, target)
    after = read(new, new_ledger, target)
    assert loads == ["a.py"]
    assert {key: after[key] for key in before} == before
    assert sum(len(r["lines"]) for r in after["regions"]) == 120
    assert after["source_snapshot"]["line_count"] == 132
    assert new_ledger.snapshot()["adapter_version"] == "engineering_material_adapters_v2"
    assert old_ledger.snapshot()["adapter_version"] == "engineering_material_adapters_v1"


def test_complete_file_can_support_contained_function_without_old_definition_field(tmp_path):
    registry, ledger = setup(tmp_path, "DEFAULT = 6\n\ndef A():\n    return DEFAULT\n")
    read(registry, ledger, {"kind": "file", "start_line": 1})
    goal = make_goal()
    assert ledger.records[0].details["targets"][0]["definition"] is None
    assert not material_matches_goal(goal, ledger.records[0])  # Historical path remains unchanged.
    assert goal_material_ids(goal, ledger.records) == ("E1",)


def test_local_window_supports_unique_short_name_without_claiming_complete_function(tmp_path):
    registry, ledger = setup(tmp_path, "class Service:\n    def A(self):\n" + "        pass\n"*100)
    read(registry, ledger, {"kind": "window", "line": 2, "context_lines": 5})
    assert goal_material_ids(make_goal(depth="body", complete=False), ledger.records) == ("E1",)
    assert goal_material_ids(make_goal(symbol="Service.A", depth="body", complete=False), ledger.records) == ("E1",)
    assert goal_material_ids(make_goal(), ledger.records) == ()


@pytest.mark.parametrize("text", [
    "class First:\n    def A(self):\n        return 1\nclass Second:\n    def A(self):\n        return 2\n",
    "def A():\n    return 1\ndef A():\n    return 2\n",
    "from other import A\nvalue = 'A'\n",
])
def test_ambiguous_duplicate_and_import_only_files_cannot_certify_named_object(tmp_path, text):
    registry, ledger = setup(tmp_path, text)
    read(registry, ledger, {"kind": "file", "start_line": 1})
    assert goal_material_ids(make_goal(), ledger.records) == ()
    assert goal_material_ids(make_goal(depth="body", complete=False), ledger.records) == ()


def test_qualified_name_does_not_select_another_class_method(tmp_path):
    registry, ledger = setup(tmp_path, "class First:\n    def A(self):\n        return 1\nclass Second:\n    def A(self):\n        return 2\n")
    read(registry, ledger, {"kind": "symbols", "names": ["First.A"]})
    assert goal_material_ids(make_goal(symbol="First.A"), ledger.records) == ("E1",)
    assert goal_material_ids(make_goal(symbol="Second.A"), ledger.records) == ()
    assert goal_material_ids(make_goal(path="other.py", symbol="First.A"), ledger.records) == ()


def test_mixed_reader_ambiguity_supplies_locations_but_not_an_arbitrary_body(tmp_path):
    registry, ledger = setup(tmp_path, "class First:\n    def A(self):\n        return 1\nclass Second:\n    def A(self):\n        return 2\n")
    read(registry, ledger, {"kind": "symbols", "names": ["A", "Second.A"]})
    assert goal_material_ids(make_goal(depth="locator", complete=False), ledger.records) == ("E1",)
    assert goal_material_ids(make_goal(depth="body", complete=False), ledger.records) == ()
    assert goal_material_ids(make_goal(), ledger.records) == ()


def long_function():
    return "def A():\n" + "    value = 1\n"*140 + "    return value\n"


def test_contiguous_definition_pages_require_both_actual_cited_parts(tmp_path):
    registry, ledger = setup(tmp_path, long_function())
    first = read(registry, ledger, {"kind": "symbols", "names": ["A"]})
    read(registry, ledger, {"kind": "definition", "line": 1, "start_line": first["targets"][0]["next_line"]})
    assert all(not r.details["content_complete"] for r in ledger.records)
    assert goal_material_ids(make_goal(), ledger.records) == ("E1", "E2")
    assert goal_material_ids(make_goal(), ledger.records[:1]) == ()
    assert goal_material_ids(make_goal(), ledger.records[1:]) == ()


def test_file_continuation_proves_file_only_after_all_lines_are_read(tmp_path):
    registry, ledger = setup(tmp_path, "visible\n"*145, path="README.md")
    requested = make_goal(path="README.md", symbol=None, depth="body", kind="project_doc")
    read(registry, ledger, {"kind": "file", "start_line": 1}, "README.md")
    assert goal_material_ids(requested, ledger.records) == ()
    read(registry, ledger, {"kind": "file", "start_line": 121}, "README.md")
    assert goal_material_ids(requested, ledger.records) == ("E1", "E2")


@pytest.mark.parametrize("breakage", ["gap", "revision", "binding", "path", "unknown_binding", "clipped"])
def test_pages_cannot_hide_missing_lines_or_source_changes(tmp_path, breakage):
    text = long_function()
    if breakage == "clipped":
        text = text.replace("    value = 1", "    value = '"+"x"*400+"'", 1)
    registry, ledger = setup(tmp_path, text, binding=None if breakage == "unknown_binding" else "1"*64)
    read(registry, ledger, {"kind": "symbols", "names": ["A"]})
    if breakage == "revision":
        (tmp_path/"a.py").write_text(text.replace("value = 1", "value = 2", 1), encoding="utf-8")
    read(registry, ledger, {"kind": "definition", "line": 1, "start_line": 122 if breakage == "gap" else 121})
    records = list(ledger.records)
    if breakage == "binding":
        provenance = json.loads(records[1].provenance_json)
        provenance["binding_identity"] = "2"*64
        records[1] = replace(records[1], provenance_json=canonical_json(provenance))
    if breakage == "path":
        records[1] = replace(records[1], evidence=replace(records[1].evidence, path="other.py"))
    assert goal_material_ids(make_goal(), records) == ()


def test_more_precise_search_is_matched_by_returned_object_not_query_equality(tmp_path):
    registry, ledger = setup(tmp_path, "def A():\n    return 1\n")
    call = ToolCall.create("code_search", {"query": "def A", "artifact_kind": "project_code"})
    ledger.observe(call, ToolExecutor(registry).execute(call))
    requested = make_goal(depth="locator", complete=False, query="A")
    assert not material_matches_goal(requested, ledger.records[0])
    assert goal_material_ids(requested, ledger.records) == ("E1",)
    assert goal_material_ids(make_goal(depth="locator", complete=False, symbol="B", query="A"), ledger.records) == ()
    assert goal_material_ids(make_goal(depth="locator", complete=False, path="other.py", query="A"), ledger.records) == ()


def test_empty_search_is_not_source_location_evidence(tmp_path):
    registry, ledger = setup(tmp_path, "value = 1\n")
    call = ToolCall.create("code_search", {"query": "A", "artifact_kind": "project_code"})
    ledger.observe(call, ToolExecutor(registry).execute(call))
    assert goal_material_ids(make_goal(depth="locator", complete=False), ledger.records) == ()


def test_qualified_symbol_literal_location_is_not_body_or_ownership_proof(tmp_path):
    registry, ledger = setup(tmp_path, "class Service:\n    def A(self):\n        return 1\n")
    call = ToolCall.create("code_search", {"query": "def A", "artifact_kind": "project_code"})
    ledger.observe(call, ToolExecutor(registry).execute(call))
    assert goal_material_ids(make_goal(depth="locator", complete=False, symbol="Service.A", query="A"), ledger.records) == ("E1",)
    assert goal_material_ids(make_goal(symbol="Service.A"), ledger.records) == ()


def test_literal_query_can_locate_a_prefix_without_claiming_a_symbol(tmp_path):
    registry, ledger = setup(tmp_path, "DEFAULT_TOP_K = 6\n")
    call = ToolCall.create("code_search", {"query": "DEFAULT_", "artifact_kind": "project_code"})
    ledger.observe(call, ToolExecutor(registry).execute(call))
    assert goal_material_ids(make_goal(depth="locator", complete=False, symbol=None, query="DEFAULT_"), ledger.records) == ("E1",)
    assert goal_material_ids(make_goal(depth="locator", complete=False, symbol="DEFAULT"), ledger.records) == ()


@pytest.mark.parametrize("semantic", [False, True])
def test_bounded_runtime_can_finish_with_two_pages_and_keeps_review_identity(tmp_path, semantic):
    requested = raw_goal("A", "A")
    reviewer = Reviewer([review(verdicts=(("fulfilled", ["E1", "E2"]),))]) if semantic else None
    actions = [ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": "a.py", "target": {"kind": "symbols", "names": ["A"]}}),
               ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": "a.py", "target": {"kind": "definition", "line": 1, "start_line": 121}}),
               answer("A 的完整实现初始化 value=1，最终返回 value [E1] [E2]。")]
    runtime, _ = build(tmp_path, actions, goals=[requested], reviewer=reviewer,
        policy="semantic_v2" if semantic else "structural_v3", reader_version=READ_PROJECT_SNAPSHOT_VERSION)
    (tmp_path/"a.py").write_text(long_function(), encoding="utf-8")
    result = runtime.run("解释 A 的完整实现")
    assert result.status == "completed" and result.tool_calls_used == 2 and result.iterations_used == 3
    assert result.finalization.review_calls == int(semantic)
    assert result.submission_records[-1].submission_input.payload["goal_availability"][0]["material_ids"] == ["E1", "E2"]
    if semantic:
        assert result.review_records[-1].review_input.payload["submission"]["answer"] == result.answer


def test_approval_citing_only_one_page_is_rejected_even_when_ledger_has_both(tmp_path):
    requested = raw_goal("A", "A")
    reviewer = Reviewer([review(verdicts=(("fulfilled", ["E1"]),))])
    actions = [ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": "a.py", "target": {"kind": "symbols", "names": ["A"]}}),
               ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": "a.py", "target": {"kind": "definition", "line": 1, "start_line": 121}}),
               answer("A 返回 value [E1] [E2]。")]
    runtime, _ = build(tmp_path, actions, goals=[requested], reviewer=reviewer,
        policy="semantic_v2", reader_version=READ_PROJECT_SNAPSHOT_VERSION)
    (tmp_path/"a.py").write_text(long_function(), encoding="utf-8")
    result = runtime.run("解释 A 的完整实现")
    assert result.status == "refused" and result.answer is None
    assert result.submission_records[0].decision == "revise_answer"


def test_new_policy_cannot_silently_use_old_reader_without_snapshot_identity(tmp_path):
    runtime, _ = build(tmp_path, [answer()], policy="structural_v3")
    with pytest.raises(ValueError, match="snapshot Reader v5"):
        runtime.run("解释 A、B 两个函数的完整实现")
