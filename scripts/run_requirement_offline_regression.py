"""Isolated offline regression for the evidence-requirement migration.

Creates only fresh ignored data/runtime artifacts. Blocks external Python
socket/DNS connections and the active product port 8000. Local event-loop
socket pairs remain usable on Windows. No real model evaluation is run.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
EXTRA_MODULES = (
    "tests/test_arch_integration_10a_decision_recovery.py",
    "tests/test_arch_integration_11a_prompt_composition.py",
    "tests/test_arch_integration_11c_rollback.py",
    "tests/test_arch_integration_13a_kind_aware_recovery.py",
    "tests/test_arch_prod_16c_recovery_rollback.py",
    "tests/test_engineering_current_request.py", "tests/test_engineering_planning.py",
    "tests/test_engineering_project_info.py", "tests/test_g11_02_theory_code.py",
    "tests/test_project_overview.py", "tests/test_product_engineering_24b.py",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL).decode("utf-8").strip()


def source_snapshot():
    paths = set(git("diff", "--name-only", "-z", "HEAD").split("\0"))
    paths.update(git("ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    files = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
             for path in sorted(paths) if path and (ROOT / path).is_file()}
    return {"head_sha": git("rev-parse", "HEAD"), "changed_file_sha256": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", nargs="+", help="Optional repository test modules instead of the full migration regression")
    parser.add_argument("--keyword", help="Optional pytest -k selection for a focused follow-up check")
    args = parser.parse_args()
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    modules = list(dict.fromkeys(args.tests or [*re.findall(r"tests/[^\s]+\.py", ci), *EXTRA_MODULES]))
    for module in modules:
        if re.fullmatch(r"tests/test_[A-Za-z0-9_]+\.py", module) is None or not (ROOT / module).is_file():
            raise ValueError("test modules must be existing files under repository tests/")
    runtime_root = (ROOT / "data/runtime").resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="requirement_offline_", dir=runtime_root)).resolve()
    if not run_root.is_relative_to(runtime_root):
        raise ValueError("unsafe offline artifact directory")
    fixture_root = run_root / "fixtures"
    # pytest recursively removes its basetemp. Use only a fresh absent child,
    # never a configurable/computed pre-existing path or production database.
    if fixture_root.exists() or not fixture_root.resolve().is_relative_to(run_root):
        raise ValueError("unsafe pytest fixture directory")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ.update({
        "DEEPSEEK_API_KEY": "", "OPENCODE_API_KEY": "",
        "ENGINEERING_REQUIREMENT_MODE": "rule",
        "ENGINEERING_EVIDENCE_POLICY": "legacy", "ENGINEERING_FINALIZATION_POLICY": "legacy",
        "ENGINEERING_KNOWLEDGE_MODE": "managed", "ENGINEERING_KNOWLEDGE_CORPUS_ROOT": "",
        "ENGINEERING_CONVERSATION_DB": str(run_root / "isolated_conversations.sqlite3"),
        "ENGINEERING_PROJECT_DB": str(run_root / "isolated_projects.sqlite3"),
        "ENGINEERING_KNOWLEDGE_DB": str(run_root / "isolated_knowledge.sqlite3"),
        "ANONYMIZED_TELEMETRY": "False",
    })
    blocked = []
    def permitted(host, port):
        if port == 8000 or str(port) == "8000":
            return False
        if host is None or host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError):
            return False
    def check(host, port):
        if not permitted(host, port):
            blocked.append(1)
            raise OSError("offline regression blocked a network/production connection")
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    original_resolve = socket.getaddrinfo
    def guarded_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check(address[0], address[1])
        return original_connect(sock, address)
    def guarded_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            check(address[0], address[1])
        return original_connect_ex(sock, address)
    def guarded_resolve(host, port, *rest, **kwargs):
        check(host, port)
        return original_resolve(host, port, *rest, **kwargs)
    socket.socket.connect, socket.socket.connect_ex = guarded_connect, guarded_connect_ex
    socket.getaddrinfo = guarded_resolve
    before = source_snapshot()
    print(f"Offline modules: {len(modules)}; artifacts: {run_root.relative_to(ROOT)}", flush=True)
    import pytest
    try:
        selection = ["-k", args.keyword] if args.keyword else []
        result = int(pytest.main(["-q", *modules, *selection, f"--basetemp={fixture_root}", f"--junitxml={run_root / 'junit.xml'}"]))
    finally:
        socket.socket.connect, socket.socket.connect_ex = original_connect, original_connect_ex
        socket.getaddrinfo = original_resolve
    after = source_snapshot()
    counts = {}
    if (run_root / "junit.xml").is_file():
        suites = list(ET.parse(run_root / "junit.xml").iter("testsuite"))
        counts = {key: sum(int(suite.get(key, 0)) for suite in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
    report = {"schema_version": "requirement_offline_regression_v1", "modules": modules,
              "source_snapshot": before, "source_changed_during_run": before != after,
              "pytest_exit_code": result, "blocked_connection_attempts": len(blocked),
              "counts": counts,
              "guard_scope": "parent Python process; child-process tests use their own existing offline fixtures"}
    (run_root / "execution.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pytest_exit_code": result, "counts": counts,
                      "blocked_connection_attempts": len(blocked), "source_changed_during_run": before != after}))
    return result if result else (2 if blocked or before != after else 0)


if __name__ == "__main__":
    raise SystemExit(main())
