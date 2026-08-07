"""G2-EVAL-07：正式检索执行与原始结果快照（run_retrieval）"""

import dataclasses
import json

import pytest

from evaluation.experiment_config import ExperimentConfig
from evaluation.experiment_runner import ExperimentRunner, PreparedExperiment
from evaluation.experiment_workspace import ExperimentWorkspace
from evaluation.index_manifest import FileIndexRecord, IndexManifest
from evaluation.retrieval_evaluation_set import RetrievalCase, RetrievalEvaluationSet
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


class FakeDoc:
    def __init__(self, metadata):
        self.metadata = metadata


class FakeRetriever:
    def __init__(self, results=None, raise_queries=(), default=()):
        self.calls = []
        self._results = results or {}
        self._raise_queries = set(raise_queries)
        self._default = list(default)

    def retrieve(self, query, top_k=5):
        self.calls.append((query, top_k))
        if query in self._raise_queries:
            raise RuntimeError("retrieve 异常注入")
        return [FakeDoc(m) for m in self._results.get(query, self._default)]


class FakePipeline:
    def __init__(self, retriever):
        self.retriever = retriever


def _write_base_config(tmp_path):
    path = tmp_path / "base_config.yaml"
    path.write_text(BASE_CONFIG_YAML, encoding="utf-8")
    return path


def _prepare(tmp_path, config, retriever):
    base = _write_base_config(tmp_path)
    paths = ExperimentWorkspace(base, tmp_path / "runs", config, "run1").prepare()
    return PreparedExperiment(
        experiment_config=config, paths=paths, pipeline=FakePipeline(retriever)
    )


def _make_manifest(
    config,
    corpus_id,
    *,
    files=None,
    total_chunks=None,
    vector_store_count=None,
    sparse_index_count=None,
    experiment_id=None,
    chunk_strategy=None,
    retriever_strategy=None,
    cfg=None,
):
    records = files if files is not None else [
        FileIndexRecord(
            relative_path="core/pipeline.py", sha256="a" * 64, size_bytes=10,
            document_id="pipeline.py", chunks=2, status="create",
        ),
        FileIndexRecord(
            relative_path="docs/x.md", sha256="b" * 64, size_bytes=10,
            document_id="x.md", chunks=1, status="create",
        ),
    ]
    total = total_chunks if total_chunks is not None else sum(f.chunks for f in records)
    vs = vector_store_count if vector_store_count is not None else total
    effective_retriever = (
        retriever_strategy if retriever_strategy is not None
        else config.retriever_strategy
    )
    if sparse_index_count is None and effective_retriever == "hybrid":
        sparse_index_count = vs
    return IndexManifest(
        schema_version=1,
        experiment_id=experiment_id if experiment_id is not None else config.experiment_id,
        corpus_id=corpus_id,
        chunk_strategy=chunk_strategy if chunk_strategy is not None else config.chunk_strategy,
        retriever_strategy=effective_retriever,
        config=cfg if cfg is not None else config.to_dict(),
        corpus_entries=(),
        files=tuple(records),
        file_count=len(records),
        total_chunks=total,
        vector_store_count=vs,
        sparse_index_count=sparse_index_count,
    )


def _make_eval_set(corpus_id, cases=None, evaluation_set_id="evalset-001"):
    if cases is None:
        cases = (
            RetrievalCase(
                case_id="q001", query="query one",
                relevant_files=("docs/x.md",),
            ),
            RetrievalCase(
                case_id="q002", query="query two",
                relevant_files=("core/pipeline.py",),
            ),
        )
    return RetrievalEvaluationSet(
        corpus_id=corpus_id, cases=cases, evaluation_set_id=evaluation_set_id
    )


def _default_results():
    return {
        "query one": [{"id": "c1", "document_id": "x.md", "score": 0.9}],
        "query two": [{"id": "c2", "document_id": "pipeline.py", "score": 0.8}],
    }


def _run(tmp_path, config=None, corpus_id="corpus-001", retriever=None,
         manifest=None, eval_set=None):
    config = config or ExperimentConfig()
    retriever = retriever or FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = manifest or _make_manifest(config, corpus_id)
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = eval_set or _make_eval_set(corpus_id)
    return ExperimentRunner(
        tmp_path / "base_config.yaml", tmp_path / "runs"
    ).run_retrieval(prepared, manifest, eval_set), prepared, retriever


def test_cases_executed_in_evaluation_set_order(tmp_path):
    result, prepared, retriever = _run(tmp_path)
    assert [q for q, _ in retriever.calls] == ["query one", "query two"]
    assert [c.case_id for c in result.cases] == ["q001", "q002"]
    assert prepared.paths.retrieval_results_path.is_file()


def test_each_case_retrieved_exactly_once(tmp_path):
    _, _, retriever = _run(tmp_path)
    assert len(retriever.calls) == 2


def test_retrieve_uses_experiment_top_k(tmp_path):
    config = ExperimentConfig(top_k=7)
    _, _, retriever = _run(tmp_path, config=config)
    assert retriever.calls == [("query one", 7), ("query two", 7)]


def test_missing_manifest_file_fails_before_retrieve(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(FileNotFoundError, match="index_manifest"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_experiment_id_mismatch_zero_calls(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001", experiment_id="other-exp")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="experiment_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []
    assert not prepared.paths.retrieval_results_path.exists()


def test_corpus_id_mismatch_zero_calls(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-A")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-B")
    with pytest.raises(RuntimeError, match="corpus_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_evaluation_set_corpus_mismatch_zero_calls(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-B")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-A")
    with pytest.raises(RuntimeError, match="corpus_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


@pytest.mark.parametrize("field,value", [
    ("chunk_strategy", "fixed"),
    ("retriever_strategy", "mmr"),
])
def test_strategy_mismatch_zero_calls(tmp_path, field, value):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    kwargs = {field: value}
    manifest = _make_manifest(config, "corpus-001", **kwargs)
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match=field):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_config_dict_mismatch_zero_calls(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(
        config, "corpus-001", cfg=dict(config.to_dict(), top_k=99)
    )
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="config"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_manifest_file_count_mismatch_zero_calls(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest = IndexManifest(
        **{**manifest.__dict__, "file_count": manifest.file_count + 1}
    )
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="file_count"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_manifest_total_chunks_mismatch_zero_calls(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(
        config, "corpus-001", total_chunks=5, vector_store_count=3
    )
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="total_chunks"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_hybrid_sparse_count_mismatch_zero_calls(tmp_path):
    config = ExperimentConfig(retriever_strategy="hybrid")
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(
        config, "corpus-001", sparse_index_count=2
    )  # vector_store_count=3
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="sparse_index_count"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_existing_result_file_rejects_rerun(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    prepared.paths.retrieval_results_path.write_text("{}", encoding="utf-8")
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(FileExistsError, match="retrieval_results"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_chunk_hit_maps_document_id_to_relative_path(tmp_path):
    result, _, _ = _run(tmp_path)
    hit = result.cases[0].hits[0]
    assert hit.chunk_id == "c1"
    assert hit.document_id == "x.md"
    assert hit.relative_path == "docs/x.md"
    assert hit.rank == 1


def test_mapping_not_from_basename_or_absolute_source(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [{
            "id": "c1",
            "document_id": "pipeline.py",
            "source": "/abs/elsewhere.py",
            "score": 0.9,
        }],
    })
    result, prepared, _ = _run(tmp_path, config=config, retriever=retriever)
    hit = result.cases[0].hits[0]
    assert hit.relative_path == "core/pipeline.py"
    text = prepared.paths.retrieval_results_path.read_text(encoding="utf-8")
    assert "/abs/elsewhere.py" not in text


def test_missing_chunk_id_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [{"document_id": "x.md", "score": 0.9}],
    })
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001", cases=(
        RetrievalCase("q001", "query one", ("docs/x.md",)),
    ))
    with pytest.raises(RuntimeError, match="id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert not prepared.paths.retrieval_results_path.exists()


def test_missing_document_id_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [{"id": "c1", "score": 0.9}],
    })
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001", cases=(
        RetrievalCase("q001", "query one", ("docs/x.md",)),
    ))
    with pytest.raises(RuntimeError, match="document_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert not prepared.paths.retrieval_results_path.exists()


def test_unknown_document_id_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [{"id": "c1", "document_id": "unknown.py", "score": 0.9}],
    })
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001", cases=(
        RetrievalCase("q001", "query one", ("docs/x.md",)),
    ))
    with pytest.raises(RuntimeError, match="未知 document_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert not prepared.paths.retrieval_results_path.exists()


def test_duplicate_chunk_id_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [
            {"id": "c1", "document_id": "x.md", "score": 0.9},
            {"id": "c1", "document_id": "pipeline.py", "score": 0.8},
        ],
    })
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001", cases=(
        RetrievalCase("q001", "query one", ("docs/x.md",)),
    ))
    with pytest.raises(RuntimeError, match="重复 Chunk ID"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert not prepared.paths.retrieval_results_path.exists()


def test_same_file_multiple_chunks_keeps_all_hits(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [
            {"id": "c1", "document_id": "x.md", "score": 0.9},
            {"id": "c2", "document_id": "x.md", "score": 0.8},
        ],
    })
    result, _, _ = _run(tmp_path, config=config, retriever=retriever)
    case = result.cases[0]
    assert [h.chunk_id for h in case.hits] == ["c1", "c2"]
    assert [h.rank for h in case.hits] == [1, 2]
    assert case.retrieved_files == ("docs/x.md",)


def test_retrieved_files_order_by_first_chunk_hit(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [
            {"id": "c1", "document_id": "x.md", "score": 0.9},
            {"id": "c7", "document_id": "pipeline.py", "score": 0.8},
            {"id": "c2", "document_id": "x.md", "score": 0.7},
        ],
    })
    result, _, _ = _run(tmp_path, config=config, retriever=retriever)
    assert result.cases[0].retrieved_files == ("docs/x.md", "core/pipeline.py")


def test_fewer_than_top_k_results_succeeds(tmp_path):
    config = ExperimentConfig(top_k=5)
    retriever = FakeRetriever({
        "query one": [{"id": "c1", "document_id": "x.md", "score": 0.5}],
    })
    result, _, _ = _run(
        tmp_path, config=config, retriever=retriever,
        eval_set=_make_eval_set("corpus-001", cases=(
            RetrievalCase("q001", "query one", ("docs/x.md",)),
        )),
    )
    assert len(result.cases[0].hits) == 1


def test_more_than_top_k_truncated_to_top_k(tmp_path):
    config = ExperimentConfig(top_k=3)
    retriever = FakeRetriever({
        "query one": [
            {"id": "c1", "document_id": "x.md", "score": 0.9},
            {"id": "c2", "document_id": "x.md", "score": 0.8},
            {"id": "c3", "document_id": "x.md", "score": 0.7},
            {"id": "c4", "document_id": "pipeline.py", "score": 0.6},
            {"id": "c5", "document_id": "pipeline.py", "score": 0.5},
        ],
    })
    result, _, _ = _run(
        tmp_path, config=config, retriever=retriever,
        eval_set=_make_eval_set("corpus-001", cases=(
            RetrievalCase("q001", "query one", ("docs/x.md",)),
        )),
    )
    assert [h.rank for h in result.cases[0].hits] == [1, 2, 3]
    assert result.cases[0].retrieved_files == ("docs/x.md",)


def test_retriever_exception_midway_no_result_file(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results(), raise_queries={"query two"})
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="retrieve 异常注入"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert len(retriever.calls) == 2
    assert not prepared.paths.retrieval_results_path.exists()


def test_scores_only_whitelist_existing_fields(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [{
            "id": "c1",
            "document_id": "x.md",
            "score": 0.9,
            "rrf_score": 0.8,
            "dense_rank": 1,
            "source": "/abs/source.py",
            "content_hash": "abc",
            "extra": "not allowed",
        }],
    })
    result, _, _ = _run(
        tmp_path, config=config, retriever=retriever,
        eval_set=_make_eval_set("corpus-001", cases=(
            RetrievalCase("q001", "query one", ("docs/x.md",)),
        )),
    )
    scores = result.cases[0].hits[0].scores
    assert scores == {"score": 0.9, "rrf_score": 0.8, "dense_rank": 1}


def test_result_json_has_no_absolute_source_api_key_repr(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever({
        "query one": [{
            "id": "c1",
            "document_id": "x.md",
            "score": 0.9,
            "source": "/abs/secret/source.py",
            "api_key": "sk-secret-key",
            "obj": "<object at 0x12345678>",
            "addr": "0x12345678",
        }],
    })
    _, prepared, _ = _run(
        tmp_path, config=config, retriever=retriever,
        eval_set=_make_eval_set("corpus-001", cases=(
            RetrievalCase("q001", "query one", ("docs/x.md",)),
        )),
    )
    text = prepared.paths.retrieval_results_path.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "/abs/secret/source.py" not in text
    assert "sk-secret-key" not in text
    assert "object at" not in text
    assert "0x12345678" not in text
    assert "api_key" not in lowered


def test_result_json_has_schema_version_and_stable_keys(tmp_path):
    _, prepared, _ = _run(tmp_path)
    raw = json.loads(prepared.paths.retrieval_results_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == RETRIEVAL_RESULT_SCHEMA_VERSION
    assert raw["retrieval_run_id"]
    assert raw["experiment_id"]
    assert raw["corpus_id"] == "corpus-001"
    assert raw["evaluation_set_id"] == "evalset-001"
    assert raw["retriever_strategy"] == "hybrid"
    assert raw["top_k"] == 5
    assert len(raw["cases"]) == 2


def test_same_binding_same_retrieval_run_id():
    kwargs = dict(
        schema_version=1,
        experiment_id="exp-1",
        corpus_id="corpus-1",
        evaluation_set_id="eval-1",
        retriever_strategy="hybrid",
        top_k=5,
    )
    assert RetrievalRunResult.compute_run_id(**kwargs) == (
        RetrievalRunResult.compute_run_id(**kwargs)
    )


@pytest.mark.parametrize("field,value", [
    ("experiment_id", "exp-2"),
    ("corpus_id", "corpus-2"),
    ("evaluation_set_id", "eval-2"),
    ("retriever_strategy", "simple"),
    ("top_k", 10),
])
def test_retrieval_run_id_changes_on_bound_field(field, value):
    base = dict(
        schema_version=1,
        experiment_id="exp-1",
        corpus_id="corpus-1",
        evaluation_set_id="eval-1",
        retriever_strategy="hybrid",
        top_k=5,
    )
    before = RetrievalRunResult.compute_run_id(**base)
    after = RetrievalRunResult.compute_run_id(**{**base, field: value})
    assert before != after


def test_atomic_write_failure_leaves_no_result_file(tmp_path, monkeypatch):
    import evaluation.retrieval_result as result_module

    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001")

    def boom(src, dst):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(result_module.os, "replace", boom)
    with pytest.raises(OSError, match="atomic replace failed"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert not prepared.paths.retrieval_results_path.exists()
    leftovers = [
        p for p in prepared.paths.workspace_path.iterdir() if p.suffix == ".tmp"
    ]
    assert leftovers == []


def test_models_are_immutable():
    hit = RetrievalHit(
        rank=1, chunk_id="c1", document_id="d1",
        relative_path="a.md", scores={"score": 0.9},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        hit.rank = 2
    with pytest.raises(dataclasses.FrozenInstanceError):
        hit.chunk_id = "c2"

    case_result = RetrievalCaseResult(
        case_id="q001", query="q", relevant_files=("a.md",),
        hits=(hit,), retrieved_files=("a.md",),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        case_result.hits = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        case_result.retrieved_files = ()

    run_result = RetrievalRunResult(
        schema_version=1, retrieval_run_id="id", experiment_id="e",
        corpus_id="c", evaluation_set_id="s", retriever_strategy="hybrid",
        top_k=5, cases=(case_result,),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        run_result.cases = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        run_result.retrieval_run_id = "other"


def test_manifest_empty_document_id_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001", files=[
        FileIndexRecord(
            relative_path="core/pipeline.py", sha256="a" * 64, size_bytes=10,
            document_id="", chunks=2, status="create",
        ),
    ])
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001", cases=(
        RetrievalCase("q001", "query one", ("core/pipeline.py",)),
    ))
    with pytest.raises(RuntimeError, match="document_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_manifest_duplicate_document_id_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001", files=[
        FileIndexRecord(
            relative_path="core/pipeline.py", sha256="a" * 64, size_bytes=10,
            document_id="dup", chunks=1, status="create",
        ),
        FileIndexRecord(
            relative_path="docs/x.md", sha256="b" * 64, size_bytes=10,
            document_id="dup", chunks=1, status="create",
        ),
    ])
    manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001", cases=(
        RetrievalCase("q001", "query one", ("docs/x.md",)),
    ))
    with pytest.raises(RuntimeError, match="document_id"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_retrieval_results_path_is_dedicated(tmp_path):
    config = ExperimentConfig()
    prepared = _prepare(tmp_path, config, FakeRetriever())
    assert prepared.paths.retrieval_results_path == (
        prepared.paths.workspace_path / "retrieval_results.json"
    )
    assert prepared.paths.retrieval_results_path != prepared.paths.index_manifest_path
    assert prepared.paths.retrieval_results_path != prepared.paths.result_path


# ============================================================
# G2-EVAL-07-R1：磁盘 index_manifest.json 与传入对象完整一致
# ============================================================


def _tamper_disk_manifest(prepared, mutate):
    path = prepared.paths.index_manifest_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_passed_manifest_mismatch_with_disk_fails_before_retrieve(tmp_path):
    """场景 A：磁盘 Manifest A 与传入 Manifest B 的 files 映射互换，
    其余顶层字段完全一致，修复前可绕过绑定校验。"""
    config = ExperimentConfig()
    disk_manifest = _make_manifest(config, "corpus-001", files=[
        FileIndexRecord(
            relative_path="core/pipeline.py", sha256="a" * 64, size_bytes=10,
            document_id="d1", chunks=1, status="create",
        ),
        FileIndexRecord(
            relative_path="docs/x.md", sha256="b" * 64, size_bytes=10,
            document_id="d2", chunks=1, status="create",
        ),
    ])
    passed_manifest = _make_manifest(config, "corpus-001", files=[
        FileIndexRecord(
            relative_path="docs/x.md", sha256="b" * 64, size_bytes=10,
            document_id="d1", chunks=1, status="create",
        ),
        FileIndexRecord(
            relative_path="core/pipeline.py", sha256="a" * 64, size_bytes=10,
            document_id="d2", chunks=1, status="create",
        ),
    ])
    assert disk_manifest.to_dict() != passed_manifest.to_dict()

    retriever = FakeRetriever({
        "query one": [{"id": "c1", "document_id": "d1", "score": 0.9}],
    })
    prepared = _prepare(tmp_path, config, retriever)
    disk_manifest.write_json(prepared.paths.index_manifest_path)
    eval_set = _make_eval_set("corpus-001", cases=(
        RetrievalCase("q001", "query one", ("core/pipeline.py",)),
    ))
    with pytest.raises(RuntimeError) as excinfo:
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, passed_manifest, eval_set)
    message = str(excinfo.value)
    assert "传入 IndexManifest" in message
    assert "不一致" in message
    assert retriever.calls == []
    assert not prepared.paths.retrieval_results_path.exists()


def test_disk_manifest_corpus_entries_modified_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    _tamper_disk_manifest(prepared, lambda p: p.__setitem__(
        "corpus_entries",
        [{"relative_path": "tampered.md", "sha256": "x" * 64, "size_bytes": 1}],
    ))
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="传入 IndexManifest|不一致"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []
    assert not prepared.paths.retrieval_results_path.exists()


def test_disk_manifest_sha256_modified_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    _tamper_disk_manifest(prepared, lambda p: p["files"][0].__setitem__(
        "sha256", "f" * 64
    ))
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="传入 IndexManifest|不一致"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_disk_manifest_missing_field_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    _tamper_disk_manifest(prepared, lambda p: p.pop("sparse_index_count"))
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="传入 IndexManifest|不一致"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_disk_manifest_invalid_json_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    prepared.paths.index_manifest_path.write_text(
        "{ not valid json", encoding="utf-8"
    )
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="解析|index_manifest"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []
    assert not prepared.paths.retrieval_results_path.exists()


def test_disk_manifest_top_level_list_fails(tmp_path):
    config = ExperimentConfig()
    retriever = FakeRetriever(_default_results())
    prepared = _prepare(tmp_path, config, retriever)
    manifest = _make_manifest(config, "corpus-001")
    manifest.write_json(prepared.paths.index_manifest_path)
    prepared.paths.index_manifest_path.write_text("[]", encoding="utf-8")
    eval_set = _make_eval_set("corpus-001")
    with pytest.raises(RuntimeError, match="object"):
        ExperimentRunner(
            tmp_path / "base_config.yaml", tmp_path / "runs"
        ).run_retrieval(prepared, manifest, eval_set)
    assert retriever.calls == []


def test_consistent_disk_manifest_still_succeeds(tmp_path):
    result, prepared, retriever = _run(tmp_path)
    assert len(retriever.calls) == 2
    assert prepared.paths.retrieval_results_path.is_file()
    assert result.retrieval_run_id
