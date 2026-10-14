"""Task 019 one-shot serial E2E launcher, reusing Task 018's probe and gate.

This task-scoped entry point refuses existing run IDs and never resumes or
retries a run. All model calls happen in one-case child processes and share a
durable SQLite budget gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ROOT = PROJECT_ROOT.parent
TASK018_DIR = Path(__file__).resolve().parent
PROBE_PATH = TASK018_DIR / "fake_e2e_probe.py"
B2_CHECKOUT = PROJECTS_ROOT / "rag-knowledge-base-b2-exact-de0ca"
B0_CHECKOUT = PROJECTS_ROOT / "rag-knowledge-base-b0"
TASK019_CHECKOUT = PROJECT_ROOT
FIXTURE_ROOT = PROJECTS_ROOT / "_task018_e2e_fixtures"
DEFAULT_RESULTS_ROOT = PROJECTS_ROOT / "_task019_direct_hybrid_live_results"
DEFAULT_RUN_ID = "task019-direct-hybrid-20261014-001"

EXPECTED_B2_HEAD = "de0ca632c4a8a0b67d6f6bb1c2c6eb55d741d131"
EXPECTED_B2_FP = "2101868665a1c8f3732d66517b63bc1142a16968941368854be8ebd96201f028"
EXPECTED_TASK017_IMPLEMENTATION = "8f48ed0e7cf90e6c2f3d707fecf261fdd4fa86ff"
EXPECTED_TASK019_FP = "9e216ddac3be326e13b8f3a1d2998a68344d4c99468e77a70f35912f7c26cce7"
EXPECTED_MODEL = "deepseek-flash"
BASE_URL = "https://api.deepseek.com/v1"
MAX_REQUESTS = 60
MAX_TOKENS = 200_000
MAX_ESTIMATED_USD = 0.15
TASK021_STAGE = None
TASK021_BUDGET_ID = "task021-authorized-20261014-001"
TASK020_HEAD = "0af34f97d3bc0052b99341e00d1741ae2efd41d4"
TASK020_FP = "211987e5d7a38bce9f456258e05bf5bb9b6ac7d1aff61f5de57759fd46bb1889"
TASK019_HEAD = "4658857ce7a4b61dce0bdcea98f72cb9a3e5c0d2"
EXPECTED_B0_HEAD = "f3c9e28aec8b29ccfcad9476ea88871aacbefa06"
EXPECTED_TASK021_HEAD = "5646e2cb919361989cd1b7d0b22644cbe275f44a"
TASK022_BUDGET_ID = "task022-cross-capability-20261014-001"
TASK022_MODE = False

TASK022_GROUPS = {
    **{f"t22_gs_{i:02d}": "git_status" for i in range(1, 5)},
    **{f"t22_ga_{i:02d}": "git_change_analysis" for i in range(1, 5)},
    **{f"t22_src_{i:02d}": "source_location_and_explanation" for i in range(1, 5)},
    **{f"t22_xt_{i:02d}": "cross_file_and_test_analysis" for i in range(1, 5)},
    **{f"t22_rag_{i:02d}": "rag_question_answering" for i in range(1, 5)},
    **{f"t22_mix_{i:02d}": "rag_and_code" for i in range(1, 5)},
    **{f"t22_ev_{i:02d}": "insufficient_evidence_and_refusal" for i in range(1, 5)},
}
TASK022_ORIGINS = {
    "t22_gs_01": "adapted from tool_calls_v2 dev-016/val-008 and Task018 case01",
    "t22_gs_02": "adapted from tool_calls_v2 dev-015 and Task018 case02/case06",
    "t22_gs_03": "adapted from tool_calls_v2 dev-014 and Task018 case03",
    "t22_gs_04": "adapted from Task018 case05 untracked fixture",
    "t22_ga_01": "adapted from Task018/021 case07 importance analysis",
    "t22_ga_02": "adapted from tool_calls_v2 dev-017/dev-018 and Task021 scale analysis",
    "t22_ga_03": "adapted from tool_calls_v2 dev-019 and Task018 commit-range fixture",
    "t22_ga_04": "adapted from tool_calls_v2 dev-029 full multi-material analysis",
    "t22_src_01": "adapted from tool_calls_v2 dev-005/dev-006 and val-003 locator tasks",
    "t22_src_02": "adapted from tool_calls_v2 dev-009/dev-025 and Task021 scale case",
    "t22_src_03": "adapted from tool_calls_v2 dev-010 implementation reading",
    "t22_src_04": "adapted from tool_calls_v2 dev-027 multi-source calculation task",
    "t22_xt_01": "adapted from tool_calls_v2 dev-029/dev-034 source-test cross-checks",
    "t22_xt_02": "adapted from tool_calls_v2 dev-021..dev-024 and val-011/val-012 candidate tests",
    "t22_xt_03": "adapted from tool_calls_v2 dev-029 git status plus diff and Task021 pure rename failure",
    "t22_xt_04": "adapted from tool_calls_v2 dev-026 source-versus-test-body boundary",
    "t22_rag_01": "adapted from integration_v7 v7h001 and existing local document-processing/RAG docs",
    "t22_rag_02": "adapted from integration_v7 v7h003 and existing local advanced-RAG doc",
    "t22_rag_03": "Task022 isolated copy of existing local document-processing knowledge document",
    "t22_rag_04": "Task022 isolated copy of existing local unit-testing knowledge document",
    "t22_mix_01": "local Function Calling document plus Task018 parser source; adapted cross-source task",
    "t22_mix_02": "Task018 retry knowledge fixture plus scale source; negative relationship-inference task",
    "t22_mix_03": "Task022 isolated unit-testing knowledge document plus current Git fixture source",
    "t22_mix_04": "adapted from integration_v7 cross-source provenance tasks and dev-028 doc/source comparison",
    "t22_ev_01": "adapted from tool_calls_v2 dev-037/dev-038 and val-019 missing-material cases",
    "t22_ev_02": "adapted from tool_calls_v2 dev-047/val-023 execution-boundary cases",
    "t22_ev_03": "Task022 negative transfer test against the isolated local knowledge corpus",
    "t22_ev_04": "adapted from tool_calls_v2 dev-044/dev-047/val-022/val-023 boundary questions",
}

# Post-run grading facts only. These values are written to the parent manifest;
# the worker receives only the original user question and project/knowledge data.
TASK022_CRITERIA = {
    "t22_gs_01": {"expected": ["docs/usage.md added", "src/main.py modified", "src/old_parser.py renamed_from", "src/new_parser.py renamed_to", "src/retired_source.py deleted", "tests/test_main.py modified"], "complete": True},
    "t22_gs_02": {"expected": ["src/retired_source.py deleted"], "complete": True},
    "t22_gs_03": {"expected": ["src/old_parser.py -> src/new_parser.py renamed"], "complete": True},
    "t22_gs_04": {"expected": ["notes/local_sample.md untracked"], "complete": True},
    "t22_ga_01": {"expected": ["importance judgment is bounded to actual diff/context", "does not infer feature from pure rename"], "complete": "bounded evidence-based prioritization or an explicit evidence limit"},
    "t22_ga_02": {"expected": ["LIMIT changed 10 -> 12", "scale multiplies by LIMIT"], "complete": True},
    "t22_ga_03": {"expected": ["docs/usage.md added with scale guidance", "src/main.py diff changed LIMIT 10 -> 12", "no unsupported causal rationale"], "complete": True},
    "t22_ga_04": {"expected": ["all six changed paths covered before claiming complete analysis"], "complete": "only if all in-scope material is actually acquired; otherwise useful partial with scope stated"},
    "t22_src_01": {"expected": ["src/main.py", "scale definition at line 3"], "complete": True},
    "t22_src_02": {"expected": ["scale(value) returns value * LIMIT", "LIMIT = 12"], "complete": True},
    "t22_src_03": {"expected": ["strips surrounding whitespace", "converts to lowercase"], "complete": True},
    "t22_src_04": {"expected": ["scale(3) = 3 * 12 = 36"], "complete": True},
    "t22_xt_01": {"expected": ["test asserts scale(2) == 24", "current function with LIMIT 12 gives 24", "does not claim test was run"], "complete": True},
    "t22_xt_02": {"expected": ["tests/test_main.py as candidate if returned", "candidate does not prove execution or coverage"], "complete": "answer scoped to actual candidate observation"},
    "t22_xt_03": {"expected": ["renamed old_parser.py -> new_parser.py", "100% content similarity/no implementation change"], "complete": True},
    "t22_xt_04": {"expected": ["test_scale asserts scale(2) == 24", "no import in file", "source alone does not prove execution"], "complete": True},
    "t22_rag_01": {"expected": ["parser, chunker, embedding versions are corpus/index identity", "fixed evaluation comparison and regression metrics after corpus changes"], "complete": True},
    "t22_rag_02": {"expected": ["evidence support is distinct from world-fact correctness", "verification does not prove semantic entailment or truth"], "complete": True},
    "t22_rag_03": {"expected": ["unchanged hash skip", "changed content updates chunks/index", "missing source marks deletion and cleans index", "chunker version identity"], "complete": True},
    "t22_rag_04": {"expected": ["Mock verifies behavior; Stub supplies fixed data", "line coverage counts executed lines", "branch coverage checks alternatives"], "complete": True},
    "t22_mix_01": {"expected": ["parse strips surrounding whitespace then lowercases", "source read is not an execution result", "Function Calling success requires actual tool execution result"], "complete": True},
    "t22_mix_02": {"expected": ["knowledge standard retry window is 12 seconds", "scale returns value * LIMIT with LIMIT = 12", "equal numbers do not establish a configuration relationship"], "complete": True},
    "t22_mix_03": {"expected": ["test source contains scale(2) == 24 assertion", "unit test intent from knowledge", "no execution evidence means no pass claim"], "complete": True},
    "t22_mix_04": {"expected": ["docs/usage.md says to scale values with scale", "current implementation multiplies by LIMIT", "knowledge provenance metadata is distinct from current project source evidence"], "complete": True},
    "t22_ev_01": {"expected": ["src/missing.py absent; no implementation claim"], "complete": "appropriate refusal or explicit missing-material boundary"},
    "t22_ev_02": {"expected": ["no test-execution tool/result is available; do not fabricate count"], "complete": "appropriate capability-boundary refusal"},
    "t22_ev_03": {"expected": ["12-second statement is a local test fixture, not verified production configuration"], "complete": "must not claim production setting without source"},
    "t22_ev_04": {"expected": ["source status/test code alone cannot establish pytest pass state"], "complete": "appropriate refusal or explicit no-execution boundary"},
}

# Fixed Task 019 order: four paired comparisons and three direct diagnostics.
PLAN = [
    {"task_order": 1, "case_id": "case01", "variant": "b2", "group": "paired"},
    {"task_order": 2, "case_id": "case01", "variant": "direct_hybrid", "group": "paired"},
    {"task_order": 3, "case_id": "case02", "variant": "b2", "group": "paired"},
    {"task_order": 4, "case_id": "case02", "variant": "direct_hybrid", "group": "paired"},
    {"task_order": 5, "case_id": "case03", "variant": "b2", "group": "paired"},
    {"task_order": 6, "case_id": "case03", "variant": "direct_hybrid", "group": "paired"},
    {"task_order": 7, "case_id": "case04", "variant": "b2", "group": "paired"},
    {"task_order": 8, "case_id": "case04", "variant": "direct_hybrid", "group": "paired"},
    {"task_order": 9, "case_id": "case05", "variant": "direct_hybrid", "group": "diagnostic"},
    {"task_order": 10, "case_id": "case07", "variant": "direct_hybrid", "group": "diagnostic"},
    {"task_order": 11, "case_id": "case08", "variant": "direct_hybrid", "group": "diagnostic"},
]

CASE_CRITERIA = {
    "case09": {"intent": "解释 src/main.py 的 scale 函数实现",
               "expected_facts": [["value * LIMIT", "LIMIT = 12"]],
               "semantic_rule": "须读取完整函数正文；不得以定位行或 diff 冒充当前实现"},
    "case10": {"intent": "列出指定 commit range 已删除的源码文件",
               "expected_facts": [["src/retired_source.py", "deleted"]],
               "semantic_rule": "文件事实和实际交付独立评价；旧 Router 阻塞单列"},
    "case01": {"intent": "列出 commit range 内全部变更文件及状态", "expected_facts": [
        ["docs/usage.md", "added"], ["src/main.py", "modified"],
        ["src/old_parser.py", "renamed_from"], ["src/new_parser.py", "renamed_to"],
        ["src/retired_source.py", "deleted"], ["tests/test_main.py", "modified"],
    ], "complete_required": True},
    "case02": {"intent": "只列出 commit range 内 deleted 文件", "expected_facts": [
        ["src/retired_source.py", "deleted"]], "complete_required": True},
    "case03": {"intent": "列出 commit range 内 rename 的旧路径和新路径", "expected_facts": [
        ["src/old_parser.py", "renamed_from"], ["src/new_parser.py", "renamed_to"]],
        "complete_required": True},
    "case04": {"intent": "检查当前 working_tree 的完整可见变更清单", "expected_facts": [],
        "complete_required": True, "empty_must_be_explained": True},
    "case05": {"intent": "只列出当前 working_tree 的 untracked 文件", "expected_facts": [
        ["notes/local_sample.md", "untracked"]], "complete_required": True},
    "case06": {"intent": "列出 commit range 内被删除的源码文件", "expected_facts": [
        ["src/retired_source.py", "deleted"]], "requirement_constraint":
        "保留 Router 产生的 PROJECT_CODE_V1；status_list 不可替代源码正文"},
    "case07": {"intent": "说明 commit range 中最重要的变更及依据", "expected_facts": [],
        "semantic_rule": "重要性不能从 status_list 单独推出；使用可信 diff/context，或说明证据不足"},
    "case08": {"intent": "从本地知识语料回答默认重试窗口", "expected_facts": [
        ["12 秒", "必须有本地检索 Evidence 支持"]], "complete_required": True},
}

COMMON_PROMPT_FILES = [
    "core/query_planning/prompt.py",
    "core/conversation_context/resolver.py",
]
DECISION_PROMPT_FILE = "core/tool_agent/decision_prompt.py"
SHARED_RUNTIME_IDENTITY_FILES = [
    "api/app.py",
    "core/tool_agent/actions.py",
    "core/tool_agent/integration.py",
    "core/tool_agent/default_tools.py",
    "core/tool_agent/decision_prompt.py",
    "core/tool_agent/runtime.py",
    "core/tool_agent/runtime_models.py",
    "core/unified_engineering_runtime.py",
]
DIRECT_RUNTIME_IDENTITY_FILES = [
    *SHARED_RUNTIME_IDENTITY_FILES,
    "core/tool_agent/changed_files_typed_finalization.py",
]
EVAL_IDENTITY_FILES = [
    "evaluation/task018_e2e/fake_e2e_probe.py",
    "evaluation/task018_e2e/shared_budget.py",
    "evaluation/task018_e2e/live_e2e_runner.py",
    "tests/test_task018_e2e_preflight.py",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe_cases() -> dict[str, Any]:
    if str(TASK018_DIR) not in sys.path:
        sys.path.insert(0, str(TASK018_DIR))
    from fake_e2e_probe import CASES
    return CASES


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, check=True,
                            capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip()


def _safe_child_env() -> dict[str, str]:
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC",
               "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
    env = {key: os.environ[key] for key in allowed if os.environ.get(key)}
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("DEEPSEEK_API_KEY", None)
    return env


def _business_fingerprint(checkout: Path) -> dict[str, Any]:
    snippet = (
        "import sys,json;from pathlib import Path;"
        "sys.path.insert(0,str(Path.cwd()));"
        "from evaluation.tool_calls_v2.manifest import business_fingerprint;"
        "x=business_fingerprint();"
        "print(json.dumps({'sha256':x['sha256'],'file_count':len(x['files'])}))"
    )
    result = subprocess.run([sys.executable, "-I", "-c", snippet], cwd=checkout,
                            env=_safe_child_env(), capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def _hash_map(root: Path, names: list[str]) -> dict[str, str]:
    return {name: _sha256(root / name) for name in names}


def _fixture_identity() -> dict[str, Any]:
    expected_heads = {
        "commit_range": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "working_tree_clean": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
        "working_tree_untracked": "d6b6c100d5e2e441957d834a29a73a8bc4ac1693",
    }
    fixtures: dict[str, Any] = {}
    for name, expected_head in expected_heads.items():
        root = FIXTURE_ROOT / name
        head = _git(root, "rev-parse", "HEAD")
        status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
        if head != expected_head:
            raise RuntimeError(f"fixture head drift: {name}")
        expected_status = "?? notes/local_sample.md" if name == "working_tree_untracked" else ""
        if status != expected_status:
            raise RuntimeError(f"fixture worktree drift: {name}")
        fixtures[name] = {"head": head, "status_porcelain": status}
    corpus_file = FIXTURE_ROOT / "case08_corpus" / "task018-rag-fixture.md"
    db_file = FIXTURE_ROOT / "case08_knowledge.sqlite3"
    corpus_sha = _sha256(corpus_file)
    db_sha = _sha256(db_file)
    if corpus_sha != "a2d6e6b86116478e9a6dbdefb8b3bb2b611b69ae736a166b8f05ad8b659cff24":
        raise RuntimeError("case08 corpus identity drift")
    if db_sha != "088ac276dfe81c0f74938450e2315dcc7400a3ebd077458573b3af3d70581dea":
        raise RuntimeError("case08 database identity drift")
    task022_corpus = FIXTURE_ROOT / "task022_knowledge_corpus"
    expected_task022_docs = {
        "agent_FunctionCalling.md": "32d0c9e4ecc8dade3203c34e9432cde4c238ee3e2686d8fb0235f42b76b30d5b",
        "rag_高级RAG.md": "782ee6f325300efd01bc7a420b82a34c2be3dd738ad5a8d1fd073655fd2340b0",
        "rag_文档处理.md": "0215dffb3a7ea64e97a1aa974affb54d9a551c167834a4b2626d7d5ed25869fd",
        "task018_retry.md": "a2d6e6b86116478e9a6dbdefb8b3bb2b611b69ae736a166b8f05ad8b659cff24",
        "unit_单元测试.md": "8c4f3baa5660939656d427e3b478895af1944e9342daeb99e25ebeea4c075141",
    }
    actual_names = sorted(item.name for item in task022_corpus.glob("*.md"))
    if actual_names != sorted(expected_task022_docs):
        raise RuntimeError("Task022 corpus document set drift")
    actual_task022_docs = {name: _sha256(task022_corpus / name) for name in actual_names}
    if actual_task022_docs != expected_task022_docs:
        raise RuntimeError("Task022 corpus source hash drift")
    task022_db_sha = _sha256(FIXTURE_ROOT / "task022_knowledge.sqlite3")
    if task022_db_sha != "5ae658d4d2448eabb90dc8ee263e584cfd9bba4660ce4e2908b83bba50d89e0a":
        raise RuntimeError("Task022 knowledge database identity drift")
    return {"git": fixtures, "case08_corpus_sha256": corpus_sha,
            "case08_database_sha256": db_sha,
            "task022_corpus_files_sha256": actual_task022_docs,
            "task022_database_sha256": task022_db_sha,
            "task022_library_identity_verified": False}


def _check_git_identity() -> dict[str, Any]:
    if TASK022_MODE:
        roots = {
            "b0": (B0_CHECKOUT, EXPECTED_B0_HEAD, "experiment/evidence-ablation-b0"),
            "b2": (B2_CHECKOUT, EXPECTED_B2_HEAD, None),
            "hybrid": (PROJECT_ROOT, None, "experiment/task022-cross-capability"),
        }
        identities = {}
        for variant, (root, expected_head, expected_branch) in roots.items():
            head = _git(root, "rev-parse", "HEAD")
            branch = _git(root, "branch", "--show-current")
            status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
            if status:
                raise RuntimeError(f"Task022 checkout is not clean: {variant}")
            if expected_head is not None and head != expected_head:
                raise RuntimeError(f"Task022 frozen commit mismatch: {variant}")
            if expected_branch is not None and branch != expected_branch:
                raise RuntimeError(f"Task022 branch mismatch: {variant}")
            if variant == "hybrid":
                _git(root, "merge-base", "--is-ancestor", EXPECTED_TASK021_HEAD, "HEAD")
            fingerprint = _business_fingerprint(root)
            identities[variant] = {
                "path": str(root), "head": head, "branch": branch,
                "business_fingerprint": fingerprint, "worktree_clean": True,
            }
        return identities
    if TASK021_STAGE:
        roots = {"direct_hybrid": (PROJECTS_ROOT / "rag-knowledge-base-task019-direct-hybrid",
                                   TASK019_HEAD, EXPECTED_TASK019_FP),
                 "task020": (PROJECTS_ROOT / "rag-knowledge-base-hybrid-task-contract",
                             TASK020_HEAD, TASK020_FP)}
        if TASK021_STAGE == "candidate":
            roots["task021"] = (PROJECT_ROOT, _git(PROJECT_ROOT, "rev-parse", "HEAD"), None)
        identities = {}
        for variant, (root, expected_head, expected_fp) in roots.items():
            head = _git(root, "rev-parse", "HEAD")
            if head != expected_head or _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
                raise RuntimeError(f"Task021 control identity/cleanliness drift: {variant}")
            fingerprint = _business_fingerprint(root)
            if expected_fp is not None and fingerprint["sha256"] != expected_fp:
                raise RuntimeError(f"Task021 control business drift: {variant}")
            if variant == "task021":
                _git(root, "merge-base", "--is-ancestor", TASK020_HEAD, "HEAD")
            identities[variant] = {"path": str(root), "head": head,
                "branch": _git(root, "branch", "--show-current"),
                "business_fingerprint": fingerprint, "worktree_clean": True}
        if _git(PROJECT_ROOT, "status", "--porcelain=v1", "--untracked-files=all"):
            raise RuntimeError("Task021 measurement seam must be committed before live")
        return identities
    b2_head = _git(B2_CHECKOUT, "rev-parse", "HEAD")
    task_head = _git(TASK019_CHECKOUT, "rev-parse", "HEAD")
    if b2_head != EXPECTED_B2_HEAD:
        raise RuntimeError("B2 commit identity mismatch")
    if not _git(TASK019_CHECKOUT, "merge-base", "--is-ancestor", EXPECTED_TASK017_IMPLEMENTATION, "HEAD") == "":
        raise RuntimeError("Task019 is not based on Task017 implementation")
    if _git(TASK019_CHECKOUT, "branch", "--show-current") != "experiment/task019-direct-hybrid":
        raise RuntimeError("Task019 experiment branch mismatch")
    b2_status = _git(B2_CHECKOUT, "status", "--porcelain=v1", "--untracked-files=all")
    if b2_status:
        raise RuntimeError("B2 comparison checkout is not clean")
    task_status = _git(TASK019_CHECKOUT, "status", "--porcelain=v1", "--untracked-files=all")
    if task_status:
        raise RuntimeError("Task019 checkout must be committed and clean before live execution")
    b2_fp = _business_fingerprint(B2_CHECKOUT)
    task_fp = _business_fingerprint(TASK019_CHECKOUT)
    if b2_fp["sha256"] != EXPECTED_B2_FP or task_fp["sha256"] != EXPECTED_TASK019_FP:
        raise RuntimeError("business fingerprint mismatch")
    return {
        "b2": {"path": str(B2_CHECKOUT), "head": b2_head,
               "branch": _git(B2_CHECKOUT, "branch", "--show-current") or "detached",
               "business_fingerprint": b2_fp},
        "task019_direct_hybrid": {"path": str(TASK019_CHECKOUT), "head": task_head,
                    "branch": _git(TASK019_CHECKOUT, "branch", "--show-current"),
                    "task017_implementation_ancestor": EXPECTED_TASK017_IMPLEMENTATION,
                    "business_fingerprint": task_fp,
                    "worktree_clean": True},
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


def _load_key_from_existing_env() -> tuple[str, str]:
    # Read only the named existing key into memory. dotenv_values does not
    # mutate this process environment. The value is passed only to a worker.
    from dotenv import dotenv_values
    env_path = PROJECTS_ROOT / "rag-knowledge-base" / ".env"
    values = dotenv_values(env_path) if env_path.is_file() else {}
    key = values.get("DEEPSEEK_API_KEY")
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError("DEEPSEEK_API_KEY_NOT_AVAILABLE_FROM_EXISTING_ENV_FILE")
    return key, str(env_path)


def _parse_worker_json(stdout: bytes | str) -> dict[str, Any]:
    if isinstance(stdout, bytes):
        marker = re.compile(rb'\{\s*"mode"\s*:')
        matches = list(marker.finditer(stdout))
        for match in reversed(matches):
            try:
                payload = stdout[match.start():].decode("utf-8", errors="strict")
                value, _ = json.JSONDecoder().raw_decode(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and {"mode", "live_mode", "results"}.issubset(value):
                return value
    else:
        marker = re.compile(r'\{\s*"mode"\s*:')
        for match in reversed(list(marker.finditer(stdout))):
            try:
                value, _ = json.JSONDecoder().raw_decode(stdout[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and {"mode", "live_mode", "results"}.issubset(value):
                return value
    raise RuntimeError("WORKER_OUTPUT_RECORD_MISSING")


def _run_child(*, item: dict[str, Any], run_id: str, output_dir: Path,
               budget_db: Path, api_key: str) -> dict[str, Any]:
    checkout = B2_CHECKOUT if item["variant"] == "b2" else TASK019_CHECKOUT
    if TASK022_MODE:
        checkout = {"b0": B0_CHECKOUT, "b2": B2_CHECKOUT,
                    "hybrid": PROJECT_ROOT}[item["variant"]]
    if TASK021_STAGE:
        checkout = {"direct_hybrid": PROJECTS_ROOT / "rag-knowledge-base-task019-direct-hybrid",
                    "task020": PROJECTS_ROOT / "rag-knowledge-base-hybrid-task-contract",
                    "task021": PROJECT_ROOT}[item["variant"]]
    command = [
        sys.executable, "-I", "-X", "utf8", str(PROBE_PATH),
        "--checkout", str(checkout), "--variant", item["variant"],
        "--fixture-root", str(FIXTURE_ROOT), "--cases", item["case_id"],
        "--provider-mode", "live", "--shared-budget-db", str(budget_db),
        "--task-order", str(item["task_order"]), "--run-id", run_id,
        "--diagnostic-log", str(output_dir / "runtime_events.jsonl"),
        "--max-requests", str(MAX_REQUESTS), "--max-tokens", str(MAX_TOKENS),
        "--max-estimated-usd", str(MAX_ESTIMATED_USD),
    ]
    if TASK022_MODE:
        command.extend(["--knowledge-db", "task022_knowledge.sqlite3"])
    if TASK021_STAGE or TASK022_MODE:
        command.extend(["--budget-run-id", run_id if TASK022_MODE else TASK021_BUDGET_ID])
    child_env = _safe_child_env()
    child_env["DEEPSEEK_API_KEY"] = api_key
    try:
        completed = subprocess.run(command, cwd=checkout, env=child_env,
            capture_output=True, timeout=300, check=False)
    except subprocess.TimeoutExpired:
        return {"worker_status": "timeout", "error_category": "WORKER_TIMEOUT_BILLING_UNKNOWN"}
    if completed.returncode != 0:
        # Decode diagnostics tolerantly after byte capture. Redact the one
        # injected credential before retaining a short traceback tail.
        stderr_bytes = completed.stderr or b""
        stderr_text = _redact(stderr_bytes.decode("utf-8", errors="replace"), api_key)
        return {"worker_status": "nonzero_exit", "exit_code": completed.returncode,
                "stderr_sha256": hashlib.sha256(stderr_bytes).hexdigest(),
                "stderr_tail": stderr_text[-8000:]}
    try:
        payload = _parse_worker_json(completed.stdout or b"")
    except Exception as exc:
        stdout_text = _redact((completed.stdout or b"").decode("utf-8", errors="replace"), api_key)
        stderr_text = _redact((completed.stderr or b"").decode("utf-8", errors="replace"), api_key)
        return {"worker_status": "invalid_output", "error_category": type(exc).__name__,
                "stdout_sha256": hashlib.sha256(completed.stdout or b"").hexdigest(),
                "stdout_tail": stdout_text[-8000:], "stderr_tail": stderr_text[-8000:]}
    payload = _redact(payload, api_key)
    serialized = json.dumps(payload, ensure_ascii=False)
    if api_key in serialized:
        return {"worker_status": "secret_redaction_check_failed"}
    if payload.get("mode") != "live" or payload.get("live_mode") is not True:
        return {"worker_status": "unexpected_worker_mode"}
    rows = payload.get("results")
    if not isinstance(rows, list) or len(rows) != 1:
        return {"worker_status": "worker_result_shape_invalid", "payload": payload}
    result = rows[0]
    if result.get("case_id") != item["case_id"] or result.get("variant") != item["variant"]:
        return {"worker_status": "worker_identity_mismatch", "payload": payload}
    return {"worker_status": "ok", "result": result}


def _write_run_state(path: Path, run_id: str, rows: list[dict[str, Any]],
                     gate: dict[str, Any] | None, stop_reason: str | None) -> None:
    _atomic_json(path, {"run_id": run_id, "planned_count": len(rows),
                        "cases": rows, "shared_budget": gate,
                        "stop_reason": stop_reason,
                        "updated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})


def execute(run_id: str, *, results_root: Path = DEFAULT_RESULTS_ROOT) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", run_id):
        raise RuntimeError("INVALID_RUN_ID")
    run_path = results_root / run_id
    if run_path.exists():
        raise RuntimeError("RUN_ID_ALREADY_EXISTS_NO_RESUME_OR_OVERWRITE")

    # Revalidate everything before creating a run record or child process.
    code_identity = _check_git_identity()
    fixture_identity = _fixture_identity()
    probe_cases = _probe_cases() if TASK022_MODE else {}
    if TASK022_MODE:
        if len(TASK022_GROUPS) != 28 or len(PLAN) != 84:
            raise RuntimeError("Task022 fixed matrix shape mismatch")
        planned = [(item["case_id"], item["variant"]) for item in PLAN]
        if len(set(planned)) != 84:
            raise RuntimeError("Task022 plan contains duplicate case/variant rows")
        if any(sum(item["variant"] == variant for item in PLAN) != 28
               for variant in ("b0", "b2", "hybrid")):
            raise RuntimeError("Task022 variant count mismatch")
    prompt_hashes = {
        "shared_planner_context": _hash_map(TASK019_CHECKOUT, COMMON_PROMPT_FILES),
        "direct_hybrid_decision_prompt_source": _sha256(
            TASK019_CHECKOUT / DECISION_PROMPT_FILE
        ),
    }
    b2_prompt_hashes = {"common": _hash_map(B2_CHECKOUT, COMMON_PROMPT_FILES)}
    if not TASK021_STAGE and not TASK022_MODE and prompt_hashes["shared_planner_context"] != b2_prompt_hashes["common"]:
        raise RuntimeError("B2_TASK019_SHARED_PROMPT_SOURCE_DRIFT")
    runtime_hashes = _hash_map(TASK019_CHECKOUT, DIRECT_RUNTIME_IDENTITY_FILES)
    b2_runtime_hashes = _hash_map(B2_CHECKOUT, SHARED_RUNTIME_IDENTITY_FILES)
    eval_hashes = _hash_map(PROJECT_ROOT, EVAL_IDENTITY_FILES)
    roots_to_check = (B0_CHECKOUT, B2_CHECKOUT, TASK019_CHECKOUT) if TASK022_MODE else (TASK019_CHECKOUT, B2_CHECKOUT)
    for root in roots_to_check:
        if not (root / "core/tool_agent/runtime.py").is_file():
            raise RuntimeError("AGENT_RUNTIME_SOURCE_MISSING")

    api_key, key_source = _load_key_from_existing_env()
    run_path.mkdir(parents=True, exist_ok=False)
    cases_state = [
        {**item, "question": probe_cases[item["case_id"]].prompt,
         "category": TASK022_GROUPS[item["case_id"]],
         "status": "NOT_EXECUTED", "criteria": TASK022_CRITERIA[item["case_id"]]}
        if TASK022_MODE else
        {**item, "status": "NOT_EXECUTED", "criteria": CASE_CRITERIA[item["case_id"]]}
        for item in PLAN
    ]
    manifest = {
        "run_id": run_id,
        "authorization": "PROJECT_OWNER_AUTHORIZED_TASK_019_LIVE",
        "mode": "real_provider_e2e",
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "code": code_identity,
        "fixture_root": str(FIXTURE_ROOT),
        "fixtures": fixture_identity,
        "prompt_source_sha256": prompt_hashes,
        "b2_common_prompt_source_sha256": b2_prompt_hashes["common"],
        "b2_decision_prompt_source_sha256": _sha256(
            B2_CHECKOUT / DECISION_PROMPT_FILE
        ),
        "runtime_source_sha256": {"direct_hybrid": runtime_hashes,
                                   "b2": b2_runtime_hashes},
        "evaluation_source_sha256": eval_hashes,
        "model": {"provider": "DeepSeek official API", "request_model": EXPECTED_MODEL,
                  "thinking": "disabled", "temperature": 0,
                  "base_url": BASE_URL, "sdk_max_retries": 0,
                  "price_basis": {"input_cache_miss_peak_usd_per_million": 0.30,
                                  "output_peak_usd_per_million": 1.20,
                                  "cached_input_charged_as_cache_miss_for_estimate": True}},
        "credential_source": {"kind": "existing local .env entry",
                              "path": key_source, "key_name": "DEEPSEEK_API_KEY",
                              "value_recorded": False,
                              "injected_scope": "one worker subprocess at a time"},
        "limits_shared_across_all_cases": {"provider_requests": MAX_REQUESTS,
                                            "tokens": MAX_TOKENS,
                                            "estimated_usd": MAX_ESTIMATED_USD,
                                            "automatic_retries": 0,
                                            "task_retries": 0},
        "plan": ([{**item, "criteria": CASE_CRITERIA[item["case_id"]]} for item in PLAN]
                 if not TASK022_MODE else []),
        "initial_status": "NO_REAL_MODEL_RUN_YET",
        "history_constraint": "Task018 live outcomes are historical context; Task019 run is the direct B2 comparison.",
    }
    if TASK021_STAGE:
        manifest["authorization"] = "PROJECT_OWNER_AUTHORIZED_TASK021_12_AGENT_RUNS"
        manifest["stage"] = TASK021_STAGE
        manifest["budget_run_id"] = TASK021_BUDGET_ID
        manifest["prompt_source_sha256"] = {
            variant: _hash_map(Path(identity["path"]), [*COMMON_PROMPT_FILES, DECISION_PROMPT_FILE])
            for variant, identity in code_identity.items()}
        manifest["runtime_source_sha256"] = {
            variant: _hash_map(Path(identity["path"]), DIRECT_RUNTIME_IDENTITY_FILES)
            for variant, identity in code_identity.items()}
        manifest.pop("b2_common_prompt_source_sha256", None)
        manifest.pop("b2_decision_prompt_source_sha256", None)
        manifest["history_constraint"] = "Task019/020 controls and Task021 candidate share four fixed tasks and fixtures; no historical scores substituted."
    if TASK022_MODE:
        manifest.update({
            "authorization": "PROJECT_OWNER_AUTHORIZED_TASK022_84_AGENT_RUNS",
            "task": "B0_B2_Hybrid_cross_capability_e2e",
            "task021_base_commit": EXPECTED_TASK021_HEAD,
            "budget_run_id": run_id,
            "schedule": "case-major, variants b0 then b2 then hybrid; one attempt per case/variant",
            "prompt_source_sha256": {
                variant: _hash_map(Path(identity["path"]), [*COMMON_PROMPT_FILES, DECISION_PROMPT_FILE])
                for variant, identity in code_identity.items()
            },
            "runtime_source_sha256": {
                "b0": _hash_map(B0_CHECKOUT, SHARED_RUNTIME_IDENTITY_FILES),
                "b2": _hash_map(B2_CHECKOUT, SHARED_RUNTIME_IDENTITY_FILES),
                "hybrid": _hash_map(PROJECT_ROOT, DIRECT_RUNTIME_IDENTITY_FILES),
            },
            "evaluation_source_sha256": eval_hashes,
            "plan": [
                {**item, "category": TASK022_GROUPS[item["case_id"]],
                 "question": probe_cases[item["case_id"]].prompt,
                 "design_origin": TASK022_ORIGINS[item["case_id"]],
                 "criteria": TASK022_CRITERIA[item["case_id"]]}
                for item in PLAN
            ],
            "criteria_use": "post-run semantic grading only; never passed to worker or model input",
            "shared_knowledge_database": "task022_knowledge.sqlite3 for every case and architecture",
            "grading_labels": ["COMPLETE_CORRECT", "USEFUL_PARTIAL", "WRONG_DELIVERY", "NO_DELIVERY"],
            "grading_policy": {
                "completed_is_not_semantic_success": True,
                "rejected_candidate_is_not_delivered": True,
                "unsupported_key_claim_is_wrong_delivery": True,
                "no_answer_is_no_delivery_even_when_refusal_is_appropriate": True,
                "explicit_supported_boundary_answer_may_satisfy_a_conditional_request": True,
                "appropriate_refusal_is_recorded_separately": True,
                "review_kind": "developer non-blind source check, not independent blind review",
            },
            "price_source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "history_constraint": "Task018-021 results informed case design only; the 84 Task022 attempts are new runs and are not pooled with historical scores.",
        })
    _atomic_json(run_path / "manifest.json", manifest)
    _write_run_state(run_path / "run_state.json", run_id, cases_state, None, None)
    budget_db = (results_root / "task021_shared_budget.sqlite3"
                 if TASK021_STAGE else run_path / "shared_budget.sqlite3")

    # Local import avoids making the product runtime depend on Task 018 tools.
    sys.path.insert(0, str(TASK018_DIR))
    from shared_budget import SharedBudgetGate
    budget_identity = TASK021_BUDGET_ID if TASK021_STAGE else run_id
    gate = SharedBudgetGate(budget_db, run_id=budget_identity, max_requests=MAX_REQUESTS,
                            max_tokens=MAX_TOKENS,
                            max_estimated_usd=MAX_ESTIMATED_USD,
                            expected_model=EXPECTED_MODEL)
    _write_run_state(run_path / "run_state.json", run_id, cases_state, gate.snapshot(), None)

    stop_reason = None
    try:
        for idx, item in enumerate(PLAN):
            cases_state[idx]["status"] = "RUNNING"
            _write_run_state(run_path / "run_state.json", run_id, cases_state,
                             gate.snapshot(), stop_reason)
            result = _run_child(item=item, run_id=run_id, output_dir=run_path,
                                budget_db=budget_db, api_key=api_key)
            if result.get("worker_status") == "ok":
                case_result = result["result"]
                attempt_status = case_result.get("infrastructure_status", "unknown")
                cases_state[idx]["status"] = "EXECUTED" if attempt_status == "ok" else "FAILED"
                attempt = {**item, "attempt_status": cases_state[idx]["status"],
                           "result": case_result}
                _append_jsonl(run_path / "attempts.jsonl", attempt)
                if attempt_status != "ok":
                    stop_reason = case_result.get("stop_reason", "AGENT_INFRASTRUCTURE_STOP")
                    gate.stop(stop_reason, billing_unknown="BILLING_UNKNOWN" in stop_reason)
            else:
                cases_state[idx]["status"] = "FAILED"
                stop_reason = result.get("error_category", result.get("worker_status", "WORKER_FAILURE"))
                try:
                    gate.stop(stop_reason, billing_unknown=("BILLING_UNKNOWN" in stop_reason
                                                            or "timeout" in result.get("worker_status", "")))
                except Exception:
                    pass
                _append_jsonl(run_path / "attempts.jsonl", {**item,
                    "attempt_status": "FAILED", "worker": result,
                    "provider_requests_reserved": gate.snapshot().get("requests_reserved")})
            try:
                gate.export_calls_jsonl(run_path / "provider_calls.jsonl")
            except Exception:
                stop_reason = "PROVIDER_RECORD_EXPORT_FAILED"
                try:
                    gate.stop(stop_reason, billing_unknown=True)
                except Exception:
                    pass
            snapshot = gate.snapshot()
            if snapshot["stopped"] or snapshot["billing_unknown"]:
                stop_reason = snapshot["stop_reason"] or "SHARED_BUDGET_STOP"
            if stop_reason:
                break
            _write_run_state(run_path / "run_state.json", run_id, cases_state,
                             snapshot, stop_reason)
        _write_run_state(run_path / "run_state.json", run_id, cases_state,
                         gate.snapshot(), stop_reason)
    except Exception as exc:
        safe_traceback = _redact(traceback.format_exc(), api_key)
        print(safe_traceback, file=sys.stderr, flush=True)
        stop_reason = f"OUTER_RUNNER_FAILURE:{type(exc).__name__}"
        try:
            gate.stop(stop_reason, billing_unknown=gate.snapshot().get("pending_provider_results", 0) > 0)
        except Exception:
            pass
        _write_run_state(run_path / "run_state.json", run_id, cases_state,
                         gate.snapshot(), stop_reason)
    finally:
        # Drop the in-memory key reference; no process environment was changed.
        api_key = ""

    gate.export_calls_jsonl(run_path / "provider_calls.jsonl")
    with sqlite3.connect(budget_db) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    gate_snapshot = gate.snapshot()
    executed = sum(row["status"] == "EXECUTED" for row in cases_state)
    failed = sum(row["status"] == "FAILED" for row in cases_state)
    not_executed = sum(row["status"] == "NOT_EXECUTED" for row in cases_state)
    summary = {
        "run_id": run_id,
        "planned_cases": len(PLAN),
        "executed_cases": executed,
        "failed_attempts": failed,
        "not_executed_cases": not_executed,
        "cases": cases_state,
        "shared_budget": gate_snapshot,
        "stop_reason": stop_reason,
        "provider_requests": gate_snapshot["requests_reserved"],
        "actual_tokens": gate_snapshot["total_tokens"],
        "estimated_usd": gate_snapshot["estimated_usd"],
        "billing_unknown": gate_snapshot["billing_unknown"],
        "completed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _atomic_json(run_path / "summary.json", summary)
    sha_files = ["manifest.json", "run_state.json", "attempts.jsonl",
                 "runtime_events.jsonl", "provider_calls.jsonl", "shared_budget.sqlite3",
                 "summary.json"]
    hashes = {name: _sha256(run_path / name) for name in sha_files
              if (run_path / name).is_file()}
    if TASK021_STAGE:
        # Snapshot billing identity with each immutable phase; the live shared
        # database continues accounting across both phases without resetting.
        with sqlite3.connect(budget_db) as source, sqlite3.connect(run_path / "shared_budget.sqlite3") as target:
            source.backup(target)
        hashes["shared_budget.sqlite3"] = _sha256(run_path / "shared_budget.sqlite3")
    _atomic_json(run_path / "sha256sums.json", hashes)
    return run_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute one fixed, owner-authorized Task 018-family E2E matrix")
    parser.add_argument("--execute-live", action="store_true",
                        help="required to enter the owner-authorized real Provider path")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--task021-stage", choices=("controls", "candidate"))
    parser.add_argument("--task022", action="store_true",
                        help="select the fixed Task 022 B0/B2/Hybrid 28-case matrix")
    args = parser.parse_args()
    if not args.execute_live:
        raise SystemExit("Live execution is disabled without --execute-live")
    if args.task021_stage:
        configure_task021(args.task021_stage)
        if args.results_root == PROJECTS_ROOT / "_task019_direct_hybrid_live_results":
            args.results_root = DEFAULT_RESULTS_ROOT
        if args.run_id == "task019-direct-hybrid-20261014-001":
            args.run_id = DEFAULT_RUN_ID
    if args.task022:
        configure_task022()
        if args.results_root == PROJECTS_ROOT / "_task019_direct_hybrid_live_results":
            args.results_root = DEFAULT_RESULTS_ROOT
        if args.run_id == "task019-direct-hybrid-20261014-001":
            args.run_id = DEFAULT_RUN_ID
    path = execute(args.run_id, results_root=args.results_root)
    print(json.dumps({"run_directory": str(path), "report_status": "RAW_RUN_SAVED",
                      "live_requests": True}, ensure_ascii=False))


def configure_task021(stage: str) -> None:
    """Reuse the fixed serial launcher and its existing gate for two phases."""
    global TASK021_STAGE, PLAN, MAX_REQUESTS, MAX_TOKENS, MAX_ESTIMATED_USD
    global B2_CHECKOUT, TASK019_CHECKOUT, DEFAULT_RESULTS_ROOT, DEFAULT_RUN_ID
    if stage not in {"controls", "candidate"}:
        raise ValueError("Invalid Task021 phase")
    TASK021_STAGE = stage
    MAX_REQUESTS, MAX_TOKENS, MAX_ESTIMATED_USD = 84, 400_000, 0.25
    B2_CHECKOUT = PROJECTS_ROOT / "rag-knowledge-base-task019-direct-hybrid"
    TASK019_CHECKOUT = (PROJECTS_ROOT / "rag-knowledge-base-hybrid-task-contract"
                        if stage == "controls" else PROJECT_ROOT)
    DEFAULT_RESULTS_ROOT = PROJECTS_ROOT / "_task021_hybrid_live_results"
    DEFAULT_RUN_ID = f"task021-{stage}-20261014-001"
    variants = ("direct_hybrid", "task020") if stage == "controls" else ("task021",)
    PLAN = [{"task_order": (1 if stage == "controls" else 9) + index,
             "case_id": case_id, "variant": variant, "group": "four_task_comparison"}
            for index, (case_id, variant) in enumerate(
                (case_id, variant) for case_id in ("case10", "case09", "case07", "case08") for variant in variants)]


def configure_task022() -> None:
    """Select the one-shot, fixed Task 022 schedule on the existing launcher."""
    global TASK022_MODE, PLAN, MAX_REQUESTS, MAX_TOKENS, MAX_ESTIMATED_USD
    global B0_CHECKOUT, B2_CHECKOUT, TASK019_CHECKOUT, DEFAULT_RESULTS_ROOT, DEFAULT_RUN_ID
    TASK022_MODE = True
    MAX_REQUESTS, MAX_TOKENS, MAX_ESTIMATED_USD = 300, 2_000_000, 1.0
    B0_CHECKOUT = PROJECTS_ROOT / "rag-knowledge-base-b0"
    B2_CHECKOUT = PROJECTS_ROOT / "rag-knowledge-base-b2-exact-de0ca"
    TASK019_CHECKOUT = PROJECT_ROOT
    DEFAULT_RESULTS_ROOT = PROJECTS_ROOT / "_task022_cross_capability_results"
    DEFAULT_RUN_ID = "task022-cross-capability-20261014-001"
    variants = ("b0", "b2", "hybrid")
    PLAN = [
        {"task_order": order, "case_id": case_id, "variant": variant,
         "group": TASK022_GROUPS[case_id]}
        for order, (case_id, variant) in enumerate(
            ((case_id, variant) for case_id in TASK022_GROUPS for variant in variants), start=1
        )
    ]


if __name__ == "__main__":
    main()
