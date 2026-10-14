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
TASK020_FP = "e0e5144cef73e6c9f9416ba09f9d91752d25da1343001c7ac542258f1a916282"
TASK019_HEAD = "4658857ce7a4b61dce0bdcea98f72cb9a3e5c0d2"

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
    return {"git": fixtures, "case08_corpus_sha256": corpus_sha,
            "case08_database_sha256": db_sha}


def _check_git_identity() -> dict[str, Any]:
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
    if TASK021_STAGE:
        command.extend(["--budget-run-id", TASK021_BUDGET_ID])
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
    prompt_hashes = {
        "shared_planner_context": _hash_map(TASK019_CHECKOUT, COMMON_PROMPT_FILES),
        "direct_hybrid_decision_prompt_source": _sha256(
            TASK019_CHECKOUT / DECISION_PROMPT_FILE
        ),
    }
    b2_prompt_hashes = {"common": _hash_map(B2_CHECKOUT, COMMON_PROMPT_FILES)}
    if not TASK021_STAGE and prompt_hashes["shared_planner_context"] != b2_prompt_hashes["common"]:
        raise RuntimeError("B2_TASK019_SHARED_PROMPT_SOURCE_DRIFT")
    runtime_hashes = _hash_map(TASK019_CHECKOUT, DIRECT_RUNTIME_IDENTITY_FILES)
    b2_runtime_hashes = _hash_map(B2_CHECKOUT, SHARED_RUNTIME_IDENTITY_FILES)
    eval_hashes = _hash_map(PROJECT_ROOT, EVAL_IDENTITY_FILES)
    for root in (TASK019_CHECKOUT, B2_CHECKOUT):
        if not (root / "core/tool_agent/runtime.py").is_file():
            raise RuntimeError("AGENT_RUNTIME_SOURCE_MISSING")

    api_key, key_source = _load_key_from_existing_env()
    run_path.mkdir(parents=True, exist_ok=False)
    cases_state = [{**item, "status": "NOT_EXECUTED", "criteria": CASE_CRITERIA[item["case_id"]]}
                   for item in PLAN]
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
        "plan": [{**item, "criteria": CASE_CRITERIA[item["case_id"]]} for item in PLAN],
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
    _atomic_json(run_path / "manifest.json", manifest)
    _write_run_state(run_path / "run_state.json", run_id, cases_state, None, None)
    budget_db = (results_root / "task021_shared_budget.sqlite3"
                 if TASK021_STAGE else run_path / "shared_budget.sqlite3")

    # Local import avoids making the product runtime depend on Task 018 tools.
    sys.path.insert(0, str(TASK018_DIR))
    from shared_budget import SharedBudgetGate
    gate = SharedBudgetGate(budget_db, run_id=TASK021_BUDGET_ID if TASK021_STAGE else run_id, max_requests=MAX_REQUESTS,
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
    parser = argparse.ArgumentParser(description="Execute the owner-authorized Task 019 matrix once")
    parser.add_argument("--execute-live", action="store_true",
                        help="required to enter the owner-authorized real Provider path")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--task021-stage", choices=("controls", "candidate"))
    args = parser.parse_args()
    if not args.execute_live:
        raise SystemExit("Live execution is disabled without --execute-live")
    if args.task021_stage:
        configure_task021(args.task021_stage)
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


if __name__ == "__main__":
    main()
