"""Object acquisition, shared bounds and public provenance under the real loop."""

import pytest

from core.tool_agent.actions import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction
from core.tool_agent.default_tools import build_readonly_tool_registry
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.integration import build_tool_agent_runtime
from core.tool_agent.models import INVALID_TOOL_ARGUMENTS, PROJECT_CONTEXT_PATH_NOT_ALLOWED, ToolCall
from core.tool_agent.runtime import _evidence_from_project_context_regions
from core.tool_agent.source_excerpt import project_context_fragments, project_context_snippet
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION
from tests._engineering_runtime_support import EmptyRetrievalPort, build_full_unified_runtime


def registry(root, version=READ_PROJECT_TARGETS_VERSION):
    return build_readonly_tool_registry(root, EmptyRetrievalPort(), read_project_context_version=version)


def execute(root, path, target):
    return ToolExecutor(registry(root)).execute(ToolCall.create("read_project_context", {"path": path, "target": target}))


def source(root, text, name="module.py"):
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return name


def test_known_file_reads_without_discovery_and_empty_is_not_evidence(tmp_path):
    path = source(tmp_path, "# Docs\nDefault is 4.\n", "README.md")
    observed = execute(tmp_path, path, {"kind": "file", "start_line": 1})
    assert observed.status == "ok"
    assert project_context_snippet(project_context_fragments(observed.result)[0]) == "# Docs\nDefault is 4."
    assert _evidence_from_project_context_regions(observed)[0].kind == "project_doc"
    source(tmp_path, "", "empty.md")
    empty = execute(tmp_path, "empty.md", {"kind": "file", "start_line": 1})
    assert empty.status == "ok" and empty.result["targets"][0]["status"] == "empty"
    assert _evidence_from_project_context_regions(empty) == ()


def test_named_defaults_methods_and_decorators_keep_separate_ranges(tmp_path):
    path = source(tmp_path, "DEFAULT = 6\n\n# unrelated text\n\nclass Service:\n    @staticmethod\n    def load():\n        return DEFAULT\n")
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["DEFAULT", "Service.load"]})
    assert observed.status == "ok"
    assert [t["definition"]["name"] for t in observed.result["targets"]] == ["DEFAULT", "Service.load"]
    assert [(e.start_line, e.end_line) for e in _evidence_from_project_context_regions(observed)] == [(1, 1), (6, 8)]
    assert all(t["content_complete"] for t in observed.result["targets"])
    assert "unrelated text" not in "".join(e.snippet for e in _evidence_from_project_context_regions(observed))


def test_ambiguous_short_name_never_reads_an_arbitrary_definition(tmp_path):
    path = source(tmp_path, "class A:\n    def load(self):\n        return 1\nclass B:\n    def load(self):\n        return 2\n")
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["load", "missing"]})
    assert observed.status == "ok" and observed.result["regions"] == []
    ambiguous, absent = observed.result["targets"]
    assert ambiguous["status"] == "ambiguous"
    assert {c["name"] for c in ambiguous["candidates"]} == {"A.load", "B.load"}
    assert absent["status"] == "not_found"
    assert _evidence_from_project_context_regions(observed) == ()


def test_duplicate_qualified_definition_is_still_ambiguous(tmp_path):
    path = source(tmp_path, "def same():\n    return 1\ndef same():\n    return 2\n")
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["same"]})
    assert observed.result["targets"][0]["status"] == "ambiguous"


def test_short_name_with_module_and_class_definitions_is_ambiguous(tmp_path):
    path = source(tmp_path, "def load():\n    return 1\nclass A:\n    def load(self):\n        return 2\n")
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["load", "A.load"]})
    assert observed.result["targets"][0]["status"] == "ambiguous"
    assert observed.result["targets"][1]["definition"]["name"] == "A.load"
    assert len(observed.result["regions"]) == 1


def test_matching_reads_actual_definitions_and_class_names_not_imports(tmp_path):
    path = source(tmp_path, "from other import get_adapter\n\nclass TestAdapters:\n    def test_mixed(self):\n        assert get_adapter('HTTP://host') == 1\n\n    def test_plain(self):\n        assert get_adapter('http://host') == 1\n", "tests/test_adapter.py")
    observed = execute(tmp_path, path, {"kind": "matching", "query": "get_adapter"})
    assert observed.status == "ok"
    assert {t["definition"]["name"] for t in observed.result["targets"]} == {"TestAdapters.test_mixed", "TestAdapters.test_plain"}
    assert all(e.start_line>1 and e.kind == "project_test" for e in _evidence_from_project_context_regions(observed))
    path = source(tmp_path, "from other import get_adapter\ndef test_unrelated():\n    assert True\n", "tests/test_import.py")
    observed = execute(tmp_path, path, {"kind": "matching", "query": "get_adapter"})
    assert observed.result["targets"][0]["status"] == "not_found"


def test_matching_reports_unread_matches(tmp_path):
    path = source(tmp_path, "\n".join(f"def test_item_{i}():\n    assert target({i})" for i in range(6)))
    observed = execute(tmp_path, path, {"kind": "matching", "query": "target"})
    assert observed.result["selection_truncated"] is True
    assert len(observed.result["regions"]) == 4


def test_known_document_matching_reads_late_text_without_ast_or_line_guess(tmp_path):
    lines = ["filler"]*150+["Transport adapter uses longest prefix.", "HTTP and HTTPS get defaults."]+["tail"]*20
    path = source(tmp_path, "\n".join(lines), "docs/advanced.rst")
    observed = execute(tmp_path, path, {"kind": "matching", "query": "adapter"})
    assert observed.status == "ok"
    evidence = _evidence_from_project_context_regions(observed)
    assert len(evidence) == 1 and evidence[0].kind == "project_doc"
    assert evidence[0].start_line == 121
    assert "longest prefix" in evidence[0].snippet and "HTTPS" in evidence[0].snippet
    assert observed.result["targets"][0]["definition"] is None


def test_text_windows_merge_overlap_but_keep_disjoint_ranges_and_shared_cap(tmp_path):
    lines = ["plain"]*300
    for number in [40, 45, 200]: lines[number-1] = "TARGET detail"
    path = source(tmp_path, "\n".join(lines), "README.md")
    observed = execute(tmp_path, path, {"kind": "matching", "query": "target"})
    regions = observed.result["regions"]
    assert [(r["start_line"],r["end_line"]) for r in regions] == [(10,75),(170,223)]
    assert sum(len(r["lines"]) for r in regions) == 120
    assert observed.result["targets"][1]["content_complete"] is False
    assert observed.result["targets"][1]["next_line"] == 224
    assert len(_evidence_from_project_context_regions(observed)) == 2


def test_multiple_targets_share_line_budget_and_continuation_is_explicit(tmp_path):
    path = source(tmp_path, "A = 1\n\ndef long():\n" + "    value = 1\n"*130 + "    return value\n\ndef other():\n    return 2\n")
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["A", "long", "other"]})
    assert sum(len(r["lines"]) for r in observed.result["regions"]) == 120
    assert observed.result["targets"][1]["content_complete"] is False
    next_line = observed.result["targets"][1]["next_line"]
    assert next_line == 122
    assert observed.result["targets"][2]["status"] == "output_limit"
    continued = execute(tmp_path, path, {"kind": "definition", "line": 3, "start_line": next_line})
    assert continued.status == "ok"
    assert continued.result["regions"][0]["start_line"] == next_line
    assert continued.result["targets"][0]["content_complete"] is False
    assert "continuation_page" in continued.result["targets"][0]["truncation_reasons"]


def test_character_budget_and_duplicate_assignment_keep_clipping_visible(tmp_path):
    path = source(tmp_path, "A = B = '"+'x'*400+"'\n\ndef long():\n"+"    value = '"+'x'*250+"'\n")
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["A", "B"]})
    assert len(observed.result["regions"]) == 1
    assert all(t["content_complete"] is False and t["truncation_reasons"] == ["line_length_limit"] for t in observed.result["targets"])
    path = source(tmp_path, "def long():\n"+("    value = '"+'x'*250+"'\n")*60)
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["long"]})
    fragments = project_context_fragments(observed.result)
    assert len(project_context_snippet(fragments[0])) <= 8000
    assert "character_limit" in observed.result["targets"][0]["truncation_reasons"]


@pytest.mark.parametrize("name,text,status", [
    ("module.py", "def broken(:\n", "parse_error"),
    ("README.md", "Some text", "unsupported_language"),
])
def test_named_target_never_substitutes_text_fallback(tmp_path, name, text, status):
    path = source(tmp_path, text, name)
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["broken"]})
    assert observed.status == "ok" and observed.result["targets"][0]["status"] == status
    assert _evidence_from_project_context_regions(observed) == ()


def test_parsing_does_not_import_or_execute_project(tmp_path):
    marker = tmp_path/"executed"
    path = source(tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('never execute')\ndef target():\n    return 1\n")
    observed = execute(tmp_path, path, {"kind": "symbols", "names": ["target"]})
    assert observed.status == "ok" and not marker.exists()


@pytest.mark.parametrize("path", ["../outside.py", "C:/outside.py", "/outside.py", ".env", "private_key.py"])
def test_object_reader_uses_existing_access_boundary(tmp_path, path):
    if path in {".env", "private_key.py"}:
        source(tmp_path, "sensitive content must not be read", path)
    observed = execute(tmp_path, path, {"kind": "file", "start_line": 1})
    assert observed.error_code == PROJECT_CONTEXT_PATH_NOT_ALLOWED


@pytest.mark.parametrize("target", [
    {"kind": "symbols", "names": ["A"], "line": 1},
    {"kind": "file"}, {"kind": "window", "line": True, "context_lines": 30},
    {"kind": "symbols", "names": ["A"]*2},
])
def test_target_shapes_are_exclusive_and_validated(tmp_path, target):
    assert execute(tmp_path, "module.py", target).error_code == INVALID_TOOL_ARGUMENTS


def test_malformed_fragment_envelope_is_fail_closed():
    region = {"mode": "definition", "start_line": 1, "end_line": 1, "lines": [{"line": 2, "text": "bad"}]}
    assert project_context_fragments({"mode": "targets", "path": "module.py", "regions": [region]}) == ()
    region = {"mode": "definition", "start_line": 1, "end_line": 40, "lines": [{"line": n, "text": "x"*200} for n in range(1, 41)]}
    assert project_context_fragments({"mode": "targets", "path": "module.py", "regions": [region, region]}) == ()


def test_legacy_contract_and_tool_count_stay_unchanged(tmp_path):
    old = registry(tmp_path, "read_project_context_v2")
    new = registry(tmp_path)
    assert len(old.list_specs()) == len(new.list_specs()) == 7
    assert old.get_spec("read_project_context").version == "read_project_context_v2"
    assert new.get_spec("read_project_context").version == READ_PROJECT_TARGETS_VERSION
    with pytest.raises(ValueError): registry(tmp_path, "unknown")


def test_object_profile_guidance_matches_the_selected_contract():
    from core.tool_agent.decision_prompt import (
        ENGINEERING_DECISION_PROMPT_OBJECT_READER_PROFILE,
        ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE,
        max_parse_repairs_for_profile,
    )
    current = ENGINEERING_DECISION_PROMPT_OBJECT_READER_PROFILE
    assert "mode=definition" not in current.template
    assert "path 与 target" in current.template
    assert max_parse_repairs_for_profile(current) == 1
    assert "mode=definition" in ENGINEERING_DECISION_PROMPT_UNIFIED_KIND_AWARE_GROUNDED_V2_PROFILE.template


def test_multiregion_read_is_one_budgeted_call_and_each_fragment_gets_id(tmp_path):
    source(tmp_path, "A = 6\n\ndef load():\n    return A\n")
    class Provider:
        def __init__(self): self.calls = 0
        def decide(self, *args, **kwargs):
            self.calls += 1
            action = ToolCallAction(action="tool_call", tool_name="read_project_context", arguments={"path": "module.py", "target": {"kind": "symbols", "names": ["A", "load"]}}) if self.calls == 1 else FinalAnswerAction(action="final_answer", answer="A 为 6 [E1]，load 返回 A [E2]。")
            return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)
    provider = Provider()
    runtime = build_tool_agent_runtime(repo_root=tmp_path, retrieval_port=EmptyRetrievalPort(), provider=provider, read_project_context_version=READ_PROJECT_TARGETS_VERSION)
    result = build_full_unified_runtime(runtime).run("读取 module.py 的 A 默认值及 load 如何使用它，引用源码。")
    assert result.status == "completed"
    assert result.tool_calls_used == 1 and result.iterations_used == 2 and result.tool_errors_used == 0
    assert [e.evidence_id for e in result.evidence] == ["E1", "E2"]
    assert [(e.start_line, e.end_line) for e in result.evidence] == [(1, 1), (3, 4)]
