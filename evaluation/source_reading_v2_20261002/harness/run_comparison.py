"""Explicit, interleaved real HTTP/DeepSeek comparison; at most 20 queries.

This runner needs --live and pinned local source repositories. It never installs
or imports the repositories under review. Each invocation records a fresh run.
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
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--smolagents-root", type=Path, required=True)
parser.add_argument("--requests-root", type=Path, required=True)
parser.add_argument("--corpus-root", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--candidate-revision", choices=("round1", "round2", "shipping"), default="shipping")
parser.add_argument("--live", action="store_true", help="Allow the 16 paid API queries; omitted means validate inputs only")
args = parser.parse_args()
RUN = args.output_dir.resolve()
CORPUS = args.corpus_root.resolve()
CATALOG = json.loads((ARCHIVE / "catalog.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
PROJECTS = {"smolagents": args.smolagents_root.resolve(), "requests": args.requests_root.resolve(), "mini": RUN / "mini"}
BASELINE = ARCHIVE / "snapshots/reader_v1.snapshot"
CANDIDATE = ARCHIVE / ("snapshots/reader_" + args.candidate_revision + ".snapshot")
NAVIGATION = ARCHIVE / "snapshots/source_navigation.snapshot"
for path in (BASELINE, CANDIDATE, NAVIGATION):
    name = path.relative_to(ARCHIVE).as_posix()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == MANIFEST["artifacts_sha256"][name], f"Snapshot hash mismatch: {name}"
for name in ("smolagents", "requests"):
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECTS[name], text=True).strip()
    assert actual == MANIFEST["source_pins"][name], f"Pin mismatch: {name}"
for name, expected in MANIFEST["source_file_sha256"].items():
    project, relative = name.split("/", 1)
    if project != "mini":
        assert hashlib.sha256((PROJECTS[project] / relative).read_bytes()).hexdigest() == expected, f"Dirty source file: {name}"
assert CORPUS.is_dir(), "Corpus path must be an existing verified local corpus"
if not args.live:
    print("INPUTS_VALIDATED: zero provider calls; add --live to run the paid matrix")
    raise SystemExit(0)
assert not RUN.exists(), "Use a new output directory; existing runs are never overwritten"
RUN.mkdir(parents=True)
load_dotenv(REPO / ".env")
sys.path.insert(0, str(REPO))
from api.schemas import EngineeringQueryResponse

PROJECTS["mini"].mkdir()
snapshot = json.loads((ARCHIVE / "fixture_snapshot.json").read_text(encoding="utf-8"))
for name, content in snapshot["files"].items():
    target = PROJECTS["mini"] / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

COUNT = 0
ROUND = args.candidate_revision
OUTPUT = RUN / "live_results.jsonl"
assert not OUTPUT.exists()
(RUN / "run_manifest.json").write_text(json.dumps({
    "started_utc": datetime.now(timezone.utc).isoformat(), "candidate_revision": ROUND,
    "planned_requests": CATALOG["planned_requests"], "max_live_requests": CATALOG["max_live_requests"],
    "source_pins": MANIFEST["source_pins"], "catalog_sha256": hashlib.sha256((ARCHIVE / "catalog.json").read_bytes()).hexdigest(),
    "baseline_reader_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
    "candidate_reader_sha256": hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),
    "current_app_sha256": {path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in MANIFEST["protected_files_unchanged"]},
    "historical_app_match": {path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() == expected for path, expected in json.loads((ARCHIVE / "raw/initial_manifest.json").read_text(encoding="utf-8"))["protected_file_sha256"].items()},
    "independent_formal_acceptance": False,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

def observations(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

@contextmanager
def server(alias, arm):
    label = ROUND + "-" + alias + "-" + arm
    runtime = RUN / ("runtime-" + label)
    runtime.mkdir()
    shutil.copy2(REPO / "config.yaml", runtime / "config.yaml")
    obs = RUN / (label + "-observations.jsonl")
    env = dict(os.environ)
    env.update({"READER_ARM": arm, "READER_BASELINE_SNAPSHOT": str(BASELINE),
        "READER_CANDIDATE_SNAPSHOT": str(CANDIDATE), "READER_NAVIGATION_SNAPSHOT": str(NAVIGATION),
        "READER_OBSERVER_SOURCE": str(HARNESS / "passive_observer.py"),
        "ENGINEERING_PROJECT_ROOT": str(PROJECTS[alias]), "ENGINEERING_KNOWLEDGE_CORPUS_ROOT": str(CORPUS),
        "ENGINEERING_CONVERSATION_DB": str(runtime / "conversations.sqlite3"),
        "ASSESSMENT_OBSERVATIONS": str(obs), "PYTHONPATH": str(HARNESS) + os.pathsep + str(REPO),
        "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "ANONYMIZED_TELEMETRY": "False"})
    assert env.get("DEEPSEEK_API_KEY", "").strip()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = (RUN / (label + "-server.log")).open("w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "comparison_server:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    session = requests.Session()
    session.trust_env = False
    try:
        deadline = time.monotonic() + 60
        while True:
            assert proc.poll() is None, "Comparison server exited; inspect its local log"
            try:
                if session.get(base + "/health", timeout=2).status_code == 200: break
            except requests.RequestException: pass
            assert time.monotonic() < deadline, "Comparison startup timeout"
            time.sleep(.5)
        identity = session.get(base + "/project", timeout=5).json()
        knowledge = session.get(base + "/engineering/knowledge", timeout=5).json()
        assert identity["project_name"] == PROJECTS[alias].name
        assert knowledge["verified"] and knowledge["ready"]
        emit({"server_ready": label, "corpus": knowledge["corpus_id"]})
        yield session, base, obs
    finally:
        session.close()
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        log.close()

def query(handle, case, arm, streaming):
    global COUNT
    COUNT += 1
    assert COUNT <= CATALOG["max_live_requests"]
    session, base, log = handle
    before = len(observations(log))
    started = time.monotonic()
    path = "/engineering/query/stream/v2" if streaming else "/engineering/query"
    emit({"starting": case["id"], "arm": arm, "request": COUNT})
    record = {"round": ROUND, "id": case["id"], "arm": arm, "project": case["project"], "cohort": case["cohort"], "question": case["question"], "path": path}
    try:
        response = session.post(base + path, json={"question": case["question"]}, stream=streaming, timeout=(5, 90))
        assert response.status_code == 200, f"HTTP {response.status_code}"
        if streaming:
            events = []
            with response:
                for line in response.iter_lines():
                    if line.startswith(b"data: "): events.append(json.loads(line[6:].decode("utf-8")))
            assert events[-1]["type"] == "done" and not any(e["type"] == "error" for e in events)
            finals = [event["result"] for event in events if event["type"] == "final"]
            assert len(finals) == 1
            payload = finals[0]
            assert "".join(e["delta"] for e in events if e["type"] == "answer_delta") == (payload["answer"] or "")
            record["stream_event_types"] = [e["type"] for e in events]
        else: payload = response.json()
        EngineeringQueryResponse.model_validate(payload)
        assert payload["iterations_used"] <= 5 and payload["tool_calls_used"] <= 4 and payload["tool_errors_used"] <= 2
        record.update({"transport_ok": True, "public_response": payload})
    except Exception as exc:
        record.update({"transport_ok": False, "error_type": type(exc).__name__, "detail": str(exc)[:200]})
    record["observations"] = observations(log)[before:]
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    with OUTPUT.open("a", encoding="utf-8") as file: file.write(json.dumps(record, ensure_ascii=False) + "\n")
    payload = record.get("public_response", {})
    emit({"finished": case["id"], "arm": arm, "transport_ok": record["transport_ok"], "status": payload.get("status"), "tools": payload.get("tool_calls_used"), "reads": [o["result"].get("definition") or {k:o["result"][k] for k in ("path","start_line","end_line")} for o in record["observations"] if o["stage"] == "source_read"]})
    if not record["transport_ok"] or payload.get("failure_code") in {"ACTION_PROVIDER_ERROR", "ACTION_TIMEOUT"}:
        raise RuntimeError("Stop paid comparison after infrastructure/provider failure")

for alias in ("smolagents", "requests", "mini"):
    cases = [case for case in CATALOG["cases"] if case["project"] == alias]
    with server(alias, "v1") as old, server(alias, "v2") as new:
        for index, case in enumerate(cases):
            arms = [("v1", old), ("v2", new)] if index % 2 == 0 else [("v2", new), ("v1", old)]
            for arm, handle in arms: query(handle, case, arm, streaming=index % 2 == 1)

emit({"finished_requests": COUNT, "results_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), "finished_utc": datetime.now(timezone.utc).isoformat()})
