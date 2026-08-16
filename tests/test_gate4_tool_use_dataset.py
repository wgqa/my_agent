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
import os
import random
from pathlib import Path

import pytest

from evaluation.gate4 import (
    ASSERTION_TYPES,
    CATEGORIES,
    CODE_REFERENCE_COMMIT,
    KNOWLEDGE_CORPUS_FILE_COUNT,
    KNOWLEDGE_CORPUS_ID,
    Gate4ToolUseEvaluationSet,
    build_manifest,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "gate4" / "data"
JSONL = DATA_DIR / "tool_use_dev_v1.jsonl"
MANIFEST = DATA_DIR / "tool_use_dev_manifest_v1.json"
PROTOCOL = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "experiments"
    / "gate4_tool_use_eval_protocol.md"
)

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


def _run_provenance_check(corpus_root: str | None) -> None:
    """按 env 语义执行 knowledge_gold provenance check。

    - corpus_root 未提供（env 未设置）→ pytest.skip（普通 pytest 下语料不一定在本机）
    - corpus_root 提供但非目录 → AssertionError（FAIL，不允许 skip）
    - corpus_root 有效 → 逐条验证 knowledge_gold source 存在，且 evidence_phrase
      是 source text 的连续 substring
    """
    if corpus_root is None:
        pytest.skip("GATE4_KNOWLEDGE_CORPUS_ROOT not configured")
    root = Path(corpus_root)
    assert root.is_dir(), f"GATE4_KNOWLEDGE_CORPUS_ROOT 不是目录: {root}"
    set_obj = _real_set()
    for case in set_obj.cases:
        if case.knowledge_gold is None:
            continue
        src = (root / case.knowledge_gold.source_name).resolve()
        assert src.is_file(), (
            f"{case.case_id} source 不存在: {case.knowledge_gold.source_name}"
        )
        text = src.read_text(encoding="utf-8")
        assert case.knowledge_gold.evidence_phrase in text, (
            f"{case.case_id} evidence_phrase 不是 "
            f"{case.knowledge_gold.source_name} 的连续 substring: "
            f"{case.knowledge_gold.evidence_phrase!r}"
        )


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
        assert committed["code_reference_commit"] == CODE_REFERENCE_COMMIT
        assert committed["knowledge_corpus_id"] == KNOWLEDGE_CORPUS_ID
        assert committed["knowledge_corpus_file_count"] == KNOWLEDGE_CORPUS_FILE_COUNT

    def test_manifest_frozen_reference_commit(self):
        # R1 硬化：code_reference_commit 必须绑定 source commit 91627bb...
        assert CODE_REFERENCE_COMMIT.startswith("91627bb3")
        assert KNOWLEDGE_CORPUS_ID == "870e5864df67"
        assert KNOWLEDGE_CORPUS_FILE_COUNT == 37

    def test_identity_frozen_values(self):
        # R1-R1（去本地路径）前后身份必须不变
        set_obj = _real_set()
        assert set_obj.evaluation_set_id == "5639ca57b09a"
        assert (
            hashlib.sha256(JSONL.read_bytes()).hexdigest()
            == "93a32e64130d79a4133fb01d1c84a3103940f286bacece5d2711c38add39e8af"
        )

    def test_g4q020_uses_merge_subquery_results_rrf(self):
        set_obj = _real_set()
        case = next(c for c in set_obj.cases if c.case_id == "g4q020")
        assert "merge_subquery_results_rrf" in case.query

    def test_g4q014_is_initial_experiment_scope(self):
        set_obj = _real_set()
        case = next(c for c in set_obj.cases if c.case_id == "g4q014")
        assert "初始实验" in case.query
        assert case.knowledge_gold is not None
        assert "Chunk 大小：约 300～600 tokens" in case.knowledge_gold.evidence_phrase

    def test_g4q022_allows_both_refuse_reason_codes(self):
        set_obj = _real_set()
        case = next(c for c in set_obj.cases if c.case_id == "g4q022")
        assert set(case.allowed_refuse_reason_codes) == {
            "UNSUPPORTED_REQUEST",
            "UNSAFE_REQUEST",
        }

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

    def test_knowledge_gold_provenance(self):
        # 开发/本地 provenance check：仅当设置了 GATE4_KNOWLEDGE_CORPUS_ROOT 才逐条
        # 验证 source existence + evidence substring；未设置则显式 skip。
        _run_provenance_check(os.environ.get("GATE4_KNOWLEDGE_CORPUS_ROOT"))

    def test_provenance_env_absent_skips(self, monkeypatch):
        monkeypatch.delenv("GATE4_KNOWLEDGE_CORPUS_ROOT", raising=False)
        with pytest.raises(pytest.skip.Exception):
            _run_provenance_check(
                os.environ.get("GATE4_KNOWLEDGE_CORPUS_ROOT")
            )

    def test_provenance_env_nonexistent_dir_fails(self, monkeypatch, tmp_path):
        bad = tmp_path / "not-a-corpus-dir"
        monkeypatch.setenv("GATE4_KNOWLEDGE_CORPUS_ROOT", str(bad))
        with pytest.raises(AssertionError, match="不是目录"):
            _run_provenance_check(
                os.environ.get("GATE4_KNOWLEDGE_CORPUS_ROOT")
            )

    def test_provenance_env_valid_corpus_passes(self, monkeypatch, tmp_path):
        # 用合成语料驱动真实 env 语义：每个 knowledge_gold source 存在，且
        # evidence_phrase 是 source text 的连续 substring（多个 case 共享同一
        # source 文件时聚合全部短语，避免覆盖）
        set_obj = _real_set()
        by_source: dict[str, set[str]] = {}
        for case in set_obj.cases:
            if case.knowledge_gold is None:
                continue
            by_source.setdefault(
                case.knowledge_gold.source_name, set()
            ).add(case.knowledge_gold.evidence_phrase)
        for source_name, phrases in by_source.items():
            src = tmp_path / source_name
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(
                "\n".join("前置 " + p + " 后置" for p in phrases),
                encoding="utf-8",
            )
        monkeypatch.setenv("GATE4_KNOWLEDGE_CORPUS_ROOT", str(tmp_path))
        _run_provenance_check(os.environ.get("GATE4_KNOWLEDGE_CORPUS_ROOT"))

    def test_no_local_drive_path_in_sources(self):
        # 防回归：测试与协议源码不得再写死本机盘符路径（动态构造避免自匹配）
        drive = chr(68)  # "D"
        forbidden_backslash = drive + ":" + "\\"
        forbidden_forward = drive + ":/"
        for f in (Path(__file__).resolve(), PROTOCOL):
            text = f.read_text(encoding="utf-8")
            assert forbidden_backslash not in text, (
                f"{f.name} 含本机盘符路径 {forbidden_backslash!r}"
            )
            assert forbidden_forward not in text, (
                f"{f.name} 含本机盘符路径 {forbidden_forward!r}"
            )


# ---------------------------------------------------------------------- #
# Loader 严格性（字段级，直接调用 _parse_case）
# ---------------------------------------------------------------------- #


def _parse(obj: dict) -> None:
    Gate4ToolUseEvaluationSet._parse_case(obj, 1)


def _knowledge_case_with_contains_all(raw_list: list) -> dict:
    """一个字段级合法的 knowledge_search case，completion_assertions 用
    answer_contains_all，value 引用调用方传入的原始 list（测 detached）。"""
    obj = _calc_case("g4q013")
    obj.update(
        category="knowledge_search",
        expected_first_tool="knowledge_search",
        required_tools=["knowledge_search"],
        forbidden_tools=["calculator", "code_search"],
        completion_assertions=[{"answer_contains_all": raw_list}],
        knowledge_gold={
            "source_name": "rag/文档处理.md",
            "evidence_phrase": "Chunk 大小：约 300～600 tokens",
        },
    )
    return obj


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
        with pytest.raises(ValueError, match="完整覆盖"):
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

    def test_sequence_must_cover_required_tools(self):
        # 每个 allowed sequence 自身都必须完整覆盖 required_tools
        obj = _calc_case(cid="g4q017")
        obj.update(
            category="multi_step",
            expected_first_action="tool_call",
            expected_first_tool=None,
            expected_first_tools=["code_search"],
            required_tools=["code_search", "calculator"],
            allowed_tool_sequences=[["code_search"], ["calculator"]],
            forbidden_tools=["knowledge_search"],
        )
        with pytest.raises(ValueError, match="完整覆盖"):
            _parse(obj)

    def test_expected_first_tools_must_match_sequences(self):
        # set(expected_first_tools) == {seq[0] for seq in allowed_tool_sequences}
        obj = _calc_case(cid="g4q017")
        obj.update(
            category="multi_step",
            expected_first_action="tool_call",
            expected_first_tool=None,
            expected_first_tools=["knowledge_search"],
            required_tools=["code_search", "calculator"],
            allowed_tool_sequences=[["code_search", "calculator"]],
            forbidden_tools=["knowledge_search"],
        )
        with pytest.raises(ValueError, match="expected_first_tools 必须等于"):
            _parse(obj)

    def test_required_forbidden_disjoint(self):
        # 全类别公共不变量：required_tools ∩ forbidden_tools == ∅
        obj = _calc_case()  # calculator，required=[calculator]
        obj["forbidden_tools"] = ["calculator"]
        with pytest.raises(ValueError, match="required_tools 与 forbidden_tools 相交"):
            _parse(obj)

    def test_duplicate_allowed_sequence_reject(self):
        obj = _calc_case(cid="g4q017")
        obj.update(
            category="multi_step",
            expected_first_action="tool_call",
            expected_first_tool=None,
            expected_first_tools=["code_search"],
            required_tools=["code_search", "calculator"],
            allowed_tool_sequences=[
                ["code_search", "calculator"],
                ["code_search", "calculator"],
            ],
            forbidden_tools=["knowledge_search"],
        )
        with pytest.raises(ValueError, match="重复序列"):
            _parse(obj)

    def test_assertion_value_detached_from_raw(self):
        # 修改原 JSON/list（解析后 append）不得改变 EvaluationSet Gold
        raw = ["300", "600"]
        case = Gate4ToolUseEvaluationSet._parse_case(
            _knowledge_case_with_contains_all(raw), 1
        )
        raw.append("999")
        assert case.completion_assertions[0].value == ("300", "600")
        assert case.completion_assertions[0].to_dict() == {
            "answer_contains_all": ["300", "600"]
        }

    def test_assertion_to_dict_is_detached(self):
        # 修改 assertion.to_dict() 返回值不得改变 EvaluationSet Gold
        case = Gate4ToolUseEvaluationSet._parse_case(
            _knowledge_case_with_contains_all(["300", "600"]), 1
        )
        d = case.completion_assertions[0].to_dict()
        d["answer_contains_all"].append("999")
        d["answer_contains_all"][0] = "zzz"
        assert case.completion_assertions[0].to_dict() == {
            "answer_contains_all": ["300", "600"]
        }
        assert case.to_dict()["completion_assertions"] == [
            {"answer_contains_all": ["300", "600"]}
        ]

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
