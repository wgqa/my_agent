from dataclasses import replace

import pytest

from core.engineering_materials import MaterialLedger, ToolResultEvidence, capability_manifest
from core.engineering_requirement_contract import canonical_json
from core.tool_agent.executor import ToolExecutor
from core.tool_agent.models import ToolCall, ToolObservation, TOOL_EXECUTION_FAILED, ToolSpec
from core.tool_agent.registry import ToolRegistry
from core.tool_agent.tools.calculator import CALCULATOR_SPEC, CalculatorHandler
from core.tool_agent.tools.code_search import CODE_SEARCH_TEST_SPEC, CodeSearchHandler
from core.tool_agent.tools.git_change import CHANGED_FILES_SPEC
from core.tool_agent.tools.project_info import PROJECT_INFO_DOCUMENTATION_SPEC
from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_SPEC, ReadProjectTargetsHandler
from core.tool_agent.tools.test_discovery import FIND_TESTS_SPEC


def registry(tmp_path):
    result = ToolRegistry()
    result.register(CALCULATOR_SPEC, CalculatorHandler())
    result.register(READ_PROJECT_TARGETS_SPEC, ReadProjectTargetsHandler(tmp_path))
    result.register(CODE_SEARCH_TEST_SPEC, CodeSearchHandler(tmp_path, version=CODE_SEARCH_TEST_SPEC.version))
    return result


def test_successful_empty_collection_is_evidence_and_failure_is_not():
    ledger = MaterialLedger((CHANGED_FILES_SPEC,))
    call = ToolCall.create("changed_files", {"mode": "working_tree"})
    error = ToolObservation(call.call_id, call.tool_name, "error", None, TOOL_EXECUTION_FAILED)
    assert ledger.observe(call, error) == ()
    payload = {"changes": [], "total_count": 0, "returned_count": 0,
               "truncated": False, "omitted_sensitive_count": 0}
    added = ledger.observe(call, ToolObservation(call.call_id, call.tool_name, "ok", payload, None))
    assert added[0].payload == payload
    assert ledger.records[0].form == "list"
    assert ledger.records[0].details["content_complete"] is True
    assert "start_line" not in added[0].to_dict()


def test_same_path_range_new_content_is_not_deduplicated(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("def A():\n    return 1\n", encoding="utf-8")
    reg = registry(tmp_path)
    ledger = MaterialLedger(reg.list_specs())
    call = ToolCall.create("read_project_context", {"path": "a.py", "target": {"kind": "symbols", "names": ["A"]}})
    first = ToolExecutor(reg).execute(call)
    assert ledger.observe(call, first)[0].evidence_id == "E1"
    assert ledger.records[0].details["content_complete"] is True
    path.write_text("def A():\n    return 2\n", encoding="utf-8")
    second_call = ToolCall.create(call.tool_name, call.arguments)
    assert ledger.observe(second_call, ToolExecutor(reg).execute(second_call))[0].evidence_id == "E2"
    assert ledger.observe(second_call, ToolExecutor(reg).execute(second_call)) == ()


def test_reader_truncation_and_unread_targets_are_preserved(tmp_path):
    (tmp_path / "a.py").write_text("def A():\n" + "    pass\n" * 130, encoding="utf-8")
    reg = registry(tmp_path)
    ledger = MaterialLedger(reg.list_specs())
    call = ToolCall.create("read_project_context", {"path": "a.py", "target": {"kind": "symbols", "names": ["A", "B"]}})
    ledger.observe(call, ToolExecutor(reg).execute(call))
    record = ledger.records[0]
    assert record.details["content_complete"] is False
    assert "line_limit" in record.details["targets"][0]["truncation_reasons"]
    assert record.details["targets"][0]["definition"]["name"] == "A"
    missing_call = ToolCall.create("read_project_context", {"path": "a.py", "target": {"kind": "symbols", "names": ["B"]}})
    missing = ledger.observe(missing_call, ToolExecutor(reg).execute(missing_call))
    assert missing[0].result_type == "reader_locator"
    assert ledger.records[-1].form == "locator"
    assert missing[0].payload["targets"][0]["status"] == "not_found"


def test_ledger_snapshots_detach_nested_payloads_and_call_ids(tmp_path):
    reg = registry(tmp_path)
    ledger = MaterialLedger(reg.list_specs())
    call = ToolCall.create("calculator", {"expression": "2+3"})
    added = ledger.observe(call, ToolExecutor(reg).execute(call))[0]
    snapshot = ledger.snapshot()
    snapshot["materials"][0]["evidence"]["payload"]["value"] = 999
    added.payload["value"] = 42
    assert ledger.evidence[0].payload["value"] == 5
    assert ledger.snapshot()["materials"][0]["provenance"]["call_id"] == call.call_id
    another = MaterialLedger(reg.list_specs())
    assert another.evidence == ()


def test_adapters_reject_unknown_tools_versions_and_changed_schemas():
    altered = ToolSpec("calculator", "altered", {"type": "object", "additionalProperties": False},
                       CALCULATOR_SPEC.output_schema, CALCULATOR_SPEC.version)
    with pytest.raises(ValueError, match="MATERIAL_ADAPTER_UNAVAILABLE"):
        capability_manifest((altered,))
    with pytest.raises(ValueError, match="MATERIAL_ADAPTER_UNAVAILABLE"):
        capability_manifest((ToolSpec("missing", "no adapter", altered.input_schema, altered.output_schema, "v1"),))


def test_structured_facts_use_closed_schemas_and_actual_counts():
    with pytest.raises(Exception):
        ToolResultEvidence("E1", "calculator", "calculator_v1", canonical_json({"expression": "1+1"}),
                           canonical_json({"value": 2, "test_passed": True}))
    with pytest.raises(ValueError, match="counts"):
        ToolResultEvidence("E1", "changed_files", "changed_files_v1", canonical_json({"mode": "working_tree"}),
                           canonical_json({"changes": [], "total_count": 1, "returned_count": 1,
                                           "truncated": False, "omitted_sensitive_count": 0}))


def test_candidate_sources_are_candidates_not_test_execution():
    ledger = MaterialLedger((FIND_TESTS_SPEC, PROJECT_INFO_DOCUMENTATION_SPEC))
    call = ToolCall.create("find_tests", {"path": "src/a.py"})
    payload = {"candidates": [{"path": "tests/test_a.py", "line": 1, "reasons": ["filename_match"]}],
               "returned_count": 1, "truncated": True, "omitted_sensitive_count": 2}
    ledger.observe(call, ToolObservation(call.call_id, call.tool_name, "ok", payload, None))
    assert ledger.records[0].form == "candidate"
    assert ledger.records[0].details["content_complete"] is False
    assert "execution" in ledger.records[0].details["limitations"]


def test_mismatched_observation_cannot_become_a_fact(tmp_path):
    reg = registry(tmp_path)
    ledger = MaterialLedger(reg.list_specs())
    call = ToolCall.create("calculator", {"expression": "2+3"})
    wrong = replace(ToolExecutor(reg).execute(call), call_id="another_run")
    with pytest.raises(ValueError, match="mismatch"):
        ledger.observe(call, wrong)


def test_public_structured_schema_rejects_fake_lines_extra_payload_and_changed_hash():
    from api.schemas import ToolResultEvidence as PublicFact
    from core.tool_agent.activity import ToolResultEvidenceAddedActivity
    item = ToolResultEvidence("E1", "calculator", "calculator_v1",
                              canonical_json({"expression": "2+3"}), canonical_json({"value": 5}))
    public = item.to_dict()
    assert PublicFact(**public).model_dump() == public
    event = ToolResultEvidenceAddedActivity.from_public_evidence(item).to_dict()
    assert event["kind"] == "tool_result" and "start_line" not in event
    for changed in ({**public, "start_line": 0}, {**public, "content_sha256": "0" * 64},
                    {**public, "payload": {"value": 5, "completed": True}}):
        with pytest.raises(Exception):
            PublicFact(**changed)
