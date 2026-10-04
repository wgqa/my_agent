"""Prepare, check or run the current three-workflow Engineering demonstration.

Uses the same question formatter, Conversation API and SSE reducer as the UI.
One conversation message per case, no task retries, no correctness scores.
--live is required to send messages; prepare/check are model-free. Normal
Planner/Decision calls and bounded parse repair remain owned by the runtime.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.product_version import PRODUCT_VERSION, product_identity
from ui.api_client import ApiClient, ApiError
from ui.components import build_core_workflow_question
from ui.streaming import EngineeringStreamState, StreamProtocolError, consume_event, validate_complete

CATALOG = REPO_ROOT / "demo/engineering_demo_cases.json"
FIXTURE = REPO_ROOT / "demo/engineering_project"


def load_cases() -> list[dict]:
    cases = json.loads(CATALOG.read_text(encoding="utf-8"))
    if len(cases) != 3 or {case["workflow"] for case in cases} != {"configuration", "change_test", "docs_code"} or len({case["id"] for case in cases}) != 3:
        raise ValueError("Expected three distinct core workflow cases")
    for case in cases:
        case["message"] = build_core_workflow_question(case["workflow"], case["subject"], case["reference"])
        if not case["message"]:
            raise ValueError("Demo input is incomplete")
    return cases


def prepare_project(workspace: Path) -> Path:
    target = workspace.resolve()
    if target.exists():
        raise ValueError("Demo workspace already exists; choose a fresh directory")
    # Never reset an existing repository. This Git history belongs only to the
    # freshly copied fixture; it is not pushed and no target code is executed.
    shutil.copytree(FIXTURE, target)
    for arguments in (
        ["init", "-q"], ["add", "README.md", "support_search", "tests"],
        ["-c", "user.name=Engineering Demo", "-c", "user.email=demo@example.invalid",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Demo baseline: default 4"],
    ):
        subprocess.run(["git", *arguments], cwd=target, check=True, capture_output=True)
    settings = target / "support_search/settings.py"
    original = settings.read_text(encoding="utf-8")
    if original.count("DEFAULT_RESULT_LIMIT = 4") != 1:
        raise ValueError("Demo default-value fixture changed unexpectedly")
    settings.write_text(original.replace("DEFAULT_RESULT_LIMIT = 4", "DEFAULT_RESULT_LIMIT = 6"), encoding="utf-8")
    return target


def preflight(client: ApiClient, expected_project: str) -> dict:
    identity = client.version()
    if identity.get("schema_version") != "product_version_v1" or identity.get("version") != PRODUCT_VERSION:
        raise ValueError("Backend version differs from this demo; restart from the same checkout")
    capabilities, knowledge, project = client.capabilities(), client.engineering_knowledge(), client.project()
    if capabilities.get("features", {}).get("engineering_agent") is not True:
        raise ValueError("Engineering runtime is unavailable")
    if knowledge.get("ready") is not True or knowledge.get("verified") is not True:
        raise ValueError("Engineering Knowledge is not ready and verified")
    if project.get("project_name") != expected_project:
        raise ValueError("Backend is bound to a different project name")
    return {"version": identity, "knowledge": knowledge, "project": project}


def run_case(client: ApiClient, case: dict) -> dict:
    conversation = client.engineering_conversations_create()
    conversation_id = conversation["id"]
    state = EngineeringStreamState()
    events = client.engineering_conversation_message_stream(conversation_id, case["message"])
    try:
        for event in events:
            state = consume_event(state, event)
        validate_complete(state)
    finally:
        close = getattr(events, "close", None)
        if close:
            close()
    if state.error_code or state.final_result is None:
        raise ValueError("Stream ended without a persisted public result")
    result = state.final_result
    for key, maximum in (("iterations_used", 5), ("tool_calls_used", 4), ("tool_errors_used", 2)):
        if type(result.get(key)) is not int or not 0 <= result[key] <= maximum:
            raise ValueError("Public runtime budget is invalid")
    detail = client.engineering_conversation_detail(conversation_id)
    messages = detail.get("messages", [])
    if len(messages) != 2 or messages[0].get("role") != "user" or messages[1].get("role") != "assistant" or messages[0].get("content") != case["message"] or messages[1].get("result") != result:
        raise ValueError("Saved turn differs from the stream result")
    return {
        "case_id": case["id"], "conversation_id": conversation_id, "workflow": case["workflow"],
        "message": case["message"], "observe": case["observe"], "public_result": result,
        "persistence_checked": True, "content_review": "not_evaluated",
    }


def run_demo(client: ApiClient, expected_project: str, output: Path) -> dict:
    cases, status = load_cases(), preflight(client, expected_project)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": "engineering_demo_v1", "product": product_identity(),
              "backend": status, "benchmark": False, "independent_acceptance": False,
              "message_retries": 0, "cases": [], "transport_error": None}
    # Reserve the output before any paid request. Existing evidence cannot be
    # overwritten, and a partial run remains reviewable if a later case fails.
    with output.open("x", encoding="utf-8") as handle:
        def save():
            handle.seek(0)
            handle.truncate()
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
        save()
        for case in cases:
            try:
                report["cases"].append(run_case(client, case))
            except (ApiError, StreamProtocolError, ValueError, KeyError) as error:
                report["transport_error"] = {"case_id": case["id"], "type": type(error).__name__}
                save()
                break
            save()
        report["runtime_statuses"] = dict(Counter(item["public_result"]["status"] for item in report["cases"]))
        save()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="mode", required=True)
    prepare = subcommands.add_parser("prepare", help="Create a fresh local Git fixture; zero models")
    prepare.add_argument("--workspace", type=Path, required=True)
    for name in ("check", "run"):
        command = subcommands.add_parser(name)
        command.add_argument("--base-url", default="http://127.0.0.1:8000")
        command.add_argument("--expected-project", default="engineering-demo")
        if name == "run":
            command.add_argument("--live", action="store_true", help="Send exactly one message per case")
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            target = prepare_project(args.workspace)
            print(f"DEMO_PROJECT_READY: {target}")
            print("default=6; baseline/docs/tests=4; target_code_executed=false")
            return 0
        if args.mode == "run" and not args.live:
            parser.error("run requires --live; use check for a model-free preflight")
        client = ApiClient(args.base_url)
        if args.mode == "check":
            preflight(client, args.expected_project)
            print(f"ENGINEERING_DEMO_PREFLIGHT_OK: {PRODUCT_VERSION}; provider_calls=0")
            return 0
        report = run_demo(client, args.expected_project, args.output)
        print(json.dumps({"recorded_cases": len(report["cases"]), "runtime_statuses": report["runtime_statuses"],
                          "transport_error": report["transport_error"], "content_review": "not_evaluated"}, ensure_ascii=False))
        return 1 if report["transport_error"] else 0
    except (ApiError, ValueError, OSError, subprocess.CalledProcessError) as error:
        detail = error.message if isinstance(error, ApiError) else str(error) if isinstance(error, ValueError) else type(error).__name__
        if isinstance(error, FileExistsError):
            detail = "Output already exists; choose a fresh result file"
        print(f"ENGINEERING_DEMO_FAILED: {detail[:240]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
