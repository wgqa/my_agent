"""Tests for G3-E2E-07A real E2E answer evaluation.

Covers: Gold isolation boundary (GenerationCase carries only case_id/query);
LLM Judge structured parser + invalid-output fallback; deterministic citation
evaluator; aggregate answer metric arithmetic; run identity distinguishes
Planner/Generator/Judge/merge config; artifact secret redaction. Uses synthetic
cases and fake clients only — no network, no model calls, no Holdout.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from evaluation.gate3.e2e import (
    GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    AnswerJudge,
    Gate3E2EConfig,
    GenerationCase,
    assert_no_secrets,
    compute_answer_metrics,
    evaluate_citations,
    load_generation_cases,
    parse_citations,
    parse_judge_output,
)
from evaluation.gate3.evaluation_set import (
    EvidenceObligation,
    Gate3Case,
    Gate3EvaluationSet,
)

PLANNER_SHA = "5b209054f5274fa8f1f88975625c80b78d7e9e2a84569179288fed0c3a3b5c95"


def _config(**kw) -> Gate3E2EConfig:
    kwargs = dict(
        source_commit="f" * 40,
        corpus_id="870e5864df67",
        corpus_file_count=37,
        gate3_dataset_freeze_id="257fa0d0a6d6",
        dev_evaluation_set_id="f2144030d754",
        dev_case_count=24,
        dev_jsonl_sha256="0b" * 32,
        planner_prompt_sha256=PLANNER_SHA,
        judge_prompt_sha256=GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    )
    kwargs.update(kw)
    return Gate3E2EConfig(**kwargs)


# ---------------------------------------------------------------------------
# Gold 隔离
# ---------------------------------------------------------------------------


class TestGoldIsolation:
    def test_generation_case_only_case_id_and_query(self):
        fields = [f.name for f in dataclasses.fields(GenerationCase)]
        assert fields == ["case_id", "query"]

    def test_load_generation_cases_strips_gold(self, tmp_path):
        dev = tmp_path / "dev.jsonl"
        dev.write_text(
            json.dumps(
                {
                    "schema_version": "gate3_case_v1",
                    "case_id": "g3q001",
                    "query": "alpha 是什么",
                    "query_type": "fact",
                    "answerability": "answerable",
                    "decomposition_expected": "forbidden",
                    "retrieval_required": True,
                    "evidence_obligations": [
                        {"obligation_id": "o1", "description": "d",
                         "relevant_files": ["a/doc1.md"], "required": True}
                    ],
                    "relevant_files": ["a/doc1.md"],
                    "tags": ["fact"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        cases = load_generation_cases(str(dev))
        assert len(cases) == 1
        gc = cases[0]
        assert gc.case_id == "g3q001"
        assert gc.query == "alpha 是什么"
        # GenerationCase 的实例字典只含 case_id/query，绝无 Gold 字段
        assert set(dataclasses.asdict(gc).keys()) == {"case_id", "query"}

    def test_load_generation_cases_rejects_missing_query(self, tmp_path):
        dev = tmp_path / "dev.jsonl"
        dev.write_text(json.dumps({"case_id": "g3q001"}) + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_generation_cases(str(dev))

    def test_generation_record_has_no_gold_keys(self):
        record = {
            "case_id": "g3q001", "query": "q", "status": "completed",
            "plan_id": "x", "route": "single_retrieval",
            "retrieval_call_count": 1, "candidate_canonical_paths": [],
            "retrieved_canonical_paths": [], "evidence_count": 0,
            "fallback_used": False, "failure_code": None,
            "answer": "a", "cited_citation_ids": [], "evidence_citation_ids": [],
        }
        for k in ("evidence_obligations", "relevant_files", "gold",
                  "expected_answer", "evaluator_rubric"):
            assert k not in record


# ---------------------------------------------------------------------------
# Judge 结构化 parser 与 fallback
# ---------------------------------------------------------------------------


class TestJudgeParser:
    def test_parse_valid(self):
        out = parse_judge_output(
            '{"obligation_coverage": {"o1": "covered", "o2": "not_covered"}, '
            '"unsupported_material_claims": ["c"]}'
        )
        assert out["obligation_coverage"] == {"o1": "covered", "o2": "not_covered"}
        assert out["unsupported_material_claims"] == ["c"]

    def test_parse_accepts_missing_claims(self):
        out = parse_judge_output('{"obligation_coverage": {"o1": "covered"}}')
        assert out["unsupported_material_claims"] == []

    def test_parse_rejects_invalid(self):
        with pytest.raises(ValueError):
            parse_judge_output("not json")
        with pytest.raises(ValueError):
            parse_judge_output("")
        with pytest.raises(ValueError):
            parse_judge_output("[1,2]")  # 非 object
        with pytest.raises(ValueError):
            parse_judge_output('{"obligation_coverage": {}}')  # 空
        with pytest.raises(ValueError):
            parse_judge_output('{"obligation_coverage": {"o1": "maybe"}}')  # 非法值
        with pytest.raises(ValueError):
            parse_judge_output(
                '{"obligation_coverage": {"o1": "covered", "o1": "not_covered"}}'
            )  # 重复 key

    def test_judge_invalid_output_fallback(self):
        client = _FakeClient("不是 JSON")
        judge = AnswerJudge(config=_config(), api_key="x", client=client)
        result = judge.judge("q", "a", [], [{"obligation_id": "o1", "description": "d"}])
        assert result["judge_status"] == "invalid"

    def test_judge_ok_output(self):
        client = _FakeClient(
            '{"obligation_coverage": {"o1": "covered"}, '
            '"unsupported_material_claims": []}'
        )
        judge = AnswerJudge(config=_config(), api_key="x", client=client)
        result = judge.judge("q", "a", [], [{"obligation_id": "o1", "description": "d"}])
        assert result["judge_status"] == "ok"
        assert result["obligation_coverage"] == {"o1": "covered"}


# ---------------------------------------------------------------------------
# Citation 解析 / 校验
# ---------------------------------------------------------------------------


class TestCitationEvaluator:
    def test_parse_citations(self):
        assert parse_citations("答案[C1]和[C3]") == {1, 3}
        assert parse_citations(None) == set()
        assert parse_citations("无引用") == set()

    def test_evaluate_citations(self):
        r = evaluate_citations("答案[C1][C9]", [1, 2, 3])
        assert r["cited_count"] == 2
        assert r["valid_count"] == 1
        assert r["invalid_count"] == 1
        assert r["invalid_ids"] == [9]
        assert r["uncited_evidence_count"] == 2
        assert r["uncited_ids"] == [2, 3]

    def test_evaluate_citations_all_valid(self):
        r = evaluate_citations("答案[C1]", [1, 2])
        assert r["invalid_count"] == 0
        assert r["uncited_evidence_count"] == 1


# ---------------------------------------------------------------------------
# 聚合算术（answer 指标）
# ---------------------------------------------------------------------------


def _dev_set_e2e():
    ob1 = EvidenceObligation("o1", "方面A", ("a.md",), True)
    ob2 = EvidenceObligation("o1", "方面B", ("b.md",), True)
    ob3 = EvidenceObligation("o2", "方面C", ("c.md",), True)
    c1 = Gate3Case(
        schema_version="gate3_case_v1", case_id="g3q001", query="q1",
        query_type="fact", answerability="answerable",
        decomposition_expected="forbidden", retrieval_required=True,
        evidence_obligations=(ob1,), relevant_files=("a.md",), tags=("fact",),
    )
    c2 = Gate3Case(
        schema_version="gate3_case_v1", case_id="g3q002", query="q2",
        query_type="comparison", answerability="answerable",
        decomposition_expected="required", retrieval_required=True,
        evidence_obligations=(ob2, ob3), relevant_files=("b.md", "c.md"),
        tags=("comparison",),
    )
    c3 = Gate3Case(
        schema_version="gate3_case_v1", case_id="g3q003", query="q3",
        query_type="unanswerable_or_no_retrieval", answerability="no_retrieval",
        decomposition_expected="forbidden", retrieval_required=False,
        evidence_obligations=(), relevant_files=(), tags=("no_retrieval",),
    )
    return Gate3EvaluationSet(
        corpus_id="870e5864df67", cases=(c1, c2, c3), evaluation_set_id="t"
    )


class TestAggregateArithmetic:
    def test_answer_metrics_arithmetic(self):
        dev_set = _dev_set_e2e()
        case_by_id = {c.case_id: c for c in dev_set.cases}
        records = [
            {"case_id": "g3q001", "status": "completed", "answer": "答案[C1]",
             "evidence_citation_ids": [1], "retrieved_canonical_paths": ["a.md"],
             "retrieval_call_count": 1, "evidence_count": 1},
            {"case_id": "g3q002", "status": "completed", "answer": "答案[C1][C2]",
             "evidence_citation_ids": [1, 2],
             "retrieved_canonical_paths": ["b.md", "c.md"],
             "retrieval_call_count": 2, "evidence_count": 2},
            {"case_id": "g3q003", "status": "completed", "answer": "42",
             "evidence_citation_ids": [], "retrieved_canonical_paths": [],
             "retrieval_call_count": 0, "evidence_count": 0},
        ]
        judgments = [
            {"case_id": "g3q001", "judge_output": {
                "judge_status": "ok", "obligation_coverage": {"o1": "covered"},
                "unsupported_material_claims": []}},
            {"case_id": "g3q002", "judge_output": {
                "judge_status": "ok",
                "obligation_coverage": {"o1": "covered", "o2": "not_covered"},
                "unsupported_material_claims": []}},
            {"case_id": "g3q003", "judge_output": {"judge_status": "not_generated"}},
        ]
        m = compute_answer_metrics(records, judgments, dev_set, case_by_id)
        assert m["answer_obligation_covered"] == 2
        assert m["answer_obligation_total"] == 3
        assert m["answer_obligation_coverage_rate"] == pytest.approx(2 / 3)
        assert m["answer_full_coverage_case_count"] == 1
        assert m["answerable_case_count"] == 2
        # 两个 answerable 的 citation 都有效（[C1]/[C1][C2] 都在 evidence 里）
        assert m["citation_valid_case_count"] == 2
        assert m["unsupported_claim_case_count"] == 0
        # pass：g3q001（全覆盖 + citation 有效 + 无 unsupported）；g3q002 不全覆盖
        assert m["answer_pass_case_count"] == 1
        assert m["non_answerable_case_count"] == 1
        assert m["non_answerable_cases"] == ["g3q003"]

    def test_answer_metrics_unsupported_and_invalid_judge(self):
        dev_set = _dev_set_e2e()
        case_by_id = {c.case_id: c for c in dev_set.cases}
        records = [
            {"case_id": "g3q001", "status": "completed", "answer": "答案[C1]",
             "evidence_citation_ids": [1], "retrieved_canonical_paths": ["a.md"],
             "retrieval_call_count": 1, "evidence_count": 1},
            {"case_id": "g3q002", "status": "completed", "answer": "答案[C1]",
             "evidence_citation_ids": [1, 2], "retrieved_canonical_paths": ["b.md"],
             "retrieval_call_count": 2, "evidence_count": 1},
            {"case_id": "g3q003", "status": "completed", "answer": "42",
             "evidence_citation_ids": [], "retrieved_canonical_paths": [],
             "retrieval_call_count": 0, "evidence_count": 0},
        ]
        judgments = [
            {"case_id": "g3q001", "judge_output": {
                "judge_status": "ok", "obligation_coverage": {"o1": "covered"},
                "unsupported_material_claims": ["明显幻觉主张"]}},
            {"case_id": "g3q002", "judge_output": {
                "judge_status": "invalid", "reason": "unparseable"}},
            {"case_id": "g3q003", "judge_output": {"judge_status": "not_generated"}},
        ]
        m = compute_answer_metrics(records, judgments, dev_set, case_by_id)
        # g3q001 有 unsupported → 不计 pass；g3q002 judge 无效 → covered 0
        assert m["unsupported_claim_case_count"] == 1
        assert m["invalid_judge_case_count"] == 1
        assert m["answer_obligation_covered"] == 1
        assert m["answer_pass_case_count"] == 0


# ---------------------------------------------------------------------------
# run identity
# ---------------------------------------------------------------------------


class TestRunIdentity:
    def test_run_id_distinguishes_models_and_merge(self):
        base = _config()
        assert base.run_id != _config(planner_model="deepseek-v4-flash").run_id
        assert base.run_id != _config(generator_model="deepseek-chat").run_id
        assert base.run_id != _config(judge_model="deepseek-v4-flash").run_id
        assert base.run_id != _config(
            merge_policy="subquery_round_robin_v1"
        ).run_id
        assert base.run_id != _config(generator_temperature=0.0).run_id

    def test_run_id_ignores_output_path(self):
        base = _config(output_dir="a/b")
        other = _config(output_dir="c/d")
        assert base.run_id == other.run_id


# ---------------------------------------------------------------------------
# secret redaction
# ---------------------------------------------------------------------------


class TestSecretRedaction:
    def test_plain_text_allowed(self):
        assert_no_secrets("普通答案文本，无秘密；讨论 Bearer 概念但无真实 token。")

    def test_real_secrets_rejected(self):
        with pytest.raises(ValueError):
            assert_no_secrets("api=sk-abcdefghijklmnopqrstuvwxyz123456")
        with pytest.raises(ValueError):
            assert_no_secrets(
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890"
            )
        with pytest.raises(ValueError):
            assert_no_secrets("DEEPSEEK_API_KEY=sk-abcdefghijklmnop")


# ---------------------------------------------------------------------------
# fake OpenAI-compatible client for Judge
# ---------------------------------------------------------------------------


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _Resp(self._content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content):
        self.chat = _FakeChat(content)
