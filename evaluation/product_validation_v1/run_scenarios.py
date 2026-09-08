"""PRODUCT-VALIDATION-22 fresh-scenario runner.

Frozen evaluation tooling: drives the real Product (FastAPI Engineering
surface) against fresh pinned repositories with the real DeepSeek provider.
This module must never modify Product behavior, retry failed requests, or
change any frozen policy between scenarios. All runtime policy (budget,
prompt, tools, corpus) is owned by the Product; this runner only sets the
project root / corpus root environment and records observed facts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK_ROOT = REPO_ROOT.parent / "_pv22_work"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decision_llm_calls(trace_events) -> int:
    """Sum provider_call_count over decision events (observable Product fact)."""

    total = 0
    for event in trace_events or []:
        count = event.get("provider_call_count")
        if isinstance(count, int):
            total += count
    return total


def _run_single_turn(client, question: str) -> dict:
    started = time.perf_counter()
    started_at = _utcnow()
    response = client.post("/engineering/query", json={"question": question})
    latency = time.perf_counter() - started
    record = {
        "turn": 1,
        "question": question,
        "started_at": started_at,
        "latency_seconds": round(latency, 2),
        "http_status": response.status_code,
    }
    if response.status_code == 200:
        payload = response.json()
        record.update(
            {
                "terminal_status": payload.get("status"),
                "answer": payload.get("answer"),
                "evidence": payload.get("evidence"),
                "tool_calls_used": payload.get("tool_calls_used"),
                "iterations_used": payload.get("iterations_used"),
                "decision_llm_calls": _decision_llm_calls(payload.get("trace")),
                "input_output_tokens": "UNKNOWN",
                "response": payload,
            }
        )
    else:
        record.update(
            {
                "terminal_status": "INFRA_HTTP_ERROR",
                "answer": None,
                "evidence": [],
                "error_body": response.text[:2000],
                "input_output_tokens": "UNKNOWN",
            }
        )
    return record


def _parse_sse_events(response) -> list[dict]:
    events: list[dict] = []
    for line in response.iter_lines():
        if not line or not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            events.append({"type": "unparseable", "raw": raw[:500]})
    return events


def _run_multi_turn(client, scenario: dict, db_note: str) -> dict:
    conversation = client.post("/engineering/conversations")
    if conversation.status_code != 201:
        return {
            "turns": [],
            "infrastructure": {
                "status": "FAIL",
                "detail": f"conversation create HTTP {conversation.status_code}",
            },
            "conversation_db": db_note,
        }
    conversation_id = conversation.json()["id"]
    turns = []
    for turn_spec in scenario["turns"]:
        started = time.perf_counter()
        started_at = _utcnow()
        try:
            with client.stream(
                "POST",
                f"/engineering/conversations/{conversation_id}/messages/stream/v1",
                json={"message": turn_spec["question"]},
            ) as response:
                http_status = response.status_code
                events = _parse_sse_events(response) if http_status == 200 else []
                error_body = None if http_status == 200 else response.read().decode("utf-8", "replace")[:2000]
        except Exception as exc:  # noqa: BLE001 - observed infra fact
            turns.append(
                {
                    "turn": turn_spec["turn"],
                    "question": turn_spec["question"],
                    "started_at": started_at,
                    "terminal_status": "INFRA_STREAM_ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                    "input_output_tokens": "UNKNOWN",
                }
            )
            continue
        latency = time.perf_counter() - started
        final = next((e for e in reversed(events) if e.get("type") == "final"), None)
        result = (final or {}).get("result") or {}
        turns.append(
            {
                "turn": turn_spec["turn"],
                "question": turn_spec["question"],
                "started_at": started_at,
                "latency_seconds": round(latency, 2),
                "http_status": http_status,
                "terminal_status": result.get("status", "INFRA_NO_FINAL_EVENT"),
                "answer": result.get("answer"),
                "evidence": result.get("evidence"),
                "tool_calls_used": result.get("tool_calls_used"),
                "iterations_used": result.get("iterations_used"),
                "decision_llm_calls": _decision_llm_calls(result.get("trace")),
                "input_output_tokens": "UNKNOWN",
                "error_body": error_body,
                "sse_event_types": [e.get("type") for e in events],
                "events": events,
            }
        )
    return {
        "conversation_id": conversation_id,
        "conversation_db": db_note,
        "turns": turns,
    }


def _worker(group: str, contract_path: Path, out_dir: Path, work_root: Path) -> None:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    group_spec = contract["repo_groups"][group]
    project_root = work_root / group_spec["worktree_relative"]
    if not project_root.is_dir():
        raise SystemExit(f"project worktree missing: {project_root}")
    corpus_root = work_root / "agent_data" / "agent_ai_v1" / "02_corpus_candidate"
    os.environ["ENGINEERING_PROJECT_ROOT"] = str(project_root)
    os.environ["ENGINEERING_KNOWLEDGE_CORPUS_ROOT"] = str(corpus_root)
    conversation_db = out_dir / f"conversations_{group}.sqlite3"
    os.environ["ENGINEERING_CONVERSATION_DB"] = str(conversation_db)

    sys.path.insert(0, str(REPO_ROOT))

    from fastapi.testclient import TestClient

    import api.app as app_module

    with TestClient(app_module.app) as client:
        knowledge = client.get("/engineering/knowledge")
        knowledge_status = knowledge.json() if knowledge.status_code == 200 else {
            "http_status": knowledge.status_code
        }
        for task_id in group_spec["tasks"]:
            scenario = contract["scenario_questions"][task_id]
            started_at = _utcnow()
            if "turns" in scenario:
                body = _run_multi_turn(client, scenario, str(conversation_db.name))
            else:
                body = {"turns": [_run_single_turn(client, scenario["question"])]}
            record = {
                "task_id": task_id,
                "category": scenario["category"],
                "repo": scenario["repo"],
                "project_root_name": project_root.name,
                "product_commit": contract["product"]["commit"],
                "prompt_profile": contract["product"]["prompt_profile"],
                "started_at": started_at,
                "finished_at": _utcnow(),
                "knowledge_status": knowledge_status,
                **body,
            }
            out_path = out_dir / f"{task_id}.json"
            out_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            terminal = [
                t.get("terminal_status") for t in body.get("turns", [])
            ]
            print(f"[done] {task_id}: terminal={terminal}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    parser.add_argument("--groups", type=str, default=None,
                        help="comma-separated repo_groups keys; default all")
    parser.add_argument("--worker", type=str, default=None,
                        help="internal: run a single group in this process")
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    groups = (
        args.groups.split(",") if args.groups else list(contract["repo_groups"])
    )
    if args.worker:
        _worker(args.worker, args.contract, args.out_dir, args.work_root)
        return
    for group in groups:
        print(f"[group] {group} starting", flush=True)
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                group,
                "--contract",
                str(args.contract),
                "--out-dir",
                str(args.out_dir),
                "--work-root",
                str(args.work_root),
            ],
            cwd=str(REPO_ROOT),
        )
        if completed.returncode != 0:
            print(f"[group] {group} worker exited {completed.returncode}", flush=True)


if __name__ == "__main__":
    main()
