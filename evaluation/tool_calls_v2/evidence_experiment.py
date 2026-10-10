"""Known-case A/B/C/D development experiment; Gold never enters model input.

Tool-material scores reuse the frozen independent scorer. Answer quality is
left for explicit independent review; runtime approval is not an eval score.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
import time
from unittest.mock import patch

from .fixtures import materialize_project, project_identity
from .manifest import REPO_ROOT, business_fingerprint, copy_seed_library, evaluator_fingerprint, library_identity, runtime_identity
from .observer import Recorder, RecordedDecisionProvider, observe, record_provider_calls
from .reporting import write_json
from .schema import DATASET_DIR, digest, load_cases, verify_gold_sources
from .scorer import score_case

EXPERIMENT_VERSION = "engineering_evidence_development_experiment_v1"
PILOT_CASE_IDS = ("dev-001", "dev-005", "dev-009", "dev-010", "dev-012", "dev-013",
                  "dev-015", "dev-021", "dev-026", "dev-037", "dev-043", "dev-048")
GROUP_SETTINGS = {"A": ("rule", "legacy", "legacy"), "B": ("rule", "goal_v2", "structural_v2"),
                  "C": ("llm", "goal_v2", "structural_v2"), "D": ("llm", "goal_v2", "semantic_v1")}


def select_cases(ids):
    cases = {case["id"]: case for case in load_cases("dev")}
    if not ids or len(ids) != len(set(ids)) or any(case_id not in cases for case_id in ids):
        raise ValueError("select distinct existing development cases; no heldout access")
    return [cases[case_id] for case_id in ids]


def _jsonl(path, values):
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def run_case(case, project, library, group, recorder):
    from .product_runtime import build_product_runtime
    from core.engineering_agent import EngineeringAgentFacade
    from core.engineering_requirement_planning import RuleRequirementProvider
    from core.engineering_verification import EngineeringEvidenceVerifier
    from core.unified_engineering_runtime import UnifiedEngineeringRuntime, LegacyToolAgentExecutionAdapter

    keys = ("ENGINEERING_REQUIREMENT_MODE", "ENGINEERING_EVIDENCE_POLICY", "ENGINEERING_FINALIZATION_POLICY")
    with patch.dict(os.environ, dict(zip(keys, GROUP_SETTINGS[group]))):
        assembly = build_product_runtime(project, library)
    if group == "A":
        # Same whole-request cooperative deadline as candidates; no changing the
        # legacy Router, Decision prompt, evidence types or verification logic.
        runtime = UnifiedEngineeringRuntime(LegacyToolAgentExecutionAdapter(assembly.tool_runtime),
            context_resolver=assembly.context_resolver, evidence_planner=assembly.planner,
            retrieval_component=assembly.retrieval, evidence_verifier=EngineeringEvidenceVerifier(),
            requirement_provider=RuleRequirementProvider())
        facade = EngineeringAgentFacade(runtime)
    else:
        runtime, facade = assembly.runtime, assembly.facade
    recorder.enabled_tools = sorted(s.name for s in assembly.tool_runtime._registry.list_specs() if s.name != "knowledge_search")
    decision = assembly.tool_runtime._provider
    assembly.tool_runtime._provider = RecordedDecisionProvider(decision, recorder)
    providers = [(decision, "decision"), (assembly.planner._planner, "planner")]
    requirement_llm = getattr(runtime._requirement_provider, "_llm", None)
    if requirement_llm is not None:
        providers.append((requirement_llm, "requirement"))
    verifier = runtime._candidate_verifier
    if verifier is not None and verifier.reviewer is not None:
        providers.append((verifier.reviewer, "review"))
    started = time.perf_counter()
    with ExitStack() as stack:
        stack.enter_context(observe(recorder))
        for provider, role in providers:
            stack.enter_context(record_provider_calls(provider, role, recorder))
            if callable(getattr(provider._client, "close", None)):
                stack.callback(provider._client.close)
        resolver = assembly.context_resolver._query_resolver
        if callable(getattr(getattr(resolver, "_client", None), "close", None)):
            stack.callback(resolver._client.close)
        result = facade.run(case["query"])
    recorder.terminal(result, (time.perf_counter() - started) * 1000)
    profile = decision._prompt_profile
    identity = runtime_identity(assembly.tool_runtime._registry)
    from core.tool_agent.decision_prompt import max_output_tokens_for_profile, max_parse_repairs_for_profile
    identity["decision"].update(version=profile.version, sha256=profile.sha256,
        output_cap=max_output_tokens_for_profile(profile), max_parse_repairs=max_parse_repairs_for_profile(profile))
    if requirement_llm is not None:
        from core.engineering_requirement_planning import (REQUIREMENT_PROMPTS, REQUIREMENT_MAX_OUTPUT_TOKENS,
            REQUIREMENT_TIMEOUT_SECONDS, REQUIREMENT_MAX_RETRIES)
        identity["requirement"] = {"version": requirement_llm._prompt_version,
            "sha256": REQUIREMENT_PROMPTS[requirement_llm._prompt_version][1],
            "output_cap": REQUIREMENT_MAX_OUTPUT_TOKENS, "timeout_seconds": REQUIREMENT_TIMEOUT_SECONDS,
            "sdk_retries": REQUIREMENT_MAX_RETRIES, "temperature": 0.0}
    if verifier is not None and verifier.reviewer is not None:
        from core.engineering_completion_review import (REVIEW_PROMPT_VERSION, REVIEW_PROMPT_SHA256,
            REVIEW_MAX_OUTPUT_TOKENS, REVIEW_MAX_INPUT_CHARACTERS, REVIEW_TIMEOUT_SECONDS, REVIEW_MAX_ATTEMPTS)
        identity["review"] = {"version": REVIEW_PROMPT_VERSION, "sha256": REVIEW_PROMPT_SHA256,
            "output_cap": REVIEW_MAX_OUTPUT_TOKENS, "input_character_limit": REVIEW_MAX_INPUT_CHARACTERS,
            "timeout_seconds": REVIEW_TIMEOUT_SECONDS, "max_calls": REVIEW_MAX_ATTEMPTS,
            "sdk_retries": 0, "temperature": 0.0}
    if result.requirement_planning is not None:
        recorder.add("requirement_result", **result.requirement_planning.metadata.to_dict())
    if hasattr(result, "finalization"):
        recorder.add("review_summary", **result.finalization.to_dict())
    return result, {"runtime": identity, "decision_version": profile.version, "decision_sha256": profile.sha256,
                    "settings": dict(zip(keys, GROUP_SETTINGS[group]))}


def execute(*, cases, groups, run_id, output, source_cache, corpus_root, live):
    if output.exists():
        raise ValueError("experiment output already exists; never overwrite a run")
    if not groups or len(set(groups)) != len(groups) or any(group not in GROUP_SETTINGS for group in groups):
        raise ValueError("invalid experiment groups")
    output.mkdir(parents=True, exist_ok=False)
    state = output / "state"
    state.mkdir()
    names = sorted({case["project"] for case in cases})
    roots = {name: state / "projects" / name for name in names}
    projects = {name: materialize_project(name, roots[name], source_cache) for name in names}
    protocol = json.loads((DATASET_DIR / "protocol.json").read_text(encoding="utf-8"))
    for name in names:
        expected = protocol["source_identities"][name]
        if projects[name]["content_sha256"] != expected["content_sha256"] or projects[name]["head"] != expected["head"]:
            raise ValueError("fixture differs from frozen source protocol")
    for case in cases:
        verify_gold_sources(case, roots[case["project"]])
    library = copy_seed_library(state / "knowledge.sqlite3", corpus_root=corpus_root)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    manifest = {"schema_version": EXPERIMENT_VERSION, "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(), "code_head": head,
        "business": business_fingerprint(), "evaluator": evaluator_fingerprint(),
        "groups": list(groups), "group_settings": {g: GROUP_SETTINGS[g] for g in groups},
        "case_ids": [case["id"] for case in cases], "cases_sha256": digest(cases),
        "projects": projects, "knowledge": library_identity(library, state / "knowledge.sqlite3"),
        "live": live, "planned_runs": len(cases) * len(groups),
        "budget": {"decisions": 5, "tools": 4, "tool_errors": 2, "deadline_seconds": 60, "review_calls": 2},
        "answer_quality": "independent review required; review accept is not Gold",
        "scope": "known development only; no heldout cases", "status": "running" if live else "prepared"}
    write_json(output / "manifest.json", manifest)
    _jsonl(output / "cases.jsonl", cases)
    if not live:
        return {"status": "prepared", "planned_runs": manifest["planned_runs"], "model_calls": 0}
    records, interrupted = [], False
    try:
        for case in cases:
            for group in groups:
                recorder = Recorder(case["id"], private_strings=(os.getenv("DEEPSEEK_API_KEY", ""),), fault=case["fault"])
                entry = {"case_id": case["id"], "group": group, "answer_quality": "pending_independent_review"}
                try:
                    if (business_fingerprint() != manifest["business"] or evaluator_fingerprint() != manifest["evaluator"]):
                        raise RuntimeError("VERSION_CHANGED")
                    result, identity = run_case(case, roots[case["project"]], library, group, recorder)
                    if business_fingerprint() != manifest["business"] or evaluator_fingerprint() != manifest["evaluator"]:
                        raise RuntimeError("VERSION_CHANGED")
                    score = score_case(case, recorder.events, mode="live")
                    provider_calls = [event for event in recorder.events if event["stage"] == "provider_call"]
                    metrics = {}
                    for role in ("planner", "requirement", "decision", "review"):
                        calls = [event for event in provider_calls if event["role"] == role]
                        metrics[role] = {"calls": len(calls), "elapsed_ms": sum(call["elapsed_ms"] for call in calls),
                            "input_tokens": sum(call["input_tokens"] for call in calls if call["input_tokens"] is not None)
                                if any(call["input_tokens"] is not None for call in calls) else None,
                            "output_tokens": sum(call["output_tokens"] for call in calls if call["output_tokens"] is not None)
                                if any(call["output_tokens"] is not None for call in calls) else None,
                            "usage_complete": bool(calls) and all(call["input_tokens"] is not None and call["output_tokens"] is not None for call in calls)}
                    audit = result.to_audit_dict() if hasattr(result, "to_audit_dict") else {"result": result.to_dict()}
                    path = output / f"{case['id']}_{group}.json"
                    write_json(path, {"identity": identity, "audit": audit, "events": recorder.events, "tool_score": score})
                    entry.update(status=result.status, reason_code=result.reason_code, failure_code=result.failure_code,
                                 tool_verdict=score["verdict"], tool_score=score, stage_metrics=metrics, identity=identity, artifact=path.name,
                                 artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                    print(f"{case['id']} {group}: {result.status}; tool={score['verdict']}", flush=True)
                except Exception as exc:
                    category = "VERSION_CHANGED" if str(exc) == "VERSION_CHANGED" else type(exc).__name__
                    entry.update(status="infrastructure_error", category=category)
                    _jsonl(output / "infrastructure_errors.jsonl", [{**entry, "events": recorder.events}])
                    interrupted = True
                records.append(entry)
                _jsonl(output / "runs.jsonl", [entry])
                if interrupted:
                    break
            if interrupted:
                break
        for name in names:
            if project_identity(name, roots[name], projects[name]["upstream_commit"]) != projects[name]:
                manifest["fixture_changed"] = True
                interrupted = True
    finally:
        # KnowledgeLibrary opens/closes each SQLite connection internally.
        close = getattr(library, "close", None)
        if callable(close):
            close()
    manifest.update(status="interrupted" if interrupted else "finished",
                    finished_at=datetime.now(timezone.utc).isoformat(), recorded_runs=len(records))
    write_json(output / "manifest.json", manifest)
    summary = {"schema_version": EXPERIMENT_VERSION, "status": manifest["status"], "groups": {},
               "answer_quality": "pending independent review; no end-to-end pass rate claimed"}
    for group in groups:
        group_runs = [entry for entry in records if entry["group"] == group]
        summary["groups"][group] = {"runs": len(group_runs),
            "completed": sum(entry["status"] == "completed" for entry in group_runs),
            "tool_pass": sum(entry.get("tool_verdict") == "PASS" for entry in group_runs),
            "failed": sum(entry["status"] == "failed" for entry in group_runs)}
    write_json(output / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Real model calls; notify the user of scope before starting")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--group", action="append", choices=tuple(GROUP_SETTINGS), default=[])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--knowledge-source", type=Path)
    parser.add_argument("--source-cache", type=Path, default=REPO_ROOT / "data/runtime/tool_call_v2/source_cache")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.run_id):
        raise ValueError("invalid run id")
    # All state stays in a fresh ignored workspace directory; never port 8000,
    # a production library, or the shared project checkout as a test fixture.
    output = REPO_ROOT / "data/runtime/evidence_experiments" / args.run_id
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    summary = execute(cases=select_cases(args.case or PILOT_CASE_IDS), groups=args.group or ["A", "C", "D"],
        run_id=args.run_id, output=output, source_cache=args.source_cache,
        corpus_root=args.knowledge_source, live=args.live)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["status"] != "interrupted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
