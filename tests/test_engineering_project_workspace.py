"""G6-VERTICAL-01 project root binding and public identity tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.app
from api.project_workspace import resolve_engineering_project


def test_unconfigured_root_uses_default_repo(monkeypatch, tmp_path):
    default_root = tmp_path / "my_agent"
    default_root.mkdir()
    monkeypatch.delenv("ENGINEERING_PROJECT_ROOT", raising=False)

    project = resolve_engineering_project(default_root)

    assert project.root == default_root.resolve()
    assert project.project_name == "my_agent"
    assert project.source == "default_repo"


def test_configured_root_binds_external_repo_and_searches_src(monkeypatch, tmp_path):
    default_root = tmp_path / "my_agent"
    default_root.mkdir()
    external_repo = tmp_path / "demo_project"
    (external_repo / "src").mkdir(parents=True)
    (external_repo / "src" / "service.py").write_text(
        "class PaymentService:\n    pass\n", encoding="utf-8"
    )

    project = resolve_engineering_project(
        default_root, configured_root=str(external_repo)
    )

    from core.tool_agent.tools.code_search import CodeSearchHandler

    matches = CodeSearchHandler(project.root).execute({"query": "PaymentService"})
    assert project.project_name == "demo_project"
    assert project.source == "configured"
    assert matches == {
        "matches": [
            {"path": "src/service.py", "line": 1, "text": "class PaymentService:"}
        ]
    }


@pytest.mark.parametrize("kind", ["missing", "file", "blank"])
def test_invalid_configured_root_fails_without_default_fallback(tmp_path, kind):
    default_root = tmp_path / "my_agent"
    default_root.mkdir()
    invalid_root = tmp_path / "missing"
    if kind == "file":
        invalid_root.write_text("not a directory", encoding="utf-8")
    configured_root = "   " if kind == "blank" else str(invalid_root)

    with pytest.raises(ValueError, match="ENGINEERING_PROJECT_ROOT"):
        resolve_engineering_project(default_root, configured_root=configured_root)


def test_project_api_returns_identity_without_absolute_path(monkeypatch, tmp_path):
    external_repo = tmp_path / "demo_project"
    external_repo.mkdir()
    monkeypatch.setattr(api.app, "engineering_project", None)
    monkeypatch.setenv("ENGINEERING_PROJECT_ROOT", str(external_repo))

    response = TestClient(api.app.app).get("/project")

    assert response.status_code == 200
    assert response.json() == {
        "project_name": "demo_project",
        "source": "configured",
    }
    assert str(external_repo) not in response.text


def test_project_api_invalid_config_is_clear_and_does_not_leak_path(monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setattr(api.app, "engineering_project", None)
    monkeypatch.setenv("ENGINEERING_PROJECT_ROOT", str(missing))

    response = TestClient(api.app.app).get("/project")

    assert response.status_code == 503
    assert response.json()["detail"] == "ENGINEERING_PROJECT_ROOT does not exist"
    assert str(missing) not in response.text


def test_lifespan_injects_configured_root_into_tool_agent(monkeypatch, tmp_path):
    external_repo = tmp_path / "demo_project"
    external_repo.mkdir()
    captured = {}

    class FakePipeline:
        def __init__(self, **_kwargs):
            self.retriever = object()
            self.config = SimpleNamespace(generator_provider="openai")

    def fake_tool_runtime(*, repo_root, **_kwargs):
        captured["repo_root"] = Path(repo_root)
        return object()

    monkeypatch.setenv("ENGINEERING_PROJECT_ROOT", str(external_repo))
    monkeypatch.setattr(api.app, "Pipeline", FakePipeline)
    monkeypatch.setattr(api.app, "PipelineRetrievalAdapter", lambda _retriever: object())
    monkeypatch.setattr(api.app, "build_pipeline_agent_runtime", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(api.app, "build_tool_agent_runtime", fake_tool_runtime)

    with TestClient(api.app.app) as client:
        assert client.get("/project").json() == {
            "project_name": "demo_project",
            "source": "configured",
        }

    assert captured["repo_root"] == external_repo.resolve()


def test_lifespan_rejects_invalid_configured_root(monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setenv("ENGINEERING_PROJECT_ROOT", str(missing))

    with pytest.raises(ValueError, match="ENGINEERING_PROJECT_ROOT does not exist"):
        with TestClient(api.app.app):
            pass
