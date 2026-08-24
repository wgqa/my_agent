from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

import scripts.run_g11_05_docs_code_consistency as runner
from core.tool_agent import (
    ENGINEERING_DECISION_PROMPT_V2_PROFILE,
    ENGINEERING_DECISION_PROMPT_V2_SHA256,
    ToolAgentBudget,
    build_readonly_tool_registry,
    max_parse_repairs_for_profile,
)
from core.tool_agent.tools.code_search import CodeSearchHandler
from core.tool_agent.tools.read_project_context import ReadProjectContextHandler


REPO_ROOT = Path(__file__).resolve().parents[1]


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _clone_at(tmp_path: Path, commit: str, name: str) -> Path:
    clone = tmp_path / name
    env = os.environ.copy()
    subprocess.run(
        ["git", "clone", "--quiet", "--no-local", str(REPO_ROOT), str(clone)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    _git(clone, "checkout", "--quiet", commit)
    return clone


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _new_git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, head


VALID_KNOWLEDGE_STATUS = {
    "schema_version": "engineering_knowledge_status_v1",
    "ready": True,
    "verified": True,
    "corpus_id": "870e5864df67",
    "file_count": 37,
    "chunk_count": 215,
    "retrieval_strategy": "bm25",
    "manifest_experiment_id": "dbc497c796d5",
}
VALID_PROJECT_STATUS = {"project_name": "my_agent", "source": "default_repo"}


def test_fixed_case_identity_has_balanced_gold_and_real_source_paths():
    assert [case["case_id"] for case in runner.CASES] == [
        "DOC01",
        "DOC02",
        "DOC03",
        "DOC04",
    ]
    assert runner.validate_gold_label_distribution() == {
        "consistent": 2,
        "outdated_or_incomplete": 2,
    }
    assert runner.validate_case_identities(project_git_root=REPO_ROOT) == runner.CASES
    assert all(case["document_source_paths"] == ["README.md"] for case in runner.CASES)
    assert runner.CASES[0]["code_source_paths"] == [
        "core/tool_agent/default_tools.py",
        "core/tool_agent/integration.py",
    ]
    assert runner.CASES[1]["code_source_paths"] == ["api/app.py"]


def test_clean_isolated_project_checkout_passes_all_dual_checkout_guards(tmp_path: Path):
    evaluator = _clone_at(tmp_path, _head(REPO_ROOT), "evaluator")
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "project")

    evaluator_root, evaluator_commit = runner.validate_evaluator_checkout(
        _head(REPO_ROOT), evaluator_git_root=evaluator
    )
    project_root, project_commit = runner.validate_project_checkout(
        runner.PROJECT_SOURCE_COMMIT, project_git_root=project
    )
    isolated_roots = runner.validate_project_evaluator_isolation(
        evaluator_git_root=evaluator_root,
        project_git_root=project_root,
    )

    assert evaluator_root == evaluator.resolve()
    assert evaluator_commit == _head(REPO_ROOT)
    assert project_commit == runner.PROJECT_SOURCE_COMMIT
    assert isolated_roots == (evaluator_root, project_root)
    assert runner.validate_case_identities(project_git_root=project_root) == runner.CASES
    assert runner.validate_project_source_paths(project_git_root=project_root) == runner.CASES
    assert all(
        not (project_root / Path(relative)).exists()
        for relative in runner.EVALUATOR_OWNED_PATHS
    )


def test_same_evaluator_and_project_root_is_rejected():
    with pytest.raises(ValueError, match="different checkouts"):
        runner.validate_project_evaluator_isolation(
            evaluator_git_root=REPO_ROOT,
            project_git_root=REPO_ROOT,
        )


def test_project_head_must_match_frozen_target(tmp_path: Path):
    wrong_project = _clone_at(tmp_path, _head(REPO_ROOT), "wrong-project")
    with pytest.raises(ValueError, match="project_source_commit"):
        runner.validate_project_checkout(
            runner.PROJECT_SOURCE_COMMIT,
            project_git_root=wrong_project,
        )


def test_project_tracked_dirty_checkout_is_rejected(tmp_path: Path):
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "dirty-project")
    readme = project / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="project_source_commit checkout has tracked modifications"):
        runner.validate_project_checkout(
            runner.PROJECT_SOURCE_COMMIT,
            project_git_root=project,
        )


def test_evaluator_head_must_match_declared_commit(tmp_path: Path):
    wrong_evaluator = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "wrong-evaluator")
    with pytest.raises(ValueError, match="evaluator_commit"):
        runner.validate_evaluator_checkout(
            _head(REPO_ROOT), evaluator_git_root=wrong_evaluator
        )


def test_evaluator_tracked_dirty_checkout_is_rejected(tmp_path: Path):
    evaluator = _clone_at(tmp_path, _head(REPO_ROOT), "dirty-evaluator")
    readme = evaluator / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evaluator_commit checkout has tracked modifications"):
        runner.validate_evaluator_checkout(_head(REPO_ROOT), evaluator_git_root=evaluator)


@pytest.mark.parametrize("relative", runner.EVALUATOR_OWNED_PATHS)
def test_project_evaluator_owned_files_are_rejected(tmp_path: Path, relative: str):
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "contaminated-project")
    owned_file = project / Path(relative)
    owned_file.parent.mkdir(parents=True, exist_ok=True)
    owned_file.write_text("G11-05 DOC01 evaluator metadata\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evaluator-owned file"):
        runner.validate_project_evaluator_isolation(
            evaluator_git_root=REPO_ROOT,
            project_git_root=project,
        )


def test_project_source_validation_uses_project_checkout(tmp_path: Path):
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "source-project")
    (project / "core/tool_agent/runtime_models.py").unlink()
    with pytest.raises(ValueError, match="missing from project checkout"):
        runner.validate_project_source_paths(project_git_root=project)


def test_incidental_doc_case_marker_does_not_trigger_path_guard(tmp_path: Path):
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "incidental-marker")
    readme = project / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "DOC01 is ordinary text\n", encoding="utf-8")
    assert runner.validate_project_evaluator_isolation(
        evaluator_git_root=REPO_ROOT,
        project_git_root=project,
    ) == (REPO_ROOT.resolve(), project.resolve())


def _copied_cases() -> list[dict]:
    return copy.deepcopy(list(runner.CASES))


def _assert_full_case_contract_drift(cases: list[dict]) -> None:
    with pytest.raises(ValueError, match="full case contract"):
        runner.validate_case_contract(tuple(cases))


def test_full_case_contract_sha256_is_frozen_for_all_cases():
    assert runner.validate_case_contract() == runner.EXPECTED_CASE_CONTRACT_SHA256
    assert set(runner.EXPECTED_CASE_CONTRACT_SHA256) == {
        "DOC01",
        "DOC02",
        "DOC03",
        "DOC04",
    }
    assert all(
        len(contract_sha256) == 64
        for contract_sha256 in runner.EXPECTED_CASE_CONTRACT_SHA256.values()
    )


def test_full_case_contract_rejects_question_drift():
    cases = _copied_cases()
    cases[0]["question"] += " "
    _assert_full_case_contract_drift(cases)


def test_full_case_contract_rejects_gold_obligation_drift():
    cases = _copied_cases()
    cases[1]["obligations"][0]["description"] += " "
    _assert_full_case_contract_drift(cases)


def test_full_case_contract_rejects_gold_label_drift():
    cases = _copied_cases()
    cases[2]["gold_label"] = "OUTDATED / INCOMPLETE"
    _assert_full_case_contract_drift(cases)


def test_full_case_contract_rejects_source_path_drift():
    cases = _copied_cases()
    cases[0]["code_source_paths"][0] = "core/tool_agent/integration.py"
    _assert_full_case_contract_drift(cases)


@pytest.mark.parametrize("field", ["required", "forbidden"])
def test_full_case_contract_rejects_tool_contract_drift(field: str):
    cases = _copied_cases()
    cases[0][field] = list(cases[0][field])[:-1]
    _assert_full_case_contract_drift(cases)


def test_fixed_questions_do_not_leak_gold_or_implementation_identity():
    questions = {case["case_id"]: case["question"] for case in runner.CASES}

    assert "七个 Tool" not in questions["DOC01"]
    assert "default_tools.py" not in questions["DOC01"]
    assert "integration.py" not in questions["DOC01"]
    assert "OUTDATED" not in questions["DOC01"]
    assert "INCONSISTENT" not in questions["DOC01"]

    assert "缺少的 Engineering 公开入口" not in questions["DOC02"]
    for leaked_text in (
        "/engineering/query",
        "/engineering/knowledge",
        "/project",
        "api/app.py",
    ):
        assert leaked_text not in questions["DOC02"]

    for leaked_text in (
        "5 iterations",
        "4 tool calls",
        "2 tool errors",
        "runtime_models.py",
        "integration.py",
    ):
        assert leaked_text not in questions["DOC03"]

    for leaked_text in ("api/app.py", "runtime_models.py", "增加四个"):
        assert leaked_text not in questions["DOC04"]


def test_required_and_forbidden_tool_contract_is_frozen():
    assert runner.REQUIRED_TOOLS == ("code_search", "read_project_context")
    assert set(runner.FORBIDDEN_TOOLS) == {
        "knowledge_search",
        "calculator",
        "changed_files",
        "git_diff",
        "find_tests",
    }
    assert not set(runner.REQUIRED_TOOLS) & set(runner.FORBIDDEN_TOOLS)


def test_production_prompt_repair_budget_registry_and_cap_are_frozen(tmp_path: Path):
    assert runner.validate_prompt_identity(
        runner.PRODUCTION_PROMPT_VERSION, runner.PRODUCTION_PROMPT_SHA256
    ) == (runner.PRODUCTION_PROMPT_VERSION, runner.PRODUCTION_PROMPT_SHA256)
    assert ENGINEERING_DECISION_PROMPT_V2_PROFILE.version == (
        runner.PRODUCTION_PROMPT_VERSION
    )
    assert ENGINEERING_DECISION_PROMPT_V2_SHA256 == runner.PRODUCTION_PROMPT_SHA256
    assert runner.validate_repair_prompt_identity(
        runner.REPAIR_PROMPT_VERSION, runner.REPAIR_PROMPT_SHA256
    ) == (runner.REPAIR_PROMPT_VERSION, runner.REPAIR_PROMPT_SHA256)
    assert max_parse_repairs_for_profile(ENGINEERING_DECISION_PROMPT_V2_PROFILE) == 1
    assert runner.BUDGET == {
        "max_agent_iterations": 5,
        "max_tool_calls": 4,
        "max_tool_errors": 2,
    }
    assert runner.REGISTRY_SIZE == 7
    assert runner.MAX_OUTPUT_TOKENS == 1200
    assert runner.PROVIDER_NETWORK_RETRIES == 0
    assert ToolAgentBudget() == ToolAgentBudget(5, 4, 2)

    class RetrievalPort:
        supported_strategies = ("bm25",)

        def search(self, query, strategy, top_k):
            return ()

    assert len(build_readonly_tool_registry(tmp_path, RetrievalPort()).list_specs()) == 7


def test_v3_is_not_accepted_as_production_identity():
    with pytest.raises(ValueError, match="production Engineering v2"):
        runner.validate_prompt_identity(
            "engineering_agent_decision_prompt_v3",
            "0e9554cffcd7240ad394afb24cc60239d583f1f0a7218b2fad0aab09507ff917",
        )


def test_environment_preflight_requires_frozen_knowledge_and_project_identity():
    assert runner.validate_engineering_knowledge_status(VALID_KNOWLEDGE_STATUS) == (
        VALID_KNOWLEDGE_STATUS
    )
    assert runner.validate_engineering_project(VALID_PROJECT_STATUS) == VALID_PROJECT_STATUS

    invalid_knowledge = dict(VALID_KNOWLEDGE_STATUS)
    invalid_knowledge["manifest_experiment_id"] = "wrong"
    with pytest.raises(ValueError, match="Engineering Knowledge status mismatch"):
        runner.validate_engineering_knowledge_status(invalid_knowledge)

    with pytest.raises(ValueError, match="Engineering Project identity mismatch"):
        runner.validate_engineering_project(
            {"project_name": "my_agent", "source": "configured"}
        )


def test_real_tools_can_locate_and_read_document_and_code_sources():
    search = CodeSearchHandler(REPO_ROOT)
    context = ReadProjectContextHandler(REPO_ROOT)

    doc_matches = search.execute({"query": "Safe Trace"})["matches"]
    assert any(match["path"] == "README.md" for match in doc_matches)
    doc_match = next(match for match in doc_matches if match["path"] == "README.md")
    doc_context = context.execute(
        {"path": doc_match["path"], "line": doc_match["line"], "context_lines": 0}
    )
    assert doc_context["path"] == "README.md"
    assert "safe trace" in doc_context["lines"][0]["text"].casefold()

    code_matches = search.execute({"query": "ENGINEERING_TRACE_ALLOWED_KEYS"})[
        "matches"
    ]
    assert any(match["path"] == "api/app.py" for match in code_matches)


def _metric_case(
    sequence: list[str],
    evidence_kinds: list[str],
    *,
    project_doc: bool = False,
    project_code: bool = False,
    pair: bool = False,
    multi_file: bool = False,
    doc_visible: bool = False,
    code_visible: bool = False,
    document_hit: bool = False,
    code_hit: bool = False,
    source_pair: bool = False,
):
    return {
        "status": "completed",
        "tool_sequence": sequence,
        "evidence_kinds": evidence_kinds,
        "iterations": len(sequence) + 1,
        "tool_calls": len(sequence),
        "tool_errors": 0,
        "evidence": [{} for _ in evidence_kinds],
        "provider_calls_total": 1,
        "repair_attempted": False,
        "repair_succeeded": False,
        "failure_code": None,
        "initial_parse_categories": [],
        "project_doc_evidence": project_doc,
        "project_code_evidence": project_code,
        "doc_code_pair": pair,
        "multi_file_evidence": multi_file,
        "doc_claim_visible": doc_visible,
        "code_behavior_visible": code_visible,
        "document_source_hit": document_hit,
        "code_source_hit": code_hit,
        "expected_source_pair": source_pair,
        "source_pair_observed": source_pair,
    }


def test_metrics_count_doc_code_pair_and_keep_gold_diagnostics_non_scoring():
    cases = [
        _metric_case(
            ["code_search", "read_project_context"],
            ["project_doc", "project_code"],
            project_doc=True,
            project_code=True,
            pair=True,
            multi_file=True,
            doc_visible=True,
            code_visible=True,
            document_hit=True,
            code_hit=True,
            source_pair=True,
        ),
        _metric_case(
            ["code_search", "read_project_context"],
            ["project_doc"],
            project_doc=True,
            doc_visible=True,
            document_hit=True,
        ),
        _metric_case(
            ["code_search", "read_project_context"],
            ["project_code"],
            project_code=True,
            code_visible=True,
            code_hit=True,
        ),
        _metric_case(["code_search"], []),
    ]

    metrics = runner._metrics(cases)

    assert metrics["case_count"] == 4
    assert metrics["project_doc_evidence_cases"] == 2
    assert metrics["project_code_evidence_cases"] == 2
    assert metrics["doc_code_pair_cases"] == 1
    assert metrics["doc_code_pair_rate"] == 0.25
    assert metrics["multi_file_evidence_cases"] == 1
    assert metrics["doc_claim_visible_cases"] == 2
    assert metrics["code_behavior_visible_cases"] == 2
    assert metrics["document_source_hit_cases"] == 2
    assert metrics["code_source_hit_cases"] == 2
    assert metrics["expected_source_pair_cases"] == 1
    assert metrics["gold_correctness_auto_scored"] is False
    assert metrics["claim_grounding_auto_scored"] is False


def test_doc_claim_and_code_behavior_visibility_are_structural_only():
    evidence = [
        {
            "kind": "project_doc",
            "path": "README.md",
            "snippet": "Safe Trace does not expose Chain-of-Thought",
        },
        {
            "kind": "project_code",
            "path": "api/app.py",
            "snippet": "ENGINEERING_TRACE_ALLOWED_KEYS = frozenset({\n    'safe'\n})",
        },
    ]
    assert runner.doc_claim_visible(evidence, ["Safe Trace", "Chain-of-Thought"])
    assert runner.code_behavior_visible(evidence)
    assert not runner.doc_claim_visible(
        [{"kind": "project_doc", "path": "README.md", "snippet": "unrelated"}],
        ["Safe Trace"],
    )


def test_normalized_artifact_omits_raw_provider_output_paths_and_keys(tmp_path: Path):
    output = tmp_path / "artifact"
    output.mkdir()
    project_root = tmp_path / "project-root"
    response = {
        "status": "completed",
        "answer": f"repo={REPO_ROOT} key=sk-test-secret-12345",
        "trace": [],
        "evidence": [
            {
                "kind": "project_doc",
                "path": "README.md",
                "snippet": f"repo={REPO_ROOT} sk-test-secret-12345",
            },
        ],
        "provider_raw_output": "must not be copied",
    }
    normalized = runner._normalize_case(
        runner.CASES[0], response, 1.0, REPO_ROOT, project_root
    )
    encoded = json.dumps(normalized, ensure_ascii=False)
    assert "provider_raw_output" not in encoded
    assert "sk-test-secret-12345" not in encoded
    assert str(REPO_ROOT) not in encoded
    (output / "case.json").write_text(encoded, encoding="utf-8")
    runner.validate_artifact_safety(output, REPO_ROOT, project_root)


def test_real_report_manifest_and_markdown_json_fences_pass_safety(tmp_path: Path):
    output = tmp_path / "artifact"
    output.mkdir()
    manifest = {
        "schema_version": "g11_05_docs_code_consistency_manifest_v2",
        "workflow": runner.WORKFLOW_ID,
        "run_id": "g11-05-safety-test",
        "endpoint": "http://127.0.0.1:8765/engineering/query",
        "evaluator_commit": "a" * 40,
        "project_source_commit": runner.PROJECT_SOURCE_COMMIT,
        "prompt_version": runner.PRODUCTION_PROMPT_VERSION,
        "prompt_sha256": runner.PRODUCTION_PROMPT_SHA256,
        "repair_prompt_version": runner.REPAIR_PROMPT_VERSION,
        "repair_prompt_sha256": runner.REPAIR_PROMPT_SHA256,
        "max_output_tokens": runner.MAX_OUTPUT_TOKENS,
        "required_tools": list(runner.REQUIRED_TOOLS),
        "forbidden_tools": list(runner.FORBIDDEN_TOOLS),
        "registry_size": runner.REGISTRY_SIZE,
    }
    cases = [
        {
            "case_id": "DOC01",
            "gold_label": runner.CASES[0]["gold_label"],
            "document_source_paths": ["README.md"],
            "code_source_paths": runner.CASES[0]["code_source_paths"],
            "document_source_hit": True,
            "code_source_hit": True,
            "expected_source_pair": True,
            "doc_claim_visible": True,
            "code_behavior_visible": True,
            "status": "completed",
            "reason_code": None,
            "failure_code": None,
            "provider_calls_total": 1,
            "repair_attempted": False,
            "repair_succeeded": False,
            "tool_sequence": ["code_search", "read_project_context"],
            "evidence_kinds": ["project_doc", "project_code"],
            "multi_file_evidence": True,
            "iterations": 3,
            "tool_calls": 2,
            "tool_errors": 0,
            "gold_obligations": runner.CASES[0]["obligations"],
            "answer": "bounded consistency result",
            "evidence": [
                {
                    "kind": "project_doc",
                    "path": "README.md",
                    "snippet": r"ordinary\literal\backslash",
                },
                {
                    "kind": "project_code",
                    "path": "core/tool_agent/default_tools.py",
                    "snippet": "def build_readonly_tool_registry():\n    return registry",
                },
            ],
        }
    ]
    metrics = runner._metrics(cases)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    runner._write_report(output / "run_report.md", manifest, cases, metrics)
    runner.validate_artifact_safety(output, REPO_ROOT, tmp_path / "project-root")


@pytest.mark.parametrize("root_name", ["evaluator", "project"])
def test_artifact_safety_rejects_each_checkout_absolute_root(
    tmp_path: Path, root_name: str
):
    output = tmp_path / "unsafe-artifact"
    output.mkdir()
    evaluator_root = tmp_path / "evaluator"
    project_root = tmp_path / "project"
    unsafe_root = evaluator_root if root_name == "evaluator" else project_root
    (output / "unsafe.json").write_text(
        json.dumps({"local_root": str(unsafe_root)}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unsafe local path"):
        runner.validate_artifact_safety(output, evaluator_root, project_root)


def test_manifest_records_dual_checkout_provenance_and_case_contract(
    monkeypatch, tmp_path: Path
):
    evaluator = _clone_at(tmp_path, _head(REPO_ROOT), "evaluator")
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "manifest-project")
    monkeypatch.setattr(
        runner,
        "validate_formal_environment",
        lambda query_url, *, knowledge_url=None, project_url=None: (
            VALID_KNOWLEDGE_STATUS,
            VALID_PROJECT_STATUS,
        ),
    )
    monkeypatch.setattr(
        runner,
        "_post_json",
        lambda url, payload: {
            "status": "completed",
            "answer": "bounded test response",
            "trace": [],
            "evidence": [],
            "iterations_used": 1,
            "tool_calls_used": 0,
            "tool_errors_used": 0,
        },
    )

    output = runner.execute_formal_run(
        query_url="http://127.0.0.1:8765/engineering/query",
        output_root=tmp_path / "runs",
        run_id="g11-05-dual-provenance",
        evaluator_commit=_head(REPO_ROOT),
        evaluator_git_root=evaluator,
        project_source_commit=runner.PROJECT_SOURCE_COMMIT,
        project_git_root=project,
        prompt_version=runner.PRODUCTION_PROMPT_VERSION,
        prompt_sha256=runner.PRODUCTION_PROMPT_SHA256,
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in output.iterdir()
        if path.is_file()
    )

    assert manifest["evaluator_commit"] == _head(REPO_ROOT)
    assert manifest["project_source_commit"] == runner.PROJECT_SOURCE_COMMIT
    assert manifest["project_target_isolated"] is True
    assert manifest["project_evaluator_same_root"] is False
    assert manifest["project_evaluator_gold_files_present"] is False
    assert manifest["case_contract_sha256"] == runner.EXPECTED_CASE_CONTRACT_SHA256
    assert str(evaluator.resolve()) not in artifact_text
    assert str(project.resolve()) not in artifact_text


def test_http_infrastructure_failure_does_not_create_agent_artifact(
    monkeypatch, tmp_path: Path
):
    evaluator = _clone_at(tmp_path, _head(REPO_ROOT), "evaluator")
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "infra-project")
    monkeypatch.setattr(
        runner,
        "validate_formal_environment",
        lambda query_url, *, knowledge_url=None, project_url=None: (
            VALID_KNOWLEDGE_STATUS,
            VALID_PROJECT_STATUS,
        ),
    )

    def fail_request(url, payload):
        raise RuntimeError("API returned HTTP 503")

    monkeypatch.setattr(runner, "_post_json", fail_request)
    output_root = tmp_path / "runs"

    with pytest.raises(RuntimeError, match="HTTP 503"):
        runner.execute_formal_run(
            query_url="http://127.0.0.1:8765/engineering/query",
            output_root=output_root,
            run_id="g11-05-infra-failure",
            evaluator_commit=_head(REPO_ROOT),
            evaluator_git_root=evaluator,
            project_source_commit=runner.PROJECT_SOURCE_COMMIT,
            project_git_root=project,
            prompt_version=runner.PRODUCTION_PROMPT_VERSION,
            prompt_sha256=runner.PRODUCTION_PROMPT_SHA256,
        )

    assert not (output_root / "g11-05-infra-failure").exists()


def test_existing_output_run_is_never_overwritten(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "runs"
    existing = output_root / "g11-05-existing"
    existing.mkdir(parents=True)
    (existing / "sentinel.txt").write_text("keep\n", encoding="utf-8")
    evaluator = _clone_at(tmp_path, _head(REPO_ROOT), "evaluator")
    project = _clone_at(tmp_path, runner.PROJECT_SOURCE_COMMIT, "existing-project")
    monkeypatch.setattr(
        runner,
        "validate_formal_environment",
        lambda query_url, *, knowledge_url=None, project_url=None: (
            VALID_KNOWLEDGE_STATUS,
            VALID_PROJECT_STATUS,
        ),
    )

    with pytest.raises(FileExistsError, match="already exists"):
        runner.execute_formal_run(
            query_url="http://127.0.0.1:8765/engineering/query",
            output_root=output_root,
            run_id="g11-05-existing",
            evaluator_commit=_head(REPO_ROOT),
            evaluator_git_root=evaluator,
            project_source_commit=runner.PROJECT_SOURCE_COMMIT,
            project_git_root=project,
            prompt_version=runner.PRODUCTION_PROMPT_VERSION,
            prompt_sha256=runner.PRODUCTION_PROMPT_SHA256,
        )
    assert (existing / "sentinel.txt").read_text(encoding="utf-8") == "keep\n"
