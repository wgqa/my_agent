"""Tests for G4-EVAL-06A Gate 4 Tool-Agent Dev dataset.

覆盖：真实数据集加载（24 case / 六类各 4 / case_id 连续）、identity
确定性（重载与行序无关）、manifest 与 jsonl_sha256 一致、knowledge_gold
登记、code_search Gold 为 repo-relative 路径、以及 Loader 严格性
（unknown/missing field、duplicate case_id、unknown category/tool、
empty/whitespace query、duplicate tags、invalid sequence、contradictory
Gold、refusal 语义、set 级 case_id 连续与类别计数）。无 LLM / 无网络。
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from evaluation.gate4 import (
    ASSERTION_TYPES,
    CATEGORIES,
    Gate4ToolUseEvaluationSet,
    build_manifest,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "gate4" / "data"
JSONL = DATA_DIR / "tool_use_dev_v1.jsonl"
MANIFEST = DATA_DIR / "tool_use_dev_manifest_v1.json"

SCHEMA_VERSION = "gate4_tool_use_case_v1"


def _calc_case(cid: str = "g4q005") -> dict:
    """一个字段级完全合法的最小 calculator case（可用于 _parse_case 或搭文件）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": cid,
        "query": f"{cid} 的测试问题？",
        "category": "calculator",
        "expected_terminal": "completed",
        "expected_first_action": "tool_call",
        "expected_first_tool": "calculator",
        "expected_first_tools": [],
        "required_tools": ["calculator"],
        "allowed_tool_sequences": [],
        "forbidden_tools": ["code_search", "knowledge_search"],
        "completion_assertions": [{"answer_number_equals": 1}],
        "allowed_refuse_reason_codes": [],
        "knowledge_gold": None,
        "tags": ["calculator", "test"],
        "rationale": "测试用例。",
    }


def _write_jsonl(tmp_path: Path, cases: list[dict]) -> Path:
    p = tmp_path / "set.jsonl"
    lines = [
        json.dumps(c, ensure_ascii=False, separators=(",", ":"))
        for c in cases
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _real_set() -> Gate4ToolUseEvaluationSet:
    return Gate4ToolUseEvaluationSet.load_jsonl(JSONL)


# ---------------------------------------------------------------------- #
# 真实数据集正向
# ---------------------------------------------------------------------- #


class TestRealDataset:
    def test_loads_24_cases(self):
        set_obj = _real_set()
        assert set_obj.case_count == 24
        assert len(set_obj.cases) == 24

    def test_six_categories_four_each(self):
        set_obj = _real_set()
        assert set_obj.category_counts == {cat: 4 for cat in CATEGORIES}

    def test_case_ids_contiguous_g4q001_to_024(self):
        set_obj = _real_set()
        ids = [c.case_id for c in set_obj.cases]
        assert ids == [f"g4q{i:03d}" for i in range(1, 25)]

    def test_evaluation_set_id_is_12_hex(self):
        set_obj = _real_set()
        assert len(set_obj.evaluation_set_id) == 12
        int(set_obj.evaluation_set_id, 16)

    def test_identity_deterministic_across_reload(self):
        assert _real_set().evaluation_set_id == _real_set().evaluation_set_id

    def test_identity_independent_of_line_order(self, tmp_path):
        lines = JSONL.read_text(encoding="utf-8").splitlines()
        original = _real_set().evaluation_set_id
        for seed in (1, 7):
            shuffled = lines[:]
            rng = random.Random(seed)
            rng.shuffle(shuffled)
            p = tmp_path / f"shuffled_{seed}.jsonl"
            p.write_text("\n".join(shuffled) + "\n", encoding="utf-8")
            assert (
                Gate4ToolUseEvaluationSet.load_jsonl(p).evaluation_set_id
                == original
            )

    def test_manifest_matches_committed(self):
        set_obj = _real_set()
        jsonl_sha256 = hashlib.sha256(JSONL.read_bytes()).hexdigest()
        manifest = build_manifest(set_obj, jsonl_sha256, created_for="G4-EVAL-06")
        committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
        assert manifest == committed
        assert committed["jsonl_sha256"] == jsonl_sha256
        assert committed["evaluation_set_id"] == set_obj.evaluation_set_id
        assert committed["case_count"] == 24
        assert committed["created_for"] == "G4-EVAL-06"

    def test_knowledge_search_cases_register_knowledge_gold(self):
        set_obj = _real_set()
        for case in set_obj.cases:
            if case.category == "knowledge_search":
                assert case.knowledge_gold is not None
                assert case.knowledge_gold.source_name.strip()
                assert case.knowledge_gold.evidence_phrase.strip()
                assert "knowledge_search" in case.required_tools
            if "knowledge_search" not in case.required_tools:
                assert case.knowledge_gold is None

    def test_multi_step_cases_have_two_tools_and_sequences(self):
        set_obj = _real_set()
        for case in set_obj.cases:
            if case.category == "multi_step":
                assert len(case.required_tools) >= 2
                assert case.allowed_tool_sequences
                assert case.expected_first_tools
                assert case.expected_first_tool is None

    def test_refusal_cases_clean_refusal(self):
        set_obj = _real_set()
        for case in set_obj.cases:
            if case.category == "refusal_safety":
                assert case.expected_terminal == "refused"
                assert case.expected_first_action == "refuse"
                assert case.required_tools == ()
                assert case.allowed_refuse_reason_codes
                assert set(case.allowed_refuse_reason_codes) <= {
                    "UNSUPPORTED_REQUEST",
                    "UNSAFE_REQUEST",
                }
                assert all(
                    a.type == "status_equals" and a.value == "refused"
                    for a in case.completion_assertions
                )

    def test_code_search_cases_assert_repo_relative_paths(self):
        set_obj = _real_set()
        prefixes = ("core/", "api/", "evaluation/", "scripts/", "tests/", "docs/")
        for case in set_obj.cases:
            if case.category == "code_search":
                path_assertions = [
                    a.value
                    for a in case.completion_assertions
                    if a.type in ("answer_contains", "path_contains")
                ]
                assert path_assertions, f"{case.case_id} 缺路径断言"
                assert any(
                    p.startswith(prefixes) for p in path_assertions
                ), f"{case.case_id} 断言不是 repo-relative 路径: {path_assertions}"

    def test_calculator_cases_have_numeric_assertions(self):
        set_obj = _real_set()
        for case in set_obj.cases:
            if case.category == "calculator":
                assert any(
                    a.type == "answer_number_equals"
                    for a in case.completion_assertions
                )

    def test_assertion_types_all_valid(self):
        set_obj = _real_set()
        used = {a.type for c in set_obj.cases for a in c.completion_assertions}
        assert used <= set(ASSERTION_TYPES)


# ---------------------------------------------------------------------- #
# Loader 严格性（字段级，直接调用 _parse_case）
# ---------------------------------------------------------------------- #


def _parse(obj: dict) -> None:
    Gate4ToolUseEvaluationSet._parse_case(obj, 1)


class TestFieldStrictness:
    def test_unknown_field_reject(self):
        obj = _calc_case()
        obj["extra_field"] = True
        with pytest.raises(ValueError, match="未知字段"):
            _parse(obj)

    def test_missing_field_reject(self):
        obj = _calc_case()
        del obj["rationale"]
        with pytest.raises(ValueError, match="缺少字段"):
            _parse(obj)

    def test_unknown_category_reject(self):
        obj = _calc_case()
        obj["category"] = "hack"
        with pytest.raises(ValueError, match="category"):
            _parse(obj)

    def test_unknown_tool_name_reject(self):
        obj = _calc_case()
        obj["required_tools"] = ["shell"]
        with pytest.raises(ValueError, match="TOOLS|shell"):
            _parse(obj)

    def test_empty_query_reject(self):
        obj = _calc_case()
        obj["query"] = ""
        with pytest.raises(ValueError, match="不能为空"):
            _parse(obj)

    def test_whitespace_only_query_reject(self):
        obj = _calc_case()
        obj["query"] = "   \t  "
        with pytest.raises(ValueError, match="不能为空"):
            _parse(obj)

    def test_duplicate_tags_reject(self):
        obj = _calc_case()
        obj["tags"] = ["a", "a"]
        with pytest.raises(ValueError, match="重复值"):
            _parse(obj)

    def test_invalid_sequence_tool_reject(self):
        obj = _calc_case(cid="g4q017")
        obj.update(
            category="multi_step",
            expected_first_action="tool_call",
            expected_first_tool=None,
            expected_first_tools=["code_search"],
            required_tools=["code_search", "calculator"],
            allowed_tool_sequences=[["code_search", "shell"]],
            forbidden_tools=["knowledge_search"],
        )
        with pytest.raises(ValueError, match="allowed_tool_sequences"):
            _parse(obj)

    def test_sequence_coverage_mismatch_reject(self):
        obj = _calc_case(cid="g4q017")
        obj.update(
            category="multi_step",
            expected_first_action="tool_call",
            expected_first_tool=None,
            expected_first_tools=["code_search"],
            required_tools=["code_search", "calculator"],
            allowed_tool_sequences=[["calculator"]],
            forbidden_tools=["knowledge_search"],
        )
        with pytest.raises(ValueError, match="覆盖的 Tool 集合必须精确等于"):
            _parse(obj)

    def test_multi_step_requires_two_tools(self):
        obj = _calc_case(cid="g4q017")
        obj.update(
            category="multi_step",
            expected_first_action="tool_call",
            expected_first_tool=None,
            expected_first_tools=["calculator"],
            required_tools=["calculator"],
            allowed_tool_sequences=[["calculator"]],
            forbidden_tools=["knowledge_search"],
        )
        with pytest.raises(ValueError, match="至少 2 个"):
            _parse(obj)

    def test_multi_step_requires_sequences(self):
        obj = _calc_case(cid="g4q017")
        obj.update(
            category="multi_step",
            expected_first_action="tool_call",
            expected_first_tool=None,
            expected_first_tools=["code_search"],
            required_tools=["code_search", "calculator"],
            allowed_tool_sequences=[],
            forbidden_tools=["knowledge_search"],
        )
        with pytest.raises(ValueError, match="allowed_tool_sequences 不能为空"):
            _parse(obj)

    def test_contradictory_status_equals_on_completed(self):
        obj = _calc_case()
        obj["completion_assertions"] = [{"status_equals": "refused"}]
        with pytest.raises(ValueError, match="status_equals"):
            _parse(obj)

    def test_direct_answer_with_expected_first_tool_reject(self):
        obj = _calc_case(cid="g4q001")
        obj.update(
            category="direct_answer",
            expected_terminal="completed",
            expected_first_action="final_answer",
            expected_first_tool="calculator",
            required_tools=[],
            forbidden_tools=["calculator", "code_search", "knowledge_search"],
        )
        with pytest.raises(ValueError, match="direct_answer 不允许设置"):
            _parse(obj)

    def test_refusal_with_non_refused_assertion_reject(self):
        obj = _calc_case(cid="g4q021")
        obj.update(
            category="refusal_safety",
            expected_terminal="refused",
            expected_first_action="refuse",
            expected_first_tool=None,
            required_tools=[],
            forbidden_tools=["calculator", "code_search", "knowledge_search"],
            completion_assertions=[{"answer_number_equals": 1}],
            allowed_refuse_reason_codes=["UNSUPPORTED_REQUEST"],
        )
        with pytest.raises(ValueError, match="refused case"):
            _parse(obj)

    def test_refusal_requires_reason_codes(self):
        obj = _calc_case(cid="g4q021")
        obj.update(
            category="refusal_safety",
            expected_terminal="refused",
            expected_first_action="refuse",
            expected_first_tool=None,
            required_tools=[],
            forbidden_tools=["calculator", "code_search", "knowledge_search"],
            completion_assertions=[{"status_equals": "refused"}],
            allowed_refuse_reason_codes=[],
        )
        with pytest.raises(ValueError, match="allowed_refuse_reason_codes 不能为空"):
            _parse(obj)

    def test_refusal_with_unknown_reason_code_reject(self):
        obj = _calc_case(cid="g4q021")
        obj.update(
            category="refusal_safety",
            expected_terminal="refused",
            expected_first_action="refuse",
            expected_first_tool=None,
            required_tools=[],
            forbidden_tools=["calculator", "code_search", "knowledge_search"],
            completion_assertions=[{"status_equals": "refused"}],
            allowed_refuse_reason_codes=["BANANA"],
        )
        with pytest.raises(ValueError, match="UNSUPPORTED_REQUEST"):
            _parse(obj)

    def test_knowledge_search_requires_knowledge_gold(self):
        obj = _calc_case(cid="g4q013")
        obj.update(
            category="knowledge_search",
            expected_first_tool="knowledge_search",
            required_tools=["knowledge_search"],
            forbidden_tools=["calculator", "code_search"],
            knowledge_gold=None,
        )
        with pytest.raises(ValueError, match="knowledge_gold"):
            _parse(obj)

    def test_non_knowledge_case_with_knowledge_gold_reject(self):
        obj = _calc_case()
        obj["knowledge_gold"] = {
            "source_name": "rag/检索与生成.md",
            "evidence_phrase": "RRF 基于排名",
        }
        with pytest.raises(ValueError, match="knowledge_gold"):
            _parse(obj)

    def test_assertion_with_two_types_reject(self):
        obj = _calc_case()
        obj["completion_assertions"] = [
            {"answer_contains": "x", "answer_number_equals": 1}
        ]
        with pytest.raises(ValueError, match="恰好含一个断言类型"):
            _parse(obj)

    def test_assertion_with_unknown_type_reject(self):
        obj = _calc_case()
        obj["completion_assertions"] = [{"regex_contains": "x"}]
        with pytest.raises(ValueError, match="未知字段"):
            _parse(obj)

    def test_answer_number_equals_bool_reject(self):
        obj = _calc_case()
        obj["completion_assertions"] = [{"answer_number_equals": True}]
        with pytest.raises(ValueError, match="数字"):
            _parse(obj)

    def test_answer_nonempty_false_reject(self):
        obj = _calc_case()
        obj["completion_assertions"] = [{"answer_nonempty": False}]
        with pytest.raises(ValueError, match="answer_nonempty 必须为 true"):
            _parse(obj)

    def test_duplicate_query_reject(self, tmp_path):
        a = _calc_case("g4q001")
        b = _calc_case("g4q002")
        b["query"] = a["query"]
        p = _write_jsonl(tmp_path, [a, b])
        with pytest.raises(ValueError, match="query 与第"):
            Gate4ToolUseEvaluationSet.load_jsonl(p)

    def test_duplicate_case_id_reject(self, tmp_path):
        a = _calc_case("g4q001")
        b = _calc_case("g4q001")
        b["query"] = "另一个问题"
        p = _write_jsonl(tmp_path, [a, b])
        with pytest.raises(ValueError, match="重复"):
            Gate4ToolUseEvaluationSet.load_jsonl(p)


# ---------------------------------------------------------------------- #
# Set 级不变量（case_id 连续、类别计数）
# ---------------------------------------------------------------------- #


class TestSetInvariants:
    def test_non_contiguous_case_id_reject(self, tmp_path):
        cases = [_calc_case(f"g4q{i:03d}") for i in range(1, 24)]
        cases.append(_calc_case("g4q025"))  # 跳过 g4q024
        p = _write_jsonl(tmp_path, cases)
        with pytest.raises(ValueError, match="必须唯一且连续"):
            Gate4ToolUseEvaluationSet.load_jsonl(p)

    def test_wrong_category_counts_reject(self, tmp_path):
        cases = [_calc_case(f"g4q{i:03d}") for i in range(1, 25)]
        p = _write_jsonl(tmp_path, cases)  # 24 个全 calculator
        with pytest.raises(ValueError, match="每类必须恰好 4"):
            Gate4ToolUseEvaluationSet.load_jsonl(p)

    def test_missing_case_count_reject(self, tmp_path):
        cases = [_calc_case(f"g4q{i:03d}") for i in range(1, 24)]
        p = _write_jsonl(tmp_path, cases)  # 只 23 个
        with pytest.raises(ValueError, match="连续|每类"):
            Gate4ToolUseEvaluationSet.load_jsonl(p)
