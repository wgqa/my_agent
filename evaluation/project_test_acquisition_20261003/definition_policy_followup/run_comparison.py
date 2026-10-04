"""Eight predeclared paired queries; one round, alternating order, no paid retries."""

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

ARCHIVE = Path(__file__).resolve().parent
REPO = ARCHIVE.parents[2]


@contextmanager
def server(project, arm, output, corpus):
    label = project.name + "-" + arm
    runtime = output / ("runtime-" + label)
    runtime.mkdir()
    shutil.copy2(REPO / "config.yaml", runtime / "config.yaml")
    observation = output / (label + "-observations.jsonl")
    environment = dict(os.environ)
    environment.update({
        "TEST_ACQUISITION_ARM": arm,
        "ENGINEERING_PROJECT_ROOT": str(project),
        "ENGINEERING_KNOWLEDGE_CORPUS_ROOT": str(corpus),
        "ENGINEERING_CONVERSATION_DB": str(runtime / "conversations.sqlite3"),
        "ASSESSMENT_OBSERVATIONS": str(observation),
        "PYTHONPATH": str(REPO), "PYTHONIOENCODING": "utf-8",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False",
    })
    assert environment.get("DEEPSEEK_API_KEY", "").strip(), "Provider key missing"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (output / (label + "-server.log")).open("w", encoding="utf-8")
    process = subprocess.Popen([
        sys.executable, "-m", "uvicorn",
        "evaluation.project_test_acquisition_20261003.definition_policy_followup.comparison_server:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
    ], cwd=runtime, env=environment, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    session = requests.Session()
    session.trust_env = False
    try:
        deadline = time.monotonic() + 60
        while True:
            assert process.poll() is None, "Server exited; inspect local log"
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
        assert knowledge["verified"] and knowledge["ready"] and knowledge["corpus_id"] == "870e5864df67"
        emit({"server_ready": label, "knowledge": knowledge})
        yield session, base, observation
    finally:
        session.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("smolagents-root", "requests-root", "corpus-root", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads((ARCHIVE / "catalog.json").read_text(encoding="utf-8"))
    for group in ("input_sha256", "production_sha256", "protected_sha256", "helper_sha256", "test_sha256", "prior_archive_sha256"):
        for name, expected in manifest[group].items():
            assert sha(REPO / name) == expected, f"Frozen input changed: {name}"
    projects = {"smolagents": args.smolagents_root.resolve(), "requests": args.requests_root.resolve()}
    for alias, project in projects.items():
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip() == manifest["source_pins"][alias]
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=project, text=True).strip()
    for name, expected in manifest["source_sha256"].items():
        alias, relative = name.split("/", 1)
        assert sha(projects[alias] / relative) == expected
    assert args.corpus_root.is_dir()
    assert len(catalog["cases"]) * 2 == catalog["max_live_requests"] == 16
    if not args.live:
        emit({"inputs_validated": True, "provider_calls": 0})
        return
    output = args.output_dir.resolve()
    assert not output.exists(), "Use a fresh output directory"
    output.mkdir(parents=True)
    load_dotenv(REPO / ".env")
    (output / "run_manifest.json").write_text(json.dumps({
        "started_utc": datetime.now(timezone.utc).isoformat(), "planned_requests": 16,
        "input_manifest_sha256": sha(ARCHIVE / "manifest.json"),
        "independent_formal_acceptance": False,
    }, indent=2) + "\n", encoding="utf-8")
    count = 0
    for alias, project in projects.items():
        cases = [case for case in catalog["cases"] if case["project"] == alias]
        with server(project, "baseline", output, args.corpus_root.resolve()) as old, server(
            project, "candidate", output, args.corpus_root.resolve(),
        ) as new:
            for index, case in enumerate(cases):
                order = [("baseline", old), ("candidate", new)] if index % 2 == 0 else [("candidate", new), ("baseline", old)]
                for arm, handle in order:
                    count += 1
                    assert count <= 16
                    query(handle, case, arm, streaming=catalog["cases"].index(case) % 2 == 1, count=count, output=output)
    emit({"finished_requests": count, "results_sha256": sha(output / "live_results.jsonl"),
          "finished_utc": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()
