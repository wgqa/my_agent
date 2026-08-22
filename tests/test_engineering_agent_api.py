"""G11-01 unified Engineering Agent entry vertical tests.

All providers are scripted. These tests exercise the real ToolAgentRuntime,
real bounded tools, the facade, and the FastAPI response contract without a
network call or a benchmark run.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import pytest

import api.app
from core.agent_runtime import Document
from core.engineering_agent import EngineeringAgentFacade
from core.tool_agent import (
    AgentDecisionOutcome,
    FinalAnswerAction,
    ToolCallAction,
    build_tool_agent_runtime,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
client = TestClient(api.app.app)


class FakeRetrievalPort:
    supported_strategies = ("bm25",)

    def __init__(self, docs=()):
        self.docs = tuple(docs)

    def search(self, query, strategy, top_k):
        return self.docs


class ScriptedProvider:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0

    def decide(self, registry, user_query, *, context=()):
        item = self.decisions[min(self.calls, len(self.decisions) - 1)]
        self.calls += 1
        if callable(item):
            return item(registry, user_query, context)
        return item


def _outcome(action):
    return AgentDecisionOutcome(
        action=action,
        failure_code=None,
        call_metadata=None,
    )


def _install(monkeypatch, decisions, *, repo_root=REPO_ROOT, docs=()):
    runtime = build_tool_agent_runtime(
        repo_root=repo_root,
        retrieval_port=FakeRetrievalPort(docs),
        provider=ScriptedProvider(decisions),
    )
    monkeypatch.setattr(api.app, "tool_agent_runtime", runtime)
    monkeypatch.setattr(
        api.app,
        "engineering_agent_facade",
        EngineeringAgentFacade(runtime),
    )
    return runtime


def _post(question, **extra):
    body = {"question": question}
    body.update(extra)
    return client.post("/engineering/query", json=body)


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


def test_knowledge_only_returns_bounded_knowledge_evidence_and_legacy_survives(
    monkeypatch,
):
    docs = (
        Document(
            chunk_id="c1",
            document_id="d1",
            source_name="docs/rrf.md",
            content="RRF combines ranked lists with reciprocal rank scores.",
            score=0.91,
            rank=1,
        ),
        Document(
            chunk_id="c1",
            document_id="d1",
            source_name="docs/rrf.md",
            content="Duplicate chunk must not become duplicate evidence.",
            score=0.8,
            rank=2,
        ),
        Document(
            chunk_id="c2",
            document_id="d1",
            source_name="docs/rrf.md",
            content="A second chunk remains independently useful.",
            score=0.7,
            rank=3,
        ),
    )
    _install(
        monkeypatch,
        [
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="knowledge_search",
                    arguments={"query": "RRF"},
                )
            ),
            _outcome(FinalAnswerAction("final_answer", "RRF uses reciprocal rank.")),
        ],
        docs=docs,
    )

    response = _post("What is RRF?")
    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "engineering_query_response_v1"
    assert data["status"] == "completed"
    assert data["tool_calls_used"] == 1
    assert [item["evidence_id"] for item in data["evidence"]] == ["E1", "E2"]
    assert all(item["kind"] == "knowledge" for item in data["evidence"])
    assert data["evidence"][0]["source_name"] == "docs/rrf.md"
    assert len(data["evidence"][0]["snippet"]) <= 500

    # The historical endpoint keeps its frozen project-evidence contract and
    # does not suddenly expose a new KnowledgeEvidence shape.
    _install(
        monkeypatch,
        [
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="knowledge_search",
                    arguments={"query": "RRF"},
                )
            ),
            _outcome(FinalAnswerAction("final_answer", "legacy answer")),
        ],
        docs=docs,
    )
    legacy = client.post("/tool-agent/query", json={"question": "What is RRF?"})
    assert legacy.status_code == 200
    assert legacy.json()["schema_version"] == "tool_agent_query_response_v1"
    assert legacy.json()["evidence"] == []


def test_repository_only_returns_project_code_evidence(monkeypatch, tmp_path):
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("class Service:\n    pass\n", encoding="utf-8")

    def read_context(_registry, _question, context):
        match = context[-1].observation_result["matches"][0]
        return _outcome(
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={
                    "path": match["path"],
                    "line": match["line"],
                    "context_lines": 1,
                },
            )
        )

    _install(
        monkeypatch,
        [
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="code_search",
                    arguments={"query": "class Service"},
                )
            ),
            read_context,
            _outcome(FinalAnswerAction("final_answer", "src/service.py")),
        ],
        repo_root=tmp_path,
    )

    response = _post("Where is Service implemented?")
    assert response.status_code == 200
    data = response.json()
    assert data["evidence"] == [
        {
            "evidence_id": "E1",
            "kind": "project_code",
            "path": "src/service.py",
            "start_line": 1,
            "end_line": 2,
            "snippet": "class Service:\n    pass",
        }
    ]
    assert str(tmp_path) not in response.text


def test_cross_source_combines_knowledge_and_repository_evidence(monkeypatch, tmp_path):
    source = tmp_path / "core" / "retrieval.py"
    source.parent.mkdir()
    source.write_text("def rrf(scores):\n    return sorted(scores)\n", encoding="utf-8")
    docs = (
        Document(
            chunk_id="rrf-1",
            document_id="knowledge-1",
            source_name="rag/rrf.md",
            content="RRF merges ranked retrieval results.",
            score=0.91,
            rank=1,
        ),
    )

    def read_context(_registry, _question, context):
        match = context[-1].observation_result["matches"][0]
        return _outcome(
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={
                    "path": match["path"],
                    "line": match["line"],
                    "context_lines": 1,
                },
            )
        )

    _install(
        monkeypatch,
        [
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="knowledge_search",
                    arguments={"query": "RRF"},
                )
            ),
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="code_search",
                    arguments={"query": "def rrf"},
                )
            ),
            read_context,
            _outcome(FinalAnswerAction("final_answer", "Theory and implementation align.")),
        ],
        repo_root=tmp_path,
        docs=docs,
    )

    response = _post("How does theory differ from this implementation?")
    assert response.status_code == 200
    data = response.json()
    assert data["iterations_used"] == 4
    assert data["tool_calls_used"] == 3
    assert [item["evidence_id"] for item in data["evidence"]] == ["E1", "E2"]
    assert [item["kind"] for item in data["evidence"]] == [
        "knowledge",
        "project_code",
    ]

    # The legacy view receives the same unified Runtime result, but re-numbers
    # only the project evidence it exposes.
    _install(
        monkeypatch,
        [
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="knowledge_search",
                    arguments={"query": "RRF"},
                )
            ),
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="code_search",
                    arguments={"query": "def rrf"},
                )
            ),
            read_context,
            _outcome(FinalAnswerAction("final_answer", "legacy view")),
        ],
        repo_root=tmp_path,
        docs=docs,
    )
    legacy = client.post(
        "/tool-agent/query",
        json={"question": "How does theory differ from this implementation?"},
    )
    assert legacy.status_code == 200
    legacy_data = legacy.json()
    assert legacy_data["schema_version"] == "tool_agent_query_response_v1"
    assert legacy_data["evidence"] == [
        {
            "evidence_id": "E1",
            "kind": "project_code",
            "path": "core/retrieval.py",
            "start_line": 1,
            "end_line": 2,
            "snippet": "def rrf(scores):\n    return sorted(scores)",
        }
    ]
    assert all(
        key not in legacy_data["evidence"][0]
        for key in ("source_name", "chunk_id", "score", "rank")
    )


def test_change_test_vertical_returns_both_project_evidence(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    source = repo / "src" / "service.py"
    test_file = repo / "tests" / "test_service.py"
    source.parent.mkdir()
    test_file.parent.mkdir()
    source.write_text("return old\n", encoding="utf-8")
    test_file.write_text("def test_service():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")
    source.write_text("return new\n", encoding="utf-8")

    def choose_diff(_registry, _question, context):
        assert context[-1].tool_name == "changed_files"
        return _outcome(
            ToolCallAction(
                action="tool_call",
                tool_name="git_diff",
                arguments={"mode": "working_tree", "path": "src/service.py"},
            )
        )

    def choose_tests(_registry, _question, context):
        assert context[-1].tool_name == "git_diff"
        return _outcome(
            ToolCallAction(
                action="tool_call",
                tool_name="find_tests",
                arguments={"path": "src/service.py"},
            )
        )

    def read_test(_registry, _question, context):
        candidate = context[-1].observation_result["candidates"][0]
        return _outcome(
            ToolCallAction(
                action="tool_call",
                tool_name="read_project_context",
                arguments={
                    "path": candidate["path"],
                    "line": candidate["line"],
                    "context_lines": 1,
                },
            )
        )

    _install(
        monkeypatch,
        [
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="changed_files",
                    arguments={"mode": "working_tree"},
                )
            ),
            choose_diff,
            choose_tests,
            read_test,
            _outcome(FinalAnswerAction("final_answer", "Change has a related test.")),
        ],
        repo_root=repo,
    )

    response = _post("Which test covers the current change?")
    assert response.status_code == 200
    data = response.json()
    assert data["iterations_used"] == 5
    assert data["tool_calls_used"] == 4
    assert [item["kind"] for item in data["evidence"]] == [
        "project_change",
        "project_test",
    ]
    assert [item["evidence_id"] for item in data["evidence"]] == ["E1", "E2"]
    assert all("\\" not in item["path"] for item in data["evidence"])


def test_engineering_request_forbids_runtime_overrides(monkeypatch):
    _install(monkeypatch, [_outcome(FinalAnswerAction("final_answer", "ok"))])
    assert _post("hello", provider="openai").status_code == 422
    assert _post("hello", history=[]).status_code == 422


def test_knowledge_absolute_provenance_fails_closed_without_evidence(monkeypatch):
    docs = (
        Document(
            chunk_id="secret",
            document_id="secret",
            source_name=r"C:\Users\private\secret.md",
            content="do not expose",
            score=1.0,
            rank=1,
        ),
    )
    _install(
        monkeypatch,
        [
            _outcome(
                ToolCallAction(
                    action="tool_call",
                    tool_name="knowledge_search",
                    arguments={"query": "secret"},
                )
            ),
            _outcome(FinalAnswerAction("final_answer", "No safe knowledge evidence.")),
        ],
        docs=docs,
    )

    response = _post("Find the private file")
    assert response.status_code == 200
    assert response.json()["evidence"] == []
    assert "private" not in response.text.lower()
    assert "secret.md" not in response.text


def test_knowledge_evidence_contract_rejects_unsafe_source_identity():
    from api.schemas import KnowledgeEvidence

    for source_name in ("/home/user/private.md", r"C:\Users\private.md", "docs/../private.md"):
        with pytest.raises(ValueError):
            KnowledgeEvidence(
                evidence_id="E1",
                kind="knowledge",
                source_name=source_name,
                chunk_id=None,
                score=1.0,
                rank=1,
                snippet="bounded",
            )
