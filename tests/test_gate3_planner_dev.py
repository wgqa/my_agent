"""Tests for Gate 3 Dev Planner calibration runner (G3-DECOMP-04B-02A).

Uses synthetic Gate3Cases + Fake Planner only; never touches network, real
API keys, Dev/Holdout data, or retrieval components.
"""

from __future__ import annotations

import json

import pytest

from core.query_planning import (
    BaseQueryPlanner,
    PlannerOutcome,
    QueryPlan,
    Subquery,
    build_planner_fallback_outcome,
)
from evaluation.experiment_corpus import ExperimentCorpus
from evaluation.gate3.evaluation_set import Gate3EvaluationSet
from evaluation.gate3.planner_dev import (
    Gate3PlannerDevConfig,
    Gate3PlannerDevRunner,
    ProviderFailFast,
    finalize_planner_dev_run,
    gold_action_for,
    write_planner_dev_artifacts,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _config(**overrides):
    defaults = dict(
        source_commit="abc123",
        corpus_id="870e5864df67",
        evaluation_set_id="f2144030d754",
        dev_jsonl_sha256="0" * 64,
        provider="deepseek",
        model="deepseek-chat",
        prompt_version="gate3_planner_prompt_v1",
        prompt_sha256="5" * 64,
        temperature=0,
        max_tokens=800,
        timeout=20.0,
        max_retries=0,
    )
    defaults.update(overrides)
    return Gate3PlannerDevConfig(**defaults)


def _normal(
    query: str,
    query_type: str,
    action: str,
    reason_code: str,
    retrieval_required: bool = True,
    subqueries: tuple = (),
    call_metadata=None,
) -> PlannerOutcome:
    plan = QueryPlan.create(
        original_query=query,
        query_type=query_type,
        retrieval_required=retrieval_required,
        action=action,
        reason_code=reason_code,
        subqueries=subqueries,
    )
    return PlannerOutcome(
        plan=plan, fallback_used=False, failure_code=None,
        call_metadata=call_metadata,
    )


def _fallback(query: str, failure_code: str = "PLAN_EMPTY",
              call_metadata=None) -> PlannerOutcome:
    return build_planner_fallback_outcome(
        query, failure_code, call_metadata=call_metadata
    )


class FakePlanner(BaseQueryPlanner):
    """builder(query) -> PlannerOutcome；记录被调用的 query 列表。"""

    def __init__(self, builder=None, error=None):
        self._builder = builder
        self._error = error
        self.queries: list[str] = []

    def plan(self, original_query: str) -> PlannerOutcome:
        self.queries.append(original_query)
        if self._error is not None:
            raise self._error
        if self._builder is None:
            return _normal(original_query, "fact", "single_retrieval",
                           "SIMPLE_FACT")
        return self._builder(original_query)


def _make_corpus(tmp_path) -> ExperimentCorpus:
    files = {
        "docs/a.md": "# A\n",
        "docs/b.md": "# B\n",
        "docs/c.md": "# C\n",
    }
    root = tmp_path / "corpus"
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return ExperimentCorpus.build(root, list(files.keys()))


def _case_dict(case_id, query, query_type, answerability,
               decomposition_expected, retrieval_required,
               obligations, relevant_files):
    return {
        "schema_version": "gate3_case_v1",
        "case_id": case_id,
        "query": query,
        "query_type": query_type,
        "answerability": answerability,
        "decomposition_expected": decomposition_expected,
        "retrieval_required": retrieval_required,
        "evidence_obligations": obligations,
        "relevant_files": relevant_files,
        "tags": [],
    }


def _answerable(case_id, query, query_type="fact", decomposition="forbidden",
                retrieval_required=True):
    return _case_dict(
        case_id, query, query_type, "answerable", decomposition,
        retrieval_required,
        [{"obligation_id": "o1", "description": "证据",
          "relevant_files": ["docs/a.md"], "required": True}],
        ["docs/a.md"],
    )


def _unanswerable(case_id, query):
    return _case_dict(case_id, query, "unanswerable_or_no_retrieval",
                      "unanswerable", "forbidden", True, [], [])


def _no_retrieval(case_id, query):
    return _case_dict(case_id, query, "unanswerable_or_no_retrieval",
                      "no_retrieval", "forbidden", False, [], [])


def _write_dev(tmp_path, case_dicts):
    path = tmp_path / "dev.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for c in case_dicts:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return Gate3EvaluationSet.load_jsonl(path, _make_corpus(tmp_path))


def _default_dev(tmp_path):
    """4 个 synthetic Case，覆盖 decomposed/single/no_retrieval 与 fallback 场景。"""
    return _write_dev(tmp_path, [
        _answerable("g3q001", "比较 A 和 B", query_type="comparison",
                    decomposition="required"),
        _answerable("g3q002", "什么是 A？", query_type="fact",
                    decomposition="forbidden"),
        _unanswerable("g3q003", "这个功能存在吗？"),
        _no_retrieval("g3q004", "把 3 和 5 相加"),
    ])


# ---------------------------------------------------------------------------
# run identity
# ---------------------------------------------------------------------------


class TestRunIdentity:
    def test_run_id_stable(self):
        assert _config().run_id == _config().run_id

    def test_run_id_changes_on_identity_fields(self):
        base = _config()
        for field, value in (
            ("provider", "other"),
            ("model", "other-model"),
            ("prompt_version", "gate3_planner_prompt_v2"),
            ("prompt_sha256", "6" * 64),
            ("source_commit", "xyz"),
            ("temperature", 1),
            ("evaluation_set_id", "other-set"),
            ("corpus_id", "other-corpus"),
        ):
            assert _config(**{field: value}).run_id != base.run_id, field

    def test_run_id_not_bound_to_time_latency_path(self):
        # config 不含时间/latency/路径字段；相同配置恒同 run_id
        assert _config().run_id == _config().run_id


# ---------------------------------------------------------------------------
# runner behavior
# ---------------------------------------------------------------------------


class TestRunner:
    def test_gold_action_mapping(self, tmp_path):
        s = _default_dev(tmp_path)
        actions = {c.case_id: gold_action_for(c) for c in s.cases}
        assert actions["g3q001"] == "decomposed_retrieval"  # required
        assert actions["g3q002"] == "single_retrieval"      # forbidden + rr=true
        assert actions["g3q003"] == "single_retrieval"      # unanswerable + rr=true
        assert actions["g3q004"] == "no_retrieval"          # forbidden + rr=false

    def test_each_case_called_once_and_sorted(self, tmp_path):
        s = _default_dev(tmp_path)
        runner = Gate3PlannerDevRunner(_config(), FakePlanner(), s)
        result = runner.run()
        assert len(result.case_results) == 4
        assert [c.case_id for c in result.case_results] == sorted(
            [c.case_id for c in s.cases]
        )
        assert result.metrics.planner_call_count == 4

    def test_gold_not_passed_to_planner(self, tmp_path):
        s = _default_dev(tmp_path)
        fake = FakePlanner()
        Gate3PlannerDevRunner(_config(), fake, s).run()
        expected_queries = [c.query for c in s.cases]
        assert sorted(fake.queries) == sorted(expected_queries)
        for q in fake.queries:
            assert not q.startswith("g3q")  # query 不是 case_id

    def test_all_single_correct_metrics(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(_config(), FakePlanner(), s).run()
        m = result.metrics
        assert m.case_count == 4
        assert m.schema_valid_count == 4
        assert m.schema_validity_rate == 1.0
        assert m.fallback_count == 0
        assert m.planner_call_count == 4
        # 默认 Fake 全部返回 fact/single：只有 g3q002（fact）query_type 正确
        assert m.query_type_exact_correct_count == 1
        assert m.query_type_exact_accuracy_all == pytest.approx(0.25)

    def test_fallback_counted_wrong_in_all_accuracy(self, tmp_path):
        s = _default_dev(tmp_path)

        def builder(q):
            if q == "什么是 A？":
                return _normal(q, "fact", "single_retrieval", "SIMPLE_FACT")
            return _fallback(q, "PLAN_EMPTY")

        result = Gate3PlannerDevRunner(_config(), FakePlanner(builder), s).run()
        m = result.metrics
        assert m.fallback_count == 3
        assert m.fallback_rate == pytest.approx(0.75)
        assert m.schema_valid_count == 1
        assert m.query_type_exact_correct_count == 1
        assert m.query_type_exact_accuracy_all == pytest.approx(0.25)
        assert m.query_type_exact_accuracy_non_fallback == 1.0

    def test_fallback_uses_unknown_not_gold(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(
            _config(), FakePlanner(lambda q: _fallback(q, "PLAN_EMPTY")), s
        ).run()
        for cr in result.case_results:
            assert cr.fallback_used is True
            assert cr.predicted_query_type == "unknown"
            assert cr.predicted_query_type != cr.gold_query_type
            assert cr.query_type_correct is False

    def test_unnecessary_and_missed_decomposition(self, tmp_path):
        s = _default_dev(tmp_path)

        def decomposed(q, qt, rc):
            return _normal(
                q, qt, "decomposed_retrieval", rc,
                subqueries=(
                    Subquery(id="sq1", query="A 是什么？",
                             evidence_target="A 的机制", required=True),
                    Subquery(id="sq2", query="B 是什么？",
                             evidence_target="B 的机制", required=True),
                ),
            )

        def builder(q):
            if q == "比较 A 和 B":
                # 命中：正确分解
                return decomposed(q, "comparison", "COMPARISON_EVIDENCE")
            # 不该分解却分解 → unnecessary
            return decomposed(q, "fact", "COMPARISON_EVIDENCE")

        result = Gate3PlannerDevRunner(_config(), FakePlanner(builder), s).run()
        m = result.metrics
        assert m.unnecessary_decomposition_count == 3
        assert m.unnecessary_decomposition_rate == pytest.approx(0.75)
        assert m.missed_decomposition_count == 0

    def test_missed_decomposition_when_should(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(_config(), FakePlanner(), s).run()
        m = result.metrics
        assert m.missed_decomposition_count == 1
        assert m.missed_decomposition_rate == pytest.approx(0.25)

    def test_usage_missing_not_fabricated(self, tmp_path):
        from core.query_planning import PlannerCallMetadata

        def md(**kw):
            base = dict(provider="p", model="m",
                        prompt_version="gate3_planner_prompt_v1",
                        prompt_sha256="5" * 64, call_count=1)
            base.update(kw)
            return PlannerCallMetadata(**base)

        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(
            _config(), FakePlanner(lambda q: _normal(
                q, "fact", "single_retrieval", "SIMPLE_FACT",
                call_metadata=md(),
            )), s
        ).run()
        m = result.metrics
        assert m.input_tokens_total == 0
        assert m.output_tokens_total == 0
        assert m.missing_usage_count == 4

    def test_latency_percentiles(self, tmp_path):
        from core.query_planning import PlannerCallMetadata

        latencies = {0: 100.0, 1: 200.0, 2: 300.0, 3: 400.0}
        calls = {"count": 0}

        def builder(q):
            i = calls["count"]
            calls["count"] += 1
            return _normal(
                q, "fact", "single_retrieval", "SIMPLE_FACT",
                call_metadata=PlannerCallMetadata(
                    provider="p", model="m",
                    prompt_version="gate3_planner_prompt_v1",
                    prompt_sha256="5" * 64, call_count=1,
                    latency_ms=latencies[i],
                ),
            )

        s = _default_dev(tmp_path)
        m = Gate3PlannerDevRunner(_config(), FakePlanner(builder), s).run().metrics
        assert m.latency_p50_ms == 200.0
        assert m.latency_p95_ms == 400.0

    def test_failure_code_distribution(self, tmp_path):
        codes = ["PLAN_EMPTY", "PLAN_INVALID_SCHEMA", "PLANNER_TIMEOUT",
                 "PLAN_EMPTY"]

        def builder(q):
            return _fallback(q, codes.pop(0))

        s = _default_dev(tmp_path)
        m = Gate3PlannerDevRunner(_config(), FakePlanner(builder), s).run().metrics
        assert m.failure_code_distribution == {
            "PLAN_EMPTY": 2, "PLAN_INVALID_SCHEMA": 1, "PLANNER_TIMEOUT": 1
        }
        assert m.timeout_count == 1
        assert m.provider_error_count == 0

    def test_unknown_exception_propagates(self, tmp_path):
        s = _default_dev(tmp_path)
        fake = FakePlanner(error=RuntimeError("boom"))
        with pytest.raises(RuntimeError):
            Gate3PlannerDevRunner(_config(), fake, s).run()

    def test_provider_fail_fast_first_case(self, tmp_path):
        s = _default_dev(tmp_path)
        runner = Gate3PlannerDevRunner(
            _config(),
            FakePlanner(lambda q: _fallback(q, "PLANNER_PROVIDER_ERROR")),
            s,
        )
        # fail_fast=False → 全部完成
        assert runner.run().metrics.case_count == 4
        # fail_fast=True → 首条即抛
        with pytest.raises(ProviderFailFast):
            runner.run(fail_fast_on_provider_error=True)

    def test_no_retrieval_components(self, tmp_path):
        import evaluation.gate3.planner_dev as mod

        src = open(mod.__file__, encoding="utf-8").read()
        for banned in ("retriever", "reranker", "generator", "router"):
            assert banned not in src.lower()

    def test_output_excludes_sensitive(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(_config(), FakePlanner(), s).run()
        text = json.dumps([c.to_dict() for c in result.case_results],
                          ensure_ascii=False)
        for token in ("api_key", "sk-", "base_url", "authorization",
                      "traceback", "RuntimeError", "secret"):
            assert token not in text


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


class TestArtifacts:
    def test_dir_overwrite_protected(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(_config(), FakePlanner(), s).run()
        pre = tmp_path / "out" / result.run_id
        pre.mkdir(parents=True, exist_ok=True)
        (pre / "x").write_text("x", encoding="utf-8")
        with pytest.raises(FileExistsError):
            write_planner_dev_artifacts(result, tmp_path / "out")

    def test_canonical_json_and_shas(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(_config(), FakePlanner(), s).run()
        out = tmp_path / "out"
        sha_map = write_planner_dev_artifacts(result, out)
        run_dir = out / result.run_id
        assert run_dir.is_dir()
        assert len(sha_map) == 3
        lines = (run_dir / "planner_results.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        assert len(lines) == 4
        assert json.loads(lines[0])["case_id"] == "g3q001"
        import hashlib

        assert sha_map["run_config.json"] == hashlib.sha256(
            (run_dir / "run_config.json").read_bytes()
        ).hexdigest()

    def test_atomic_write(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(_config(), FakePlanner(), s).run()
        out = tmp_path / "out2"
        write_planner_dev_artifacts(result, out)
        leftovers = [p.name for p in (out / result.run_id).glob("*.part")]
        assert leftovers == []

    def test_result_summary_finalize(self, tmp_path):
        s = _default_dev(tmp_path)
        result = Gate3PlannerDevRunner(_config(), FakePlanner(), s).run()
        out = tmp_path / "out3"
        write_planner_dev_artifacts(result, out)
        run_dir = out / result.run_id
        (run_dir / "planner_semantic_review.md").write_text(
            "# review\n", encoding="utf-8"
        )
        sha_map = finalize_planner_dev_run(run_dir)
        result_json = json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8")
        )
        assert result_json["run_id"] == result.run_id
        assert result_json["metrics"]["case_count"] == 4
        assert "result.json" not in result_json["artifact_sha256"]
        assert len(result_json["artifact_sha256"]) == 4
        assert "result.json" in sha_map

    def test_finalize_missing_artifact_fails(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            finalize_planner_dev_run(run_dir)


# ---------------------------------------------------------------------------
# CLI API key behavior
# ---------------------------------------------------------------------------


class TestApiKeyBehavior:
    def test_missing_key_fails_before_network(self, monkeypatch):
        import scripts.run_gate3_planner_dev as cli

        monkeypatch.delenv("DEEPSEEK_API_KEY_TEST", raising=False)
        with pytest.raises(SystemExit):
            cli._resolve_api_key("DEEPSEEK_API_KEY_TEST")
