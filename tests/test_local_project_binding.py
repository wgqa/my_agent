"""Local conversation/project binding through real tools, with zero providers."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.app as backend
from api.conversation_store import ConversationStore, project_key_for_root
from api.project_registry import ProjectRegistry, ProjectRuntimeCache
from api.project_workspace import EngineeringProject
from core.engineering_agent import EngineeringAgentFacade
from core.engineering_context import EngineeringContextResolver
from core.conversation_context import ConversationQueryResolution
from core.knowledge_library import KnowledgeLibrary
from core.tool_agent import AgentDecisionOutcome, FinalAnswerAction, ToolCallAction, build_tool_agent_runtime
from tests._engineering_runtime_support import build_full_unified_runtime


class FileReaderProvider:
    def decide(self, _registry, _question, *, context=()):
        observation = next((item for item in reversed(context)
                            if getattr(item, "tool_name", None) == "read_project_context"), None)
        if observation is None:
            action = ToolCallAction(action="tool_call", tool_name="read_project_context",
                                    arguments={"path": "config.py", "line": 1, "context_lines": 1})
        else:
            action = FinalAnswerAction("final_answer", f"配置为 {observation.observation_result['lines'][0]['text']} [E1]")
        return AgentDecisionOutcome(action=action, failure_code=None, call_metadata=None)


def build_project_facade(project, port):
    class QueryResolver:
        def resolve(self, _history, user_input):
            return ConversationQueryResolution(user_input, True, False)
    runtime = build_tool_agent_runtime(repo_root=project.root, retrieval_port=port, provider=FileReaderProvider())
    return EngineeringAgentFacade(build_full_unified_runtime(runtime, retrieval_port=port,
                                  context_resolver=EngineeringContextResolver(QueryResolver())))


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    first_root, second_root = tmp_path / "甲 项目", tmp_path / "乙 项目"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "config.py").write_text("MARKER = 'alphaprojectmarker'\n", encoding="utf-8")
    (second_root / "config.py").write_text("MARKER = 'betaprojectmarker'\n", encoding="utf-8")
    first = EngineeringProject(first_root.resolve(), first_root.name, "default_repo")
    registry = ProjectRegistry(tmp_path / "projects.sqlite3")
    record = registry.register(first)
    store = ConversationStore(tmp_path / "conversations.sqlite3")
    library = KnowledgeLibrary(tmp_path / "knowledge.sqlite3")
    builds = []
    def factory(project):
        builds.append(project.root)
        return build_project_facade(project, library.retrieval_port)
    cache = ProjectRuntimeCache(factory)
    default_facade = factory(first)
    cache.seed(record.id, default_facade)
    monkeypatch.setattr(backend, "engineering_project", first)
    monkeypatch.setattr(backend, "engineering_agent_facade", default_facade)
    monkeypatch.setattr(backend, "project_registry", registry)
    monkeypatch.setattr(backend, "project_runtime_cache", cache)
    monkeypatch.setattr(backend, "conversation_store", store)
    monkeypatch.setattr(backend, "engineering_knowledge_backend", library)
    return SimpleNamespace(client=TestClient(backend.app), registry=registry, cache=cache, store=store,
                           first=record, second_root=second_root, builds=builds, library=library)


def add_second(mounted):
    response = mounted.client.post("/engineering/projects", json={"path": str(mounted.second_root)})
    assert response.status_code == 200
    return response.json()


def create(mounted, project_id):
    response = mounted.client.post("/engineering/conversations", json={"project_id": project_id})
    assert response.status_code == 201
    assert response.json()["project_id"] == project_id
    return response.json()


def stream(mounted, conversation, version="v1"):
    response = mounted.client.post(
        f"/engineering/conversations/{conversation['id']}/messages/stream/{version}",
        params={"project_id": conversation["project_id"]},
        json={"message": "请读取 config.py 文件中的配置，用源码引用回答。"},
    )
    assert response.status_code == 200
    assert response.headers["x-engineering-stream-schema"] == f"engineering_query_stream_{version}"
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "done"
    return next(event["result"] for event in events if event["type"] == "final")


def test_registration_is_idempotent_persistent_and_does_not_expose_paths(mounted):
    first = add_second(mounted)
    second = add_second(mounted)
    assert first["id"] == second["id"]
    assert first["project_name"] == mounted.second_root.name
    assert str(mounted.second_root) not in json.dumps(first, ensure_ascii=False)
    assert "project_key" not in first
    assert ProjectRegistry(mounted.registry.path).get(first["id"]).project.root == mounted.second_root.resolve()
    projects = mounted.client.get("/engineering/projects").json()["projects"]
    assert len(projects) == 2
    assert next(item for item in projects if item["id"] == mounted.first.id)["is_default"] is True
    assert len(mounted.builds) == 1  # Registration does not initialize providers.


@pytest.mark.parametrize("path", ["", " ", "relative/project", "https://github.com/example/project", "missing", "file"])
def test_invalid_roots_cannot_fall_back_to_default_or_register(mounted, tmp_path, path):
    if path == "missing":
        path = str(tmp_path / "not-there")
    elif path == "file":
        path = str(mounted.first.project.root / "config.py")
    response = mounted.client.post("/engineering/projects", json={"path": path})
    assert response.status_code in (400, 422)
    assert len(mounted.registry.list_projects()) == 1
    assert len(mounted.builds) == 1


@pytest.mark.parametrize("stream_version", ["v1", "v2"])
def test_two_bound_conversations_read_their_own_files_without_restart(mounted, stream_version):
    second = add_second(mounted)
    first_conversation = create(mounted, mounted.first.id)
    second_conversation = create(mounted, second["id"])
    for conversation, expected, absent in (
        (first_conversation, "alphaprojectmarker", "betaprojectmarker"),
        (second_conversation, "betaprojectmarker", "alphaprojectmarker"),
        (first_conversation, "alphaprojectmarker", "betaprojectmarker"),
    ):
        result = stream(mounted, conversation, stream_version)
        assert result["status"] == "completed"
        assert expected in result["evidence"][0]["snippet"]
        assert absent not in json.dumps(result)
    assert len(mounted.builds) == 2
    assert backend.engineering_project.root == mounted.first.project.root
    all_conversations = mounted.client.get("/engineering/conversations?scope=all").json()["conversations"]
    assert {item["project_id"] for item in all_conversations} == {mounted.first.id, second["id"]}
    assert str(mounted.second_root) not in json.dumps(all_conversations, ensure_ascii=False)
    assert [item["id"] for item in mounted.client.get("/engineering/conversations").json()["conversations"]] == [first_conversation["id"]]
    detail = mounted.client.get(f"/engineering/conversations/{first_conversation['id']}", params={"project_id": mounted.first.id}).json()
    assert len(detail["messages"]) == 4


@pytest.mark.parametrize("stream_version", ["v1", "v2"])
def test_wrong_project_and_client_rebinding_are_rejected_before_runtime(mounted, stream_version):
    second = add_second(mounted)
    conversation = create(mounted, mounted.first.id)
    url = f"/engineering/conversations/{conversation['id']}"
    wrong = {"project_id": second["id"]}
    assert mounted.client.get(url, params=wrong).status_code == 404
    assert mounted.client.delete(url, params=wrong).status_code == 404
    assert mounted.client.post(url + f"/messages/stream/{stream_version}", params=wrong, json={"message": "read config.py"}).status_code == 404
    assert len(mounted.builds) == 1
    assert mounted.client.post("/engineering/conversations", json={"project_id": "unknown"}).status_code == 404
    assert mounted.client.post("/engineering/conversations", json={"project_id": mounted.first.id, "root": str(mounted.second_root)}).status_code == 422
    assert mounted.client.post(url + f"/messages/stream/{stream_version}", json={"message": "read config.py", "project_id": second["id"]}).status_code == 422


@pytest.mark.parametrize("stream_version", ["v1", "v2"])
def test_removed_project_keeps_history_but_cannot_run_or_create(mounted, stream_version):
    second = add_second(mounted)
    conversation = create(mounted, second["id"])
    (mounted.second_root / "config.py").unlink()
    mounted.second_root.rmdir()
    assert mounted.client.get(f"/engineering/conversations/{conversation['id']}", params={"project_id": second["id"]}).status_code == 200
    assert mounted.client.post("/engineering/conversations", json={"project_id": second["id"]}).status_code == 409
    response = mounted.client.post(f"/engineering/conversations/{conversation['id']}/messages/stream/{stream_version}", params={"project_id": second["id"]}, json={"message": "read config.py"})
    assert response.status_code == 409
    assert len(mounted.builds) == 1
    assert not next(item for item in mounted.client.get("/engineering/projects").json()["projects"] if item["id"] == second["id"])["available"]


def test_restart_restores_bindings_and_unknown_roots_stay_out_of_all_view(mounted, monkeypatch):
    second = add_second(mounted)
    conversation = create(mounted, second["id"])
    mounted.store.create_conversation(project_key="unregistered-root", project_name="hidden", project_source="configured")
    monkeypatch.setattr(backend, "project_registry", ProjectRegistry(mounted.registry.path))
    monkeypatch.setattr(backend, "conversation_store", ConversationStore(mounted.store.path))
    detail = mounted.client.get(f"/engineering/conversations/{conversation['id']}", params={"project_id": second["id"]})
    assert detail.json()["project_id"] == second["id"]
    assert [item["id"] for item in mounted.client.get("/engineering/conversations?scope=all").json()["conversations"]] == [conversation["id"]]


def test_same_named_projects_and_default_change_keep_explicit_binding(mounted, tmp_path, monkeypatch):
    another_root = tmp_path / "other" / mounted.first.project.project_name
    another_root.mkdir(parents=True)
    second = mounted.client.post("/engineering/projects", json={"path": str(another_root)}).json()
    assert second["id"] != mounted.first.id
    conversation = create(mounted, mounted.first.id)
    monkeypatch.setattr(backend, "engineering_project", mounted.registry.get(second["id"]).project)
    assert mounted.client.get(f"/engineering/conversations/{conversation['id']}").status_code == 404
    assert mounted.client.get(f"/engineering/conversations/{conversation['id']}", params={"project_id": mounted.first.id}).status_code == 200
    assert stream(mounted, conversation)["status"] == "completed"


def test_cache_reuses_concurrent_build_and_eviction_preserves_inflight_reference(mounted):
    second = mounted.registry.add_local(str(mounted.second_root))
    calls = []
    def factory(project):
        calls.append(project.root)
        return object()
    cache = ProjectRuntimeCache(factory, max_entries=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        facades = list(pool.map(lambda _: cache.get(mounted.first), range(8)))
    assert len(calls) == 1
    assert all(facade is facades[0] for facade in facades)
    retained = facades[0]
    cache.get(second)
    assert retained is not cache.get(mounted.first)
    assert len(calls) == 3


def test_other_project_creation_cannot_rebind_an_inflight_turn(mounted, monkeypatch):
    second = add_second(mounted)
    first_conversation = create(mounted, mounted.first.id)
    entered, proceed = threading.Event(), threading.Event()
    real_facade = mounted.cache.get(mounted.first)
    class BlockingFacade:
        def run(self, question, **kwargs):
            entered.set()
            assert proceed.wait(timeout=5)
            return real_facade.run(question, **kwargs)
    mounted.cache.seed(mounted.first.id, BlockingFacade())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(stream, mounted, first_conversation)
        assert entered.wait(timeout=5)
        try:
            create(mounted, second["id"])
            mounted.client.get("/engineering/conversations?scope=all")
        finally:
            proceed.set()
        result = future.result(timeout=10)
    assert "alphaprojectmarker" in result["evidence"][0]["snippet"]
    assert "betaprojectmarker" not in json.dumps(result)


def test_real_product_assembler_uses_registered_root_and_shared_library(mounted, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-project-test-key")
    roots, ports = [], []
    def capture(**kwargs):
        roots.append(kwargs["repo_root"])
        ports.append(kwargs["retrieval_port"])
        return build_tool_agent_runtime(**{**kwargs, "provider": FileReaderProvider()})
    monkeypatch.setattr(backend, "build_tool_agent_runtime", capture)
    binding = backend._build_engineering_project_runtime(mounted.registry.add_local(str(mounted.second_root)).project)
    assert roots == [mounted.second_root.resolve()]
    assert ports == [mounted.library.retrieval_port]
    assert isinstance(binding.facade, EngineeringAgentFacade)


def test_failed_project_assembly_never_falls_back_or_saves_a_partial_turn(mounted, monkeypatch):
    second = add_second(mounted)
    conversation = create(mounted, second["id"])
    calls = []
    def fail(project):
        calls.append(project.root)
        raise RuntimeError("simulated project assembly failure")
    cache = ProjectRuntimeCache(fail)
    cache.seed(mounted.first.id, backend.engineering_agent_facade)
    monkeypatch.setattr(backend, "project_runtime_cache", cache)
    url = f"/engineering/conversations/{conversation['id']}"
    response = mounted.client.post(url + "/messages/stream/v1", params={"project_id": second["id"]}, json={"message": "read config.py"})
    assert response.status_code == 503
    assert calls == [mounted.second_root.resolve()]
    assert mounted.client.get(url, params={"project_id": second["id"]}).json()["messages"] == []
    assert cache.get(mounted.first) is backend.engineering_agent_facade
