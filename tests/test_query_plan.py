"""Tests for Gate 3 QueryPlan strong-typed contract (G3-PLAN-03).

Covers: fixed plan_id test vectors, legal plan construction (no_retrieval /
single_retrieval / 2-3 subquery decomposed / fallback), strict from_dict /
to_dict isolation, field-level validation, cross-field invariants, and the
fallback factory. Uses synthetic examples only; never reads Gate 3 Dev,
real Cases, or sealed data; never calls models or network.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from core.query_planning import (
    QUERY_PLAN_CLASSIFIED_QUERY_TYPES,
    QUERY_PLAN_FALLBACK_POLICY,
    QUERY_PLAN_FALLBACK_QUERY_TYPE,
    QUERY_PLAN_QUERY_TYPES,
    QUERY_PLAN_SCHEMA_VERSION,
    Subquery,
    QueryPlan,
    build_fallback_query_plan,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _local_sha256(payload: dict) -> str:
    """测试端独立实现的 canonical 哈希（不 import 生产 helper）。"""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:12]


def _sq(
    sq_id: str = "sq1",
    query: str = "BM25 检索有什么特点？",
    evidence_target: str = "BM25 的机制与适用场景",
    required: bool = True,
) -> Subquery:
    return Subquery(
        id=sq_id, query=query, evidence_target=evidence_target, required=required
    )


def _pair() -> tuple[Subquery, Subquery]:
    return (
        Subquery(
            id="sq1",
            query="BM25 检索有什么特点？",
            evidence_target="BM25 的机制与适用场景",
            required=True,
        ),
        Subquery(
            id="sq2",
            query="Dense 检索有什么特点？",
            evidence_target="Dense 检索的机制与适用场景",
            required=True,
        ),
    )


def _triple() -> tuple[Subquery, Subquery, Subquery]:
    return (
        Subquery(id="sq1", query="组件 A 的机制是什么？", evidence_target="组件 A 的机制", required=True),
        Subquery(id="sq2", query="组件 B 的机制是什么？", evidence_target="组件 B 的机制", required=True),
        Subquery(id="sq3", query="组件 C 的机制是什么？", evidence_target="组件 C 的机制", required=True),
    )


def _single(
    original_query: str = "什么是 BM25？",
    query_type: str = "fact",
    reason_code: str = "SIMPLE_FACT",
    retrieval_required: bool = True,
    action: str = "single_retrieval",
    subqueries: tuple[Subquery, ...] = (),
) -> QueryPlan:
    return QueryPlan.create(
        original_query=original_query,
        query_type=query_type,
        retrieval_required=retrieval_required,
        action=action,
        reason_code=reason_code,
        subqueries=subqueries,
    )


def _no_retrieval(original_query: str = "今天是几号？") -> QueryPlan:
    return QueryPlan.create(
        original_query=original_query,
        query_type="unanswerable_or_no_retrieval",
        retrieval_required=False,
        action="no_retrieval",
        reason_code="NO_RETRIEVAL_NEEDED",
        subqueries=(),
    )


def _decomposed(
    subqueries: tuple[Subquery, ...] | None = None,
    original_query: str = "比较 BM25 和 Dense 检索",
    query_type: str = "comparison",
    reason_code: str = "COMPARISON_EVIDENCE",
) -> QueryPlan:
    return QueryPlan.create(
        original_query=original_query,
        query_type=query_type,
        retrieval_required=True,
        action="decomposed_retrieval",
        reason_code=reason_code,
        subqueries=_pair() if subqueries is None else subqueries,
    )


# ---------------------------------------------------------------------------
# fixed plan_id test vectors
# ---------------------------------------------------------------------------


class TestFixedPlanIdVectors:
    def test_vector_1_single_fact(self):
        plan = QueryPlan.create(
            original_query="什么是 BM25？",
            query_type="fact",
            retrieval_required=True,
            action="single_retrieval",
            reason_code="SIMPLE_FACT",
            subqueries=(),
        )
        assert plan.plan_id == "b8aa7cf8f976"

    def test_vector_2_decomposed_comparison(self):
        plan = QueryPlan.create(
            original_query="比较 BM25 和 Dense 检索",
            query_type="comparison",
            retrieval_required=True,
            action="decomposed_retrieval",
            reason_code="COMPARISON_EVIDENCE",
            subqueries=_pair(),
        )
        assert plan.plan_id == "84233ef03b4b"


# ---------------------------------------------------------------------------
# normal path
# ---------------------------------------------------------------------------


class TestNormalPath:
    def test_legal_no_retrieval(self):
        plan = _no_retrieval()
        assert plan.schema_version == QUERY_PLAN_SCHEMA_VERSION
        assert plan.query_type == "unanswerable_or_no_retrieval"
        assert plan.retrieval_required is False
        assert plan.action == "no_retrieval"
        assert plan.reason_code == "NO_RETRIEVAL_NEEDED"
        assert plan.subqueries == ()
        assert plan.fallback_policy == QUERY_PLAN_FALLBACK_POLICY
        assert len(plan.plan_id) == 12

    def test_legal_single_retrieval(self):
        plan = _single()
        assert plan.retrieval_required is True
        assert plan.action == "single_retrieval"
        assert plan.subqueries == ()
        assert plan.query_type == "fact"
        assert plan.reason_code == "SIMPLE_FACT"

    def test_legal_two_subquery_decomposed(self):
        plan = _decomposed()
        assert plan.action == "decomposed_retrieval"
        assert plan.retrieval_required is True
        assert [s.id for s in plan.subqueries] == ["sq1", "sq2"]
        assert all(s.required for s in plan.subqueries)
        assert isinstance(plan.subqueries, tuple)

    def test_legal_three_subquery_decomposed(self):
        plan = _decomposed(subqueries=_triple())
        assert [s.id for s in plan.subqueries] == ["sq1", "sq2", "sq3"]
        assert all(s.required for s in plan.subqueries)
        assert len(plan.subqueries) == 3

    def test_legal_fallback(self):
        plan = build_fallback_query_plan("什么是 BM25？")
        assert plan.retrieval_required is True
        assert plan.action == "single_retrieval"
        assert plan.reason_code == "PLANNER_FALLBACK"
        assert plan.subqueries == ()
        assert plan.fallback_policy == QUERY_PLAN_FALLBACK_POLICY
        assert plan.query_type == QUERY_PLAN_FALLBACK_QUERY_TYPE

    def test_to_dict_from_dict_roundtrip(self):
        plan = _decomposed()
        restored = QueryPlan.from_dict(plan.to_dict())
        assert restored == plan
        assert restored.plan_id == plan.plan_id
        assert [s.to_dict() for s in restored.subqueries] == [
            s.to_dict() for s in plan.subqueries
        ]

    def test_subquery_from_dict_roundtrip(self):
        sq = _sq()
        assert Subquery.from_dict(sq.to_dict()) == sq

    def test_tuple_and_frozen_immutability(self):
        plan = _decomposed()
        with pytest.raises(TypeError):
            plan.subqueries[0] = _sq("sq1")
        with pytest.raises(FrozenInstanceError):
            plan.original_query = "改不了"
        sq = _sq()
        with pytest.raises(FrozenInstanceError):
            sq.query = "改不了"

    def test_to_dict_mutation_isolated(self):
        plan = _decomposed()
        d = plan.to_dict()
        d["plan_id"] = "0" * 12
        d["original_query"] = "被篡改"
        d["subqueries"][0]["query"] = "被篡改"
        d["subqueries"].append(
            {"id": "sq3", "query": "x", "evidence_target": "y", "required": True}
        )
        d["subqueries"].clear()
        assert plan.plan_id != "0" * 12
        assert plan.original_query != "被篡改"
        assert plan.subqueries[0].query != "被篡改"
        assert len(plan.subqueries) == 2

    def test_dict_key_order_does_not_affect_from_dict(self):
        plan = _single()
        d = plan.to_dict()
        shuffled = {
            "fallback_policy": d["fallback_policy"],
            "subqueries": d["subqueries"],
            "reason_code": d["reason_code"],
            "action": d["action"],
            "retrieval_required": d["retrieval_required"],
            "query_type": d["query_type"],
            "original_query": d["original_query"],
            "plan_id": d["plan_id"],
            "schema_version": d["schema_version"],
        }
        restored = QueryPlan.from_dict(shuffled)
        assert restored == plan

    def test_subquery_order_affects_plan_id(self):
        plan = _decomposed()
        payload = plan.identity_payload()
        assert plan.plan_id == _local_sha256(payload)
        reversed_payload = dict(payload)
        reversed_payload["subqueries"] = list(reversed(payload["subqueries"]))
        assert _local_sha256(reversed_payload) != _local_sha256(payload)

    def test_identity_payload_excludes_plan_id(self):
        plan = _decomposed()
        payload = plan.identity_payload()
        assert "plan_id" not in payload
        assert payload["schema_version"] == QUERY_PLAN_SCHEMA_VERSION
        assert payload["original_query"] == plan.original_query
        assert payload["query_type"] == plan.query_type
        assert payload["retrieval_required"] is plan.retrieval_required
        assert payload["action"] == plan.action
        assert payload["reason_code"] == plan.reason_code
        assert payload["fallback_policy"] == plan.fallback_policy
        assert [s["id"] for s in payload["subqueries"]] == ["sq1", "sq2"]

    def test_to_dict_includes_plan_id_and_all_fields(self):
        plan = _single()
        d = plan.to_dict()
        assert d["schema_version"] == QUERY_PLAN_SCHEMA_VERSION
        assert d["plan_id"] == plan.plan_id
        assert d["original_query"] == plan.original_query
        assert d["query_type"] == plan.query_type
        assert d["retrieval_required"] is plan.retrieval_required
        assert d["action"] == plan.action
        assert d["reason_code"] == plan.reason_code
        assert d["subqueries"] == []
        assert d["fallback_policy"] == QUERY_PLAN_FALLBACK_POLICY


# ---------------------------------------------------------------------------
# field-level errors
# ---------------------------------------------------------------------------


class TestFieldErrors:
    def test_original_query_empty(self):
        with pytest.raises(ValueError) as ei:
            _single(original_query="")
        assert "original_query" in str(ei.value)

    def test_original_query_whitespace_only(self):
        with pytest.raises(ValueError):
            _single(original_query="   ")

    def test_original_query_leading_whitespace(self):
        with pytest.raises(ValueError):
            _single(original_query=" 什么是 BM25？")

    def test_original_query_trailing_whitespace(self):
        with pytest.raises(ValueError):
            _single(original_query="什么是 BM25？ ")

    def test_original_query_too_long(self):
        with pytest.raises(ValueError) as ei:
            _single(original_query="x" * 4001)
        assert "4000" in str(ei.value)

    def test_original_query_wrong_type(self):
        with pytest.raises(TypeError):
            _single(original_query=42)

    def test_unknown_query_type(self):
        with pytest.raises(ValueError) as ei:
            _single(query_type="mystery")
        assert "mystery" in str(ei.value)

    def test_query_type_wrong_type(self):
        with pytest.raises(TypeError):
            _single(query_type=5)

    def test_unknown_action(self):
        with pytest.raises(ValueError) as ei:
            _single(action="parallel_retrieval")
        assert "parallel_retrieval" in str(ei.value)

    def test_action_wrong_type(self):
        with pytest.raises(TypeError):
            _single(action=1)

    def test_unknown_reason_code(self):
        with pytest.raises(ValueError) as ei:
            _single(reason_code="I_THOUGHT_SO")
        assert "I_THOUGHT_SO" in str(ei.value)

    def test_reason_code_wrong_type(self):
        with pytest.raises(TypeError):
            _single(reason_code=None)

    def test_retrieval_required_int_rejected(self):
        with pytest.raises(TypeError) as ei:
            _single(retrieval_required=1)
        assert "retrieval_required" in str(ei.value)

    def test_retrieval_required_string_rejected(self):
        with pytest.raises(TypeError):
            _single(retrieval_required="true")

    def test_retrieval_required_none_rejected(self):
        with pytest.raises(TypeError):
            _single(retrieval_required=None)

    def test_wrong_schema_version(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="x",
                query_type="fact",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
                schema_version="query_plan_v2",
            )
        assert "query_plan_v2" in str(ei.value)

    def test_schema_version_wrong_type(self):
        with pytest.raises(TypeError):
            QueryPlan.create(
                original_query="x",
                query_type="fact",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
                schema_version=123,
            )

    def test_wrong_fallback_policy(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="x",
                query_type="fact",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
                fallback_policy="hybrid_original_query",
            )
        assert "hybrid_original_query" in str(ei.value)

    def test_plan_id_wrong_format_uppercase(self):
        d = _single().to_dict()
        d["plan_id"] = d["plan_id"].upper()
        with pytest.raises(ValueError):
            QueryPlan.from_dict(d)

    def test_plan_id_wrong_length(self):
        d = _single().to_dict()
        d["plan_id"] = "abc"
        with pytest.raises(ValueError):
            QueryPlan.from_dict(d)

    def test_plan_id_mismatch_rejected(self):
        d = _single().to_dict()
        d["plan_id"] = "0" * 12
        with pytest.raises(ValueError) as ei:
            QueryPlan.from_dict(d)
        assert "plan_id" in str(ei.value)

    def test_from_dict_plan_id_non_string_raises_typeerror(self):
        d = _single().to_dict()
        for bad in (123, None):
            bad_d = dict(d)
            bad_d["plan_id"] = bad
            with pytest.raises(TypeError) as ei:
                QueryPlan.from_dict(bad_d)
            assert "plan_id" in str(ei.value)

    def test_create_non_serializable_fields_raise_field_typeerror(self):
        base = {
            "original_query": "什么是 BM25？",
            "query_type": "fact",
            "retrieval_required": True,
            "action": "single_retrieval",
            "reason_code": "SIMPLE_FACT",
        }
        fields = (
            "schema_version",
            "original_query",
            "query_type",
            "retrieval_required",
            "action",
            "reason_code",
            "fallback_policy",
        )
        for field in fields:
            kwargs = dict(base)
            kwargs[field] = {1, 2, 3}  # set 不可 JSON 序列化
            with pytest.raises(TypeError) as ei:
                QueryPlan.create(**kwargs)
            assert field in str(ei.value)
            assert "not JSON serializable" not in str(ei.value)

    def test_query_plan_unknown_field_rejected(self):
        d = _single().to_dict()
        d["selected_strategy"] = "bm25"
        with pytest.raises(ValueError) as ei:
            QueryPlan.from_dict(d)
        assert "selected_strategy" in str(ei.value)

    def test_query_plan_missing_field_rejected(self):
        d = _single().to_dict()
        del d["reason_code"]
        with pytest.raises(ValueError) as ei:
            QueryPlan.from_dict(d)
        assert "reason_code" in str(ei.value)

    def test_query_plan_not_dict_rejected(self):
        with pytest.raises(TypeError):
            QueryPlan.from_dict(["x"])

    def test_from_dict_subqueries_not_list(self):
        d = _single().to_dict()
        d["subqueries"] = "nope"
        with pytest.raises(TypeError):
            QueryPlan.from_dict(d)

    def test_from_dict_invalid_subquery(self):
        d = _decomposed().to_dict()
        del d["subqueries"][0]["query"]
        with pytest.raises(ValueError):
            QueryPlan.from_dict(d)

    def test_subquery_unknown_field_rejected(self):
        d = _sq().to_dict()
        d["score"] = 1
        with pytest.raises(ValueError) as ei:
            Subquery.from_dict(d)
        assert "score" in str(ei.value)

    def test_subquery_missing_field_rejected(self):
        d = _sq().to_dict()
        del d["evidence_target"]
        with pytest.raises(ValueError) as ei:
            Subquery.from_dict(d)
        assert "evidence_target" in str(ei.value)

    def test_subquery_not_dict_rejected(self):
        with pytest.raises(TypeError):
            Subquery.from_dict("sq1")

    def test_subquery_id_wrong_value(self):
        with pytest.raises(ValueError) as ei:
            _sq(sq_id="sq4")
        assert "sq4" in str(ei.value)

    def test_subquery_id_wrong_type(self):
        with pytest.raises(TypeError):
            _sq(sq_id=1)

    def test_subquery_query_empty(self):
        with pytest.raises(ValueError):
            _sq(query="")

    def test_subquery_query_whitespace_only(self):
        with pytest.raises(ValueError):
            _sq(query="   ")

    def test_subquery_query_leading_whitespace(self):
        with pytest.raises(ValueError):
            _sq(query=" x")

    def test_subquery_query_trailing_whitespace(self):
        with pytest.raises(ValueError):
            _sq(query="x ")

    def test_subquery_query_too_long(self):
        with pytest.raises(ValueError) as ei:
            _sq(query="x" * 1001)
        assert "1000" in str(ei.value)

    def test_subquery_query_wrong_type(self):
        with pytest.raises(TypeError):
            _sq(query=123)

    def test_subquery_evidence_target_empty(self):
        with pytest.raises(ValueError):
            _sq(query="x", evidence_target="")

    def test_subquery_evidence_target_whitespace_only(self):
        with pytest.raises(ValueError):
            _sq(query="x", evidence_target="  ")

    def test_subquery_evidence_target_leading_whitespace(self):
        with pytest.raises(ValueError):
            _sq(query="x", evidence_target=" y")

    def test_subquery_evidence_target_trailing_whitespace(self):
        with pytest.raises(ValueError):
            _sq(query="x", evidence_target="y ")

    def test_subquery_evidence_target_too_long(self):
        with pytest.raises(ValueError) as ei:
            _sq(query="x", evidence_target="y" * 501)
        assert "500" in str(ei.value)

    def test_subquery_evidence_target_wrong_type(self):
        with pytest.raises(TypeError):
            _sq(query="x", evidence_target=True)

    def test_subquery_required_false_rejected(self):
        with pytest.raises(ValueError) as ei:
            _sq(query="x", evidence_target="y", required=False)
        assert "required" in str(ei.value)

    def test_subquery_required_int_rejected(self):
        with pytest.raises(TypeError):
            _sq(query="x", evidence_target="y", required=1)

    def test_subquery_required_string_rejected(self):
        with pytest.raises(TypeError):
            _sq(query="x", evidence_target="y", required="true")


# ---------------------------------------------------------------------------
# cross-field invariants
# ---------------------------------------------------------------------------


class TestCrossFieldInvariants:
    def test_no_retrieval_with_retrieval_true(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="今天是几号？",
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=True,
                action="no_retrieval",
                reason_code="NO_RETRIEVAL_NEEDED",
                subqueries=(),
            )
        assert "retrieval_required" in str(ei.value)

    def test_no_retrieval_with_subquery(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="今天是几号？",
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=False,
                action="no_retrieval",
                reason_code="NO_RETRIEVAL_NEEDED",
                subqueries=_pair(),
            )
        assert "subqueries" in str(ei.value)

    def test_no_retrieval_wrong_query_type(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="什么是 BM25？",
                query_type="fact",
                retrieval_required=False,
                action="no_retrieval",
                reason_code="NO_RETRIEVAL_NEEDED",
                subqueries=(),
            )
        assert "query_type" in str(ei.value)

    def test_no_retrieval_wrong_reason_code(self):
        with pytest.raises(ValueError):
            QueryPlan.create(
                original_query="今天是几号？",
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=False,
                action="no_retrieval",
                reason_code="SIMPLE_FACT",
                subqueries=(),
            )

    def test_no_retrieval_needed_used_on_other_action(self):
        with pytest.raises(ValueError) as ei:
            _single(reason_code="NO_RETRIEVAL_NEEDED")
        assert "NO_RETRIEVAL_NEEDED" in str(ei.value)

    def test_single_retrieval_with_subquery(self):
        with pytest.raises(ValueError) as ei:
            _single(subqueries=_pair())
        assert "subqueries" in str(ei.value)

    def test_decomposed_with_zero_subqueries(self):
        with pytest.raises(ValueError) as ei:
            _decomposed(subqueries=())
        assert "2 或 3" in str(ei.value) or "subqueries" in str(ei.value)

    def test_decomposed_with_one_subquery(self):
        with pytest.raises(ValueError) as ei:
            _decomposed(subqueries=(_sq("sq1"),))
        assert "2 或 3" in str(ei.value)

    def test_decomposed_with_four_subqueries(self):
        with pytest.raises(ValueError) as ei:
            _decomposed(subqueries=_triple() + (_sq("sq1"),))
        assert "4" in str(ei.value) or "subqueries" in str(ei.value)

    def test_decomposed_with_retrieval_false(self):
        with pytest.raises(ValueError):
            QueryPlan.create(
                original_query="比较 BM25 和 Dense 检索",
                query_type="comparison",
                retrieval_required=False,
                action="decomposed_retrieval",
                reason_code="COMPARISON_EVIDENCE",
                subqueries=_pair(),
            )

    def test_decomposed_sq_id_not_continuous(self):
        with pytest.raises(ValueError) as ei:
            _decomposed(subqueries=(_sq("sq1"), _sq("sq3")))
        assert "sq2" in str(ei.value) or "连续" in str(ei.value)

    def test_decomposed_sq_id_out_of_order(self):
        with pytest.raises(ValueError) as ei:
            _decomposed(subqueries=(_sq("sq2"), _sq("sq1")))
        assert "连续" in str(ei.value) or "sq1" in str(ei.value)

    def test_decomposed_duplicate_query_rejected(self):
        with pytest.raises(ValueError) as ei:
            _decomposed(
                subqueries=(
                    Subquery(id="sq1", query="BM25 的特点", evidence_target="A", required=True),
                    Subquery(id="sq2", query="BM25 的特点", evidence_target="B", required=True),
                )
            )
        assert "重复" in str(ei.value)

    def test_planner_fallback_used_for_decomposed(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="比较 BM25 和 Dense 检索",
                query_type="comparison",
                retrieval_required=True,
                action="decomposed_retrieval",
                reason_code="PLANNER_FALLBACK",
                subqueries=_pair(),
            )
        assert "PLANNER_FALLBACK" in str(ei.value)

    def test_planner_fallback_on_no_retrieval(self):
        with pytest.raises(ValueError):
            QueryPlan.create(
                original_query="今天是几号？",
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=False,
                action="no_retrieval",
                reason_code="PLANNER_FALLBACK",
                subqueries=(),
            )

    def test_unanswerable_retrieval_true_decomposed(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="这个功能存在吗？",
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=True,
                action="decomposed_retrieval",
                reason_code="UNANSWERABLE_CHECK",
                subqueries=_pair(),
            )
        assert "single_retrieval" in str(ei.value)

    def test_unanswerable_check_wrong_reason_code(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="这个功能存在吗？",
                query_type="unanswerable_or_no_retrieval",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
                subqueries=(),
            )
        assert "UNANSWERABLE_CHECK" in str(ei.value)

    def test_unanswerable_check_legal(self):
        plan = QueryPlan.create(
            original_query="这个功能存在吗？",
            query_type="unanswerable_or_no_retrieval",
            retrieval_required=True,
            action="single_retrieval",
            reason_code="UNANSWERABLE_CHECK",
            subqueries=(),
        )
        assert plan.action == "single_retrieval"
        assert plan.retrieval_required is True
        assert plan.reason_code == "UNANSWERABLE_CHECK"
        assert plan.subqueries == ()


# ---------------------------------------------------------------------------
# create strictness
# ---------------------------------------------------------------------------


class TestCreateStrictness:
    def test_subqueries_not_tuple_or_list(self):
        with pytest.raises(TypeError):
            QueryPlan.create(
                original_query="x",
                query_type="fact",
                retrieval_required=True,
                action="single_retrieval",
                reason_code="SIMPLE_FACT",
                subqueries="sq1",
            )

    def test_subqueries_element_not_subquery(self):
        with pytest.raises(TypeError):
            QueryPlan.create(
                original_query="比较 A 和 B",
                query_type="comparison",
                retrieval_required=True,
                action="decomposed_retrieval",
                reason_code="COMPARISON_EVIDENCE",
                subqueries=[
                    {"id": "sq1", "query": "A", "evidence_target": "B",
                     "required": True}
                ],
            )


# ---------------------------------------------------------------------------
# fallback factory
# ---------------------------------------------------------------------------


class TestFallbackFactory:
    def test_fallback_legal_fields(self):
        plan = build_fallback_query_plan("什么是 BM25？")
        assert plan.retrieval_required is True
        assert plan.action == "single_retrieval"
        assert plan.reason_code == "PLANNER_FALLBACK"
        assert plan.subqueries == ()
        assert plan.fallback_policy == QUERY_PLAN_FALLBACK_POLICY
        assert plan.schema_version == QUERY_PLAN_SCHEMA_VERSION

    def test_fallback_uses_system_unknown_query_type(self):
        plan = build_fallback_query_plan("什么是 BM25？")
        assert plan.query_type == QUERY_PLAN_FALLBACK_QUERY_TYPE
        assert plan.query_type == "unknown"

    def test_fallback_does_not_accept_query_type_param(self):
        with pytest.raises(TypeError):
            build_fallback_query_plan("x", "fact")

    def test_fallback_plan_id_stable(self):
        a = build_fallback_query_plan("什么是 BM25？")
        b = build_fallback_query_plan("什么是 BM25？")
        assert a.plan_id == b.plan_id
        assert len(a.plan_id) == 12

    def test_fallback_plan_id_changes_with_query(self):
        a = build_fallback_query_plan("什么是 BM25？")
        b = build_fallback_query_plan("什么是 Dense？")
        assert a.plan_id != b.plan_id

    def test_fallback_empty_query_rejected(self):
        with pytest.raises(ValueError):
            build_fallback_query_plan("")

    def test_fallback_whitespace_query_rejected(self):
        with pytest.raises(ValueError):
            build_fallback_query_plan("  ")

    def test_fallback_original_query_wrong_type(self):
        with pytest.raises(TypeError):
            build_fallback_query_plan(42)


class TestQueryTypeConstants:
    def test_classified_types_are_exactly_seven(self):
        assert QUERY_PLAN_CLASSIFIED_QUERY_TYPES == (
            "fact",
            "comparison",
            "causal",
            "multi_entity",
            "code_symbol",
            "troubleshooting",
            "unanswerable_or_no_retrieval",
        )

    def test_fallback_type_is_unknown(self):
        assert QUERY_PLAN_FALLBACK_QUERY_TYPE == "unknown"

    def test_total_enum_contains_classified_and_unknown(self):
        assert QUERY_PLAN_QUERY_TYPES == (
            QUERY_PLAN_CLASSIFIED_QUERY_TYPES
            + (QUERY_PLAN_FALLBACK_QUERY_TYPE,)
        )
        assert QUERY_PLAN_FALLBACK_QUERY_TYPE in QUERY_PLAN_QUERY_TYPES
        assert all(q in QUERY_PLAN_QUERY_TYPES for q in QUERY_PLAN_CLASSIFIED_QUERY_TYPES)


class TestUnknownFallbackInvariants:
    def test_unknown_with_planner_fallback_legal(self):
        plan = build_fallback_query_plan("x")
        assert plan.query_type == "unknown"
        assert plan.reason_code == "PLANNER_FALLBACK"

    def test_unknown_with_simple_fact_rejected(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="x", query_type="unknown",
                retrieval_required=True, action="single_retrieval",
                reason_code="SIMPLE_FACT", subqueries=(),
            )
        assert "unknown" in str(ei.value)

    def test_unknown_with_decomposed_rejected(self):
        with pytest.raises(ValueError):
            QueryPlan.create(
                original_query="比较 A 和 B", query_type="unknown",
                retrieval_required=True, action="decomposed_retrieval",
                reason_code="COMPARISON_EVIDENCE",
                subqueries=(
                    Subquery(id="sq1", query="A 是什么？",
                             evidence_target="A 的机制", required=True),
                    Subquery(id="sq2", query="B 是什么？",
                             evidence_target="B 的机制", required=True),
                ),
            )

    def test_fact_with_planner_fallback_rejected(self):
        with pytest.raises(ValueError) as ei:
            QueryPlan.create(
                original_query="x", query_type="fact",
                retrieval_required=True, action="single_retrieval",
                reason_code="PLANNER_FALLBACK", subqueries=(),
            )
        assert "PLANNER_FALLBACK" in str(ei.value)

    def test_comparison_with_planner_fallback_rejected(self):
        with pytest.raises(ValueError):
            QueryPlan.create(
                original_query="x", query_type="comparison",
                retrieval_required=True, action="single_retrieval",
                reason_code="PLANNER_FALLBACK", subqueries=(),
            )
