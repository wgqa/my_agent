"""Tests for G3-E2E-07A-R1 offline evaluation provenance repair.

Covers: repair performs no LLM call; generation artifact hash enters identity
+ dev SHA mismatch rejects; Judge input mismatch rejects (no auto-rerun);
zero-obligation judgments excluded; dual source commits bound into identity;
parent run identity bound; metrics independently recomputable; original parent
artifacts never modified; secrets do not leak. Uses a tiny synthetic parent
run bundle and no network.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from evaluation.gate3.e2e import (
    GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    Gate3E2EConfig,
    build_repair_config,
    compute_answer_metrics,
    compute_deterministic_metrics,
    load_run_case_results,
    reevaluate_existing_e2e_run,
    should_call_judge,
)
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3.evaluation_set import (
    EvidenceObligation,
    Gate3Case,
    Gate3EvaluationSet,
)

PLANNER_SHA = "5b209054f5274fa8f1f88975625c80b78d7e9e2a84569179288fed0c3a3b5c95"
GEN_COMMIT = "6a783c4862b18d7dc9f35069dd6cde0fad507925"
EVAL_COMMIT = "f8368bd6d487ebb48a19a221d84b9df1d14e5f24"


def _make_parent_bundle(tmp_path):
    """合成一个 4172 风格的父 run bundle：3 case（1 answerable ok / 1 zero-obl / 1 failed）。"""
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "a.md").write_text("alpha beta", encoding="utf-8")
    (corpus_root / "b.md").write_text("gamma delta", encoding="utf-8")
    rel = ["a.md", "b.md"]

    c1 = Gate3Case(
        schema_version="gate3_case_v1", case_id="g3q001", query="q1 alpha",
        query_type="fact", answerability="answerable",
        decomposition_expected="forbidden", retrieval_required=True,
        evidence_obligations=(EvidenceObligation("o1", "描述A", ("a.md",), True),),
        relevant_files=("a.md",), tags=("fact",),
    )
    c2 = Gate3Case(
        schema_version="gate3_case_v1", case_id="g3q002", query="q2 求和",
        query_type="unanswerable_or_no_retrieval", answerability="no_retrieval",
        decomposition_expected="forbidden", retrieval_required=False,
        evidence_obligations=(), relevant_files=(), tags=("no_retrieval",),
    )
    c3 = Gate3Case(
        schema_version="gate3_case_v1", case_id="g3q003", query="q3 gamma",
        query_type="fact", answerability="answerable",
        decomposition_expected="forbidden", retrieval_required=True,
        evidence_obligations=(EvidenceObligation("o1", "描述B", ("b.md",), True),),
        relevant_files=("b.md",), tags=("fact",),
    )
    dev_path = tmp_path / "dev.jsonl"
    dev_path.write_text(
        "\n".join(json.dumps(c.to_dict(), ensure_ascii=False)
                  for c in (c1, c2, c3)) + "\n",
        encoding="utf-8",
    )
    dev_sha = hashlib.sha256(dev_path.read_bytes()).hexdigest()

    cfg = Gate3E2EConfig(
        source_commit=GEN_COMMIT, corpus_id="870e5864df67", corpus_file_count=37,
        gate3_dataset_freeze_id="257fa0d0a6d6",
        dev_evaluation_set_id="f2144030d754", dev_case_count=3,
        dev_jsonl_sha256=dev_sha, planner_prompt_sha256=PLANNER_SHA,
        judge_prompt_sha256=GATE3_ANSWER_JUDGE_PROMPT_SHA256,
    )
    parent = tmp_path / "parent_run"
    parent.mkdir()
    (parent / "run_config.json").write_text(
        json.dumps(cfg.to_dict(), ensure_ascii=False), encoding="utf-8"
    )
    records = [
        {"case_id": "g3q001", "query": "q1 alpha", "status": "completed",
         "error_code": None, "plan_id": "p1", "plan": {"action": "single_retrieval",
         "query_type": "fact", "reason_code": "SIMPLE_FACT", "subquery_count": 0},
         "route": "single_retrieval", "retrieval_call_count": 1,
         "candidate_canonical_paths": ["a.md"],
         "retrieved_canonical_paths": ["a.md"], "evidence_count": 1,
         "fallback_used": False, "failure_code": None, "answer": "答案[C1]",
         "cited_citation_ids": [1], "evidence_citation_ids": [1]},
        {"case_id": "g3q002", "query": "q2 求和", "status": "completed",
         "error_code": None, "plan_id": "p2", "plan": {"action": "no_retrieval",
         "query_type": "unanswerable_or_no_retrieval", "reason_code": "X",
         "subquery_count": 0}, "route": "direct_answer",
         "retrieval_call_count": 0, "candidate_canonical_paths": [],
         "retrieved_canonical_paths": [], "evidence_count": 0,
         "fallback_used": False, "failure_code": None, "answer": "42",
         "cited_citation_ids": [], "evidence_citation_ids": []},
        {"case_id": "g3q003", "query": "q3 gamma", "status": "failed",
         "error_code": "GENERATION_FAILED", "plan_id": "p3",
         "plan": {"action": "single_retrieval", "query_type": "fact",
         "reason_code": "SIMPLE_FACT", "subquery_count": 0},
         "route": "single_retrieval", "retrieval_call_count": 1,
         "candidate_canonical_paths": ["b.md"], "retrieved_canonical_paths": [],
         "evidence_count": 0, "fallback_used": False, "failure_code": None,
         "answer": None, "cited_citation_ids": [], "evidence_citation_ids": []},
    ]
    (parent / "case_results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    (parent / "cited_evidence.jsonl").write_text(
        json.dumps({"case_id": "g3q001", "items": [
            {"citation_id": "[C1]", "source_name": "a.md",
             "canonical_path": "a.md", "content": "alpha beta"}]},
            ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    judge_input = {
        "query": "q1 alpha", "answer": "答案[C1]",
        "cited_evidence": [{"citation_id": "[C1]", "source_name": "a.md",
                            "canonical_path": "a.md", "content": "alpha beta"}],
        "gold_obligations": [{"obligation_id": "o1", "description": "描述A"}],
    }
    judgments = [
        {"case_id": "g3q001", "judge_input": judge_input, "judge_output": {
            "judge_status": "ok", "obligation_coverage": {"o1": "covered"},
            "unsupported_material_claims": []}},
        {"case_id": "g3q002", "judge_input": {}, "judge_output": {
            "judge_status": "invalid"}},
        {"case_id": "g3q003", "judge_input": {}, "judge_output": {
            "judge_status": "not_generated"}},
    ]
    (parent / "answer_judgments.jsonl").write_text(
        "\n".join(json.dumps(j, ensure_ascii=False) for j in judgments) + "\n",
        encoding="utf-8",
    )
    manifest = {"corpus_entries": [{"relative_path": "a.md"},
                                   {"relative_path": "b.md"}]}
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "parent": parent, "dev": str(dev_path), "corpus": str(corpus_root),
        "manifest": str(tmp_path / "manifest.json"),
        "records": records, "judgments": judgments,
    }


def _dev_set(bundle):
    frozen = json.loads(open(bundle["manifest"], encoding="utf-8").read())
    rel = [e["relative_path"] for e in frozen["corpus_entries"]]
    corpus = ExperimentCorpus.build(bundle["corpus"], rel)
    return Gate3EvaluationSet.load_jsonl(bundle["dev"], corpus)


def _repair(bundle, tmp_path, eval_commit=EVAL_COMMIT, **kw):
    return reevaluate_existing_e2e_run(
        bundle["parent"], tmp_path / "repairs",
        evaluation_source_commit=eval_commit,
        dev_jsonl_path=bundle["dev"],
        frozen_index_manifest_path=bundle["manifest"],
        corpus_root=bundle["corpus"],
        **kw,
    )


@pytest.fixture
def bundle_factory(tmp_path):
    return _make_parent_bundle(tmp_path)


class TestRepairOffline:
    def test_no_llm_client_created(self, bundle_factory, tmp_path, monkeypatch):
        # 若 repair 触碰任何 LLM client 则失败
        def _boom(*a, **k):
            raise AssertionError("repair 不得创建 LLM client")

        monkeypatch.setattr("evaluation.gate3.e2e.AnswerJudge", _boom)
        monkeypatch.setattr("evaluation.gate3.e2e.OpenAI", _boom)
        result = _repair(bundle_factory, tmp_path)
        assert result["reusable_judgments"] == 1
        assert result["input_mismatch"] == 0

    def test_metrics_independent_recomputation(self, bundle_factory, tmp_path):
        result = _repair(bundle_factory, tmp_path)
        repair_dir = tmp_path / "repairs" / result["repair_id"]
        dev = _dev_set(bundle_factory)
        case_by_id = {c.case_id: c for c in dev.cases}
        records = load_run_case_results(bundle_factory["parent"])
        judgments = [json.loads(l) for l in
                     (repair_dir / "answer_judgments.jsonl")
                     .read_text("utf-8").splitlines() if l.strip()]
        det = compute_deterministic_metrics(records, dev, case_by_id)
        ans = compute_answer_metrics(records, judgments, dev, case_by_id)
        assert ans == result["metrics"]["answer"]
        assert det == result["metrics"]["deterministic"]

    def test_original_case_results_not_modified(self, bundle_factory, tmp_path):
        before = hashlib.sha256(
            (bundle_factory["parent"] / "case_results.jsonl").read_bytes()
        ).hexdigest()
        _repair(bundle_factory, tmp_path)
        after = hashlib.sha256(
            (bundle_factory["parent"] / "case_results.jsonl").read_bytes()
        ).hexdigest()
        assert before == after


class TestRepairRejects:
    def test_dev_sha_mismatch_rejects(self, bundle_factory, tmp_path):
        # 篡改 run_config 中 dev_jsonl_sha256 → 与实际文件不符 → 拒绝
        cfg_path = bundle_factory["parent"] / "run_config.json"
        pc = json.loads(cfg_path.read_text("utf-8"))
        pc["dev_jsonl_sha256"] = "ab" * 32
        cfg_path.write_text(json.dumps(pc, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ValueError):
            _repair(bundle_factory, tmp_path)

    def test_judge_input_mismatch_rejects(self, bundle_factory, tmp_path):
        # 篡改父 run 中 g3q001 的 judge_input.answer → 输入一致性失败 → 停止
        jp = bundle_factory["parent"] / "answer_judgments.jsonl"
        judgments = [json.loads(l) for l in jp.read_text("utf-8").splitlines()
                     if l.strip()]
        for j in judgments:
            if j["case_id"] == "g3q001":
                j["judge_input"]["answer"] = "被篡改的答案"
        jp.write_text(
            "\n".join(json.dumps(j, ensure_ascii=False) for j in judgments) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError):
            _repair(bundle_factory, tmp_path)

    def test_missing_reusable_judgment_rejects(self, bundle_factory, tmp_path):
        # 删除 g3q001 的 ok 判断 → mismatch
        jp = bundle_factory["parent"] / "answer_judgments.jsonl"
        judgments = [json.loads(l) for l in jp.read_text("utf-8").splitlines()
                     if l.strip()]
        for j in judgments:
            if j["case_id"] == "g3q001":
                j["judge_output"] = {"judge_status": "invalid"}
        jp.write_text(
            "\n".join(json.dumps(j, ensure_ascii=False) for j in judgments) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError):
            _repair(bundle_factory, tmp_path)


class TestZeroObligation:
    def test_zero_obligation_excluded_from_judgments(self, bundle_factory, tmp_path):
        result = _repair(bundle_factory, tmp_path)
        repair_dir = tmp_path / "repairs" / result["repair_id"]
        judgments = [json.loads(l) for l in
                     (repair_dir / "answer_judgments.jsonl")
                     .read_text("utf-8").splitlines() if l.strip()]
        by_case = {j["case_id"]: j["judge_output"] for j in judgments}
        assert by_case["g3q002"] == {"judge_status": "not_required",
                                     "reason": "zero_obligation"}
        assert by_case["g3q001"]["judge_status"] == "ok"
        assert by_case["g3q003"]["judge_status"] == "not_generated"

    def test_zero_obligation_out_of_denominators(self, bundle_factory, tmp_path):
        result = _repair(bundle_factory, tmp_path)
        a = result["metrics"]["answer"]
        # answerable = g3q001 + g3q003；g3q002 不计入
        assert a["answerable_case_count"] == 2
        assert a["answer_obligation_total"] == 2
        # g3q001 covered，g3q003 failed → no_answer=1
        assert a["answer_obligation_covered"] == 1
        assert a["no_answer_case_count"] == 1
        assert a["citation_valid_denominator"] == 1
        assert a["citation_valid_case_count"] == 1


class TestIdentity:
    def test_dual_source_commits_bound(self, bundle_factory):
        rc1 = build_repair_config(bundle_factory["parent"],
                                  evaluation_source_commit=EVAL_COMMIT,
                                  judge_model="deepseek-chat")
        rc2 = build_repair_config(bundle_factory["parent"],
                                  evaluation_source_commit="f" * 40,
                                  judge_model="deepseek-chat")
        assert rc1.repair_id != rc2.repair_id
        assert rc1.generation_source_commit == GEN_COMMIT
        assert rc1.evaluation_source_commit == EVAL_COMMIT

    def test_generation_artifact_hash_changes_identity(self, bundle_factory):
        rc_before = build_repair_config(bundle_factory["parent"],
                                        evaluation_source_commit=EVAL_COMMIT,
                                        judge_model="deepseek-chat")
        with open(bundle_factory["parent"] / "case_results.jsonl", "a",
                  encoding="utf-8") as f:
            f.write("{}")
        rc_after = build_repair_config(bundle_factory["parent"],
                                       evaluation_source_commit=EVAL_COMMIT,
                                       judge_model="deepseek-chat")
        assert rc_before.repair_id != rc_after.repair_id
        assert rc_before.case_results_sha256 != rc_after.case_results_sha256

    def test_parent_run_identity_bound(self, bundle_factory):
        rc = build_repair_config(bundle_factory["parent"],
                                 evaluation_source_commit=EVAL_COMMIT,
                                 judge_model="deepseek-chat")
        pc = json.loads((bundle_factory["parent"] / "run_config.json")
                        .read_text("utf-8"))
        assert rc.parent_generation_run_id == pc["run_id"]

    def test_should_call_judge_gating(self):
        assert should_call_judge({"status": "completed", "answer": "a"}, True)
        assert not should_call_judge({"status": "completed", "answer": "a"}, False)


class TestSecrets:
    def test_repair_artifacts_no_secrets(self, bundle_factory, tmp_path):
        result = _repair(bundle_factory, tmp_path)
        repair_dir = tmp_path / "repairs" / result["repair_id"]
        from evaluation.gate3.e2e import assert_no_secrets
        for f in repair_dir.iterdir():
            if f.is_file():
                assert_no_secrets(f.read_text("utf-8"))
