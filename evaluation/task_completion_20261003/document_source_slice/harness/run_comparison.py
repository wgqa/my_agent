"""Frozen document-source diagnostic; 24 queries, no paid retries."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

from dotenv import load_dotenv
import requests

from evaluation.source_search_v6_20261003.harness.run_comparison import emit, query, sha

ARCHIVE = Path(__file__).resolve().parents[1]
REPO = ARCHIVE.parents[2]


@contextmanager
def server(project, arm, output, corpus):
    label = project.name + "-" + arm
    runtime = output / ("runtime-" + label)
    runtime.mkdir()
    shutil.copy2(REPO / "config.yaml", runtime / "config.yaml")
    observation_path = output / (label + "-observations.jsonl")
    environment = dict(os.environ)
    environment.update({
        "DOCUMENT_REQUIREMENT_SNAPSHOT": str(ARCHIVE / f"snapshots/requirements_{arm}.snapshot"),
        "ENGINEERING_PROJECT_ROOT": str(project),
        "ENGINEERING_KNOWLEDGE_CORPUS_ROOT": str(corpus),
        "ENGINEERING_CONVERSATION_DB": str(runtime / "conversations.sqlite3"),
        "ASSESSMENT_OBSERVATIONS": str(observation_path),
        "PYTHONPATH": str(REPO),
        "PYTHONIOENCODING": "utf-8",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False",
    })
    assert environment.get("DEEPSEEK_API_KEY", "").strip(), "Provider key missing"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (output / (label + "-server.log")).open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "evaluation.task_completion_20261003.document_source_slice.harness.comparison_server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=runtime, env=environment, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    session = requests.Session()
    session.trust_env = False
    try:
        deadline = time.monotonic() + 60
        while True:
            assert proc.poll() is None, "Server exited; inspect local log"
            try:
                if session.get(base + "/health", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            assert time.monotonic() < deadline, "Startup timeout"
            time.sleep(.5)
        identity = session.get(base + "/project", timeout=5).json()
        knowledge = session.get(base + "/engineering/knowledge", timeout=5).json()
        assert identity["project_name"] == project.name
        assert knowledge["verified"] and knowledge["ready"]
        emit({"server_ready": label, "knowledge": knowledge})
        yield session, base, observation_path
    finally:
        session.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("smolagents-root", "requests-root", "corpus-root", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads((ARCHIVE / "catalog.json").read_text(encoding="utf-8"))
    for name, expected in manifest["artifacts_sha256"].items():
        assert sha(ARCHIVE / name) == expected, f"Frozen input changed: {name}"
    for name, expected in manifest["runtime_file_sha256"].items():
        assert sha(REPO / name) == expected, f"Runtime changed: {name}"
    for name, expected in manifest["reused_harness_files_sha256"].items():
        assert sha(REPO / name) == expected, f"Historical helper changed: {name}"
    projects = {"smolagents": args.smolagents_root.resolve(), "requests": args.requests_root.resolve()}
    for alias, project in projects.items():
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip() == manifest["source_pins"][alias]
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=project, text=True).strip()
    for name, expected in manifest["source_file_sha256"].items():
        alias, relative = name.split("/", 1)
        assert sha(projects[alias] / relative) == expected, f"Source changed: {name}"
    corpus = args.corpus_root.resolve()
    assert corpus.is_dir()
    assert len(catalog["cases"]) * 2 == catalog["planned_requests"] == catalog["max_live_requests"] == 24
    if not args.live:
        emit({"inputs_validated": True, "provider_calls": 0})
        return
    output = args.output_dir.resolve()
    assert not output.exists(), "Use a fresh output directory; never overwrite results"
    output.mkdir(parents=True)
    load_dotenv(REPO / ".env")
    run_manifest = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "planned_requests": 24,
        "input_manifest_sha256": sha(ARCHIVE / "manifest.json"),
        "independent_formal_acceptance": False,
    }
    (output / "run_manifest.json").write_bytes((json.dumps(run_manifest, indent=2) + "\n").encode())
    count = 0
    for alias in ("smolagents", "requests"):
        cases = [case for case in catalog["cases"] if case["project"] == alias]
        with server(projects[alias], "baseline", output, corpus) as old, server(projects[alias], "candidate", output, corpus) as new:
            for index, case in enumerate(cases):
                order = [("baseline", old), ("candidate", new)] if index % 2 == 0 else [("candidate", new), ("baseline", old)]
                for arm, handle in order:
                    count += 1
                    assert count <= 24
                    query(handle, case, arm, streaming=index % 2 == 1, count=count, output=output)
    emit({"finished_requests": count, "results_sha256": sha(output / "live_results.jsonl"),
          "finished_utc": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()
