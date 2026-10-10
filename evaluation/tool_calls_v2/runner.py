"""Sequential offline proof / scripted assembly / explicit real-model runs."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from .fixtures import materialize_project, prepare_source_cache, project_identity
from .manifest import (REPO_ROOT, business_fingerprint, copy_seed_library, create_manifest, evaluator_fingerprint, library_identity)
from .observer import RecordedDecisionProvider, Recorder, observe, record_provider_calls
from .reporting import write_json, write_report
from .schema import DATASET_DIR, PRIMARY_TOOLS, digest, load_cases, validate_case, verify_gold_sources
from .scorer import score_case, summarize

OWN_STATE = REPO_ROOT / "data/runtime/tool_call_v2"
RESULTS = Path(__file__).parent / "results"


def scoring_identity() -> str:
    return digest({name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() for name in ("schema.py", "scorer.py")})


def run_gold_proof(case: dict, registry, recorder: Recorder) -> None:
    from core.tool_agent.executor import ToolExecutor
    from core.tool_agent.models import ToolCall

    executor, started = ToolExecutor(registry.without(frozenset({"knowledge_search"}))), time.perf_counter()
    with observe(recorder):
        for action in case["reference_calls"]:
            executor.execute(ToolCall.create(action["tool"], action["arguments"]))
    calls = [e for e in recorder.events if e["stage"] == "tool"]
    recorder.add("terminal", status=case["terminal_statuses"][0], reason_code=case["refusal_codes"][0] if case["terminal_statuses"][0] == "refused" else None,
                 failure_code=None, answer=None, tool_calls_used=len(calls), tool_errors_used=sum(e["status"] == "error" for e in calls),
                 iterations_used=len(calls) + 1, execution=None, elapsed_ms=(time.perf_counter() - started) * 1000,
                 provenance="synthetic terminal for reachability only; not a facade or model result")


def run_facade(case: dict, project: Path, library, recorder: Recorder, *, live: bool):
    from .product_runtime import ScriptedReferenceProvider, build_product_runtime

    assembly = build_product_runtime(project, library, scripted_provider=None if live else ScriptedReferenceProvider(case))
    recorder.enabled_tools = sorted(s.name for s in assembly.tool_runtime._registry.list_specs() if s.name != "knowledge_search")
    decision_provider = assembly.tool_runtime._provider
    assembly.tool_runtime._provider = RecordedDecisionProvider(decision_provider, recorder)
    started = time.perf_counter()
    with ExitStack() as stack:
        stack.enter_context(observe(recorder))
        if live:
            stack.enter_context(record_provider_calls(decision_provider, "decision", recorder))
            stack.enter_context(record_provider_calls(assembly.planner._planner, "planner", recorder))
            for provider in (decision_provider, assembly.planner._planner, assembly.context_resolver._query_resolver):
                client = getattr(provider, "_client", None)
                if callable(getattr(client, "close", None)):
                    stack.callback(client.close)
        # Gold, expected answers and reference paths are not passed into live mode.
        result = assembly.facade.run(case["query"])
    recorder.terminal(result, (time.perf_counter() - started) * 1000)
    return result


def _json_lines(path: Path, values: list[dict]) -> None:
    path.write_text("".join(json.dumps(v, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for v in values), encoding="utf-8", newline="\n")


def _load_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def recompute(source: Path, destination: Path, *, allow_rule_change: bool = False) -> dict:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    for name in ("calls.jsonl", "cases.jsonl"):
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != manifest["artifacts_sha256"][name]:
            raise ValueError(f"Saved artifact changed: {name}")
    current_rules = scoring_identity()
    if current_rules != manifest["scoring_sha256"] and not allow_rule_change:
        raise ValueError("Scoring rules changed; use a new analysis with --allow-rule-change")
    cases, events = _load_lines(source / "cases.jsonl"), _load_lines(source / "calls.jsonl")
    for case in cases:
        validate_case(case)
    if digest(cases) != manifest["cases_sha256"]:
        raise ValueError("Frozen cases differ from manifest")
    records = {}
    for event in events:
        if event["case_id"] not in {c["id"] for c in cases}:
            raise ValueError("Unplanned call record")
        records.setdefault(event["case_id"], []).append(event)
    scores = [score_case(c, records[c["id"]], mode=manifest["mode"]) for c in cases if c["id"] in records]
    for score in scores:
        if score["project"] in manifest.get("contaminated_projects", []):
            score["record_problems"].append("FIXTURE_CHANGED")
            score["valid"], score["verdict"] = False, "INVALID"
    summary = summarize(cases, scores, records, mode=manifest["mode"])
    destination.mkdir(parents=True, exist_ok=False)
    analysis = {**manifest, "run_id": destination.name, "rescore_of": manifest["run_id"], "scoring_sha256": current_rules,
                "rescore_evaluator": evaluator_fingerprint(),
                "scoring_rules_changed": current_rules != manifest["scoring_sha256"]}
    for name in ("calls.jsonl", "cases.jsonl"):
        shutil.copyfile(source / name, destination / name)
    write_json(destination / "manifest.json", analysis)
    write_report(destination, analysis, cases, scores, summary)
    return summary


def assert_live_identity(events: list[dict], runtime: dict) -> None:
    for event in events:
        if event["stage"] not in ("planner", "decision") or not event.get("metadata"):
            continue
        metadata, role = event["metadata"], event["stage"]
        expected = runtime[role]
        if (metadata["provider"] != runtime["provider"] or metadata["model"] != runtime["model"]
                or metadata["prompt_version"] != expected["version"] or metadata["prompt_sha256"] != expected["sha256"]
                or (role == "decision" and metadata["toolset_sha256"] != runtime["primary_toolset_sha256"])):
            raise RuntimeError("RUNTIME_IDENTITY_CHANGED")


def execute(cases: list[dict], *, run_id: str, mode: str, state_dir: Path, output: Path, source_cache: Path,
            corpus_root: Path | None = None) -> dict:
    if mode not in ("gold_proof", "scripted", "live"):
        raise ValueError("Unsupported evaluation mode")
    if output.exists() or state_dir.exists():
        raise ValueError("Output/state already exists; choose a new run ID")
    if not cases:
        raise ValueError("Empty case selection")
    # The evaluator owns only newly created directories, never a server's state.
    state_dir.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    names = sorted({c["project"] for c in cases})
    roots = {name: state_dir / "projects" / name for name in names}
    projects = {name: materialize_project(name, roots[name], source_cache) for name in names}
    protocol = json.loads((DATASET_DIR / "protocol.json").read_text(encoding="utf-8"))
    for name in names:
        if projects[name]["content_sha256"] != protocol["source_identities"][name]["content_sha256"] or projects[name]["head"] != protocol["source_identities"][name]["head"]:
            raise ValueError(f"Fixture differs from frozen protocol: {name}")
    for case in cases:
        verify_gold_sources(case, roots[case["project"]])
    db_path = state_dir / "knowledge.sqlite3"
    library = copy_seed_library(db_path, corpus_root=corpus_root)
    from .product_runtime import build_evaluation_registry

    registries = {name: build_evaluation_registry(roots[name], library.retrieval_port) for name in names}
    manifest = create_manifest(run_id=run_id, mode=mode, cases=cases, projects=projects,
        library=library_identity(library, db_path), registry=registries[names[0]], timestamp=datetime.now(timezone.utc).isoformat())
    manifest["scoring_sha256"] = scoring_identity()
    manifest["status"] = "running"
    write_json(output / "manifest.json", manifest)
    _json_lines(output / "cases.jsonl", cases)
    records, scores = {}, []
    calls_path = output / "calls.jsonl"
    calls_path.touch(exist_ok=False)
    stopped = False
    for case in cases:
        recorder = Recorder(case["id"], private_strings=(str(REPO_ROOT), REPO_ROOT.as_posix(), str(state_dir.resolve()), state_dir.resolve().as_posix(), os.getenv("DEEPSEEK_API_KEY", "")), fault=case["fault"])
        try:
            if business_fingerprint()["sha256"] != manifest["business"]["sha256"] or evaluator_fingerprint()["sha256"] != manifest["evaluator"]["sha256"]:
                raise RuntimeError("VERSION_CHANGED")
            verify_gold_sources(case, roots[case["project"]])
            if mode == "gold_proof":
                run_gold_proof(case, registries[case["project"]], recorder)
            else:
                run_facade(case, roots[case["project"]], library, recorder, live=mode == "live")
            if mode == "live":
                assert_live_identity(recorder.events, manifest["runtime"])
            if business_fingerprint()["sha256"] != manifest["business"]["sha256"] or evaluator_fingerprint()["sha256"] != manifest["evaluator"]["sha256"]:
                raise RuntimeError("VERSION_CHANGED")
        except Exception as exc:
            # Exceptions can contain API response headers/keys; never persist their text.
            recorder.add("infrastructure_error", category=str(exc) if str(exc) in ("VERSION_CHANGED", "RUNTIME_IDENTITY_CHANGED") else type(exc).__name__)
            stopped = True
        records[case["id"]] = recorder.events
        with calls_path.open("a", encoding="utf-8", newline="\n") as handle:
            for event in recorder.events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
        score = score_case(case, recorder.events, mode=mode)
        scores.append(score)
        print(f"{case['id']} {score['verdict']}", flush=True)
        if stopped:
            break
    for name in names:
        after = project_identity(name, roots[name], projects[name]["upstream_commit"])
        if after != projects[name]:
            manifest["fixture_changed"] = True
            manifest.setdefault("contaminated_projects", []).append(name)
            stopped = True
            # A contaminated fixture makes recorded cases of that project invalid.
            for score in scores:
                if score["project"] == name:
                    score["record_problems"].append("FIXTURE_CHANGED")
                    score["valid"], score["verdict"] = False, "INVALID"
    summary = summarize(cases, scores, records, mode=mode)
    manifest.update(status="interrupted" if stopped else "finished", finished_at=datetime.now(timezone.utc).isoformat(),
                    artifacts_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (calls_path, output / "cases.jsonl")})
    write_json(output / "manifest.json", manifest)
    write_report(output, manifest, cases, scores, summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", action="store_true", help="Explicitly call real Planner and Decision models; notify the owner before using")
    modes.add_argument("--scripted", action="store_true", help="Replay reference actions through the actual facade, replacing both model stages")
    modes.add_argument("--prepare-sources", action="store_true", help="Download pinned repositories only; zero model calls")
    modes.add_argument("--rescore", type=Path, help="Recompute a saved run, with no model calls")
    parser.add_argument("--allow-rule-change", action="store_true")
    parser.add_argument("--split", choices=("dev", "validation", "all"), default="all")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-cache", type=Path, default=OWN_STATE / "source_cache")
    parser.add_argument("--knowledge-source", type=Path)
    args = parser.parse_args(argv)
    if args.prepare_sources:
        prepare_source_cache(args.source_cache)
        print("Pinned sources prepared; model calls: 0")
        return 0
    mode = "live" if args.live else "scripted" if args.scripted else "gold_proof"
    run_id = args.run_id or f"{mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id) or run_id.upper() in {"NUL", "CON", "PRN", "AUX", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        parser.error("Invalid run ID")
    output = args.output or RESULTS / run_id
    if args.rescore:
        summary = recompute(args.rescore, output, allow_rule_change=args.allow_rule_change)
    else:
        if args.live and args.split == "all":
            parser.error("Live runs must explicitly select --split dev or --split validation")
        cases = load_cases(args.split)
        if args.case:
            known = {c["id"] for c in cases}
            if len(set(args.case)) != len(args.case) or not set(args.case) <= known:
                parser.error("Duplicate, unknown, or wrong-split case IDs")
            cases = [c for c in cases if c["id"] in args.case]
        if args.live and args.split == "dev" and not args.case:
            # Four preselected pilots are part of 48, never repeated for a nicer score.
            pilot = ("dev-001", "dev-025", "dev-039", "dev-046")
            cases = [next(c for c in cases if c["id"] == name) for name in pilot] + [c for c in cases if c["id"] not in pilot]
        summary = execute(cases, run_id=run_id, mode=mode, state_dir=args.state_dir or OWN_STATE / "runs" / run_id,
                          output=output, source_cache=args.source_cache, corpus_root=args.knowledge_source)
    print(json.dumps({"mode": summary["mode"], "recorded": summary["recorded_requests"], "verdicts": summary["verdicts"],
                      "model_quality_result": summary["is_model_quality_result"]}, ensure_ascii=False))
    return 0 if not summary["invalid_records"] and not summary["not_run"] and (summary["mode"] != "gold_proof" or summary["verdicts"].get("PASS") == summary["planned_requests"]) else 1
