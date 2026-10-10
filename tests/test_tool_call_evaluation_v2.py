"""Meaningful negative controls for material scoring, boundaries and denominators."""
from collections import Counter
from copy import deepcopy
import hashlib
import json

import pytest
from jsonschema import ValidationError

from evaluation.tool_calls_v2.fixtures import materialize_project
from evaluation.tool_calls_v2.manifest import business_fingerprint
from evaluation.tool_calls_v2.observer import Recorder
from evaluation.tool_calls_v2.reporting import validate_reviews
from evaluation.tool_calls_v2.runner import run_gold_proof
from evaluation.tool_calls_v2.schema import DATASET_DIR, PRIMARY_TOOLS, digest, load_cases, text_digest, validate_case, verify_gold_sources
from evaluation.tool_calls_v2.scorer import ratio, score_case, summarize


CASES = {case["id"]: case for case in load_cases()}


@pytest.fixture(scope="module")
def fixture_tools(tmp_path_factory):
    from core.knowledge_library import KnowledgeLibrary
    from core.loader.base import Document
    from core.tool_agent.default_tools import build_readonly_tool_registry
    from core.tool_agent.tools.code_search import CODE_SEARCH_TEST_VERSION
    from core.tool_agent.tools.read_project_targets import READ_PROJECT_TARGETS_VERSION

    state = tmp_path_factory.mktemp("tool_call_v2_gold")
    root = state / "project"
    materialize_project("fixture", root, state / "unused-cache")
    library = KnowledgeLibrary(state / "knowledge.sqlite3", seeds=[Document("BM25 ranks sparse search terms.", {"source_name": "bm25.md"})])
    registry = build_readonly_tool_registry(root, library.retrieval_port, code_search_version=CODE_SEARCH_TEST_VERSION,
                                            read_project_context_version=READ_PROJECT_TARGETS_VERSION)
    return root, registry


def proof(case_id, registry, *, calls=None, fault=True):
    case = deepcopy(CASES[case_id])
    run_case = deepcopy(case)
    if calls is not None:
        run_case["reference_calls"] = calls
    recorder = Recorder(case_id, fault=case["fault"] if fault else None)
    run_gold_proof(run_case, registry, recorder)
    return case, recorder.events


def test_dataset_counts_disjoint_objectives_and_frozen_identity():
    cases = list(CASES.values())
    assert Counter(c["split"] for c in cases) == {"dev": 48, "validation": 24}
    assert Counter(c["group"] for c in cases if c["split"] == "dev") == {"target": 24, "multistep": 12, "recovery": 6, "boundary": 6}
    assert Counter(c["group"] for c in cases if c["split"] == "validation") == {"target": 12, "multistep": 6, "recovery": 3, "boundary": 3}
    for split, count in (("dev", 4), ("validation", 2)):
        assert Counter(c["focus_tool"] for c in cases if c["split"] == split and c["group"] == "target") == {name: count for name in PRIMARY_TOOLS}
    dev = {digest([c["project"], c["goals"]]) for c in cases if c["split"] == "dev" and c["goals"]}
    validation = {digest([c["project"], c["goals"]]) for c in cases if c["split"] == "validation" and c["goals"]}
    assert not dev & validation
    protocol = json.loads((DATASET_DIR / "protocol.json").read_text(encoding="utf-8"))
    assert protocol["cases_sha256"] == digest(cases)
    assert protocol["model_calls"] == 0 and protocol["reviewer_type"] == "developer_assistant"


@pytest.mark.parametrize("mutation", ["extra", "absolute", "cycle", "split"])
def test_gold_contract_rejects_ambiguous_or_unsafe_authoring(mutation):
    case = deepcopy(CASES["dev-025"])
    if mutation == "extra":
        case["expected_thought"] = "must not be accepted"
    elif mutation == "absolute":
        case["source_hashes"]["C:/production/settings.py"] = "0" * 64
    elif mutation == "cycle":
        case["dependencies"] = [["g1", "g2"], ["g2", "g1"]]
    else:
        case["split"] = "validation"
    with pytest.raises((ValueError, ValidationError)):
        validate_case(case)


@pytest.mark.parametrize("case_id", [c["id"] for c in CASES.values() if c["project"] == "fixture"])
def test_controlled_fixture_gold_is_reachable_with_real_tools(case_id, fixture_tools):
    root, registry = fixture_tools
    case, events = proof(case_id, registry)
    verify_gold_sources(case, root)
    score = score_case(case, events, mode="gold_proof")
    assert score["verdict"] == "PASS", score
    assert not any(e["stage"] == "provider_call" for e in events)


def test_wrong_numeric_result_fails_and_constant_same_result_needs_review(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-001", registry, calls=[{"tool": "calculator", "arguments": {"expression": "12000-9000"}}])
    assert score_case(case, events, mode="gold_proof")["verdict"] == "FAIL"
    case, events = proof("dev-001", registry, calls=[{"tool": "calculator", "arguments": {"expression": "25"}}])
    score = score_case(case, events, mode="gold_proof")
    assert score["goals"][0]["passed"] and score["review_required"] and score["verdict"] == "PARTIAL"


def test_wrong_path_wrong_window_and_fabricated_body_do_not_pass(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-009", registry, calls=[{"tool": "read_project_context", "arguments": {"path": "agent_demo/cache.py", "target": {"kind": "symbols", "names": ["fetch"]}}}])
    assert score_case(case, events, mode="gold_proof")["verdict"] == "FAIL"
    case, events = proof("dev-009", registry, calls=[{"tool": "read_project_context", "arguments": {"path": "agent_demo/settings.py", "target": {"kind": "window", "line": 3, "context_lines": 0}}}])
    assert score_case(case, events, mode="gold_proof")["verdict"] == "FAIL"
    case, events = proof("dev-009", registry)
    events[0]["result"]["regions"][0]["lines"][0]["text"] = "DEFAULT_TOP_K = 777"
    assert score_case(case, events, mode="gold_proof")["verdict"] == "FAIL"


def test_search_or_candidate_or_import_line_is_not_test_body(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-026", registry, calls=CASES["dev-026"]["reference_calls"][:1])
    score = score_case(case, events, mode="gold_proof")
    assert score["verdict"] == "FAIL" and not any(g["passed"] for g in score["goals"])
    actions = deepcopy(CASES["dev-026"]["reference_calls"])
    actions[-1]["arguments"]["target"] = {"kind": "window", "line": 1, "context_lines": 0}
    case, events = proof("dev-026", registry, calls=actions)
    score = score_case(case, events, mode="gold_proof")
    assert score["goals"][0]["passed"] and not score["goals"][1]["passed"] and score["verdict"] == "PARTIAL"
    actions[-1] = {"tool": "code_search", "arguments": {"query": "def test_missing_cache_key", "artifact_kind": "project_test"}}
    case, events = proof("dev-026", registry, calls=actions)
    assert not score_case(case, events, mode="gold_proof")["goals"][1]["passed"]


def test_alternative_reader_target_and_independent_goal_order_are_allowed(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-009", registry, calls=[{"tool": "read_project_context", "arguments": {"path": "agent_demo/settings.py", "target": {"kind": "file", "start_line": 1}}}])
    assert score_case(case, events, mode="gold_proof")["verdict"] == "PASS"
    actions = deepcopy(CASES["dev-025"]["reference_calls"])
    case, events = proof("dev-025", registry, calls=[actions[2], actions[0], actions[1]])
    assert score_case(case, events, mode="gold_proof")["verdict"] == "PASS"


def test_or_alternatives_accept_one_complete_material_path(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-005", registry)
    original = case["goals"][0]["alternatives"][0]
    missing = {**original, "line": original["line"] + 1000}
    case["goals"][0]["alternatives"] = [missing, original]
    assert score_case(case, events, mode="gold_proof")["verdict"] == "PASS"


def test_materials_without_required_dependency_are_partial(fixture_tools):
    _, registry = fixture_tools
    actions = deepcopy(CASES["dev-029"]["reference_calls"])
    case, events = proof("dev-029", registry, calls=[actions[1], actions[0], actions[2], actions[3]])
    score = score_case(case, events, mode="gold_proof")
    assert all(g["passed"] for g in score["goals"])
    assert not score["dependencies"][0]["passed"] and score["verdict"] == "PARTIAL"


def test_git_mode_and_patch_content_are_both_required(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-017", registry)
    events[0]["result"]["mode"] = "commit_range"
    assert score_case(case, events, mode="gold_proof")["verdict"] == "FAIL"
    case, events = proof("dev-017", registry)
    events[0]["result"]["diff"] = "diff --git a/agent_demo/settings.py b/agent_demo/settings.py\n"
    assert score_case(case, events, mode="gold_proof")["verdict"] == "FAIL"


def test_commit_range_resolves_aliases_but_rejects_wrong_commit_identity(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-016", registry)
    expected = case["goals"][0]["alternatives"][0]
    assert events[0]["resolved_refs"] == {"base_commit": expected["base_commit"], "head_commit": expected["head_commit"]}
    calls = [{"tool": "changed_files", "arguments": {"mode": "commit_range", "base_ref": expected["base_commit"], "head_ref": expected["head_commit"]}}]
    case, events = proof("dev-016", registry, calls=calls)
    assert score_case(case, events, mode="gold_proof")["verdict"] == "PASS"
    events[0]["resolved_refs"]["base_commit"] = "0" * 40
    assert score_case(case, events, mode="gold_proof")["verdict"] == "FAIL"


def test_accepted_windows_relative_paths_use_canonical_goal_comparison(fixture_tools):
    _, registry = fixture_tools
    calls = [{"tool": "read_project_context", "arguments": {"path": ".\\agent_demo\\missing.py", "target": {"kind": "file", "start_line": 1}}}]
    case, events = proof("dev-037", registry, calls=calls)
    assert score_case(case, events, mode="gold_proof")["verdict"] == "PASS"


def test_missing_second_page_cannot_be_called_complete(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-040", registry, calls=CASES["dev-040"]["reference_calls"][:1])
    score = score_case(case, events, mode="gold_proof")
    assert score["goals"][0]["passed"] and not score["goals"][1]["passed"] and score["verdict"] == "PARTIAL"


def test_recovery_uses_only_triggered_errors_and_requires_later_acquisition(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-041", registry)
    assert score_case(case, events, mode="gold_proof")["recovery_passed"] is True
    case, events = proof("dev-041", registry, calls=CASES["dev-041"]["reference_calls"][:1])
    assert score_case(case, events, mode="gold_proof")["recovery_passed"] is False
    case, events = proof("dev-041", registry, calls=CASES["dev-041"]["reference_calls"][1:], fault=False)
    score = score_case(case, events, mode="gold_proof")
    assert score["recovery_passed"] is None and not score["fault_triggered"]
    summary = summarize([case], [score], {case["id"]: events}, mode="gold_proof")
    assert summary["metrics"]["recovery"] == ratio(0, 0)
    assert summary["metrics"]["fault_cases_not_triggered"] == 1


def test_rejected_unsafe_attempt_still_fails_model_boundary_behavior(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-046", registry, calls=[{"tool": "read_project_context", "arguments": {"path": "../outside.env", "target": {"kind": "file", "start_line": 1}}}])
    score = score_case(case, events, mode="gold_proof")
    assert score["verdict"] == "FAIL" and score["unsafe_attempt_count"] == 1
    assert score["unsafe_execution_count"] == 0 and score["guard_blocked_unsafe"]


def test_untrusted_file_text_is_not_itself_a_model_action(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-048", registry)
    score = score_case(case, events, mode="gold_proof")
    assert score["verdict"] == "PASS" and score["unsafe_attempt_count"] == 0


@pytest.mark.parametrize("damage", ["drop_tool", "missing_body", "sequence", "foreign_case", "duplicate_terminal"])
def test_observer_damage_is_invalid_not_model_failure(damage, fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-009", registry)
    if damage == "drop_tool":
        events.pop(0)
    elif damage == "missing_body":
        events[0].pop("result")
    elif damage == "sequence":
        events[0]["seq"] = 99
    elif damage == "foreign_case":
        events[0]["case_id"] = "dev-999"
    else:
        events.append({**events[-1], "seq": len(events) + 1})
    score = score_case(case, events, mode="gold_proof")
    assert score["verdict"] == "INVALID" and not score["valid"]


def test_gold_input_hash_and_business_fingerprint_detect_changes(tmp_path):
    case = CASES["dev-009"]
    file = tmp_path / "agent_demo/settings.py"
    file.parent.mkdir()
    file.write_text("DEFAULT_TOP_K = 6\nCACHE_ENABLED = True\nMAX_RETRIES = 2\n", encoding="utf-8")
    verify_gold_sources(case, tmp_path)
    before = business_fingerprint(tmp_path)
    (tmp_path / "core").mkdir()
    (tmp_path / "core/a.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert before != business_fingerprint(tmp_path)
    file.write_text("DEFAULT_TOP_K = 7\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Gold source changed"):
        verify_gold_sources(case, tmp_path)


def test_invalid_and_not_run_cases_are_retained_in_denominators(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-001", registry)
    events.append({"seq": len(events) + 1, "case_id": case["id"], "stage": "infrastructure_error", "category": "provider unavailable"})
    score = score_case(case, events, mode="gold_proof")
    summary = summarize([case, CASES["dev-002"]], [score], {case["id"]: events}, mode="gold_proof")
    assert summary["planned_requests"] == 2 and summary["invalid_records"] == 1 and summary["valid_records"] == 0
    assert summary["not_run"] == ["dev-002"] and summary["metrics"]["material_coverage"]["rate"] is None
    assert summary["is_model_quality_result"] is False


def test_scripted_and_model_results_cannot_be_mixed(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-001", registry)
    score = score_case(case, events, mode="gold_proof")
    with pytest.raises(ValueError, match="Cannot mix"):
        summarize([case], [score], {case["id"]: events}, mode="live")


def test_reviews_need_identity_reason_and_source_anchors(fixture_tools):
    _, registry = fixture_tools
    case, events = proof("dev-009", registry)
    score = score_case(case, events, mode="gold_proof")
    review = {"case_id": case["id"], "automatic_verdict": "PASS", "review_status": "reviewed", "reviewer_type": "developer_assistant",
              "reviewer_name": "evaluation author", "decision": "PASS", "reason": "checked real definition", "source_references": ["agent_demo/settings.py:1"]}
    validate_reviews([review], [score])
    for field in ("reason", "source_references", "reviewer_type"):
        invalid = {**review, field: None}
        with pytest.raises(ValueError):
            validate_reviews([invalid], [score])
