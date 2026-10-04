"""One declared round per phase, no paid task retries or changed questions."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv
from evaluation.core_workflows_20261004.run import REPO, REQUESTS_PIN, git, server
from evaluation.source_search_v6_20261003.harness.run_comparison import emit, observations, query, sha

ARCHIVE = Path(__file__).resolve().parent


def conversation_query(handle, case, count, output):
    """Exercise the homepage's actual first-turn conversation endpoint."""
    from api.schemas import EngineeringQueryResponse
    session, base, observation_path = handle
    created = session.post(base+"/engineering/conversations", timeout=5)
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    path = f"/engineering/conversations/{conversation_id}/messages/stream/v1"
    before = len(observations(observation_path))
    started = time.monotonic()
    emit({"starting": case["id"], "arm": "entry-confirmation", "request": count})
    record = {"id": case["id"], "arm": "entry-confirmation", "project": case["project"],
        "cohort": case["cohort"], "question": case["question"], "path": path}
    try:
        with session.post(base+path, json={"message": case["question"]}, stream=True, timeout=(5,120)) as response:
            assert response.status_code == 200
            events = [json.loads(line[6:].decode("utf-8")) for line in response.iter_lines() if line.startswith(b"data: ")]
        assert events[-1]["type"] == "done" and not any(event["type"]=="error" for event in events)
        finals = [event["result"] for event in events if event["type"]=="final"]
        assert len(finals)==1
        payload = finals[0]
        EngineeringQueryResponse.model_validate(payload)
        assert "".join(event["delta"] for event in events if event["type"]=="answer_delta") == (payload["answer"] or "")
        assert payload["iterations_used"]<=5 and payload["tool_calls_used"]<=4 and payload["tool_errors_used"]<=2
        detail = session.get(base+f"/engineering/conversations/{conversation_id}",timeout=5).json()
        assert [message["role"] for message in detail["messages"]] == ["user","assistant"]
        assert detail["messages"][0]["content"] == case["question"]
        assert detail["messages"][1]["result"] == payload
        record.update(transport_ok=True, public_response=payload, persistence_ok=True,
            stream_event_types=[event["type"] for event in events])
    except Exception as exc:
        record.update(transport_ok=False,error_type=type(exc).__name__,detail=str(exc)[:200])
    record["observations"] = observations(observation_path)[before:]
    record["elapsed_seconds"] = round(time.monotonic()-started,3)
    with (output/"live_results.jsonl").open("a",encoding="utf-8") as file:
        file.write(json.dumps(record,ensure_ascii=False)+"\n")
    payload = record.get("public_response",{})
    emit({"finished":case["id"],"status":payload.get("status"),"transport_ok":record["transport_ok"],"persistence_ok":record.get("persistence_ok")})
    if not record["transport_ok"] or payload.get("failure_code") in {"ACTION_PROVIDER_ERROR","ACTION_TIMEOUT"}:
        raise RuntimeError("Stop after failure; no automatic paid task retry")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["development", "confirmation", "entry_confirmation", "change_entry_confirmation"], required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    catalog = json.loads((ARCHIVE/"catalog.json").read_text(encoding="utf-8"))
    cases = [case for case in catalog["cases"] if case["phase"] == args.phase]
    assert len(cases) == catalog["phase_limits"][args.phase] <= 8
    projects = {"fixture": args.workspace/"support-search", "requests": args.workspace/"requests"}
    assert git(projects["requests"], "rev-parse", "HEAD") == REQUESTS_PIN
    if not args.live:
        emit({"phase": args.phase, "requests": len(cases), "provider_calls": 0})
        return
    assert args.output_dir is not None and args.corpus_root is not None
    output = args.output_dir.resolve()
    assert not output.exists(), "Never overwrite results"
    output.mkdir(parents=True)
    load_dotenv(REPO/".env")
    os.environ["CORE_WORKFLOW_OBJECT_READER"] = "1" if args.phase == "development" else "0"
    inputs = [path for directory in ("api", "core", "ui") for path in (REPO/directory).rglob("*.py")]
    inputs += list(ARCHIVE.glob("*.py"))+[ARCHIVE/"catalog.json", REPO/"config.yaml",
        ARCHIVE.parent/"run.py", ARCHIVE.parent/"observe_server.py",
        REPO/"evaluation/source_search_v6_20261003/harness/run_comparison.py",
        REPO/"evaluation/source_search_v6_20261003/harness/passive_observer.py"]
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(), "phase": args.phase,
        "planned_requests": len(cases), "paid_task_retries": 0,
        "object_reader_override": args.phase == "development", "independent_acceptance": False,
        "code_head": git(REPO, "rev-parse", "HEAD"),
        "input_sha256": {str(path.relative_to(REPO)).replace("\\", "/"): sha(path) for path in sorted(inputs)},
        "projects": {alias: {"head": git(project, "rev-parse", "HEAD"), "status": git(project, "status", "--porcelain"),
            "source_sha256": {str(path.relative_to(project)).replace("\\", "/"): sha(path) for directory in ("support_search", "src", "tests", "docs") if (project/directory).exists() for path in (project/directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts},
            "readme_sha256": sha(project/"README.md")} for alias, project in projects.items()}}
    (output/"run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    count = 0
    for alias, project in projects.items():
        with server(project.resolve(), output, args.corpus_root.resolve(), observer_module="evaluation.core_workflows_20261004.acquisition.observe_server") as handle:
            for case in cases:
                if case["project"] == alias:
                    count += 1
                    if args.phase in {"entry_confirmation", "change_entry_confirmation"}:
                        conversation_query(handle,case,count,output)
                    else:
                        query(handle, case, "object-reader-"+args.phase, count%2 == 0, count, output)
    changed = [name for name, expected in manifest["input_sha256"].items() if sha(REPO/name) != expected]
    assert not changed, "Runtime changed during evaluation"
    emit({"finished_requests": count, "results_sha256": sha(output/"live_results.jsonl")})


if __name__ == "__main__":
    main()
