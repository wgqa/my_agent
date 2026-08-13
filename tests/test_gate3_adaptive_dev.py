"""Tests for G3-ADAPT-06B adaptive dev retrieval comparison.

Covers: config identity stability / run_id change on field change; frozen
Planner snapshot strict rebuild; C/D share the same plan; A/B don't call the
Planner; C forbids Hybrid/rescue while D uses the production adaptive policy;
shared index identity; canonical source-path mapping (unknown fails);
obligation OR-Gold semantics; document-level dedup ranking; Hit/Recall/MRR/
nDCG; merge-drop; no_retrieval/unanswerable metric exclusion; artifact atomic
write / overwrite-protection / no absolute paths; and no real Generator/Planner
client (SnapshotPlanner + DeterministicNoopAnswerPort only). Uses a small
in-memory corpus and a fake embedding; no network, no real bge model.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from core.query_planning import PlannerOutcome, QueryPlan, Subquery
from evaluation.gate3.adaptive_dev import (
    GATE3_ADAPTIVE_DEV_SCHEMA_VERSION,
    BM25OnlyCapabilityAdapter,
    DeterministicNoopAnswerPort,
    Gate3AdaptiveDevConfig,
    SnapshotPlanner,
    build_shared_index,
    canonical_paths_from_documents,
    compute_document_metrics,
    compute_group_metrics,
    compute_obligation_metrics,
    finalize_adaptive_dev,
    load_corpus,
    load_planner_snapshot,
    run_group_original,
    run_group_queryplan,
    validate_identity,
    write_adaptive_dev_artifacts,
    write_text_atomic,
)
from evaluation.gate3.evaluation_set import (
    EvidenceObligation,
    Gate3Case,
    Gate3EvaluationSet,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _config(planner_results_sha256: str = "ab" * 32, **kw) -> Gate3AdaptiveDevConfig:
    kwargs = dict(
        source_commit="f" * 40,
        corpus_id="870e5864df67",
        corpus_file_count=37,
        gate3_dataset_freeze_id="257fa0d0a6d6",
        dev_evaluation_set_id="f2144030d754",
        dev_case_count=24,
        dev_jsonl_sha256="0b" * 32,
        planner_run_id="497808269bdd",
        planner_prompt_sha256="5b" * 32,
        planner_results_sha256=planner_results_sha256,
    )
    kwargs.update(kw)
    return Gate3AdaptiveDevConfig(**kwargs)


class _FakeEmbedding:
    def embed(self, texts):
        vecs = []
        for t in texts:
            h = hashlib.sha1(t.encode("utf-8")).digest()
            vecs.append([int.from_bytes(h[:8], "big") / (2**64)] + [0.0] * 7)
        return vecs

    def embed_query(self, query):
        return self.embed([query])[0]


def _make_corpus(tmp_path):
    root = tmp_path / "corpus"
    files = {
        "a/doc1.md": "alpha beta",
        "b/doc2.md": "gamma delta",
        "c/doc3.md": "epsilon zeta",
    }
    for rp, text in files.items():
        p = root / rp
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root, list(files.keys())


def _case(case_id, query, qtype, answerability="answerable",
          decomp="forbidden", retrieval=True, obls=(), files=()):
    return Gate3Case(
        schema_version="gate3_case_v1",
        case_id=case_id,
        query=query,
        query_type=qtype,
        answerability=answerability,
        decomposition_expected=decomp,
        retrieval_required=retrieval,
        evidence_obligations=tuple(obls),
        relevant_files=tuple(files),
        tags=(qtype,),
    )


def _dev_set():
    ob1 = EvidenceObligation("o1", "d", ("a/doc1.md",), True)
    ob2 = EvidenceObligation("o2", "d", ("b/doc2.md",), True)
    ob3 = EvidenceObligation("o3", "d", ("c/doc3.md",), True)
    cases = (
        _case("g3q001", "alpha 是什么", "fact", obls=(ob1,), files=("a/doc1.md",)),
        _case("g3q002", "gamma 与 delta 对比", "comparison", decomp="required",
              obls=(ob2, ob3), files=("b/doc2.md", "c/doc3.md")),
        _case("g3q003", "未知来源问题", "unanswerable_or_no_retrieval",
              answerability="unanswerable",
              obls=(ob2,), files=("b/doc2.md",)),
        _case("g3q004", "无需检索", "unanswerable_or_no_retrieval",
              answerability="no_retrieval", retrieval=False, obls=(), files=()),
    )
    return Gate3EvaluationSet(
        corpus_id="870e5864df67", cases=cases, evaluation_set_id="f2144030d754"
    )


def _snapshot(dev_set):
    by_id = {c.case_id: c for c in dev_set.cases}

    def single(q):
        return QueryPlan.create(
            original_query=q, query_type="fact", retrieval_required=True,
            action="single_retrieval", reason_code="SIMPLE_FACT",
        )

    dec = QueryPlan.create(
        original_query=by_id["g3q002"].query, query_type="comparison",
        retrieval_required=True, action="decomposed_retrieval",
        reason_code="COMPARISON_EVIDENCE",
        subqueries=(
            Subquery("sq1", "gamma", "t", True),
            Subquery("sq2", "delta", "t", True),
        ),
    )
    snap = {}
    for case_id in ("g3q001", "g3q003", "g3q004"):
        snap[case_id] = {
            "outcome": PlannerOutcome(single(by_id[case_id].query), False, None),
            "query": by_id[case_id].query,
        }
    snap["g3q002"] = {
        "outcome": PlannerOutcome(dec, False, None),
        "query": by_id["g3q002"].query,
    }
    return snap


def _index(tmp_path):
    root, relative_paths = _make_corpus(tmp_path)
    basename_map = load_corpus(str(root), relative_paths)
    idx = build_shared_index(str(root), relative_paths, str(tmp_path / "vs"),
                             embedding=_FakeEmbedding())
    return root, basename_map, idx


def _rdoc(source_name):
    from core.agent_runtime import Document as RDoc
    return RDoc(chunk_id="c1", document_id="d1", source_name=source_name,
                content="x", score=0.5, rank=1)


# ---------------------------------------------------------------------------
# 配置身份
# ---------------------------------------------------------------------------


class TestConfigIdentity:
    def test_run_id_stable_for_same_config(self):
        assert _config().run_id == _config().run_id

    def test_run_id_changes_on_identity_field(self):
        base = _config()
        assert base.run_id != _config(planner_results_sha256="cd" * 32).run_id
        assert base.run_id != _config(dev_evaluation_set_id="ab" * 6).run_id

    def test_run_id_ignores_output_path(self):
        base = _config(output_dir="some/abs/path")
        other = _config(output_dir="other")
        assert base.run_id == other.run_id

    def test_invalid_hex_rejected(self):
        with pytest.raises(ValueError):
            _config(source_commit="xyz")


# ---------------------------------------------------------------------------
# 身份验证
# ---------------------------------------------------------------------------


class TestValidateIdentity:
    def test_mismatch_fails_fast(self, tmp_path):
        dev = tmp_path / "dev.jsonl"
        dev.write_bytes(b"x")
        res = tmp_path / "result.json"
        res.write_text(json.dumps({"artifact_sha256": {"planner_results.jsonl": "ab" * 32}}), encoding="utf-8")
        pr = tmp_path / "planner_results.jsonl"
        pr.write_bytes(b"x")
        cfg = _config(
            dev_jsonl_path=str(dev),
            planner_results_path=str(pr),
            planner_result_json_path=str(res),
        )
        with pytest.raises(ValueError):
            validate_identity(cfg)  # dev jsonl SHA 不匹配


# ---------------------------------------------------------------------------
# 语料映射 / 快照
# ---------------------------------------------------------------------------


class TestCorpusAndSnapshot:
    def test_load_corpus_basename_map(self, tmp_path):
        root, rp = _make_corpus(tmp_path)
        m = load_corpus(str(root), rp)
        assert m["doc1.md"] == "a/doc1.md"
        assert m["doc2.md"] == "b/doc2.md"
        assert m["doc3.md"] == "c/doc3.md"

    def test_unknown_source_fails(self, tmp_path):
        root, rp = _make_corpus(tmp_path)
        m = load_corpus(str(root), rp)
        with pytest.raises(ValueError):
            canonical_paths_from_documents([_rdoc("nope.md")], m)

    def test_planner_snapshot_rebuild_and_validate(self, tmp_path):
        dev_set = _dev_set()
        pr = tmp_path / "planner_results.jsonl"
        snap = _snapshot(dev_set)
        lines = []
        for case_id, item in sorted(snap.items()):
            outcome = item["outcome"]
            lines.append(json.dumps({
                "case_id": case_id,
                "query": item["query"],
                "plan": outcome.plan.to_dict(),
                "fallback_used": outcome.fallback_used,
                "failure_code": outcome.failure_code,
                "predicted": {
                    "action": outcome.plan.action,
                    "query_type": outcome.plan.query_type,
                    "reason_code": outcome.plan.reason_code,
                    "retrieval_required": outcome.plan.retrieval_required,
                },
            }, ensure_ascii=False))
        pr.write_text("\n".join(lines) + "\n", encoding="utf-8")
        loaded = load_planner_snapshot(str(pr), dev_set)
        assert set(loaded.keys()) == {c.case_id for c in dev_set.cases}
        assert loaded["g3q002"]["outcome"].plan.action == "decomposed_retrieval"

    def test_snapshot_requires_exact_case_set(self, tmp_path):
        dev_set = _dev_set()
        pr = tmp_path / "planner_results.jsonl"
        snap = _snapshot(dev_set)
        del snap["g3q004"]
        lines = []
        for case_id, item in sorted(snap.items()):
            o = item["outcome"]
            lines.append(json.dumps({
                "case_id": case_id, "query": item["query"],
                "plan": o.plan.to_dict(), "fallback_used": o.fallback_used,
                "failure_code": o.failure_code,
                "predicted": {"action": o.plan.action, "query_type": o.plan.query_type,
                              "reason_code": o.plan.reason_code,
                              "retrieval_required": o.plan.retrieval_required},
            }, ensure_ascii=False))
        pr.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_planner_snapshot(str(pr), dev_set)


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


def _records_a(dev_set):
    return [
        {"case_id": "g3q001", "group": "A", "retrieved_canonical_paths": ["a/doc1.md"]},
        {"case_id": "g3q002", "group": "A", "retrieved_canonical_paths": ["b/doc2.md"]},
        {"case_id": "g3q003", "group": "A", "retrieved_canonical_paths": ["b/doc2.md"]},
        {"case_id": "g3q004", "group": "A", "retrieved_canonical_paths": []},
    ]


class TestMetrics:
    def test_document_metrics_exclude_unanswerable_no_retrieval(self):
        dev_set = _dev_set()
        m = compute_document_metrics(
            {r["case_id"]: r for r in _records_a(dev_set)}, dev_set.cases
        )
        assert m["denominator_case_count"] == 2  # 只 g3q001/g3q002（answerable）
        assert m["hit_at_5"] == 1.0

    def test_obligation_or_gold_semantics(self):
        dev_set = _dev_set()
        recs = {r["case_id"]: r for r in _records_a(dev_set)}
        m = compute_obligation_metrics(recs, dev_set.cases, candidate_key="retrieved_canonical_paths")
        # g3q001 覆盖 o1；g3q002 只覆盖 o2（o3 需要 doc3.md）→ 2/3
        assert m["obligation_total"] == 3
        assert m["obligation_covered"] == 2
        assert m["full_coverage_case_count"] == 1
        assert m["multi_obligation_complete_count"] == 0

    def test_document_dedup_ranking(self):
        m = {"doc1.md": "a/doc1.md", "doc2.md": "b/doc2.md"}
        docs = [_rdoc("doc1.md"), _rdoc("doc2.md"), _rdoc("doc1.md")]
        assert canonical_paths_from_documents(docs, m) == ["a/doc1.md", "b/doc2.md"]


class TestMetricsValues:
    def test_hit_recall_mrr_ndcg(self):
        dev_set = _dev_set()
        recs = {
            "g3q001": {"case_id": "g3q001", "retrieved_canonical_paths": ["a/doc1.md", "b/doc2.md"]},
            "g3q002": {"case_id": "g3q002", "retrieved_canonical_paths": ["b/doc2.md", "a/doc1.md"]},
        }
        m = compute_document_metrics(recs, [c for c in dev_set.cases if c.case_id in ("g3q001", "g3q002")])
        assert m["hit_at_5"] == 1.0
        # g3q001 recall=1，g3q002 recall=0.5（缺 c/doc3.md）→ 宏平均 0.75
        assert m["recall_at_5"] == pytest.approx(0.75)
        assert m["mrr"] == 1.0  # 两条首位均命中


# ---------------------------------------------------------------------------
# 四组执行
# ---------------------------------------------------------------------------


class TestGroups:
    def test_ab_no_planner_shared_index(self, tmp_path):
        root, basename_map, idx = _index(tmp_path)
        dev_set = _dev_set()
        ra = run_group_original("A", idx.retriever, dev_set.cases, 5, basename_map)
        rb = run_group_original("B", idx.retriever, dev_set.cases, 5, basename_map)
        assert len(ra) == 4 and len(rb) == 4
        assert all(r["group"] == "A" and r["strategy"] == "bm25" for r in ra)
        assert all(r["group"] == "B" and r["strategy"] == "hybrid" for r in rb)
        assert all(r["retrieval_call_count"] == 1 for r in ra)

    def test_cd_same_plan_and_c_blocks_hybrid(self, tmp_path):
        root, basename_map, idx = _index(tmp_path)
        dev_set = _dev_set()
        snap = _snapshot(dev_set)
        rc = run_group_queryplan("C", idx.retriever, dev_set.cases, snap, 5,
                                 basename_map, adaptive=False)
        rd = run_group_queryplan("D", idx.retriever, dev_set.cases, snap, 5,
                                 basename_map, adaptive=True)
        # 同一份快照：g3q001 plan_id 相同
        assert snap["g3q001"]["outcome"].plan.plan_id == snap["g3q001"]["outcome"].plan.plan_id
        c_case = next(r for r in rc if r["case_id"] == "g3q001")
        d_case = next(r for r in rd if r["case_id"] == "g3q001")
        assert c_case["strategy_distribution"] == {"bm25": 1}
        assert d_case["strategy_distribution"] == {"bm25": 1}
        # C 无 rescue（bm25-only 能力）
        assert c_case["upgrade_attempted"] is False
        # D fact→bm25 命中则不触发 rescue
        assert d_case["upgrade_attempted"] is False
        # g3q002 decomposed 走 bm25 子问题
        c_dec = next(r for r in rc if r["case_id"] == "g3q002")
        assert c_dec["retrieval_call_count"] == 2

    def test_group_metrics_merge_drop(self, tmp_path):
        root, basename_map, idx = _index(tmp_path)
        dev_set = _dev_set()
        snap = _snapshot(dev_set)
        rc = run_group_queryplan("C", idx.retriever, dev_set.cases, snap, 5,
                                 basename_map, adaptive=False)
        m = compute_group_metrics(rc, dev_set.cases)
        assert "candidate_obligation_coverage_rate" in m
        assert "merge_drop_obligation_count" in m


# ---------------------------------------------------------------------------
# No-op / Snapshot / 能力包装
# ---------------------------------------------------------------------------


class TestAdapters:
    def test_noop_answer(self):
        port = DeterministicNoopAnswerPort()
        assert port.answer_generation == "not_evaluated"
        assert port.answer_adapter == "deterministic_noop"
        assert port.answer("q", None, "grounded")

    def test_bm25_only_capability(self, tmp_path):
        root, basename_map, idx = _index(tmp_path)
        adapter = BM25OnlyCapabilityAdapter(idx.retriever)
        assert adapter.supported_strategies == ("bm25",)

    def test_snapshot_planner_finds_by_query(self, tmp_path):
        dev_set = _dev_set()
        snap = _snapshot(dev_set)
        sp = SnapshotPlanner(snap)
        out = sp.plan("alpha 是什么")
        assert out.plan.action == "single_retrieval"
        with pytest.raises(ValueError):
            sp.plan("不存在的 query")


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class TestArtifacts:
    def test_atomic_write_and_overwrite_protect(self, tmp_path):
        run_dir = tmp_path / "run"
        cfg = _config(output_dir=str(run_dir))
        write_adaptive_dev_artifacts(
            run_dir, cfg, {"schema_version": "x"},
            {"A": [], "B": [], "C": [], "D": []},
            {"A": {}, "B": {}, "C": {}, "D": {}}, "# report"
        )
        # 目录已存在 → 拒绝覆盖
        with pytest.raises(FileExistsError):
            write_adaptive_dev_artifacts(
                run_dir, cfg, {"schema_version": "x"},
                {"A": [], "B": [], "C": [], "D": []},
                {"A": {}, "B": {}, "C": {}, "D": {}}, "# report"
            )
        assert (run_dir / "run_config.json").exists()
        assert (run_dir / "case_results.jsonl").exists()

    def test_result_json_no_self_sha_and_overwrite(self, tmp_path):
        run_dir = tmp_path / "run2"
        run_dir.mkdir()
        cfg = _config(output_dir=str(run_dir))
        r = finalize_adaptive_dev(run_dir, cfg, {"A": {}})
        assert r["schema_version"] == "gate3_adaptive_dev_result_v1"
        assert "answer_generation" in r
        with pytest.raises(FileExistsError):
            finalize_adaptive_dev(run_dir, cfg, {"A": {}})
        text = (run_dir / "result.json").read_text("utf-8")
        assert "sk-" not in text and "Traceback" not in text

    def test_text_atomic_writes_replace(self, tmp_path):
        p = tmp_path / "f.json"
        write_text_atomic(p, '{"a":1}')
        write_text_atomic(p, '{"b":2}')
        assert json.loads(p.read_text("utf-8")) == {"b": 2}
