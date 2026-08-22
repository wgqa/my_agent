"""Deterministic G11-02 R4 verified Engineering Knowledge contracts."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.app
from core.engineering_knowledge import (
    EXPECTED_CHUNK_COUNT,
    EXPECTED_CORPUS_ID,
    EXPECTED_EXPERIMENT_ID,
    EXPECTED_FILE_COUNT,
    EngineeringKnowledgeError,
    VerifiedEngineeringKnowledge,
    build_verified_engineering_knowledge,
)
from scripts import run_g11_02_theory_code as runner


REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPO_ROOT.parent / "rag数据集" / "benchmark_work" / "agent_ai_v1" / "02_corpus_candidate"
AUTHORITY_MANIFEST = (
    REPO_ROOT
    / "experiments"
    / "dbc497c796d5"
    / "agent-ai-v1-recursive-bm25-baseline-001"
    / "index_manifest.json"
)


def _copy_manifest(tmp_path: Path, mutate) -> Path:
    manifest = json.loads(AUTHORITY_MANIFEST.read_text(encoding="utf-8"))
    mutate(manifest)
    target = tmp_path / "index_manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return target


def _copy_corpus(tmp_path: Path) -> Path:
    target = tmp_path / "corpus"
    import shutil

    shutil.copytree(CORPUS_ROOT, target)
    return target


def test_verified_backend_is_exact_frozen_corpus_and_topics_are_retrievable():
    backend = build_verified_engineering_knowledge(CORPUS_ROOT, repo_root=REPO_ROOT)

    assert backend.identity.corpus_id == EXPECTED_CORPUS_ID
    assert backend.identity.file_count == EXPECTED_FILE_COUNT == 37
    assert backend.identity.chunk_count == EXPECTED_CHUNK_COUNT == 215
    assert backend.identity.manifest_experiment_id == EXPECTED_EXPERIMENT_ID
    assert backend.bm25_doc_count == EXPECTED_CHUNK_COUNT
    assert len(backend.source_names) == EXPECTED_FILE_COUNT
    assert backend.absolute_provenance_count == 0

    queries = (
        "RRF BM25 dense rank fusion",
        "MMR lambda diversity relevance",
        "reranker candidate_k final_k pipeline",
        "context token budget citation validator",
    )
    for query in queries:
        matches = backend.retrieval_port.search(query, "bm25", 5)
        assert matches
        assert all("\\" not in item.source_name for item in matches)
        assert all(not Path(item.source_name).is_absolute() for item in matches)


def test_contaminated_corpus_is_rejected(tmp_path):
    corpus = _copy_corpus(tmp_path)
    extra = corpus / "Temp" / "rag_test.txt"
    extra.parent.mkdir()
    extra.write_text("temporary test content", encoding="utf-8")

    with pytest.raises(EngineeringKnowledgeError, match="do not match"):
        build_verified_engineering_knowledge(corpus, repo_root=REPO_ROOT)


def test_corpus_hash_mismatch_is_rejected(tmp_path):
    corpus = _copy_corpus(tmp_path)
    first_file = next(path for path in corpus.rglob("*") if path.is_file())
    first_file.write_text(first_file.read_text(encoding="utf-8") + "changed", encoding="utf-8")

    with pytest.raises(EngineeringKnowledgeError, match="hash or size"):
        build_verified_engineering_knowledge(corpus, repo_root=REPO_ROOT)


def test_missing_corpus_file_is_rejected(tmp_path):
    corpus = _copy_corpus(tmp_path)
    next(path for path in corpus.rglob("*") if path.is_file()).unlink()

    with pytest.raises(EngineeringKnowledgeError, match="do not match"):
        build_verified_engineering_knowledge(corpus, repo_root=REPO_ROOT)


def test_wrong_corpus_identity_and_traversal_manifest_are_rejected(tmp_path):
    wrong_identity = _copy_manifest(
        tmp_path / "identity",
        lambda manifest: manifest.update({"corpus_id": "wrong"}),
    )
    with pytest.raises(EngineeringKnowledgeError, match="identity"):
        VerifiedEngineeringKnowledge(
            CORPUS_ROOT,
            authority_manifest=wrong_identity,
        )

    traversal_identity = _copy_manifest(
        tmp_path / "traversal",
        lambda manifest: manifest["corpus_entries"][0].update(
            {"relative_path": "../outside.md"}
        ),
    )
    with pytest.raises(EngineeringKnowledgeError, match="unsafe"):
        VerifiedEngineeringKnowledge(CORPUS_ROOT, authority_manifest=traversal_identity)


def test_symlink_escape_is_rejected_or_skipped_when_windows_denies_symlink(tmp_path):
    corpus = _copy_corpus(tmp_path)
    source = next(path for path in corpus.rglob("*") if path.is_file())
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    source.unlink()
    try:
        os.symlink(outside, source)
    except OSError:
        pytest.skip("Windows symlink creation is unavailable")

    with pytest.raises(EngineeringKnowledgeError, match="outside corpus root"):
        build_verified_engineering_knowledge(corpus, repo_root=REPO_ROOT)


def test_engineering_runtime_uses_dedicated_verified_port(monkeypatch, tmp_path):
    legacy_port = object()
    engineering_port = object()
    calls = []

    def fake_builder(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(api.app, "Pipeline", lambda **kwargs: SimpleNamespace(retriever=object()))
    monkeypatch.setattr(
        api.app,
        "resolve_engineering_project",
        lambda _root: SimpleNamespace(root=tmp_path),
    )
    monkeypatch.setattr(api.app, "_resolve_agent_provider", lambda _pipeline: ("fake", "key"))
    monkeypatch.setattr(api.app, "build_pipeline_agent_runtime", lambda *args, **kwargs: object())
    monkeypatch.setattr(api.app, "PipelineRetrievalAdapter", lambda _retriever: legacy_port)
    monkeypatch.setattr(
        api.app,
        "build_verified_engineering_knowledge",
        lambda *args, **kwargs: SimpleNamespace(
            retrieval_port=engineering_port,
            identity=SimpleNamespace(
                corpus_id=EXPECTED_CORPUS_ID,
                file_count=37,
                chunk_count=215,
                retrieval_strategy="bm25",
                manifest_experiment_id=EXPECTED_EXPERIMENT_ID,
                verified=True,
            ),
        ),
    )
    monkeypatch.setattr(api.app, "build_tool_agent_runtime", fake_builder)
    monkeypatch.setattr(api.app, "EngineeringAgentFacade", lambda runtime: runtime)
    monkeypatch.setenv("ENGINEERING_KNOWLEDGE_CORPUS_ROOT", str(CORPUS_ROOT))

    async def run_lifespan():
        async with api.app.lifespan(api.app.app):
            assert len(calls) == 2
            assert calls[0]["retrieval_port"] is legacy_port
            assert calls[1]["retrieval_port"] is engineering_port

    asyncio.run(run_lifespan())


def test_knowledge_status_is_safe_and_capabilities_are_independent(monkeypatch):
    identity = SimpleNamespace(
        corpus_id=EXPECTED_CORPUS_ID,
        file_count=37,
        chunk_count=215,
        retrieval_strategy="bm25",
        manifest_experiment_id=EXPECTED_EXPERIMENT_ID,
        verified=True,
    )
    monkeypatch.setattr(
        api.app,
        "engineering_knowledge_backend",
        SimpleNamespace(identity=identity),
    )
    monkeypatch.setattr(api.app, "engineering_agent_facade", object())
    monkeypatch.setattr(api.app, "tool_agent_runtime", object())
    response = api.app.engineering_knowledge()
    assert response.ready is True
    assert response.verified is True
    assert response.model_dump() == {
        "schema_version": "engineering_knowledge_status_v1",
        "ready": True,
        "verified": True,
        "corpus_id": EXPECTED_CORPUS_ID,
        "file_count": 37,
        "chunk_count": 215,
        "retrieval_strategy": "bm25",
        "manifest_experiment_id": EXPECTED_EXPERIMENT_ID,
    }
    assert "corpus_root" not in response.model_dump()
    assert api.app.capabilities().features.engineering_agent is True

    monkeypatch.setattr(api.app, "engineering_agent_facade", None)
    assert api.app.capabilities().features.engineering_agent is False


def test_runner_knowledge_preflight_blocks_query_calls(monkeypatch, tmp_path):
    post_called = False

    monkeypatch.setattr(runner, "validate_source_commit", lambda *args, **kwargs: "a" * 40)
    monkeypatch.setattr(
        runner,
        "_get_json",
        lambda _url: {"schema_version": "engineering_knowledge_status_v1", "ready": False},
    )

    def fail_post(*args, **kwargs):
        nonlocal post_called
        post_called = True
        raise AssertionError("query must not be called after failed knowledge preflight")

    monkeypatch.setattr(runner, "_post_json", fail_post)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_g11_02_theory_code.py",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "blocked",
            "--source-commit",
            "a" * 40,
            "--git-root",
            str(REPO_ROOT),
            "--prompt-version",
            "tool_agent_decision_prompt_v3",
            "--prompt-sha256",
            runner.KNOWN_PROMPT_IDENTITIES["tool_agent_decision_prompt_v3"],
        ],
    )
    with pytest.raises(ValueError, match="status mismatch"):
        runner.main()
    assert post_called is False


def test_runner_records_service_backend_identity(monkeypatch, tmp_path):
    status = {
        "schema_version": "engineering_knowledge_status_v1",
        "ready": True,
        "verified": True,
        "corpus_id": EXPECTED_CORPUS_ID,
        "file_count": 37,
        "chunk_count": 215,
        "retrieval_strategy": "bm25",
        "manifest_experiment_id": EXPECTED_EXPERIMENT_ID,
    }
    responses = iter(
        {
            "status": "completed",
            "answer": "ok",
            "iterations_used": 1,
            "tool_calls_used": 0,
            "tool_errors_used": 0,
            "trace": [],
            "evidence": [],
        }
        for _ in runner.CASES
    )
    monkeypatch.setattr(runner, "validate_source_commit", lambda *args, **kwargs: "a" * 40)
    monkeypatch.setattr(runner, "_get_json", lambda _url: status)
    monkeypatch.setattr(runner, "_post_json", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_g11_02_theory_code.py",
            "--output-root",
            str(tmp_path),
            "--run-id",
            "recorded",
            "--source-commit",
            "a" * 40,
            "--git-root",
            str(REPO_ROOT),
            "--prompt-version",
            "tool_agent_decision_prompt_v3",
            "--prompt-sha256",
            runner.KNOWN_PROMPT_IDENTITIES["tool_agent_decision_prompt_v3"],
        ],
    )
    assert runner.main() == 0
    manifest = json.loads((tmp_path / "recorded" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["knowledge_backend"] == status
    assert manifest["knowledge_corpus_id"] == EXPECTED_CORPUS_ID
