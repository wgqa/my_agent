"""G2-REAL-11：CLI 薄入口 orchestration 测试（不访问 Benchmark/网络）"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_retrieval_experiment as cli
from evaluation.experiment_config import ExperimentConfig


def test_build_config_is_frozen_baseline():
    config = cli.build_config()
    assert config == ExperimentConfig(
        embedding_provider="bge",
        embedding_model="BAAI/bge-small-zh-v1.5",
        chunk_strategy="recursive",
        chunk_size=512,
        chunk_overlap=64,
        retriever_strategy="hybrid",
        top_k=5,
        dense_candidate_k=30,
        sparse_candidate_k=30,
        rrf_k=60.0,
        rrf_tie_breaker="chunk_id_asc",
    )


def test_cli_run_calls_existing_chain_in_order(tmp_path, monkeypatch):
    calls = []
    corpus = SimpleNamespace(corpus_id="corpus-1")
    eval_set = SimpleNamespace(corpus_id="corpus-1", evaluation_set_id="eval-1")
    result = SimpleNamespace(
        retrieval_run_id="run-id",
        metrics_run_id="metrics-id",
        result_id="result-id",
        file_count=37,
        total_chunks=100,
        case_count=50,
        top_k=5,
        mean_hit_at_k=0.9,
        mean_recall_at_k=0.8,
        mean_mrr=0.7,
        mean_ndcg_at_k=0.6,
    )

    def fake_build(root, relative_paths):
        calls.append(("build", root, relative_paths))
        return corpus

    def fake_load(path, c):
        calls.append(("load", path, c))
        return eval_set

    def fake_run_experiment(self, config, run_id, c, e):
        calls.append(("run_experiment", config, run_id, c, e))
        return result

    monkeypatch.setattr(
        cli, "ExperimentCorpus", type("FakeCorpus", (), {
            "build": staticmethod(fake_build)
        })
    )
    monkeypatch.setattr(
        cli, "RetrievalEvaluationSet", type("FakeEvalSet", (), {
            "load_jsonl": staticmethod(fake_load)
        })
    )
    monkeypatch.setattr(cli.ExperimentRunner, "run_experiment", fake_run_experiment)

    args = SimpleNamespace(
        corpus_root=str(tmp_path / "corpus"),
        evaluation=str(tmp_path / "evaluation.jsonl"),
        base_config=str(tmp_path / "config.yaml"),
        workspace_root=str(tmp_path / "runs"),
        run_id="agent-ai-v1-recursive-hybrid-baseline-001",
    )
    facts = cli.run(args)

    assert [c[0] for c in calls] == ["build", "load", "run_experiment"]
    assert calls[0][2] == []
    assert calls[1][1] == Path(args.evaluation)
    assert calls[1][2] is corpus
    assert calls[2][2] == args.run_id
    assert calls[2][3] is corpus
    assert calls[2][4] is eval_set
    assert isinstance(calls[2][1], ExperimentConfig)
    assert facts["file_count"] == 37
    assert facts["case_count"] == 50
    assert facts["result_json"].endswith("result.json")


def test_cli_main_prints_json(tmp_path, monkeypatch, capsys):
    def fake_run(args):
        return {"ok": True}

    monkeypatch.setattr(cli, "run", fake_run)
    argv = [
        "--corpus-root", str(tmp_path / "corpus"),
        "--evaluation", str(tmp_path / "evaluation.jsonl"),
        "--base-config", str(tmp_path / "config.yaml"),
        "--workspace-root", str(tmp_path / "runs"),
        "--run-id", "run-1",
    ]
    cli.main(argv)
    captured = capsys.readouterr().out
    assert '"ok": true' in captured
