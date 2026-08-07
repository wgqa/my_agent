"""G2-EVAL-08：文档级 Retrieval Metrics 与原子指标快照"""

import dataclasses
import json

import pytest

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_runner import ExperimentRunner, PreparedExperiment
from evaluation.experiment_workspace import ExperimentWorkspace
from evaluation.retrieval_evaluation_set import RetrievalCase, RetrievalEvaluationSet
from evaluation.retrieval_metrics import (
    METRICS_SCHEMA_VERSION,
    RetrievalCaseMetrics,
    RetrievalMetricsResult,
)
from evaluation.retrieval_result import (
    RETRIEVAL_RESULT_SCHEMA_VERSION,
    RetrievalCaseResult,
    RetrievalHit,
    RetrievalRunResult,
)


BASE_CONFIG_YAML = """\
embedding:
  provider: bge
  model: BAAI/bge-small-zh-v1.5
chunker:
  strategy: recursive
  size_tokens: 512
  overlap_tokens: 64
retriever:
  strategy: hybrid
  top_k: 5
  dense_candidate_k: 30
  sparse_candidate_k: 30
  rrf_k: 60.0
reranker:
  enabled: true
  candidate_k: 20
  final_k: 5
generator:
  provider: deepseek
  model: deepseek-v4-flash
vector_store:
  path: ./data/vector_store
"""


def _write_base_config(tmp_path):
    path = tmp_path / "base_config.yaml"
    path.write_text(BASE_CONFIG_YAML, encoding="utf-8")
    return path


def _prepare(tmp_path, config=None):
    config = config or ExperimentConfig()
    base = _write_base_config(tmp_path)
    paths = ExperimentWorkspace(base, tmp_path / "runs", config, "run1").prepare()
    return PreparedExperiment(
        experiment_config=config, paths=paths, pipeline=object()
    )


def _hit(rank, chunk_id, document_id, relative_path, scores=None):
    return RetrievalHit(
        rank=rank,
        chunk_id=chunk_id,
        document_id=document_id,
        relative_path=relative_path,
        scores=scores or {},
    )


def _case_result(case_id, query, relevant_files, hits):
    files = []
    for h in hits:
        if h.relative_path not in files:
            files.append(h.relative_path)
    return RetrievalCaseResult(
        case_id=case_id,
        query=query,
        relevant_files=tuple(relevant_files),
        hits=tuple(hits),
        retrieved_files=tuple(files),
    )


def _run_result(
    config=None,
    corpus_id="corpus-001",
    evaluation_set_id="evalset-001",
    cases=None,
    experiment_id=None,
    retriever_strategy=None,
    top_k=None,
    retrieval_run_id=None,
):
    config = config or ExperimentConfig()
    experiment_id = experiment_id or config.experiment_id
    retriever_strategy = retriever_strategy or config.retriever_strategy
    top_k = top_k if top_k is not None else config.top_k
    run_id = retrieval_run_id or RetrievalRunResult.compute_run_id(
        schema_version=RETRIEVAL_RESULT_SCHEMA_VERSION,
        experiment_id=experiment_id,
        corpus_id=corpus_id,
        evaluation_set_id=evaluation_set_id,
        retriever_strategy=retriever_strategy,
        top_k=top_k,
    )
    return RetrievalRunResult(
        schema_version=RETRIEVAL_RESULT_SCHEMA_VERSION,
        retrieval_run_id=run_id,
        experiment_id=experiment_id,
        corpus_id=corpus_id,
        evaluation_set_id=evaluation_set_id,
        retriever_strategy=retriever_strategy,
        top_k=top_k,
        cases=tuple(cases or ()),
    )


def _eval_set(corpus_id="corpus-001", evaluation_set_id="evalset-001", cases=None):
    return RetrievalEvaluationSet(
        corpus_id=corpus_id,
        cases=tuple(cases or ()),
        evaluation_set_id=evaluation_set_id,
    )


def _default_cases():
    return [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1, "c1", "d1", "a.md")],
        ),
        _case_result(
            "q002", "query two", ("a.md", "b.md", "c.md"),
            [
                _hit(1, "c7", "d2", "b.md"),
                _hit(2, "c1", "d1", "a.md"),
            ],
        ),
    ]


def _default_eval_cases():
    return [
        RetrievalCase("q001", "query one", ("a.md",)),
        RetrievalCase("q002", "query two", ("a.md", "b.md", "c.md")),
    ]


def _write_results(prepared, run_result):
    run_result.write_json(prepared.paths.retrieval_results_path)


def _compute(tmp_path, config=None, run_result=None, eval_set=None):
    config = config or ExperimentConfig()
    run_result = run_result or _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = eval_set or _eval_set(cases=_default_eval_cases())
    result = ExperimentRunner(
        tmp_path / "base_config.yaml", tmp_path / "runs"
    ).compute_retrieval_metrics(prepared, run_result, eval_set)
    return result, prepared


def test_normal_two_case_metrics_hand_computed(tmp_path):
    result, prepared = _compute(tmp_path)
    assert prepared.paths.retrieval_metrics_path.is_file()

    q001, q002 = result.cases
    assert q001.case_id == "q001"
    assert q001.hit_at_k == pytest.approx(1.0)
    assert q001.recall_at_k == pytest.approx(1.0)
    assert q001.mrr == pytest.approx(1.0)
    assert q001.ndcg_at_k == pytest.approx(1.0)
    assert q001.relevant_file_count == 1
    assert q001.retrieved_file_count == 1
    assert q001.first_relevant_rank == 1

    assert q002.hit_at_k == pytest.approx(1.0)
    assert q002.recall_at_k == pytest.approx(2.0 / 3.0)
    assert q002.mrr == pytest.approx(1.0)
    expected_ndcg = (1.0 + 1.0 / __import__("math").log2(3)) / (
        1.0 + 1.0 / __import__("math").log2(3) + 0.5
    )
    assert q002.ndcg_at_k == pytest.approx(expected_ndcg)
    assert q002.first_relevant_rank == 1

    assert result.mean_hit_at_k == pytest.approx(1.0)
    assert result.mean_recall_at_k == pytest.approx((1.0 + 2.0 / 3.0) / 2.0)
    assert result.mean_mrr == pytest.approx(1.0)
    assert result.mean_ndcg_at_k == pytest.approx((1.0 + expected_ndcg) / 2.0)
    assert result.case_count == 2


def test_hit_at_k_hit_and_miss(tmp_path):
    cases = [
        _case_result("q001", "q", ("a.md",), [_hit(1, "c1", "d1", "a.md")]),
        _case_result("q002", "q2", ("z.md",), [_hit(1, "c9", "d9", "x.md")]),
    ]
    result, _ = _compute(
        tmp_path,
        run_result=_run_result(cases=cases),
        eval_set=_eval_set(cases=[
            RetrievalCase("q001", "q", ("a.md",)),
            RetrievalCase("q002", "q2", ("z.md",)),
        ]),
    )
    assert result.cases[0].hit_at_k == 1.0
    assert result.cases[1].hit_at_k == 0.0


def test_recall_partial_relevant_files(tmp_path):
    cases = [
        _case_result(
            "q001", "q", ("a.md", "b.md", "c.md"),
            [_hit(1, "c1", "d1", "a.md")],
        ),
    ]
    result, _ = _compute(
        tmp_path,
        run_result=_run_result(cases=cases),
        eval_set=_eval_set(cases=[
            RetrievalCase("q001", "q", ("a.md", "b.md", "c.md")),
        ]),
    )
    assert result.cases[0].recall_at_k == pytest.approx(1.0 / 3.0)


def test_same_file_multiple_chunks_do_not_inflate_recall(tmp_path):
    cases = [
        _case_result(
            "q001", "q", ("a.md",),
            [
                _hit(1, "c1", "d1", "a.md"),
                _hit(2, "c2", "d1", "a.md"),
            ],
        ),
    ]
    result, _ = _compute(
        tmp_path,
        run_result=_run_result(cases=cases),
        eval_set=_eval_set(cases=[RetrievalCase("q001", "q", ("a.md",))]),
    )
    case = result.cases[0]
    assert case.recall_at_k == pytest.approx(1.0)
    assert case.retrieved_file_count == 1
    assert case.recall_at_k <= 1.0


def test_recall_never_exceeds_one(tmp_path):
    cases = [
        _case_result(
            "q001", "q", ("a.md", "b.md"),
            [
                _hit(1, "c1", "d1", "a.md"),
                _hit(2, "c2", "d2", "b.md"),
            ],
        ),
    ]
    result, _ = _compute(
        tmp_path,
        run_result=_run_result(cases=cases),
        eval_set=_eval_set(cases=[RetrievalCase("q001", "q", ("a.md", "b.md"))]),
    )
    assert result.cases[0].recall_at_k == pytest.approx(1.0)


def test_mrr_first_second_and_none(tmp_path):
    cases = [
        _case_result("q1", "q", ("a.md",), [_hit(1, "c1", "d1", "a.md")]),
        _case_result(
            "q2", "q", ("a.md",),
            [_hit(1, "c9", "d9", "x.md"), _hit(2, "c1", "d1", "a.md")],
        ),
        _case_result("q3", "q", ("z.md",), [_hit(1, "c9", "d9", "x.md")]),
    ]
    result, _ = _compute(
        tmp_path,
        run_result=_run_result(cases=cases),
        eval_set=_eval_set(cases=[
            RetrievalCase("q1", "q", ("a.md",)),
            RetrievalCase("q2", "q", ("a.md",)),
            RetrievalCase("q3", "q", ("z.md",)),
        ]),
    )
    assert result.cases[0].mrr == pytest.approx(1.0)
    assert result.cases[1].mrr == pytest.approx(0.5)
    assert result.cases[2].mrr == pytest.approx(0.0)


def test_ndcg_ideal_non_ideal_and_none(tmp_path):
    ideal = _case_result(
        "q1", "q", ("a.md", "b.md"),
        [
            _hit(1, "c1", "d1", "a.md"),
            _hit(2, "c2", "d2", "b.md"),
        ],
    )
    non_ideal = _case_result(
        "q2", "q", ("a.md", "b.md"),
        [
            _hit(1, "c9", "d9", "x.md"),
            _hit(2, "c1", "d1", "a.md"),
        ],
    )
    none = _case_result("q3", "q", ("z.md",), [_hit(1, "c9", "d9", "x.md")])
    result, _ = _compute(
        tmp_path,
        run_result=_run_result(cases=[ideal, non_ideal, none]),
        eval_set=_eval_set(cases=[
            RetrievalCase("q1", "q", ("a.md", "b.md")),
            RetrievalCase("q2", "q", ("a.md", "b.md")),
            RetrievalCase("q3", "q", ("z.md",)),
        ]),
    )
    assert result.cases[0].ndcg_at_k == pytest.approx(1.0)
    assert result.cases[1].ndcg_at_k < 1.0
    assert result.cases[1].ndcg_at_k > 0.0
    assert result.cases[2].ndcg_at_k == pytest.approx(0.0)


def test_first_relevant_rank(tmp_path):
    cases = [
        _case_result(
            "q1", "q", ("a.md",),
            [_hit(1, "c9", "d9", "x.md"), _hit(2, "c1", "d1", "a.md")],
        ),
        _case_result("q2", "q", ("z.md",), [_hit(1, "c9", "d9", "x.md")]),
    ]
    result, _ = _compute(
        tmp_path,
        run_result=_run_result(cases=cases),
        eval_set=_eval_set(cases=[
            RetrievalCase("q1", "q", ("a.md",)),
            RetrievalCase("q2", "q", ("z.md",)),
        ]),
    )
    assert result.cases[0].first_relevant_rank == 2
    assert result.cases[1].first_relevant_rank is None


def test_disk_results_missing_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(FileNotFoundError, match="retrieval_results"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_disk_results_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    disk_run = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, disk_run)
    tampered = dataclasses.replace(
        disk_run,
        cases=(dataclasses.replace(
            disk_run.cases[0],
            hits=(_hit(1, "cX", "d1", "a.md"),),
        ), disk_run.cases[1]),
    )
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="不一致"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, tampered, eval_set)
    assert not prepared.paths.retrieval_metrics_path.exists()


def test_disk_results_invalid_json_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    prepared.paths.retrieval_results_path.write_text(
        "{ not valid json", encoding="utf-8"
    )
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="解析"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)
    assert not prepared.paths.retrieval_metrics_path.exists()


def test_disk_results_top_level_list_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    prepared.paths.retrieval_results_path.write_text("[]", encoding="utf-8")
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="object"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_experiment_id_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(
        config=config, cases=_default_cases(), experiment_id="other-exp"
    )
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="experiment_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_corpus_id_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(corpus_id="other-corpus", cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="corpus_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_evaluation_set_id_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(evaluation_set_id="other-eval", cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="evaluation_set_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_retriever_strategy_mismatch_fails(tmp_path):
    config = ExperimentConfig()  # hybrid
    run_result = _run_result(
        config=config, cases=_default_cases(), retriever_strategy="simple"
    )
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="retriever_strategy"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_top_k_mismatch_fails(tmp_path):
    config = ExperimentConfig()  # top_k=5
    run_result = _run_result(config=config, cases=_default_cases(), top_k=3)
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="top_k"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_tampered_retrieval_run_id_fails(tmp_path):
    config = ExperimentConfig()
    tampered = _run_result(
        config=config,
        cases=_default_cases(),
        retrieval_run_id="deadbeefdead",
    )
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, tampered)
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(RuntimeError, match="retrieval_run_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, tampered, eval_set)


def test_case_count_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=_default_eval_cases()[:1])
    with pytest.raises(RuntimeError, match="Case|数量"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_case_id_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[
        RetrievalCase("qXXX", "query one", ("a.md",)),
        RetrievalCase("q002", "query two", ("a.md", "b.md", "c.md")),
    ])
    with pytest.raises(RuntimeError, match="case_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_query_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[
        RetrievalCase("q001", "tampered query", ("a.md",)),
        RetrievalCase("q002", "query two", ("a.md", "b.md", "c.md")),
    ])
    with pytest.raises(RuntimeError, match="query"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_relevant_files_snapshot_mismatch_fails(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[
        RetrievalCase("q001", "query one", ("z.md",)),
        RetrievalCase("q002", "query two", ("a.md", "b.md", "c.md")),
    ])
    with pytest.raises(RuntimeError, match="relevant_files"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_non_contiguous_hit_ranks_fail(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1, "c1", "d1", "a.md"), _hit(3, "c2", "d2", "b.md")],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[RetrievalCase("q001", "query one", ("a.md",))])
    with pytest.raises(RuntimeError, match="rank"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_duplicate_chunk_id_fails(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [
                _hit(1, "c1", "d1", "a.md"),
                _hit(2, "c1", "d2", "b.md"),
            ],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[RetrievalCase("q001", "query one", ("a.md",))])
    with pytest.raises(RuntimeError, match="重复 Chunk"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_retrieved_files_tampered_order_fails(tmp_path):
    config = ExperimentConfig()
    case = _case_result(
        "q001", "query one", ("a.md",),
        [
            _hit(1, "c1", "d1", "a.md"),
            _hit(2, "c2", "d2", "b.md"),
        ],
    )
    tampered = dataclasses.replace(
        case, retrieved_files=("b.md", "a.md")
    )
    run_result = _run_result(config=config, cases=[tampered])
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[RetrievalCase("q001", "query one", ("a.md",))])
    with pytest.raises(RuntimeError, match="retrieved_files"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_retrieved_files_duplicates_fail(tmp_path):
    config = ExperimentConfig()
    case = _case_result(
        "q001", "query one", ("a.md",),
        [_hit(1, "c1", "d1", "a.md")],
    )
    tampered = dataclasses.replace(case, retrieved_files=("a.md", "a.md"))
    run_result = _run_result(config=config, cases=[tampered])
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[RetrievalCase("q001", "query one", ("a.md",))])
    with pytest.raises(RuntimeError, match="重复|retrieved_files"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_hits_exceeding_top_k_fails(tmp_path):
    config = ExperimentConfig(top_k=1)
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [
                _hit(1, "c1", "d1", "a.md"),
                _hit(2, "c2", "d2", "b.md"),
            ],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=[RetrievalCase("q001", "query one", ("a.md",))])
    with pytest.raises(RuntimeError, match="top_k"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_same_input_same_metrics_run_id():
    kwargs = dict(
        schema_version=1,
        retrieval_run_id="run-1",
        evaluation_set_id="eval-1",
        top_k=5,
        metric_scope="document",
        relevance="binary",
        aggregation="macro",
    )
    assert RetrievalMetricsResult.compute_metrics_run_id(**kwargs) == (
        RetrievalMetricsResult.compute_metrics_run_id(**kwargs)
    )


@pytest.mark.parametrize("field,value", [
    ("retrieval_run_id", "run-2"),
    ("evaluation_set_id", "eval-2"),
    ("top_k", 10),
    ("schema_version", 2),
])
def test_metrics_run_id_changes_on_bound_field(field, value):
    base = dict(
        schema_version=1,
        retrieval_run_id="run-1",
        evaluation_set_id="eval-1",
        top_k=5,
        metric_scope="document",
        relevance="binary",
        aggregation="macro",
    )
    before = RetrievalMetricsResult.compute_metrics_run_id(**base)
    after = RetrievalMetricsResult.compute_metrics_run_id(**{**base, field: value})
    assert before != after


def test_metrics_json_has_no_absolute_path_api_key_repr(tmp_path):
    result, prepared = _compute(tmp_path)
    text = prepared.paths.retrieval_metrics_path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert str(tmp_path) not in text
    assert "api_key" not in lowered
    assert "object at" not in text
    assert "0x" not in lowered
    assert result.metrics_run_id


def test_atomic_write_failure_leaves_no_metrics_file(tmp_path, monkeypatch):
    import evaluation.retrieval_metrics as metrics_module

    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=_default_eval_cases())

    def boom(src, dst):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(metrics_module.os, "replace", boom)
    with pytest.raises(OSError, match="atomic replace failed"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)
    assert not prepared.paths.retrieval_metrics_path.exists()
    leftovers = [
        p for p in prepared.paths.workspace_path.iterdir() if p.suffix == ".tmp"
    ]
    assert leftovers == []


def test_models_are_immutable():
    case_metrics = RetrievalCaseMetrics(
        case_id="q001",
        hit_at_k=1.0,
        recall_at_k=1.0,
        mrr=1.0,
        ndcg_at_k=1.0,
        relevant_file_count=1,
        retrieved_file_count=1,
        first_relevant_rank=1,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        case_metrics.hit_at_k = 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        case_metrics.first_relevant_rank = None

    metrics = RetrievalMetricsResult(
        schema_version=METRICS_SCHEMA_VERSION,
        metrics_run_id="id",
        experiment_id="e",
        corpus_id="c",
        evaluation_set_id="s",
        retrieval_run_id="r",
        retriever_strategy="hybrid",
        top_k=5,
        case_count=1,
        cases=(case_metrics,),
        mean_hit_at_k=1.0,
        mean_recall_at_k=1.0,
        mean_mrr=1.0,
        mean_ndcg_at_k=1.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        metrics.cases = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        metrics.mean_mrr = 0.0


def test_existing_metrics_file_rejects_rerun(tmp_path):
    config = ExperimentConfig()
    run_result = _run_result(config=config, cases=_default_cases())
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    prepared.paths.retrieval_metrics_path.write_text("{}", encoding="utf-8")
    eval_set = _eval_set(cases=_default_eval_cases())
    with pytest.raises(FileExistsError, match="retrieval_metrics"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_retrieval_metrics_path_is_dedicated(tmp_path):
    config = ExperimentConfig()
    prepared = _prepare(tmp_path, config)
    assert prepared.paths.retrieval_metrics_path == (
        prepared.paths.workspace_path / "retrieval_metrics.json"
    )
    assert prepared.paths.retrieval_metrics_path != prepared.paths.retrieval_results_path
    assert prepared.paths.retrieval_metrics_path != prepared.paths.result_path


# ============================================================
# G2-EVAL-08-R1：Retrieval 快照二次校验严格值 + 类型
# ============================================================


def _run_single_case(tmp_path, config, run_result, eval_case):
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=(eval_case,))
    return prepared, eval_set


def test_rank_bool_rejected(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(True, "c1", "d1", "a.md")],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared, eval_set = _run_single_case(
        tmp_path, config, run_result, RetrievalCase("q001", "query one", ("a.md",))
    )
    with pytest.raises(RuntimeError, match="rank"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)
    assert not prepared.paths.retrieval_metrics_path.exists()


def test_rank_float_rejected(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1.0, "c1", "d1", "a.md")],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared, eval_set = _run_single_case(
        tmp_path, config, run_result, RetrievalCase("q001", "query one", ("a.md",))
    )
    with pytest.raises(RuntimeError, match="rank"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)
    assert not prepared.paths.retrieval_metrics_path.exists()


def test_rank_valid_int_accepted(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1, "c1", "d1", "a.md")],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared, eval_set = _run_single_case(
        tmp_path, config, run_result, RetrievalCase("q001", "query one", ("a.md",))
    )
    result = ExperimentRunner(
        tmp_path / "base_config.yaml", tmp_path / "runs"
    ).compute_retrieval_metrics(prepared, run_result, eval_set)
    assert result.cases[0].mrr == pytest.approx(1.0)


def test_non_string_chunk_id_rejected(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1, 123, "d1", "a.md")],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared, eval_set = _run_single_case(
        tmp_path, config, run_result, RetrievalCase("q001", "query one", ("a.md",))
    )
    with pytest.raises(RuntimeError, match="chunk_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)
    assert not prepared.paths.retrieval_metrics_path.exists()


def test_non_string_document_id_rejected(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1, "c1", 123, "a.md")],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared, eval_set = _run_single_case(
        tmp_path, config, run_result, RetrievalCase("q001", "query one", ("a.md",))
    )
    with pytest.raises(RuntimeError, match="document_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_non_string_relative_path_rejected(tmp_path):
    config = ExperimentConfig()
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1, "c1", "d1", 123)],
        ),
    ]
    run_result = _run_result(config=config, cases=cases)
    prepared, eval_set = _run_single_case(
        tmp_path, config, run_result, RetrievalCase("q001", "query one", ("a.md",))
    )
    with pytest.raises(RuntimeError, match="relative_path"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


def test_non_string_retrieved_files_item_rejected(tmp_path):
    config = ExperimentConfig()
    case = _case_result(
        "q001", "query one", ("a.md",),
        [_hit(1, "c1", "d1", "a.md")],
    )
    tampered = dataclasses.replace(case, retrieved_files=(123,))
    run_result = _run_result(config=config, cases=[tampered])
    prepared, eval_set = _run_single_case(
        tmp_path, config, run_result, RetrievalCase("q001", "query one", ("a.md",))
    )
    with pytest.raises(RuntimeError, match="字符串"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)


@pytest.mark.parametrize("top_k", [True, 1.0])
def test_top_k_bool_or_float_binding_rejected(tmp_path, top_k):
    config = ExperimentConfig(top_k=1)
    cases = [
        _case_result(
            "q001", "query one", ("a.md",),
            [_hit(1, "c1", "d1", "a.md")],
        ),
    ]
    run_result = _run_result(config=config, cases=cases, top_k=top_k)
    prepared = _prepare(tmp_path, config)
    _write_results(prepared, run_result)
    eval_set = _eval_set(cases=(RetrievalCase("q001", "query one", ("a.md",)),))
    with pytest.raises(RuntimeError, match="top_k"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).compute_retrieval_metrics(prepared, run_result, eval_set)
    assert not prepared.paths.retrieval_metrics_path.exists()
