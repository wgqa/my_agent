"""Interleaved v5/v6 HTTP comparison, exactly 16 queries without paid retries.

Adapted from source_reading_v2_20261002. Both variants use the same current
reader, app, policy and prompts. Gold is never sent to the app or provider.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import requests
from dotenv import load_dotenv

HARNESS = Path(__file__).resolve().parent
ARCHIVE = HARNESS.parent
REPO = HARNESS.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def observations(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


@contextmanager
def server(project, arm, output, corpus):
    label = project.name + "-" + arm
    runtime = output / ("runtime-" + label)
    runtime.mkdir()
    shutil.copy2(REPO / "config.yaml", runtime / "config.yaml")
    observation_path = output / (label + "-observations.jsonl")
    environment = dict(os.environ)
    environment.update({
        "SEARCH_SNAPSHOT": str(ARCHIVE / f"snapshots/code_search_{arm}.snapshot"),
        "ENGINEERING_PROJECT_ROOT": str(project), "ENGINEERING_KNOWLEDGE_CORPUS_ROOT": str(corpus),
        "ENGINEERING_CONVERSATION_DB": str(runtime / "conversations.sqlite3"),
        "ASSESSMENT_OBSERVATIONS": str(observation_path), "PYTHONPATH": str(HARNESS) + os.pathsep + str(REPO),
        "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False",
    })
    assert environment.get("DEEPSEEK_API_KEY", "").strip(), "Provider key missing"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (output / (label + "-server.log")).open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "comparison_server:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=runtime, env=environment, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    session = requests.Session()
    session.trust_env = False
    try:
        deadline = time.monotonic() + 60
        while True:
            assert proc.poll() is None, "Comparison server exited; inspect local log"
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


def query(handle, case, arm, streaming, count, output):
    from api.schemas import EngineeringQueryResponse
    session, base, observation_path = handle
    before = len(observations(observation_path))
    started = time.monotonic()
    path = "/engineering/query/stream/v2" if streaming else "/engineering/query"
    emit({"starting": case["id"], "arm": arm, "request": count})
    record = {"id": case["id"], "arm": arm, "project": case["project"], "cohort": case["cohort"], "question": case["question"], "path": path}
    try:
        response = session.post(base + path, json={"question": case["question"]}, stream=streaming, timeout=(5, 120))
        assert response.status_code == 200, f"HTTP {response.status_code}"
        if streaming:
            with response:
                events = [json.loads(line[6:].decode("utf-8")) for line in response.iter_lines() if line.startswith(b"data: ")]
            assert events[-1]["type"] == "done" and not any(e["type"] == "error" for e in events)
            finals = [e["result"] for e in events if e["type"] == "final"]
            assert len(finals) == 1
            payload = finals[0]
            assert "".join(e["delta"] for e in events if e["type"] == "answer_delta") == (payload["answer"] or "")
            record["stream_event_types"] = [e["type"] for e in events]
            record["search_activities"] = [e for e in events if e["type"] == "activity" and e.get("tool_name") == "code_search"]
        else:
            payload = response.json()
        EngineeringQueryResponse.model_validate(payload)
        assert payload["iterations_used"] <= 5 and payload["tool_calls_used"] <= 4 and payload["tool_errors_used"] <= 2
        record.update({"transport_ok": True, "public_response": payload})
    except Exception as exc:
        record.update({"transport_ok": False, "error_type": type(exc).__name__, "detail": str(exc)[:200]})
    record["observations"] = observations(observation_path)[before:]
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    with (output / "live_results.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")
    payload = record.get("public_response", {})
    emit({"finished": case["id"], "arm": arm, "transport_ok": record["transport_ok"], "status": payload.get("status"),
          "tools": payload.get("tool_calls_used"), "seconds": record["elapsed_seconds"],
          "searches": [{"args": o["arguments"], "truncated": (o["result"] or {}).get("truncated")} for o in record["observations"] if o["stage"] == "source_search"],
          "reads": [{k: (o["result"] or {}).get(k) for k in ("path", "start_line", "end_line", "definition")} for o in record["observations"] if o["stage"] == "source_read"]})
    if not record["transport_ok"] or payload.get("failure_code") in {"ACTION_PROVIDER_ERROR", "ACTION_TIMEOUT"}:
        raise RuntimeError("Stop paid matrix after infrastructure/provider failure; no automatic retries")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("smolagents-root", "requests-root", "corpus-root", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Permit the 16 real queries; otherwise only validate inputs")
    args = parser.parse_args()
    catalog = json.loads((ARCHIVE / "catalog.json").read_text(encoding="utf-8"))
    manifest = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
    projects = {"smolagents": args.smolagents_root.resolve(), "requests": args.requests_root.resolve()}
    for name, expected in manifest["artifacts_sha256"].items():
        assert sha(ARCHIVE / name) == expected, f"Frozen input changed: {name}"
    for name, expected in manifest["runtime_file_sha256"].items():
        assert sha(REPO / name) == expected, f"Runtime changed: {name}"
    for alias, project in projects.items():
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip()
        assert actual == manifest["source_pins"][alias], f"Pin mismatch: {alias}"
        # A clean pinned checkout binds all potential search hits, not only gold.
        assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=project, text=True).strip(), f"Dirty source checkout: {alias}"
    for name, expected in manifest["source_file_sha256"].items():
        alias, relative = name.split("/", 1)
        assert sha(projects[alias] / relative) == expected, f"Source changed: {name}"
    assert args.corpus_root.is_dir(), "Verified local corpus must exist"
    assert len(catalog["cases"]) * 2 == catalog["planned_requests"] == catalog["max_live_requests"] == 16
    if not args.live:
        emit({"inputs_validated": True, "provider_calls": 0})
        return
    output = args.output_dir.resolve()
    assert not output.exists(), "Use a fresh output directory; never overwrite results"
    output.mkdir(parents=True)
    load_dotenv(REPO / ".env")
    sys.path.insert(0, str(REPO))
    run_manifest = {"started_utc": datetime.now(timezone.utc).isoformat(), "planned_requests": 16,
                    "input_manifest_sha256": sha(ARCHIVE / "manifest.json"), "independent_formal_acceptance": False}
    (output / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")
    count = 0
    for alias in ("smolagents", "requests"):
        cases = [case for case in catalog["cases"] if case["project"] == alias]
        with server(projects[alias], "v5", output, args.corpus_root.resolve()) as old, server(projects[alias], "v6", output, args.corpus_root.resolve()) as new:
            for index, case in enumerate(cases):
                order = [("v5", old), ("v6", new)] if index % 2 == 0 else [("v6", new), ("v5", old)]
                for arm, handle in order:
                    count += 1
                    assert count <= 16
                    query(handle, case, arm, streaming=index % 2 == 1, count=count, output=output)
    emit({"finished_requests": count, "results_sha256": sha(output / "live_results.jsonl"), "finished_utc": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()
