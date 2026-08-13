"""Tests for Gate 3 bounded Planner output boundary (G3-DECOMP-04A).

Covers: BaseQueryPlanner interface, PlannerOutcome invariants, strict
JSON parsing with duplicate-key rejection, failure classification, unified
fallback, and caller-error propagation. Uses synthetic examples only; never
reads Gate 3 Dev/Holdout, never calls models or network.
"""

from __future__ import annotations

import json

import pytest

from core.query_planning import (
    PLANNER_FAILURE_CODES,
    PLANNER_MODEL_ALLOWED_FIELDS,
    QUERY_PLAN_FALLBACK_POLICY,
    QUERY_PLAN_SCHEMA_VERSION,
    BaseQueryPlanner,
    PlannerOutcome,
    QueryPlan,
    build_fallback_query_plan,
    parse_planner_output,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _no_retrieval_raw() -> str:
    return json.dumps(
        {
            "query_type": "unanswerable_or_no_retrieval",
            "retrieval_required": False,
            "action": "no_retrieval",
            "reason_code": "NO_RETRIEVAL_NEEDED",
            "subqueries": [],
        },
        ensure_ascii=False,
    )


def _single_raw() -> str:
    return json.dumps(
        {
            "query_type": "fact",
            "retrieval_required": True,
            "action": "single_retrieval",
            "reason_code": "SIMPLE_FACT",
            "subqueries": [],
        },
        ensure_ascii=False,
    )


def _decomposed_raw(n: int = 2) -> str:
    subs = [
        {
            "id": "sq1",
            "query": "BM25 检索有什么特点？",
            "evidence_target": "BM25 的机制与适用场景",
            "required": True,
        },
        {
            "id": "sq2",
            "query": "Dense 检索有什么特点？",
            "evidence_target": "Dense 检索的机制与适用场景",
            "required": True,
        },
    ]
    if n == 3:
        subs.append(
            {
                "id": "sq3",
                "query": "Hybrid 检索有什么特点？",
                "evidence_target": "Hybrid 融合的机制",
                "required": True,
            }
        )
    return json.dumps(
        {
            "query_type": "comparison",
            "retrieval_required": True,
            "action": "decomposed_retrieval",
            "reason_code": "COMPARISON_EVIDENCE",
            "subqueries": subs,
        },
        ensure_ascii=False,
    )


def _parse(raw: str, original_query: str = "什么是 BM25？",
           fallback_query_type: str = "fact") -> PlannerOutcome:
    return parse_planner_output(
        original_query=original_query,
        raw_output=raw,
        fallback_query_type=fallback_query_type,
    )


def _assert_fallback(outcome: PlannerOutcome, code: str) -> None:
    assert outcome.fallback_used is True
    assert outcome.failure_code == code
    assert outcome.plan.action == "single_retrieval"
    assert outcome.plan.reason_code == "PLANNER_FALLBACK"
    assert outcome.plan.retrieval_required is True
    assert outcome.plan.subqueries == ()
    assert isinstance(outcome.plan, QueryPlan)


# ---------------------------------------------------------------------------
# 5.1 normal parsing
# ---------------------------------------------------------------------------


class TestNormalParsing:
    def test_valid_no_retrieval(self):
        o = _parse(_no_retrieval_raw(), fallback_query_type="unanswerable_or_no_retrieval")
        assert o.fallback_used is False
        assert o.failure_code is None
        assert o.plan.action == "no_retrieval"
        assert o.plan.query_type == "unanswerable_or_no_retrieval"
        assert o.plan.retrieval_required is False
        assert o.plan.reason_code == "NO_RETRIEVAL_NEEDED"
        assert o.plan.subqueries == ()

    def test_valid_single_retrieval(self):
        o = _parse(_single_raw())
        assert o.fallback_used is False
        assert o.failure_code is None
        assert o.plan.action == "single_retrieval"
        assert o.plan.query_type == "fact"
        assert o.plan.reason_code == "SIMPLE_FACT"

    def test_valid_decomposed_two(self):
        o = _parse(_decomposed_raw(2), original_query="比较 BM25 和 Dense 检索",
                   fallback_query_type="comparison")
        assert o.fallback_used is False
        assert o.failure_code is None
        assert o.plan.action == "decomposed_retrieval"
        assert [s.id for s in o.plan.subqueries] == ["sq1", "sq2"]

    def test_valid_decomposed_three(self):
        o = _parse(_decomposed_raw(3), fallback_query_type="comparison")
        assert o.fallback_used is False
        assert [s.id for s in o.plan.subqueries] == ["sq1", "sq2", "sq3"]

    def test_json_key_order_does_not_matter(self):
        obj = json.loads(_single_raw())
        shuffled = {
            "subqueries": obj["subqueries"],
            "reason_code": obj["reason_code"],
            "action": obj["action"],
            "retrieval_required": obj["retrieval_required"],
            "query_type": obj["query_type"],
        }
        raw = json.dumps(shuffled, ensure_ascii=False)
        o = _parse(raw)
        assert o.fallback_used is False
        assert o.plan.reason_code == "SIMPLE_FACT"

    def test_model_cannot_override_original_query(self):
        caller_query = "调用方注入的原问题"
        o = _parse(_single_raw(), original_query=caller_query)
        assert o.plan.original_query == caller_query
        assert o.plan.original_query != "什么是 BM25？"

    def test_schema_fallback_planid_from_local(self):
        o = _parse(_single_raw())
        assert o.plan.schema_version == QUERY_PLAN_SCHEMA_VERSION
        assert o.plan.fallback_policy == QUERY_PLAN_FALLBACK_POLICY
        assert len(o.plan.plan_id) == 12

    def test_normal_outcome_flags(self):
        o = _parse(_single_raw())
        assert o.fallback_used is False
        assert o.failure_code is None
        assert o.plan.reason_code != "PLANNER_FALLBACK"

    def test_normal_plan_roundtrips_via_from_dict(self):
        o = _parse(_decomposed_raw(2), original_query="比较 BM25 和 Dense 检索",
                   fallback_query_type="comparison")
        restored = QueryPlan.from_dict(o.plan.to_dict())
        assert restored == o.plan


# ---------------------------------------------------------------------------
# 5.2 empty and JSON errors
# ---------------------------------------------------------------------------


class TestEmptyAndJsonErrors:
    def test_empty_string_fallback(self):
        _assert_fallback(_parse(""), "PLAN_EMPTY")

    def test_whitespace_only_fallback(self):
        _assert_fallback(_parse("   \n\t  "), "PLAN_EMPTY")

    def test_invalid_json_fallback(self):
        _assert_fallback(_parse("not json at all"), "PLAN_INVALID_SCHEMA")

    def test_leading_explanation_text_fallback(self):
        raw = "让我先想想：\n" + _single_raw()
        _assert_fallback(_parse(raw), "PLAN_INVALID_SCHEMA")

    def test_trailing_explanation_text_fallback(self):
        raw = _single_raw() + "\n以上就是我的计划。"
        _assert_fallback(_parse(raw), "PLAN_INVALID_SCHEMA")

    def test_markdown_code_fence_fallback(self):
        raw = "```json\n" + _single_raw() + "\n```"
        _assert_fallback(_parse(raw), "PLAN_INVALID_SCHEMA")

    def test_top_level_list_fallback(self):
        _assert_fallback(_parse('[{"a": 1}]'), "PLAN_INVALID_SCHEMA")

    def test_top_level_null_fallback(self):
        _assert_fallback(_parse("null"), "PLAN_INVALID_SCHEMA")

    def test_duplicate_top_level_key_fallback(self):
        raw = (
            '{"query_type":"fact","query_type":"comparison",'
            '"retrieval_required":true,"action":"single_retrieval",'
            '"reason_code":"SIMPLE_FACT","subqueries":[]}'
        )
        _assert_fallback(_parse(raw), "PLAN_INVALID_SCHEMA")

    def test_duplicate_key_inside_subquery_fallback(self):
        # 直接手写 raw JSON，使第一个 subquery 是真正的嵌套 JSON object，
        # 并在其内部制造重复 "id" key。若暂时移除 object_pairs_hook 的重复
        # key 检测，Python 默认解析会“末值覆盖前值”得到 id="sq1"，从而成为
        # 一份合法的两子问题 comparison QueryPlan——因此本测试只有检测到
        # 嵌套重复 key 才会失败（PLAN_INVALID_SCHEMA），不是依赖其他 Schema 错误。
        raw = """
        {
          "query_type": "comparison",
          "retrieval_required": true,
          "action": "decomposed_retrieval",
          "reason_code": "COMPARISON_EVIDENCE",
          "subqueries": [
            {
              "id": "sq1",
              "id": "sq1",
              "query": "A 的特点是什么？",
              "evidence_target": "A 的机制",
              "required": true
            },
            {
              "id": "sq2",
              "query": "B 的特点是什么？",
              "evidence_target": "B 的机制",
              "required": true
            }
          ]
        }
        """
        _assert_fallback(
            _parse(raw, original_query="比较 A 和 B",
                   fallback_query_type="comparison"),
            "PLAN_INVALID_SCHEMA",
        )


# ---------------------------------------------------------------------------
# 5.3 field boundaries
# ---------------------------------------------------------------------------


class TestFieldBoundaries:
    def test_missing_each_allowed_field_fallback(self):
        obj = json.loads(_single_raw())
        for field in ("query_type", "retrieval_required", "action",
                      "reason_code", "subqueries"):
            d = dict(obj)
            del d[field]
            _assert_fallback(
                _parse(json.dumps(d, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
            )

    def test_each_unknown_field_fallback(self):
        obj = json.loads(_single_raw())
        for field in ("original_query", "plan_id", "fallback_policy",
                      "selected_strategy", "candidate_k", "reranker_enabled",
                      "max_rounds", "gold", "chain_of_thought"):
            d = dict(obj)
            d[field] = "任意值"
            _assert_fallback(
                _parse(json.dumps(d, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
            )

    def test_model_original_query_fallback(self):
        obj = json.loads(_single_raw())
        obj["original_query"] = "模型试图注入原问题"
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_model_plan_id_fallback(self):
        obj = json.loads(_single_raw())
        obj["plan_id"] = "b8aa7cf8f976"
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_model_fallback_policy_fallback(self):
        obj = json.loads(_single_raw())
        obj["fallback_policy"] = "hybrid_original_query"
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_model_selected_strategy_fallback(self):
        obj = json.loads(_single_raw())
        obj["selected_strategy"] = "bm25"
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_model_candidate_k_fallback(self):
        obj = json.loads(_single_raw())
        obj["candidate_k"] = 30
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_model_reason_code_planner_fallback(self):
        obj = json.loads(_single_raw())
        obj["reason_code"] = "PLANNER_FALLBACK"
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_subqueries_not_list_fallback(self):
        obj = json.loads(_single_raw())
        obj["subqueries"] = "sq1, sq2"
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_subquery_not_object_fallback(self):
        obj = json.loads(_decomposed_raw(2))
        obj["subqueries"] = ["sq1", "sq2"]
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison"),
            "PLAN_INVALID_SCHEMA",
        )

    def test_subquery_missing_field_fallback(self):
        obj = json.loads(_decomposed_raw(2))
        del obj["subqueries"][0]["query"]
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison"),
            "PLAN_INVALID_SCHEMA",
        )

    def test_subquery_extra_field_fallback(self):
        obj = json.loads(_decomposed_raw(2))
        obj["subqueries"][0]["score"] = 0.9
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison"),
            "PLAN_INVALID_SCHEMA",
        )


# ---------------------------------------------------------------------------
# 5.4 failure classification
# ---------------------------------------------------------------------------


class TestFailureClassification:
    def test_decomposed_zero_fallback_under(self):
        obj = json.loads(_decomposed_raw(2))
        obj["subqueries"] = []
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison"),
            "PLAN_UNDER_DECOMPOSE",
        )

    def test_decomposed_one_fallback_under(self):
        obj = json.loads(_decomposed_raw(2))
        obj["subqueries"] = [obj["subqueries"][0]]
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison"),
            "PLAN_UNDER_DECOMPOSE",
        )

    def test_decomposed_four_fallback_over(self):
        obj = json.loads(_decomposed_raw(3))
        obj["subqueries"].append(
            {
                "id": "sq1",
                "query": "第四条子问题",
                "evidence_target": "多余证据",
                "required": True,
            }
        )
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison"),
            "PLAN_OVER_DECOMPOSE",
        )

    def test_exact_duplicate_query_fallback_duplicate(self):
        obj = json.loads(_decomposed_raw(2))
        obj["subqueries"][1]["query"] = obj["subqueries"][0]["query"]
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison"),
            "PLAN_DUPLICATE_SUBQUERY",
        )

    def test_case_difference_not_exact_duplicate(self):
        obj = json.loads(_decomposed_raw(2))
        obj["subqueries"][1]["query"] = "bm25 检索有什么特点？"  # 大小写不同
        o = _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison")
        assert o.fallback_used is False
        assert o.failure_code is None
        assert o.plan.action == "decomposed_retrieval"

    def test_inner_whitespace_difference_not_exact_duplicate(self):
        obj = json.loads(_decomposed_raw(2))
        obj["subqueries"][1]["query"] = "BM25  检索有什么特点？"  # 中间多空格
        o = _parse(json.dumps(obj, ensure_ascii=False), fallback_query_type="comparison")
        assert o.fallback_used is False
        assert o.failure_code is None

    def test_cross_field_invalid_combination_fallback(self):
        # no_retrieval 却 retrieval_required=true
        obj = json.loads(_no_retrieval_raw())
        obj["retrieval_required"] = True
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False),
                   fallback_query_type="unanswerable_or_no_retrieval"),
            "PLAN_INVALID_SCHEMA",
        )

    def test_single_retrieval_with_subqueries_fallback(self):
        obj = json.loads(_single_raw())
        obj["subqueries"] = json.loads(_decomposed_raw(2))["subqueries"]
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_unknown_action_fallback(self):
        obj = json.loads(_single_raw())
        obj["action"] = "parallel_retrieval"
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )

    def test_retrieval_required_wrong_type_fallback(self):
        obj = json.loads(_single_raw())
        obj["retrieval_required"] = 1
        _assert_fallback(
            _parse(json.dumps(obj, ensure_ascii=False)), "PLAN_INVALID_SCHEMA"
        )


# ---------------------------------------------------------------------------
# 5.5 caller errors are not swallowed
# ---------------------------------------------------------------------------


class TestCallerErrors:
    def test_original_query_non_str(self):
        with pytest.raises(TypeError):
            parse_planner_output(
                original_query=42, raw_output=_single_raw(),
                fallback_query_type="fact",
            )

    def test_original_query_blank(self):
        with pytest.raises(ValueError):
            parse_planner_output(
                original_query="   ", raw_output=_single_raw(),
                fallback_query_type="fact",
            )

    def test_original_query_leading_whitespace(self):
        with pytest.raises(ValueError):
            parse_planner_output(
                original_query=" 什么是 BM25？", raw_output=_single_raw(),
                fallback_query_type="fact",
            )

    def test_fallback_query_type_non_str(self):
        with pytest.raises(TypeError):
            parse_planner_output(
                original_query="x", raw_output=_single_raw(),
                fallback_query_type=5,
            )

    def test_fallback_query_type_not_in_enum(self):
        with pytest.raises(ValueError):
            parse_planner_output(
                original_query="x", raw_output=_single_raw(),
                fallback_query_type="mystery",
            )

    def test_raw_output_non_str(self):
        with pytest.raises(TypeError):
            parse_planner_output(
                original_query="x", raw_output=42, fallback_query_type="fact",
            )

    def test_caller_errors_never_return_fallback(self):
        with pytest.raises((TypeError, ValueError)):
            parse_planner_output(
                original_query="x", raw_output=_single_raw(),
                fallback_query_type="mystery",
            )


# ---------------------------------------------------------------------------
# 5.6 PlannerOutcome invariants
# ---------------------------------------------------------------------------


class TestPlannerOutcomeInvariants:
    def test_plan_must_be_queryplan(self):
        with pytest.raises(TypeError):
            PlannerOutcome(plan={"not": "plan"}, fallback_used=False,
                           failure_code=None)

    def test_fallback_used_must_be_bool(self):
        plan = build_fallback_query_plan("x", "fact")
        with pytest.raises(TypeError):
            PlannerOutcome(plan=plan, fallback_used=1, failure_code="PLAN_EMPTY")

    def test_normal_with_failure_code_rejected(self):
        plan = build_fallback_query_plan("x", "fact")
        with pytest.raises(ValueError):
            PlannerOutcome(plan=plan, fallback_used=False,
                           failure_code="PLAN_EMPTY")

    def test_fallback_without_failure_code_rejected(self):
        plan = build_fallback_query_plan("x", "fact")
        with pytest.raises(ValueError):
            PlannerOutcome(plan=plan, fallback_used=True, failure_code=None)

    def test_fallback_used_but_not_fallback_plan_rejected(self):
        o = _parse(_single_raw())
        with pytest.raises(ValueError):
            PlannerOutcome(plan=o.plan, fallback_used=True,
                           failure_code="PLAN_EMPTY")

    def test_failure_code_not_allowed_rejected(self):
        plan = build_fallback_query_plan("x", "fact")
        with pytest.raises(ValueError):
            PlannerOutcome(plan=plan, fallback_used=True,
                           failure_code="MYSTERY_CODE")

    def test_to_dict_excludes_sensitive_fields(self):
        o = _parse(_single_raw())
        d = o.to_dict()
        assert set(d) == {"plan", "fallback_used", "failure_code"}
        for sensitive in ("raw_output", "exception", "traceback", "prompt",
                          "chain_of_thought", "latency"):
            assert sensitive not in d
            assert sensitive not in json.dumps(d, ensure_ascii=False)

    def test_fallback_plan_id_uses_local_policy(self):
        o = _parse("", original_query="什么是 BM25？", fallback_query_type="fact")
        assert o.plan.reason_code == "PLANNER_FALLBACK"
        assert o.plan.action == "single_retrieval"
        assert o.plan.fallback_policy == QUERY_PLAN_FALLBACK_POLICY
        assert o.plan.subqueries == ()
        assert o.plan.retrieval_required is True


# ---------------------------------------------------------------------------
# 5.7 existing identity no-regression
# ---------------------------------------------------------------------------


class TestExistingIdentityNoRegression:
    def test_fixed_vector_1_via_parse(self):
        o = _parse(_single_raw(), original_query="什么是 BM25？")
        assert o.plan.plan_id == "b8aa7cf8f976"

    def test_fixed_vector_2_via_parse(self):
        o = _parse(_decomposed_raw(2), original_query="比较 BM25 和 Dense 检索",
                   fallback_query_type="comparison")
        assert o.plan.plan_id == "84233ef03b4b"

    def test_parse_never_changes_plan_id_of_valid_plan(self):
        a = _parse(_single_raw(), original_query="什么是 BM25？")
        b = QueryPlan.create(
            original_query="什么是 BM25？",
            query_type="fact",
            retrieval_required=True,
            action="single_retrieval",
            reason_code="SIMPLE_FACT",
            subqueries=(),
        )
        assert a.plan.plan_id == b.plan_id


# ---------------------------------------------------------------------------
# BaseQueryPlanner interface
# ---------------------------------------------------------------------------


class _StubPlanner(BaseQueryPlanner):
    """最小可实例化子类，仅验证接口可被继承。"""

    def plan(self, original_query: str) -> PlannerOutcome:
        return parse_planner_output(
            original_query=original_query,
            raw_output=_single_raw(),
            fallback_query_type="fact",
        )


class TestBaseQueryPlanner:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseQueryPlanner()  # type: ignore[abstract]

    def test_subclass_plan_works(self):
        planner = _StubPlanner()
        o = planner.plan("什么是 BM25？")
        assert isinstance(o, PlannerOutcome)
        assert o.plan.plan_id == "b8aa7cf8f976"

    def test_failure_codes_and_allowed_fields_public(self):
        assert "PLAN_EMPTY" in PLANNER_FAILURE_CODES
        assert "PLAN_INVALID_SCHEMA" in PLANNER_FAILURE_CODES
        assert "PLAN_OVER_DECOMPOSE" in PLANNER_FAILURE_CODES
        assert "PLAN_UNDER_DECOMPOSE" in PLANNER_FAILURE_CODES
        assert "PLAN_DUPLICATE_SUBQUERY" in PLANNER_FAILURE_CODES
        assert "PLAN_NEW_ENTITY" in PLANNER_FAILURE_CODES
        assert "PLANNER_TIMEOUT" in PLANNER_FAILURE_CODES
        assert PLANNER_MODEL_ALLOWED_FIELDS == {
            "query_type", "retrieval_required", "action", "reason_code",
            "subqueries",
        }
